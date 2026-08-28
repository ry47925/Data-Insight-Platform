import json
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Dataset, AIConversation
from app.services.ai_service import AIService
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
        client = self.ai_service._get_clients().get(self.ai_service._default_client)
        if not client:
            return {"error": "请先配置API Key才能使用AI问答功能"}

        if not catalog.get("datasets"):
            return {"relevant": False, "reason": "数据目录为空，请先在左侧选择数据集或保存的目录"}

        catalog_text = self._catalog_to_prompt(catalog)

        system_intent = """你是数据问答意图解析器。用户会给出数据目录和一个问题，你需要：
1. 判断目录中是否有与问题相关的数据表（可从表名、字段名、字段类型判断）。
2. 如果完全没有相关表，返回 {"relevant": false, "reason": "简述为什么无关"}。
3. 如果相关，返回结构化查询意图 JSON：
{
  "relevant": true,
  "intent": {
    "dataset_ids": [相关数据集ID],
    "target_column": "要统计/预测的列名（若无填 null）",
    "aggregation": "count/sum/mean/max/min/groupby/filter/null（count=计数，filter=只筛选不聚合）",
    "group_by": "分组维度列名（如省份/年份，无则 null）",
    "filters": [{"column": "列名", "op": "eq/gt/lt/gte/lte/contains/in", "value": 值或数组}],
    "time_column": "时间列名（若问题涉及年份/日期则填，无则 null）",
    "time_range": {"start": "2020-01-01", "end": "2023-12-31"} 或 null,
    "needs_model": false,
    "reasoning": "一句话说明你的选择依据"
  }
}
规则：
- 只允许使用目录中出现过的字段名，不能虚构字段。
- aggregation=count 时 target_column 可为 null；group_by 存在时用 groupby。
- **预测类问题（"预测/用XX模型/对未来XX"）：目录中存在 ml_model 数据集时必须设 needs_model=true**，并在 dataset_ids 里同时包含该模型数据集和待预测数据集的ID。这是硬性要求：只要用户提到"预测""模型""明年/未来产量"等词，就必须走 needs_model=true，不能退化为对现有字段的 count/groupby 统计。
- 纯统计问题（"平均/总数/占比/分布"等）才用 aggregation/group_by，且不设 needs_model。
- 时间列若为数值年份（如 2023），直接作为数值处理，filters 中用 eq/gt 等即可。
"""
        user_intent = f"【数据目录】\n{catalog_text}\n\n【用户问题】\n{question}"

        try:
            model_name = self.ai_service._get_model_name()
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_intent},
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
            return {**parsed, "usage": usage}
        except Exception as e:
            return {"error": f"意图解析失败: {str(e)}"}

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

        try:
            return self._aggregate_dataframe(df, ds, intent)
        except Exception as e:
            return {"success": False, "error": f"聚合计算失败: {str(e)}"}

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

        if not predict_ds_id:
            return {"success": False, "error": "未找到待预测数据集，请同时选择模型和待预测数据"}

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

            df = self.data_service.load_dataset(predict_ds_id)
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
            # 若存在年份列，给出分年汇总（可选）
            # 仅保留少量样本行注入 prompt（控制 token 消耗），精确汇总仍全量
            summary["sample_rows"] = df.head(10).to_dict(orient="records")

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
        label_text = ", ".join(f"#{k}({v})" for k, v in labels.items()) or "?"
        computed_by = exec_result.get("computed_by", "?")

        result = exec_result.get("result", {})
        if exec_result.get("result_type") == "aggregate":
            return (
                f"【后端已精确计算结果（来源数据集: {label_text}，计算方式: {computed_by}）】\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}\n"
            )
        if exec_result.get("result_type") == "rows":
            return (
                f"【后端已精确筛选结果（来源数据集: {label_text}，共 {result.get('count', 0)} 行，展示前 {len(result.get('rows', []))} 行）】\n"
                f"{json.dumps(result.get('rows', []), ensure_ascii=False, default=str)}\n"
            )
        if exec_result.get("result_type") == "prediction":
            return (
                f"【模型预测结果（模型: {label_text}，计算方式: {computed_by}）】\n"
                f"{json.dumps(result, ensure_ascii=False, default=str)}\n"
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
        client = self.ai_service._get_clients().get(self.ai_service._default_client)
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
        system_qa = """你是数据问答助手。用户会提供【后端已精确计算的结果】和原始问题，你需要：
1. 基于计算结果直接、准确地回答用户问题，数字必须与提供的结果一致，不得编造或改动。
2. 若计算失败或结果为空，如实说明原因，不要臆造数据。
3. 回答使用自然语言，简洁清晰；可以补充必要的解读（如对比、趋势），但不得脱离结果数据。
4. 若结果中只有部分信息，明确说明哪些已计算、哪些无法得出。
"""

        history_messages = self.ai_service._load_conversation_messages(conv)
        all_messages = [{"role": "system", "content": system_qa}]
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
