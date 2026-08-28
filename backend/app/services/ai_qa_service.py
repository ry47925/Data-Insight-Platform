import json
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Dataset, AIConversation
from app.services.ai_service import AIService
from app.services.ai_context.prompts_qa import SYSTEM_INTENT, SYSTEM_QA
from app.services.data_service import DataService


class AIQAService:
    """AI 数据问答服务（独立于分析型对话）

    与现有分析型对话（AIService.chat_with_context）隔离：
    - 分析型对话：注入产物元信息/操作记录，AI 做诊断与建议，不注入真实数据值。
    - 问答型对话：本地精确计算聚合/预测结果后注入，AI 只负责解读与组织语言。

    核心链路（两步 LLM + 本地计算）：
      1. 在数据目录（Catalog）上做相关性选表，输出结构化查询意图；
      2. 后端执行精确计算（pandas 聚合 / 远程 SQL / 模型预测）；
      3. 将计算结果注入主对话，由 AI 生成最终回答。

    无关问题在第 1 步即被拦截：目录中无相关表时返回 [NEEDS_CONTEXT_QA]，
    由 AI 列举目录可用数据并引导用户补充选择，避免编造结果。
    """

    def __init__(self, db: Session):
        self.db = db
        self.ai_service = AIService(db)
        self.data_service = DataService(db)

    # ========== 数据目录（Catalog）构建 ==========

    def build_catalog(self, dataset_ids: List[int], user_id: int) -> Dict[str, Any]:
        """构建轻量数据目录：只取 schema/行数/来源/血缘，不载入全量数据

        Args:
            dataset_ids: 用户勾选/全选的数据集ID列表
            user_id: 当前用户ID

        Returns:
            {"datasets": [{"dataset_id", "name", "artifact_type", "module_label",
                           "row_count", "source_type", "columns": [{name, type}],
                           "root_dataset_id", "connection_id", "table_name"}],
             "total": N}
        """
        if not dataset_ids:
            return {"datasets": [], "total": 0}

        datasets = self.db.query(Dataset).filter(
            Dataset.id.in_(dataset_ids),
            Dataset.user_id == user_id,
            Dataset.status == "active"
        ).all()

        catalog = []
        for ds in datasets:
            columns = []
            schema = ds.schema or {}
            col_schema = schema.get("columns", schema) if isinstance(schema, dict) else []
            if isinstance(col_schema, list):
                for col in col_schema:
                    if isinstance(col, dict):
                        columns.append({
                            "name": col.get("name") or col.get("column") or "",
                            "type": col.get("type") or col.get("dtype") or ""
                        })
                    else:
                        columns.append({"name": str(col), "type": ""})
            elif isinstance(col_schema, dict):
                # 兼容 schema = {"age": "int64", ...} 形式
                columns = [{"name": str(k), "type": str(v)} for k, v in col_schema.items()]

            catalog.append({
                "dataset_id": ds.id,
                "name": ds.name,
                "artifact_type": ds.artifact_type,
                "module_label": ds.module_label,
                "row_count": ds.row_count,
                "source_type": ds.source_type,
                "connection_id": ds.connection_id,
                "table_name": ds.table_name,
                "root_dataset_id": ds.root_dataset_id or ds.id,
                "columns": columns[:200]  # 防止超长 schema 撑爆 prompt
            })

        return {"datasets": catalog, "total": len(catalog)}

    def _catalog_to_prompt(self, catalog: Dict[str, Any]) -> str:
        """将目录压缩为 prompt 文本（表名+字段+行数+来源）"""
        if not catalog.get("datasets"):
            return "（数据目录为空）"
        lines = []
        for ds in catalog["datasets"]:
            cols = ", ".join(
                f"{c['name']}({c['type'] or '?'})" for c in ds["columns"][:50]
            )
            lines.append(
                f"- [数据集#{ds['dataset_id']}] {ds['name']}"
                f" | 类型:{ds['artifact_type'] or '?'} | 行数:{ds['row_count'] or '?'}"
                f" | 来源:{ds['source_type'] or '?'}"
                f" | 字段: {cols[:600]}"
            )
        return "\n".join(lines)

    # ========== 第一步：意图解析（NL → 结构化查询） ==========

    def resolve_query_intent(self, question: str, catalog: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """第一步 LLM：在目录上判定相关表，输出结构化查询意图

        Returns:
            成功: {"relevant": True, "intent": {...}, "usage": {...}}
            无关: {"relevant": False, "reason": "...", "usage": {...}}
            失败: {"error": "..."}
        """
        client = self.ai_service._client_provider.get_default_client()
        if not client:
            return {"error": "请先配置API Key才能使用AI问答功能"}

        if not catalog.get("datasets"):
            return {"relevant": False, "reason": "数据目录为空，请先在左侧选择数据集或保存的目录"}

        catalog_text = self._catalog_to_prompt(catalog)

        user_intent = f"【数据目录】\n{catalog_text}\n\n【用户问题】\n{question}"

        try:
            model_name = self.ai_service._get_model_name()
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_INTENT},
                    {"role": "user", "content": user_intent}
                ],
                temperature=0.1,
                max_tokens=1500
            )
            content = response.choices[0].message.content
            usage = self._extract_usage(response)

            # 提取 JSON（兼容 ```json 代码块包裹）
            json_match = re.search(r"\{[\s\S]*\}", content)
            if not json_match:
                return {"error": "意图解析结果无法识别"}
            parsed = json.loads(json_match.group(0))
            # 规范化 dataset_ids：LLM 可能返回 "#1227" / "1227" 等字符串，统一转 int
            intent = parsed.get("intent") or {}
            if intent:
                raw_ids = intent.get("dataset_ids") or []
                clean_ids = []
                for rid in raw_ids:
                    try:
                        clean_ids.append(int(str(rid).lstrip("#").strip()))
                    except (ValueError, TypeError):
                        continue
                intent["dataset_ids"] = clean_ids
                parsed["intent"] = intent
            # 兜底：LLM 判为无关，但问题明显是在询问当前数据集的元数据（各列类型/缺失/结构）时，
            # 直接降级为 profile 概览，避免因未匹配到具体列名而误判无关（产品问答默认在问勾选的数据）
            if not parsed.get("relevant"):
                fallback = self._fallback_meta_related(question, catalog)
                if fallback:
                    return {**fallback, "usage": usage}
            return {**parsed, "usage": usage}
        except Exception as e:
            return {"error": f"意图解析失败: {str(e)}"}

    def _fallback_meta_related(self, question: str, catalog: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """目录内有数据，但问题在询问数据本身概况（各列类型/缺失/结构/有哪些列）时，
        不因未命中具体列名就判无关，降级为对首张相关表的元数据概览（aggregation=profile）。

        Args:
            question: 用户问题
            catalog: 数据目录

        Returns:
            命中则返回可用的意图结果；否则 None
        """
        datasets = catalog.get("datasets") or []
        if not datasets:
            return None
        # 分布/异常值相关 → describe；各列/类型/缺失/结构 → profile
        describe_keywords = re.compile(
            r"(分布情况|分布形态|数值分布|分布特征|均值|标准差|方差|分位数|四分位|"
            r"集中趋势|离散程度|异常值|离群|异常点|极值|多大.*波动|整体.*水平)",
            re.I
        )
        meta_keywords = re.compile(
            r"(各列|每一列|列的类型|每列.*类型|字段类型|有哪些列|没有.*列|"
            r"缺失情况|缺失值|缺.*数据|数据概览|数据结构|数据情况|字段情况|有哪些字段)",
            re.I
        )
        if describe_keywords.search(question):
            aggregation = "describe"
        elif meta_keywords.search(question):
            aggregation = "profile"
        else:
            return None
        ds_top = datasets[0]
        reasoning = ("问题在询问数据的分布统计与异常值情况，直接对该表数值列做描述性统计。"
                     if aggregation == "describe"
                     else "问题在询问数据表各列的类型与缺失情况，属于元数据概览，直接查看该表的列概况。")
        return {
            "relevant": True,
            "intent": {
                "dataset_ids": [ds_top["dataset_id"]],
                "target_column": None,
                "aggregation": aggregation,
                "group_by": None,
                "filters": [],
                "time_column": None,
                "time_range": None,
                "requires_group_column": False,
                "needs_model": False,
                "reasoning": reasoning
            }
        }

    def _extract_usage(self, response) -> Dict[str, int]:
        """提取 token 用量（与 AIService 保持一致）"""
        if hasattr(response, "usage") and response.usage:
            return {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0)
            }
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # ========== 第二步：本地精确计算 ==========

    def _detect_group_missing_column(self, intent: Dict[str, Any], user_id: int) -> Optional[Dict[str, Any]]:
        """分组意图但缺分组列：加载数据集，提取可分组候选列，返回引导结果

        当意图解析标记了 requires_group_column=true（用户说了"分组统计/占比分布"等
        但未指明按哪个字段分组），从主数据集提取候选分组列，交由 AI 自然引导用户选择，
        避免退化为返回总行数或僵硬地罗列错误原因。

        Returns:
            命中: {"success": True, "result_type": "group_hint",
                   "result": {"candidate_columns": [...], "aggregation": "..."},
                   "dataset_labels": {...}}
            未命中（无需引导）: None
        """
        if not intent.get("requires_group_column"):
            return None
        dataset_ids = intent.get("dataset_ids") or []
        if not dataset_ids:
            return None

        ds_id = dataset_ids[0]
        ds = self.db.query(Dataset).filter(
            Dataset.id == ds_id, Dataset.user_id == user_id, Dataset.status == "active"
        ).first()
        if not ds:
            return None

        # 从 schema 提取字段类型，优先作为候选分组列判断依据（低开销）
        schema = ds.schema or {}
        col_schema = schema.get("columns", schema) if isinstance(schema, dict) else []
        schema_types = {}
        if isinstance(col_schema, list):
            for col in col_schema:
                if isinstance(col, dict):
                    name = col.get("name") or col.get("column") or ""
                    schema_types[name] = (col.get("type") or col.get("dtype") or "").lower()
                else:
                    schema_types[str(col)] = ""
        elif isinstance(col_schema, dict):
            schema_types = {str(k): str(v).lower() for k, v in col_schema.items()}

        # 数值/时间类列不适合作为分组维度，过滤掉
        numeric_hits = ("int", "float", "number", "datetime", "date", "bool", "id")
        candidates = []
        for col, ctype in schema_types.items():
            if col and not any(h in ctype for h in numeric_hits):
                candidates.append(col)
        # 若 schema 信息不足以判断（空），尝试加载真实数据推断候选列
        if not candidates:
            try:
                df = self.data_service.load_dataset(ds_id)
                df = self._coerce_numeric(df)
                for col in df.columns:
                    # 低基数（近似分类）列作为候选分组维度
                    try:
                        nunique = df[col].nunique(dropna=True)
                    except Exception:
                        continue
                    if nunique <= min(200, max(1, len(df) // 2)):
                        candidates.append(col)
            except Exception:
                candidates = []
            candidates = candidates[:20]

        if not candidates:
            return None

        aggregation = intent.get("aggregation") or "count"
        return {
            "success": True,
            "result_type": "group_hint",
            "result": {
                "candidate_columns": candidates[:20],
                "aggregation": aggregation
            },
            "computed_by": "pandas",
            "dataset_labels": {ds_id: ds.name}
        }

    def execute_intent(self, intent: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """第二步：按意图在本地执行精确计算，返回结果（不依赖 LLM 算术）

        Returns:
            {"success": True, "result_type": "aggregate"/"rows"/"prediction",
             "result": {...} 或 [...] , "computed_by": "pandas"/"remote_sql", "dataset_labels": {...}}
            失败: {"success": False, "error": "..."}
        """
        dataset_ids = intent.get("dataset_ids") or []
        if not dataset_ids:
            return {"success": False, "error": "未指定数据集"}

        # 分组意图但缺分组列：识别并返回候选分组列，交由 AI 自然引导追问（不返回计算值）
        group_hint = self._detect_group_missing_column(intent, user_id)
        if group_hint:
            return group_hint

        # 模型预测分支：needs_model=true 时在目录中查找 ml_model 数据集，不依赖顺序
        if intent.get("needs_model"):
            model_ids = [did for did in dataset_ids
                         if self.db.query(Dataset).filter(
                             Dataset.id == did, Dataset.user_id == user_id,
                             Dataset.status == "active", Dataset.artifact_type == "ml_model"
                         ).first()]
            if model_ids:
                model_ds = self.db.query(Dataset).filter(Dataset.id == model_ids[0]).first()
                return self._run_model_prediction(model_ds, intent, user_id)
            # 有预测意图但目录中无模型：给出明确提示，避免退化为统计
            return {"success": False, "error": "您的问题需要模型预测，但当前数据目录中没有 ml_model 类型的数据集（模型），请选择模型产物后重试"}

        # 取第一个数据集为主表（多表关联/合并不在当前阶段，先单表精确计算）
        dataset_id = dataset_ids[0]
        ds = self.db.query(Dataset).filter(
            Dataset.id == dataset_id, Dataset.user_id == user_id, Dataset.status == "active"
        ).first()
        if not ds:
            return {"success": False, "error": f"数据集 #{dataset_id} 不存在或不可用"}

        # 加载数据（本地DF全量，远程走SQL下推）
        try:
            if ds.connection_id and ds.table_name and ds.source_type == "remote_db":
                return self._run_remote_aggregate(ds, intent, user_id)
            df = self.data_service.load_dataset(dataset_id)
        except Exception as e:
            return {"success": False, "error": f"加载数据集失败: {str(e)}"}

        # 数值类型规范化（远程加载可能为 object）
        df = self._coerce_numeric(df)
        if df.empty:
            return {"success": False, "error": "数据集为空，无法计算"}

        # 元数据概览：询问"各列类型/缺失/结构"时，直接返回每列类型与缺失统计
        agg = intent.get("aggregation") or "count"
        if agg == "profile":
            return self._run_profile(df, ds)
        # 分布统计：询问"均值/标准差/四分位/分布/异常值"时，计算数值列描述统计与异常值
        if agg == "describe":
            return self._run_describe(df, ds, intent)

        try:
            return self._aggregate_dataframe(df, ds, intent)
        except Exception as e:
            return {"success": False, "error": f"聚合计算失败: {str(e)}"}

    def _run_profile(self, df: pd.DataFrame, ds: Dataset) -> Dict[str, Any]:
        """统计每列的数据类型与缺失情况（元数据概览）

        Args:
            df: 已加载的 DataFrame
            ds: 数据集对象

        Returns:
            {"success": True, "result_type": "profile",
             "result": {"row_count", "columns": [{column, type, null_count, null_rate}]}, ...}
        """
        total = len(df)
        columns = []
        for col in df.columns:
            s = df[col]
            nulls = int(s.isna().sum())
            columns.append({
                "column": str(col),
                "type": str(s.dtype),
                "null_count": nulls,
                "null_rate": round(nulls / total, 4) if total else 0
            })
        return {
            "success": True,
            "result_type": "profile",
            "result": {"row_count": total, "columns": columns},
            "computed_by": "pandas",
            "dataset_labels": {ds.id: ds.name}
        }

    def _run_describe(self, df: pd.DataFrame, ds: Dataset, intent: Dict[str, Any]) -> Dict[str, Any]:
        """数值列分布统计与异常值检测（描述性统计）

        对指定数值列（未指定则覆盖全部数值列）计算：
        均值、标准差、最小/最大、四分位数（Q1/中位数/Q3），
        并基于 IQR=Q3-Q1 以 1.5 倍箱线图法则判定异常值数量与比例。

        Args:
            df: 已加载的 DataFrame
            ds: 数据集对象
            intent: 查询意图（可选 target_column 限制到单列）

        Returns:
            {"success": True, "result_type": "describe",
             "result": {"row_count", "columns": [{"column", "count", "mean", "std", "min",
                           "q1", "median", "q3", "max", "outlier_count", "outlier_rate", "null_count"}]}, ...}
        """
        target = intent.get("target_column")
        total = len(df)

        # 数值列：target 指定则只用它（须为数值列），否则取全部数值列
        numeric_cols = list(df.select_dtypes(include=["number"]).columns)
        if target:
            cols = [target] if target in df.columns and target in numeric_cols else []
        else:
            cols = numeric_cols
        if not cols:
            return {"success": False, "error": "未找到可做分布统计的数值列，请指定一个数值列后再试"}

        stats = []
        for c in cols:
            s = df[c].dropna()
            n = int(s.count())
            if n == 0:
                stats.append({"column": c, "count": 0, "null_count": int(df[c].isna().sum()),
                              "mean": None, "std": None, "min": None, "q1": None,
                              "median": None, "q3": None, "max": None,
                              "outlier_count": 0, "outlier_rate": 0.0})
                continue
            q1, med, q3 = s.quantile([0.25, 0.5, 0.75]).tolist()
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outliers = int(s[(s < lower) | (s > upper)].count())
            stats.append({
                "column": c,
                "count": n,
                "mean": round(float(s.mean()), 4),
                "std": round(float(s.std()), 4) if n > 1 else 0,
                "min": round(float(s.min()), 4),
                "q1": round(float(q1), 4),
                "median": round(float(med), 4),
                "q3": round(float(q3), 4),
                "max": round(float(s.max()), 4),
                "outlier_count": outliers,
                "outlier_rate": round(outliers / total, 4) if total else 0,
                "null_count": int(df[c].isna().sum())
            })

        return {
            "success": True,
            "result_type": "describe",
            "result": {"row_count": total, "columns": stats},
            "computed_by": "pandas",
            "dataset_labels": {ds.id: ds.name}
        }

    def _aggregate_dataframe(self, df: pd.DataFrame, ds: Dataset, intent: Dict[str, Any]) -> Dict[str, Any]:
        """对 DataFrame 执行聚合/筛选"""
        target = intent.get("target_column")
        group_by = intent.get("group_by")
        aggregation = intent.get("aggregation") or "count"
        filters = intent.get("filters") or []

        # 校验字段存在
        available = set(df.columns)
        used_cols = [c for c in [target, group_by] if c] + [f.get("column") for f in filters if f.get("column")]
        missing = [c for c in used_cols if c and c not in available]
        if missing:
            return {"success": False, "error": f"字段不存在: {missing}（实际字段: {sorted(available)[:30]}）"}

        # 应用筛选
        df_filtered = df
        for f in filters:
            col, op = f.get("column"), f.get("op", "eq")
            val = f.get("value")
            if col not in df_filtered.columns:
                continue
            if op == "eq":
                df_filtered = df_filtered[df_filtered[col] == val]
            elif op == "gt":
                df_filtered = df_filtered[df_filtered[col] > val]
            elif op == "lt":
                df_filtered = df_filtered[df_filtered[col] < val]
            elif op == "gte":
                df_filtered = df_filtered[df_filtered[col] >= val]
            elif op == "lte":
                df_filtered = df_filtered[df_filtered[col] <= val]
            elif op == "contains":
                df_filtered = df_filtered[df_filtered[col].astype(str).str.contains(str(val), na=False)]
            elif op == "in":
                df_filtered = df_filtered[df_filtered[col].isin(val if isinstance(val, list) else [val])]

        # 无聚合字段时：计数或返回筛选后行数
        if not target and not group_by:
            return {
                "success": True,
                "result_type": "aggregate",
                "result": {"count": int(len(df_filtered))},
                "computed_by": "pandas",
                "dataset_labels": {ds.id: ds.name}
            }

        # groupby 聚合
        if group_by:
            if aggregation == "count":
                grouped = df_filtered.groupby(group_by).size().reset_index(name="count")
            elif aggregation in ("sum", "mean", "max", "min") and target:
                grouped = df_filtered.groupby(group_by)[target].agg(aggregation).reset_index()
                grouped = grouped.rename(columns={target: f"{aggregation}_{target}"})
            else:
                grouped = df_filtered.groupby(group_by).size().reset_index(name="count")
            result = grouped.head(2000).to_dict(orient="records")  # 精确结果，仅限制展示行数
            return {
                "success": True,
                "result_type": "aggregate",
                "result": {"grouped": result, "count": int(len(df_filtered))},
                "computed_by": "pandas",
                "dataset_labels": {ds.id: ds.name}
            }

        # 单值聚合
        if aggregation in ("sum", "mean", "max", "min") and target:
            value = df_filtered[target].agg(aggregation)
            return {
                "success": True,
                "result_type": "aggregate",
                "result": {f"{aggregation}_{target}": self._json_safe(value)},
                "computed_by": "pandas",
                "dataset_labels": {ds.id: ds.name}
            }

        # 默认：返回筛选后样本行（精确，但限制展示）
        rows = df_filtered.head(100).to_dict(orient="records")
        return {
            "success": True,
            "result_type": "rows",
            "result": {"rows": rows, "count": int(len(df_filtered))},
            "computed_by": "pandas",
            "dataset_labels": {ds.id: ds.name}
        }

    def _run_remote_aggregate(self, ds: Dataset, intent: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """远程表：SQL 下推聚合（count / 数值统计）"""
        try:
            metrics = [{"type": "count"}]
            agg = intent.get("aggregation") or "count"
            target = intent.get("target_column")
            if target and agg in ("sum", "mean", "max", "min"):
                metrics.append({"type": "numeric_stats", "columns": [target]})
            result = self.data_service.query_remote_aggregate(
                connection_id=ds.connection_id,
                table_name=ds.table_name,
                user_id=user_id,
                metrics=metrics
            )
            return {
                "success": True,
                "result_type": "aggregate",
                "result": result,
                "computed_by": "remote_sql",
                "dataset_labels": {ds.id: ds.name}
            }
        except Exception as e:
            return {"success": False, "error": f"远程聚合失败: {str(e)}"}

    def _run_model_prediction(self, model_ds: Dataset, intent: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """模型预测：加载 joblib 模型，对目标数据集预测，返回 TOP/汇总（精确）"""
        import io
        import joblib

        # 找待预测数据集：意图中的其他数据集，或同血缘的 raw_data
        dataset_ids = intent.get("dataset_ids") or []
        predict_ds_id = None
        source_desc = "意图指定"
        for did in dataset_ids:
            if did != model_ds.id:
                predict_ds_id = did
                break
        if predict_ds_id is None:
            # 同血缘最近的 raw_data / predict_data
            root = model_ds.root_dataset_id or model_ds.id
            candidates = self.db.query(Dataset).filter(
                Dataset.user_id == user_id,
                Dataset.status == "active",
                Dataset.root_dataset_id == root,
                Dataset.artifact_type.in_(["raw_data", "predict_data"])
            ).order_by(Dataset.id.desc()).all()
            if candidates:
                predict_ds_id = candidates[0].id
                source_desc = "血缘自动匹配"

        # 仍无待预测数据：自动回退到模型训练数据集（model_ds.parent_id）做全量预测
        # 这样用户只选了模型也能立即得到预测结果，而不是报"未找到待预测数据集"
        training_ds_id = None
        if not predict_ds_id and model_ds.parent_id:
            train_ds = self.db.query(Dataset).filter(
                Dataset.id == model_ds.parent_id,
                Dataset.user_id == user_id,
                Dataset.status == "active"
            ).first()
            if train_ds:
                training_ds_id = train_ds.id

        if not predict_ds_id and not training_ds_id:
            return {"success": False, "error": "未找到待预测数据集，请同时选择模型和待预测数据，或先关联训练数据"}

        to_encode_df = None
        if predict_ds_id:
            try:
                to_encode_df = self.data_service.load_dataset(predict_ds_id)
            except Exception:
                to_encode_df = None
        if to_encode_df is None and training_ds_id:
            predict_ds_id = training_ds_id
            source_desc = "训练数据回退"
            try:
                to_encode_df = self.data_service.load_dataset(training_ds_id)
            except Exception:
                return {"success": False, "error": "训练数据加载失败，无法回退预测"}

        try:
            model_bytes = self._read_file_bytes(model_ds)
            model_data = joblib.load(io.BytesIO(model_bytes))
            pipeline = model_data["pipeline"]
            feature_columns = model_data.get("feature_columns", [])
            label_encoder = model_data.get("label_encoder")
            target_column = model_data.get("target_column")
            task_type = model_data.get("task_type", "classification")
            feature_encoders = model_data.get("feature_encoders", {}) or {}
            model_algo = model_data.get("algorithm", "")

            df = to_encode_df.copy() if to_encode_df is not None else self.data_service.load_dataset(predict_ds_id)
            df = self._coerce_numeric(df)
            missing = [c for c in feature_columns if c not in df.columns]
            if missing:
                return {"success": False, "error": f"待预测数据缺少特征列: {missing}"}

            X = df[feature_columns].copy()
            # datetime 列转换为 timestamp（与训练一致）
            for col in X.select_dtypes(include=['datetime64', 'datetime']).columns:
                X[col] = pd.to_numeric(X[col], errors='coerce')
            # 低基数分类特征：用训练时编码器转换，未见类别映射为 NaN（与 ml.py 预测一致）
            for col in X.select_dtypes(include=['object', 'category']).columns:
                le = feature_encoders.get(col)
                if le is not None:
                    mask = X[col].notna()
                    if mask.any():
                        try:
                            X.loc[mask, col] = le.transform(X[col][mask].astype(str))
                        except ValueError:
                            X.loc[mask, col] = [
                                le.transform([str(v)])[0] if str(v) in le.classes_ else float("nan")
                                for v in X.loc[mask, col]
                            ]
                    X[col] = pd.to_numeric(X[col], errors='coerce')
                else:
                    X[col] = pd.to_numeric(X[col], errors='coerce')
            # 缺失值处理：非 NaN 原生支持算法填充
            from app.services.algorithm_registry import native_nan_support
            if not native_nan_support(model_algo):
                X = X.fillna(X.mean(numeric_only=True))
                X = X.fillna(0)

            y_pred = pipeline.predict(X)
            pred_col = "prediction"
            if label_encoder is not None and task_type == "classification":
                try:
                    df[pred_col] = label_encoder.inverse_transform(y_pred)
                except Exception:
                    df[pred_col] = y_pred
            else:
                df[pred_col] = y_pred

            # 汇总（精确）：TOP 分组分布 + 预测值统计
            summary = {"total": int(len(df)), "columns": list(df.columns[:50])}
            if task_type == "classification":
                vc = df[pred_col].value_counts()
                summary["top_predictions"] = [
                    {"value": self._json_safe(k), "count": int(v)}
                    for k, v in vc.head(20).items()
                ]
            else:
                summary["prediction_stats"] = {
                    "min": self._json_safe(df[pred_col].min()),
                    "max": self._json_safe(df[pred_col].max()),
                    "mean": self._json_safe(df[pred_col].mean())
                }
            # ===== 滚动外推一周期（仅当存在可识别的时间列）=====
            # 原理：将训练数据最新一条记录的时间特征前滚一个周期，其余特征保持，
            # 喂给模型得到"下一期"的预测值。这是对"预测未来"的轻量实现，不含新时序模型。
            forecast = None
            time_col = self._detect_time_column(predict_ds_id, df, feature_columns)
            if time_col and not task_type == "classification":
                try:
                    forecast = self._rolling_forecast(df, time_col, X, pipeline)
                except Exception as _fe:
                    forecast = {"error": f"时间外推失败: {str(_fe)}"}

            # 仅保留少量样本行注入 prompt（控制 token 消耗），精确汇总仍全量
            summary["sample_rows"] = df.head(10).to_dict(orient="records")
            if forecast is not None:
                summary["forecast"] = forecast

            # 预测数据来源标注（供前端/AI 说明是训练数据回退还是显式选择）
            summary["predict_source"] = source_desc
            summary["predict_dataset_name"] = self._dataset_label(predict_ds_id) or "?"

            return {
                "success": True,
                "result_type": "prediction",
                "result": summary,
                "computed_by": "ml_model",
                "dataset_labels": {model_ds.id: model_ds.name},
                "predict_dataset_id": predict_ds_id
            }
        except Exception as e:
            return {"success": False, "error": f"模型预测失败: {str(e)}"}

    def _dataset_label(self, dataset_id: int) -> str:
        """获取数据集名称（用于预测来源标注）"""
        if not dataset_id:
            return ""
        try:
            ds = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
            return ds.name if ds else ""
        except Exception:
            return ""

    def _detect_time_column(self, dataset_id, df, feature_columns):
        """检测数据中可用于滚动外推的时间列

        优先：feature_columns 中 datetime 类型，或名称含 时间/年/月/date/year/month 的数值列。
        返回列名或 None。
        """
        # 1) datetime/datetime64 类型列
        for col in df.columns:
            if str(df[col].dtype).startswith("datetime"):
                return col
        # 2) 名称含时间关键词的数值列（时间戳/年份）
        keywords = ("时间", "年", "月", "date", "year", "month", "time", "日期", "period", "周期")
        for col in feature_columns:
            if col in df.columns:
                low = str(col).lower()
                if any(k.lower() in low for k in keywords):
                    return col
        return None

    def _rolling_forecast(self, df, time_col, X, pipeline):
        """滚动外推一周期：取最新一条记录，把时间特征前滚一周期后预测

        时间列可能是 datetime64（直接步长+1）或数值（年份/月份，推测周期单位后 +1）。
        生成下一期预测，同时输出本期（最新记录）预测作为对比。
        """
        last_idx = X.index[-1]
        last_features = X.loc[[last_idx]].copy()
        raw = df[time_col]
        # 判断时间列类型：优先 datetime64；其次尝试将字符串日期（'YYYY-MM-DD' 等）解析为 datetime
        is_datetime = str(raw.dtype).startswith("datetime")
        if not is_datetime and raw.dtype == object:
            parsed = pd.to_datetime(raw, errors="coerce")
            if parsed.notna().sum() >= len(raw) * 0.8:
                df[time_col] = parsed
                raw = parsed
                is_datetime = True
        if is_datetime:
            last_time = df.loc[last_idx, time_col]
            # 推算步长：若为年/月粒度则 +1（月）+12（年以12个月计）
            # 简单策略：若值为 Timestamp，则推断频率，默认 +1 个月
            period = pd.DateOffset(months=1)
            next_time = last_time + period
            # 将下期时间填入特征（datetime64 列转为 timestamp 数值，与训练一致）
            next_features = last_features.copy()
            next_features[time_col] = pd.to_numeric(pd.Series([next_time]), errors="coerce").iloc[0]
        else:
            # 数值时间列（年份/月份）：推断周期
            series = pd.to_numeric(df[time_col], errors="coerce")
            diffs = series.dropna().diff().dropna()
            step = int(diffs.median()) if not diffs.empty and diffs.median() not in (0, None) else 1
            if step == 0 or pd.isna(step):
                step = 1
            last_val = series.loc[last_idx] if last_idx in series.index else series.iloc[-1]
            next_val = float(last_val) + step
            next_features = last_features.copy()
            next_features[time_col] = next_val

        # 对下期特征做与本期相同的编码后预测
        np_features = next_features.to_numpy()
        try:
            next_pred = pipeline.predict(np_features)[0]
        except Exception:
            next_pred = None

        current_pred = pipeline.predict(last_features.to_numpy())[0]
        # (label_encoder 反编码已在主流程处理，这里用原始预测值即可，交由 AI 解读)
        if np.isscalar(next_pred):
            next_time_str = str(next_time) if is_datetime else str(float(series.loc[last_idx]) + step)
            return {
                "period": "下一周期",
                "method": "滚动外推一周期（基于训练数据最新记录）",
                "current_prediction": self._json_safe(current_pred),
                "next_prediction": self._json_safe(next_pred),
                "time_column": time_col,
                "latest_time": str(df.loc[last_idx, time_col]),
                "next_time": next_time_str
            }
        return None

    def _read_file_bytes(self, ds: Dataset) -> bytes:
        """从本地/MinIO 读取模型文件字节（复用 storage_manager 路径）"""
        from app.services.storage_manager import storage_manager
        return storage_manager.get_file_bytes(ds.file_path)

    def _coerce_numeric(self, df: pd.DataFrame) -> pd.DataFrame:
        """将字符串数字列转为数值（远程加载常见），转换失败保留原样"""
        for col in df.columns:
            if df[col].dtype == object:
                converted = pd.to_numeric(df[col], errors="coerce")
                # 超过80%可转才生效，避免误伤分类列
                if converted.notna().sum() >= len(df) * 0.8:
                    df[col] = converted
        return df

    def _json_safe(self, value: Any) -> Any:
        """将 numpy 标量转 Python 原生类型（JSON 可序列化）"""
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass
        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
        return value

    # ========== 结果注入与主对话 ==========

    def _result_to_prompt(self, exec_result: Dict[str, Any]) -> str:
        """将计算结果转为注入主对话的文本（精确，供 AI 解读）"""
        if not exec_result.get("success"):
            return f"（计算失败：{exec_result.get('error', '未知错误')}）"

        labels = exec_result.get("dataset_labels", {})
        label_text = "、".join(str(v) for v in labels.values()) or "相关数据集"

        result = exec_result.get("result", {})
        if exec_result.get("result_type") == "group_hint":
            # 分组意图但缺列名：把候选分组列以自然语言呈现给 AI 做追问引导，不注入计算值
            candidates = result.get("candidate_columns", [])
            agg = result.get("aggregation") or "数量"
            cand_text = "、".join(f"「{c}」" for c in candidates[:12])
            return (
                f"【需要补充分组列】用户提出了分组统计意图（{agg}），但未指定按哪个字段分组。"
                f"请从候选字段中选择最合适的一个（或自然询问用户希望按哪个字段分组，例如：{cand_text}），"
                f"得到用户确认后再计算。请用自然、口语化的语气引导用户补充分组字段，不要罗列错误原因。"
            )
        if exec_result.get("result_type") == "aggregate":
            return (
                f"【后端已基于「{label_text}」精确计算得到以下结果（数值均为精确值，请直接用于回答）：】\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}\n"
            )
        if exec_result.get("result_type") == "rows":
            return (
                f"【后端已从「{label_text}」精确筛选出 {result.get('count', 0)} 行，以下为展示的前 {len(result.get('rows', []))} 行：】\n"
                f"{json.dumps(result.get('rows', []), ensure_ascii=False, default=str)}\n"
            )
        if exec_result.get("result_type") == "prediction":
            return (
                f"【基于模型对「{label_text}」的预测结果如下（请直接用于回答，并按外推时间自然呈现：】\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}\n"
            )
        if exec_result.get("result_type") == "profile":
            cols = result.get("columns", [])
            total = result.get("row_count", 0)
            lines = "\n".join(
                f"- {c['column']}（类型 {c['type']}）：缺失 {c['null_count']} 行（{c['null_rate'] * 100:.1f}%）"
                for c in cols
            )
            return (
                f"【基于「{label_text}」共 {total} 行，各列类型与缺失情况如下，请据此直接、自然地回答：】\n{lines}\n"
            )
        if exec_result.get("result_type") == "describe":
            cols = result.get("columns", [])
            total = result.get("row_count", 0)
            lines = "\n".join(
                f"- {c['column']}：样本 {c['count']}，均值 {c['mean']}，标准差 {c['std']}，"
                f"最小 {c['min']} / Q1 {c['q1']} / 中位数 {c['median']} / Q3 {c['q3']} / 最大 {c['max']}，"
                f"异常值（箱线图法则）{c['outlier_count']} 个（{c['outlier_rate'] * 100:.1f}%）"
                for c in cols
            )
            return (
                f"【基于「{label_text}」共 {total} 行，数值列分布统计与异常值检测结果如下"
                f"（异常值按四分位距 Q3-Q1 的 1.5 倍箱线图法则判定），请据此直接、自然地回答：】\n{lines}\n"
            )
        return "（无结果）"

    def chat_with_qa(
        self,
        question: str,
        dataset_ids: List[int],
        conversation_id: int = None,
        user_id: int = None,
        start_new_topic: bool = False
    ) -> Dict[str, Any]:
        """问答主流程：意图解析 → 本地计算 → 结果注入 → AI 解读

        Args:
            question: 用户问题
            dataset_ids: 数据目录的数据集ID列表（面板勾选/全选/常驻目录）
            conversation_id: 会话ID（可选）
            user_id: 用户ID
            start_new_topic: 是否开始新话题

        Returns:
            {"answer", "conversation_id", "usage", "needs_context", "suggested_questions",
             "relevant": bool, "exec_result": {...}（可选）}
        """
        client = self.ai_service._client_provider.get_default_client()
        if not client:
            return {"error": "请先配置API Key才能使用AI问答功能"}

        user_id = user_id or 1
        dataset_ids = dataset_ids or []

        # 获取或创建会话（问答使用独立 module_type=ai_qa）
        if conversation_id:
            conv = self.ai_service.get_conversation(conversation_id, user_id=user_id)
            if not conv:
                return {"error": "会话不存在"}
            if self.ai_service.is_conversation_expired(conv):
                return {"error": "会话已过期（长时间无活动），请开始新话题"}
            if getattr(conv, "follow_up_remaining", settings.AI_CONVERSATION_FOLLOWUP_MAX) <= 0:
                return {"error": "本话题追问次数已用完，请开启新会话继续提问"}
        else:
            title = question[:30] + ("..." if len(question) > 30 else "")
            conv = self.ai_service.create_conversation(
                dataset_id=None, module_type="ai_qa", initial_message=title, user_id=user_id
            )

        if start_new_topic and conversation_id:
            self.ai_service._save_message(conv.id, "system",
                                          "[话题切换] 用户已开始新话题，之前的数据与讨论不再相关，请基于当前问题重新分析。", None)

        # 构建目录（数据目录来自勾选集合）
        catalog = self.build_catalog(dataset_ids, user_id)
        if not catalog.get("datasets"):
            self._record_qa_message(conv.id, question, "数据目录为空，请先在左侧选择数据集或选择已保存的目录。", 0)
            return {
                "answer": "数据目录为空。请在左侧勾选数据产物（可多选/全选）或选择一个已保存的目录后重试。",
                "conversation_id": conv.id,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "needs_context": [],
                "relevant": False,
                "suggested_questions": []
            }

        # ===== 第一步：意图解析 =====
        intent_result = self.resolve_query_intent(question, catalog, user_id)
        print(f"[QA-DEBUG] resolve_query_intent 结果: {json.dumps(intent_result, ensure_ascii=False, default=str)[:500]}", flush=True)
        if "error" in intent_result:
            return {"error": intent_result["error"]}

        total_usage = dict(intent_result.get("usage") or {})
        intent = intent_result.get("intent") if intent_result.get("relevant") else None

        # 无关问题拦截：列举目录
        if intent is None:
            catalog_list = "\n".join(
                f"- #{d['dataset_id']} {d['name']}（{d['artifact_type'] or '未知'}）"
                for d in catalog["datasets"][:20]
            )
            answer = (
                f"在您当前选择的数据目录中，未找到与该问题相关的数据表（目录包含：\n{catalog_list}）。\n"
                f"您可以：1) 勾选更多数据产物后重试；2) 检查问题表述是否与现有字段匹配；3) 选择已保存的常驻目录。"
            )
            self._record_qa_message(conv.id, question, answer, total_usage.get("total_tokens", 0))
            return {
                "answer": answer,
                "conversation_id": conv.id,
                "usage": total_usage,
                "needs_context": [],
                "relevant": False,
                "suggested_questions": []
            }

        # ===== 第二步：本地精确计算 =====
        exec_result = self.execute_intent(intent, user_id)
        result_text = self._result_to_prompt(exec_result)
        if "error" in intent_result:
            pass  # 已在上面处理

        # ===== 第三步：结果注入主对话，AI 解读 =====

        history_messages = self.ai_service._load_conversation_messages(conv)
        all_messages = [{"role": "system", "content": SYSTEM_QA}]
        history_only = [m for m in history_messages if m["role"] in ("user", "assistant")]
        historical_summary = getattr(conv, "summary", None)
        try:
            from app.services.ai_context import compress_conversation
            compressed = compress_conversation(history_only, historical_summary)
        except Exception:
            compressed = {"messages": history_only[-8:], "new_summary": None}
        for msg in compressed["messages"]:
            all_messages.append(msg)

        user_payload = f"【用户问题】\n{question}\n\n{result_text}\n\n请基于以上结果回答用户问题。"
        all_messages.append({"role": "user", "content": user_payload})

        try:
            model_name = self.ai_service._get_model_name()
            response = client.chat.completions.create(
                model=model_name,
                messages=all_messages,
                temperature=0.3,
                max_tokens=2500
            )
            answer = response.choices[0].message.content
            usage = self._extract_usage(response)
            for k, v in usage.items():
                total_usage[k] = total_usage.get(k, 0) + v

            # 追问建议解析（复用）
            suggested_questions, answer = self.ai_service._parse_suggested_followups(answer)

            self._record_qa_message(conv.id, question, answer, total_usage.get("total_tokens", 0))

            # 更新会话状态
            conv.follow_up_remaining = max(0, getattr(conv, "follow_up_remaining", settings.AI_CONVERSATION_FOLLOWUP_MAX) - 1)
            conv.expires_at = __import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(
                minutes=settings.AI_CONVERSATION_TTL_MINUTES)
            if compressed.get("new_summary"):
                conv.summary = compressed["new_summary"]

            # 保存本次选择的数据目录快照，便于从历史会话恢复上一轮的数据集上下文
            conv.last_context_items = [
                {
                    "type": "dataset",
                    "ref_id": d["dataset_id"],
                    "label": f"{d['name']} (ID:{d['dataset_id']})",
                    "artifact_type": d.get("artifact_type"),
                    "artifact_label": d.get("artifact_type") or d.get("module_label")
                }
                for d in catalog["datasets"]
            ]
            self.db.commit()

            self.ai_service._log_usage(
                conversation_id=conv.id, module_type="ai_qa",
                prompt_tokens=total_usage.get("prompt_tokens", 0),
                completion_tokens=total_usage.get("completion_tokens", 0),
                total_tokens=total_usage.get("total_tokens", 0)
            )

            return {
                "answer": answer,
                "conversation_id": conv.id,
                "usage": total_usage,
                "needs_context": [],
                "relevant": True,
                "exec_result": exec_result,
                "suggested_questions": suggested_questions
            }
        except Exception as e:
            return {"error": f"AI回复生成失败: {str(e)}"}

    def _record_qa_message(self, conversation_id: int, question: str, answer: str, total_tokens: int = 0):
        """保存问答消息到 ai_messages 与 conversation JSON（兼容历史）"""
        self.ai_service._save_message(conversation_id, "user", question, None)
        self.ai_service._save_message(conversation_id, "assistant", answer, None, total_tokens)
        conv = self.db.query(AIConversation).filter(AIConversation.id == conversation_id).first()
        if conv:
            updated = list(conv.conversation) if conv.conversation else []
            updated.append({"role": "user", "content": question})
            updated.append({"role": "assistant", "content": answer})
            self.ai_service.update_conversation(conversation_id, updated)

    # ========== 常驻目录管理 ==========

    def list_catalogs(self, user_id: int) -> List[Dict[str, Any]]:
        """列出用户保存的常驻目录"""
        from app.models import DataCatalog
        catalogs = self.db.query(DataCatalog).filter(DataCatalog.user_id == user_id).order_by(DataCatalog.id.desc()).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "dataset_ids": [e["dataset_id"] for e in (c.dataset_entries or [])],
                "is_default": c.is_default,
                "created_at": c.created_at.isoformat() if c.created_at else None
            }
            for c in catalogs
        ]

    def save_catalog(self, name: str, dataset_ids: List[int], user_id: int,
                     description: str = "", catalog_id: int = None) -> Dict[str, Any]:
        """保存/更新常驻目录"""
        from app.models import DataCatalog
        if not name.strip():
            return {"error": "目录名称不能为空"}
        if not dataset_ids:
            return {"error": "目录至少需要包含一个数据集"}

        entries = [{"dataset_id": int(did)} for did in dataset_ids]

        if catalog_id:
            catalog = self.db.query(DataCatalog).filter(
                DataCatalog.id == catalog_id, DataCatalog.user_id == user_id
            ).first()
            if not catalog:
                return {"error": "目录不存在"}
            catalog.name = name.strip()
            catalog.description = description
            catalog.dataset_entries = entries
            self.db.commit()
            return {"success": True, "catalog_id": catalog.id}

        catalog = DataCatalog(
            user_id=user_id,
            name=name.strip(),
            description=description,
            dataset_entries=entries
        )
        self.db.add(catalog)
        self.db.commit()
        self.db.refresh(catalog)
        return {"success": True, "catalog_id": catalog.id}

    def delete_catalog(self, catalog_id: int, user_id: int) -> Dict[str, Any]:
        """删除常驻目录"""
        from app.models import DataCatalog
        catalog = self.db.query(DataCatalog).filter(
            DataCatalog.id == catalog_id, DataCatalog.user_id == user_id
        ).first()
        if not catalog:
            return {"error": "目录不存在"}
        self.db.delete(catalog)
        self.db.commit()
        return {"success": True}
