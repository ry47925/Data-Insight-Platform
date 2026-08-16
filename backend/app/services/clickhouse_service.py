"""
ClickHouse 分析加速服务（一期）

职责：
1. ClickHouse 可用性检测与客户端管理（HTTP 8123，clickhouse-connect）
2. 数据集数据副本同步（建表 / 分块 INSERT / 注册表 / 对拍校验）
3. 聚合分析查询原语，供 data_analysis.py 等模块走 ClickHouse 优先

降级约定（保证功能完整、无报错、准确分析）：
- clickhouse-connect 未安装 / CLICKHOUSE_ENABLED=false → 全部功能禁用，调用方回退 pandas
- 查询超时 / 连接失败 / SQL 不兼容 → 抛出 ClickHouseUnavailable，调用方捕获后回退 pandas
- 同步失败只影响副本状态（registry.status=failed），不影响主流程（上传/导入仍成功）
- 对拍校验不通过 → 副本标记 failed，分析回退 pandas，绝不返回偏差数据
"""
import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.config import settings

# clickhouse-connect 可选导入：未安装时功能禁用，自动降级 pandas
try:
    import clickhouse_connect
    _CH_CLIENT_AVAILABLE = True
except ImportError:
    clickhouse_connect = None
    _CH_CLIENT_AVAILABLE = False


class ClickHouseUnavailable(Exception):
    """ClickHouse 不可用/查询失败信号，调用方捕获后回退 pandas"""
    pass


# 标识符白名单（支持中文等 Unicode 字母/数字/下划线，防 SQL 注入）
# Python 3 re 默认 Unicode 模式：\w 匹配中英文、数字、下划线；反引号/引号/空格/运算符等一律拒绝，
# 规避 ClickHouse 标识符注入与表/列名解析歧义（如"年龄"这类中文列名可正常同步）。
_IDENTIFIER_PATTERN = re.compile(r'^\w+$')

# ClickHouse 库内表名
_REGISTRY_TABLE = "dataset_registry"
_DATASET_TABLE_PREFIX = "ds_"


def _ch_now() -> str:
    """当前时间（ClickHouse DateTime64 字符串，UTC）"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


class ClickHouseService:
    """ClickHouse 分析加速服务（可用性 / 同步 / 注册表 / 查询原语）"""

    def __init__(self):
        self._client = None
        self._available_cache: Optional[bool] = None
        self._last_check_at = 0.0
        # 可用性缓存间隔（秒）：避免每个分析请求都探测 CH
        self._check_interval = 10.0
        # 线程锁：clickhouse-connect 的 client 不允许同一 session 并发查询
        # （FastAPI 多 worker/多请求并发调用会抛
        #  "Attempt to execute concurrent queries within the same session"），
        # 所有 client 操作串行化执行
        self._lock = threading.RLock()

    # ==================== 可用性与客户端 ====================

    def is_enabled(self) -> bool:
        """功能是否启用（配置开关 + 依赖已安装）"""
        return bool(settings.CLICKHOUSE_ENABLED) and _CH_CLIENT_AVAILABLE

    def is_available(self, refresh: bool = False) -> bool:
        """ClickHouse 是否可用（ping + 确保 analysis 库存在），带短缓存"""
        if not self.is_enabled():
            return False
        now = time.time()
        if not refresh and self._available_cache is not None and now - self._last_check_at < self._check_interval:
            return self._available_cache
        try:
            self._command("SELECT 1")
            db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
            self._command(f"CREATE DATABASE IF NOT EXISTS {db}")
            self._available_cache = True
        except Exception as e:
            print(f"⚠️ ClickHouse 不可用，降级 pandas: {e}")
            self._available_cache = False
        self._last_check_at = now
        return bool(self._available_cache)

    def _get_client(self):
        """获取 ClickHouse HTTP 客户端（懒初始化，加锁防并发重复创建）"""
        if not self.is_enabled():
            raise ClickHouseUnavailable("ClickHouse 未启用")
        with self._lock:
            if self._client is None:
                self._client = clickhouse_connect.get_client(
                    host=settings.CLICKHOUSE_HOST,
                    port=settings.CLICKHOUSE_PORT,
                    username=settings.CLICKHOUSE_USER,
                    password=settings.CLICKHOUSE_PASSWORD,
                    database=settings.CLICKHOUSE_DATABASE,
                    connect_timeout=settings.CLICKHOUSE_QUERY_TIMEOUT,
                    send_receive_timeout=settings.CLICKHOUSE_QUERY_TIMEOUT,
                )
            return self._client

    def _command(self, sql: str, parameters: Optional[dict] = None):
        """线程安全的 client.command（单 client 不支持并发查询，统一加锁串行化）"""
        with self._lock:
            return self._get_client().command(sql, parameters=parameters)

    def _validate_identifier(self, name: str, label: str = "标识符") -> str:
        """校验 SQL 标识符（表名/列名），拒绝非法字符防注入"""
        if not name or not _IDENTIFIER_PATTERN.match(name):
            raise ValueError(f"非法{label}: {name}")
        return name

    # ==================== 类型映射 ====================

    def map_dtype(self, dtype: str) -> str:
        """pandas dtype 字符串 -> ClickHouse 类型（统一 Nullable 兼容 NaN）"""
        dtype = str(dtype)
        if dtype.startswith('int'):
            return 'Nullable(Int64)'
        if dtype.startswith('float'):
            return 'Nullable(Float64)'
        if dtype.startswith('bool'):
            return 'Nullable(UInt8)'
        if dtype.startswith('datetime'):
            return 'Nullable(DateTime64(3))'
        return 'Nullable(String)'

    def _schema_from_df(self, df: pd.DataFrame) -> Dict[str, str]:
        """从 DataFrame 生成 {列名: dtype 字符串} schema（与 DataService.get_schema 一致）"""
        return {col: str(df[col].dtype) for col in df.columns}

    def _normalize_for_insert(self, df: pd.DataFrame) -> None:
        """插入前原地归一化，保证 clickhouse-connect 可正确写入

        兼容 pandas 版本差异（本地 2.x 与镜像 3.x 对日期字符串的推断不同）：
        - pandas 3.0 会把 '2023-01-01' 之类的 object 列推断为 datetime.date 对象，
          写入 String 列时报 "'datetime.date' object has no attribute 'encode'"
        - 处理：datetime64 列统一为 datetime64[ns]；object 列含 date/datetime 对象时转字符串
        """
        import datetime as _dt

        for col in df.columns:
            dtype = df[col].dtype
            if pd.api.types.is_datetime64_any_dtype(dtype):
                if str(dtype) != "datetime64[ns]":
                    df[col] = df[col].astype("datetime64[ns]")
            elif dtype == object:
                non_null = df[col].dropna()
                if len(non_null) > 0 and isinstance(
                    non_null.iloc[0], (_dt.date, _dt.datetime, pd.Timestamp)
                ):
                    df[col] = df[col].apply(
                        lambda v: v.strftime('%Y-%m-%d %H:%M:%S')
                        if isinstance(v, (_dt.date, _dt.datetime, pd.Timestamp)) and not pd.isna(v)
                        else (None if pd.isna(v) else v)
                    )

    # ==================== 注册表（dataset_registry）====================

    def _ensure_registry(self) -> None:
        """确保注册表存在（幂等）"""
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        self._command(f"""
            CREATE TABLE IF NOT EXISTS {db}.{_REGISTRY_TABLE} (
                dataset_id UInt64,
                table_name String,
                dataset_name String,
                row_count UInt64,
                columns_json String,
                data_version UInt64,
                status String,
                synced_at DateTime64(3),
                last_error String
            ) ENGINE = MergeTree ORDER BY dataset_id
        """)

    def registry_get(self, dataset_id: int) -> Optional[dict]:
        """查询注册表记录（未同步返回 None）

        ORDER BY data_version DESC：ClickHouse 的 DELETE 为异步 mutation，重建同步时
        旧记录可能短暂存在，按版本号取最新记录，避免读到过期状态。
        """
        try:
            self._ensure_registry()
            db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
            rows = self._query_rows(
                f"SELECT * FROM {db}.{_REGISTRY_TABLE} "
                f"WHERE dataset_id = {int(dataset_id)} "
                f"ORDER BY data_version DESC, synced_at DESC LIMIT 1")
            return rows[0] if rows else None
        except ClickHouseUnavailable:
            raise
        except Exception as e:
            print(f"⚠️ ClickHouse 注册表查询失败: {e}")
            raise ClickHouseUnavailable(f"注册表查询失败: {e}")

    def registry_upsert(self, dataset_id: int, dataset_name: str = "", table_name: str = "",
                        row_count: int = 0, columns_json: str = "", data_version: int = 1,
                        status: str = "synced", last_error: str = "") -> None:
        """写入/更新注册表记录（删除旧记录后插入，保证幂等）"""
        self._ensure_registry()
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        self._command(
            f"DELETE FROM {db}.{_REGISTRY_TABLE} WHERE dataset_id = {{did:UInt64}}",
            parameters={"did": int(dataset_id)},
        )
        self._command(
            f"""INSERT INTO {db}.{_REGISTRY_TABLE}
                (dataset_id, table_name, dataset_name, row_count, columns_json,
                 data_version, status, synced_at, last_error)
                VALUES ({{did:UInt64}}, {{tbl:String}}, {{dname:String}}, {{rc:UInt64}},
                        {{cj:String}}, {{dv:UInt64}}, {{st:String}}, {{stime:DateTime64(3)}}, {{err:String}})""",
            parameters={
                "did": int(dataset_id), "tbl": table_name or self.table_name(dataset_id),
                "dname": dataset_name, "rc": int(row_count or 0), "cj": columns_json or "{}",
                "dv": int(data_version), "st": status, "stime": _ch_now(), "err": last_error or "",
            },
        )

    def registry_delete(self, dataset_id: int) -> None:
        """删除注册表记录"""
        try:
            self._ensure_registry()
            db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
            self._command(
                f"DELETE FROM {db}.{_REGISTRY_TABLE} WHERE dataset_id = {{did:UInt64}}",
                parameters={"did": int(dataset_id)},
            )
        except Exception as e:
            print(f"⚠️ ClickHouse 注册表删除失败: {e}")

    def registry_list(self) -> List[dict]:
        """全部注册表记录（管理端展示用）"""
        self._ensure_registry()
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        return self._query_rows(f"SELECT * FROM {db}.{_REGISTRY_TABLE} ORDER BY dataset_id")

    # ==================== 数据集副本表 ====================

    def table_name(self, dataset_id: int) -> str:
        return f"{_DATASET_TABLE_PREFIX}{int(dataset_id)}"

    def ensure_dataset_table(self, dataset_id: int, columns_schema: Dict[str, str]) -> None:
        """全量覆盖建表（DROP + CREATE），schema 来自 pandas dtype 映射"""
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        self._command(f"DROP TABLE IF EXISTS {db}.{tbl}")
        col_defs = []
        for col, dtype in columns_schema.items():
            safe_col = self._validate_identifier(str(col), f"列名: {col}")
            col_defs.append(f"`{safe_col}` {self.map_dtype(dtype)}")
        if not col_defs:
            raise ValueError("数据集无列，无法同步")
        ddl = (f"CREATE TABLE {db}.{tbl} (\n  " + ",\n  ".join(col_defs) + "\n)"
               f" ENGINE = MergeTree ORDER BY tuple()")
        self._command(ddl)

    def drop_dataset_table(self, dataset_id: int) -> None:
        """删除数据集副本表"""
        try:
            db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
            tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
            self._command(f"DROP TABLE IF EXISTS {db}.{tbl}")
        except Exception as e:
            print(f"⚠️ ClickHouse 副本表删除失败: {e}")

    # ==================== 查询原语 ====================

    def _query_rows(self, sql: str, timeout: Optional[int] = None,
                    parameters: Optional[dict] = None) -> List[dict]:
        """执行 SELECT 返回 dict 列表；失败抛 ClickHouseUnavailable

        parameters：命名参数 {name:Type} 语法对应的值字典，避免拼 SQL 注入与浮点格式化问题。
        """
        try:
            # 加锁串行化查询：clickhouse-connect 单 client 不允许并发查询
            with self._lock:
                client = self._get_client()
                result = client.query(sql, parameters=parameters)
                columns = list(result.column_names)
                return [dict(zip(columns, row)) for row in result.result_rows]
        except ClickHouseUnavailable:
            raise
        except Exception as e:
            raise ClickHouseUnavailable(f"ClickHouse 查询失败: {e}")

    def query(self, sql: str, timeout: Optional[int] = None,
              parameters: Optional[dict] = None) -> List[dict]:
        """对外查询入口（调用方需自行保证表名/列名已校验；parameters 为命名参数值字典）"""
        return self._query_rows(sql, timeout=timeout, parameters=parameters)


    # ==================== 分析聚合原语（批次C：statistics/quality/recommendations/chart）====================

    def _col_categories(self, columns_schema: Dict[str, str]):
        """按 pandas dtype 字符串分类列：数值 / 时间 / 分类（与 DataService 判定对齐）"""
        numeric, datetime_cols, categorical = [], [], []
        for col, dtype in columns_schema.items():
            d = str(dtype)
            if d.startswith(('int', 'float', 'bool')):
                numeric.append(col)
            elif d.startswith('datetime'):
                datetime_cols.append(col)
            else:
                categorical.append(col)
        return numeric, datetime_cols, categorical

    def _numeric_cols(self, columns_schema: Dict[str, str]) -> List[str]:
        """schema 中 dtype 为数值（int/float/bool）的列"""
        return [c for c, d in columns_schema.items() if str(d).startswith(('int', 'float', 'bool'))]

    def compute_statistics(self, dataset_id: int, columns_schema: Dict[str, str]) -> Dict[str, Any]:
        """CH 全量统计摘要，返回与 data_analysis 本地 pandas 统计一致的结构

        覆盖三部分（与 compute_numeric_stats / _compute_categorical_stats / _compute_basic_info 对齐）：
        - numeric_stats：全量聚合（均值/分位数/偏度/峰度/众数/零值/缺失）
        - categorical_stats：每列 top10 取值与占比（分类列含时间列）
        - basic_info：列类型/缺失/唯一值等基本信息
        失败抛 ClickHouseUnavailable，调用方捕获后回退 pandas。
        """
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        numeric, datetime_cols, categorical = self._col_categories(columns_schema)
        # 与 common.get_numeric_columns 对齐：统计模块中 bool 列不作为数值列（图表推荐判定则相反）
        bool_cols = [c for c in numeric if str(columns_schema[c]).startswith('bool')]
        numeric = [c for c in numeric if c not in bool_cols]
        # object 数字字符串列（>80% 非空值可转数值）对齐 pandas get_numeric_columns 视为数值列，
        # 复用 object_column_type 抽样判定（与图表推荐分支一致），避免同一列在 CH/pandas 统计中分类不同
        for col in list(categorical):
            if str(columns_schema[col]) in ("object", "str") \
                    and self.object_column_type(dataset_id, col) == "numeric":
                numeric.append(col)
                categorical.remove(col)
        # 分类列包含时间列与布尔列（与 pandas 的"非数值列即分类"判定一致）
        categorical = categorical + datetime_cols + bool_cols
        all_cols = numeric + categorical

        # 1. 主聚合查询：行数 + 数值列统计 + 全列缺失/唯一值
        exprs = ["count() AS __n__"]
        for col in numeric:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"sum(toFloat64(`{sc}`)) AS `__s_{sc}`")
            exprs.append(f"avg(toFloat64(`{sc}`)) AS `__a_{sc}`")
            exprs.append(f"stddevSamp(toFloat64(`{sc}`)) AS `__sd_{sc}`")
            exprs.append(f"min(toFloat64(`{sc}`)) AS `__mn_{sc}`")
            exprs.append(f"max(toFloat64(`{sc}`)) AS `__mx_{sc}`")
            exprs.append(
                f"quantilesExact(0.25, 0.5, 0.75, 0.9, 0.95, 0.99)(toFloat64(`{sc}`)) AS `__q_{sc}`")
            exprs.append(f"skewSamp(toFloat64(`{sc}`)) AS `__sk_{sc}`")
            exprs.append(f"kurtSamp(toFloat64(`{sc}`)) AS `__ku_{sc}`")
            exprs.append(f"countIf(toFloat64(`{sc}`) = 0) AS `__z_{sc}`")
            exprs.append(f"countIf(isInfinite(toFloat64(`{sc}`))) AS `__inf_{sc}`")
        for col in all_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"uniqExact(`{sc}`) AS `__u_{sc}`")
            exprs.append(f"count(`{sc}`) AS `__nn_{sc}`")
        row = self._query_rows(f"SELECT {', '.join(exprs)} FROM {db}.{tbl}")[0]
        total = int(row["__n__"] or 0)

        # 2. numeric_stats（对照 compute_numeric_stats）
        numeric_stats: Dict[str, Any] = {}
        for col in numeric:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            nn = int(row[f"__nn_{sc}"] or 0)
            missing_count = total - nn
            missing_rate = round(missing_count / total * 100, 2) if total > 0 else 0
            if nn > 0:
                q = row[f"__q_{sc}"] or [None] * 6
                mean_val = float(row[f"__a_{sc}"] or 0.0)
                std_val = float(row[f"__sd_{sc}"] or 0.0)
                cv = round(std_val / mean_val, 4) if mean_val != 0 else None
                zero_count = int(row[f"__z_{sc}"] or 0)
                # 含 ±inf 的列：pandas 的 std 为 NaN（JSON null），CH stddevSamp 返回 0.0，统一置 None
                inf_cnt = int(row[f"__inf_{sc}"] or 0)
                has_inf = inf_cnt > 0
                # kurtSamp 为普通峰度，pandas kurtosis() 默认减 3（Fisher 超额峰度）
                kurt_v = None if _f(row[f"__ku_{sc}"]) is None else _f(row[f"__ku_{sc}"]) - 3
                numeric_stats[col] = {
                    "mean": _round4(_f(row[f"__a_{sc}"])),
                    "median": _round4(_f(q[1])),
                    "std": None if has_inf else _round4(_f(row[f"__sd_{sc}"])),
                    "min": _round4(_f(row[f"__mn_{sc}"])),
                    "max": _round4(_f(row[f"__mx_{sc}"])),
                    "q25": _round4(_f(q[0])), "q50": _round4(_f(q[1])), "q75": _round4(_f(q[2])),
                    "p90": _round4(_f(q[3])), "p95": _round4(_f(q[4])), "p99": _round4(_f(q[5])),
                    "skewness": _round4(_f(row[f"__sk_{sc}"])),
                    "kurtosis": _round4(kurt_v),
                    "cv": None if has_inf else cv,
                    "mode": self._column_mode(db, tbl, sc),
                    "zero_count": zero_count,
                    "zero_rate": round(zero_count / nn * 100, 2),
                    "unique_count": int(row[f"__u_{sc}"] or 0),
                    "missing_count": missing_count,
                    "missing_rate": missing_rate,
                }
            else:
                numeric_stats[col] = {
                    "mean": None, "median": None, "std": None,
                    "min": None, "max": None,
                    "q25": None, "q50": None, "q75": None,
                    "p90": None, "p95": None, "p99": None,
                    "skewness": None, "kurtosis": None,
                    "cv": None, "mode": None,
                    "zero_count": 0, "zero_rate": 0,
                    "unique_count": 0,
                    "missing_count": missing_count,
                    "missing_rate": missing_rate,
                }

        # 3. categorical_stats（对照 _compute_categorical_stats）
        categorical_stats: Dict[str, Any] = {}
        for col in categorical:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            nn = int(row[f"__nn_{sc}"] or 0)
            missing_count = total - nn
            top_values = []
            if nn > 0:
                top_rows = self._query_rows(
                    f"SELECT toString(`{sc}`) AS `k`, count() AS `cnt` "
                    f"FROM {db}.{tbl} WHERE `{sc}` IS NOT NULL "
                    f"GROUP BY `k` ORDER BY `cnt` DESC, `k` ASC LIMIT 10"
                )
                for tr in top_rows:
                    top_values.append({
                        "value": str(tr["k"]),
                        "count": int(tr["cnt"]),
                        "rate": round(int(tr["cnt"]) / nn * 100, 2),
                    })
            categorical_stats[col] = {
                "unique_count": int(row[f"__u_{sc}"] or 0),
                "missing_count": missing_count,
                "missing_rate": round(missing_count / total * 100, 2) if total > 0 else 0,
                "top_values": top_values,
            }

        # 4. basic_info（对照 _compute_basic_info）
        numeric_set = set(numeric)
        columns_info = []
        for col in all_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            missing_count = total - int(row[f"__nn_{sc}"] or 0)
            unique_count = int(row[f"__u_{sc}"] or 0)
            columns_info.append({
                "name": col,
                "type": str(columns_schema[col]),
                "is_numeric": col in numeric_set,
                "missing_count": missing_count,
                "missing_rate": round(missing_count / total * 100, 2) if total > 0 else 0,
                "unique_count": unique_count,
                "is_constant": unique_count == 1,
                "missing_too_many": (missing_count / total) > 0.5 if total > 0 else False,
            })
        return {
            "numeric_stats": numeric_stats,
            "categorical_stats": categorical_stats,
            "basic_info": {
                "row_count": total,
                "column_count": len(all_cols),
                "numeric_count": len(numeric),
                "categorical_count": len(all_cols) - len(numeric),
                "columns": columns_info,
            },
        }

    def _column_mode(self, db: str, tbl: str, sc: str) -> Any:
        """列众数（出现次数最多的取值），无值时返回 None"""
        rows = self._query_rows(
            f"SELECT `{sc}` AS `m` FROM {db}.{tbl} WHERE `{sc}` IS NOT NULL "
            f"GROUP BY `m` ORDER BY count() DESC, `m` ASC LIMIT 1"
        )
        if not rows or rows[0].get("m") is None:
            return None
        val = rows[0]["m"]
        if isinstance(val, bool):
            return bool(val)
        if isinstance(val, int):
            return int(val)
        if isinstance(val, float):
            return float(val)
        return str(val)

    def compute_quality(self, dataset_id: int, columns_schema: Dict[str, str]) -> Dict[str, Any]:
        """CH 全量数据质量检测，返回与 data_analysis 本地质量检测一致的结构

        - 缺失列：count(col) < count(*)
        - 常量列：uniqExact(col) <= 1
        - 重复行：count() - uniqExact(tuple(全列))（等价 pandas duplicated().sum()）
        - 无穷列：仅 Float64 列可检测 isInfinite
        失败抛 ClickHouseUnavailable，调用方捕获后回退 pandas。
        """
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        all_cols = list(columns_schema.keys())
        float_cols = [c for c, d in columns_schema.items() if str(d).startswith('float')]

        exprs = ["count() AS __n__"]
        for col in all_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"count(`{sc}`) AS `__nn_{sc}`")
            exprs.append(f"uniqExact(`{sc}`) AS `__u_{sc}`")
        for col in float_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"countIf(isInfinite(`{sc}`)) AS `__inf_{sc}`")
        tuple_expr = ", ".join(
            f"`{self._validate_identifier(str(c), f'列名: {c}')}`" for c in all_cols)
        exprs.append(f"uniqExact(tuple({tuple_expr})) AS __ur__")
        row = self._query_rows(f"SELECT {', '.join(exprs)} FROM {db}.{tbl}")[0]

        total = int(row["__n__"] or 0)
        # 与 common.check_data_quality 对齐：nan_columns 仅统计数值列缺失（非数值列不检测）
        nan_columns = [
            c for c in all_cols
            if str(columns_schema[c]).startswith(('int', 'float', 'bool'))
            and (total - int(row[f"__nn_{self._validate_identifier(str(c))}"] or 0)) > 0
        ]
        constant_columns = [
            c for c in all_cols if int(row[f"__u_{self._validate_identifier(str(c))}"] or 0) <= 1
        ]
        infinite_columns = [
            c for c in float_cols if int(row[f"__inf_{self._validate_identifier(str(c))}"] or 0) > 0
        ]
        unique_rows = int(row["__ur__"] or 0)
        duplicate_rows = max(0, total - unique_rows)
        total_cells = total * len(all_cols) if all_cols else 0
        total_missing = sum(
            max(0, total - int(row[f"__nn_{self._validate_identifier(str(c))}"] or 0)) for c in all_cols
        )
        overall_missing_rate = round(total_missing / total_cells * 100, 2) if total_cells > 0 else 0

        return {
            "overall_missing_rate": overall_missing_rate,
            "missing_columns_count": len(nan_columns),
            "infinite_columns": infinite_columns,
            "duplicate_rows": duplicate_rows,
            "constant_columns": constant_columns,
        }

    def compute_column_profiles(self, dataset_id: int, columns_schema: Dict[str, str],
                                columns: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """列画像：唯一值数/缺失数/数值列 min-max 与四分位数（供图表推荐复用）

        columns：指定列名列表（可选），缺省为全部列。
        失败抛 ClickHouseUnavailable，调用方捕获后回退 pandas。
        """
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        target = list(columns_schema.keys()) if not columns \
            else [c for c in columns if c in columns_schema]
        numeric = [c for c in target if str(columns_schema[c]).startswith(('int', 'float', 'bool'))]

        exprs = ["count() AS __n__"]
        for col in target:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"uniqExact(`{sc}`) AS `__u_{sc}`")
            exprs.append(f"count(`{sc}`) AS `__nn_{sc}`")
        for col in numeric:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"min(`{sc}`) AS `__mn_{sc}`")
            exprs.append(f"max(`{sc}`) AS `__mx_{sc}`")
            exprs.append(f"quantilesExact(0.25, 0.75)(toFloat64(`{sc}`)) AS `__q_{sc}`")
        row = self._query_rows(f"SELECT {', '.join(exprs)} FROM {db}.{tbl}")[0]

        total = int(row["__n__"] or 0)
        profiles: Dict[str, Dict[str, Any]] = {}
        for col in target:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            dtype = str(columns_schema[col])
            nn = int(row[f"__nn_{sc}"] or 0)
            p = {
                "name": col,
                "dtype": dtype,
                "is_numeric": col in numeric,
                "is_datetime": dtype.startswith('datetime'),
                "unique_count": int(row[f"__u_{sc}"] or 0),
                "missing_count": total - nn,
                "total": total,
            }
            if col in numeric:
                p["min"] = row[f"__mn_{sc}"]
                p["max"] = row[f"__mx_{sc}"]
                q = row[f"__q_{sc}"] or [None, None]
                p["q1"] = q[0]
                p["q3"] = q[1]
            profiles[col] = p
        return profiles

    def object_column_type(self, dataset_id: int, col: str, limit: int = 1000) -> str:
        """抽样判定 object 列在 pandas 视角下的类型：numeric / datetime / categorical

        同步后 object 列在 CH 中为 String，SQL 无法推断其"数字字符串/日期字符串"语义，
        这里抽样 1000 行用 pandas 判定，与 data_analysis._is_numeric_column/_is_datetime_column
        的对齐（成功率 >80% 视为数值列）。
        """
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        sc = self._validate_identifier(str(col), f"列名: {col}")
        rows = self._query_rows(
            f"SELECT `{sc}` AS `v` FROM {db}.{tbl} WHERE `{sc}` IS NOT NULL LIMIT {int(limit)}")
        values = [r["v"] for r in rows]
        if not values:
            return "categorical"
        s = pd.Series(values)
        converted = pd.to_numeric(s, errors='coerce')
        if converted.notna().sum() / len(values) > 0.8:
            return "numeric"
        try:
            pd.to_datetime(values, errors='raise')
            return "datetime"
        except (ValueError, TypeError):
            return "categorical"

    def numeric_extras(self, dataset_id: int, columns: List[str]) -> Dict[str, Dict[str, Any]]:
        """对指定列补充数值画像（min/max/q1/q3），支持 String 数字列 toFloat64 转换

        供图表推荐中 object 数字字符串列使用，使其画像与 pandas 数值列对齐。
        """
        if not columns:
            return {}
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        exprs = []
        for col in columns:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"min(toFloat64(`{sc}`)) AS `__mn_{sc}`")
            exprs.append(f"max(toFloat64(`{sc}`)) AS `__mx_{sc}`")
            exprs.append(f"quantilesExact(0.25, 0.75)(toFloat64(`{sc}`)) AS `__q_{sc}`")
        row = self._query_rows(f"SELECT {', '.join(exprs)} FROM {db}.{tbl}")[0]
        out: Dict[str, Dict[str, Any]] = {}
        for col in columns:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            q = row[f"__q_{sc}"] or [None, None]
            out[col] = {"min": row[f"__mn_{sc}"], "max": row[f"__mx_{sc}"],
                        "q1": q[0], "q3": q[1]}
        return out

    def count_outliers(self, dataset_id: int, thresholds: Dict[str, tuple]) -> Dict[str, int]:
        """按 (lower, upper) 区间统计每列离群值数量（IQR 法，忽略 NULL 与 pandas 一致）"""
        if not thresholds:
            return {}
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        exprs = []
        params = {}
        for i, (col, (lo, up)) in enumerate(thresholds.items()):
            sc = self._validate_identifier(str(col), f"列名: {col}")
            # 命名参数名用序号（lo_0/up_0…），不能拼中文列名：clickhouse-connect 的
            # {name:Type} 语法要求 name 为 ASCII 标识符，中文列名会导致 SYNTAX_ERROR
            exprs.append(
                f"countIf(toFloat64(`{sc}`) < {{lo_{i}:Float64}} "
                f"OR toFloat64(`{sc}`) > {{up_{i}:Float64}}) AS `__out_{sc}`")
            params[f"lo_{i}"] = float(lo)
            params[f"up_{i}"] = float(up)
        row = self._query_rows(
            f"SELECT {', '.join(exprs)} FROM {db}.{tbl}", parameters=params)[0]
        return {col: int(row[f"__out_{self._validate_identifier(str(col))}"] or 0) for col in thresholds}

    def compute_chart_agg(self, dataset_id: int, chart_type: str, params: Dict[str, Any],
                          columns_schema: Dict[str, str]) -> Dict[str, Any]:
        """聚合型图表数据 CH 全量计算（histogram / bar / stacked_bar / pie）

        仅支持这四类聚合型图表；其余类型抛 ClickHouseUnavailable，调用方回退 pandas。
        object 列的角色判定用抽样与 pandas 对齐：被当数值列使用时回退 pandas。
        失败抛 ClickHouseUnavailable / ValueError，调用方捕获后回退 pandas。
        """
        if chart_type not in {"histogram", "bar", "stacked_bar", "pie"}:
            raise ClickHouseUnavailable(f"图表类型 {chart_type} 不在 CH 加速范围")
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")
        if chart_type == "histogram":
            return self._chart_histogram(db, tbl, dataset_id, params, columns_schema)
        if chart_type == "pie":
            return self._chart_pie(db, tbl, dataset_id, params, columns_schema)
        return self._chart_bar(db, tbl, dataset_id, params, columns_schema,
                               stacked=(chart_type == "stacked_bar"))

    def _chart_histogram(self, db: str, tbl: str, dataset_id: int,
                         params: Dict[str, Any], columns_schema: Dict[str, str]) -> Dict[str, Any]:
        """直方图：全局 bin 边界（np.linspace）+ 每列区间计数（与 pandas 逻辑一致）"""
        columns_param = params.get("columns") or []
        column = params.get("column")
        if column:
            columns_param = [column]
        elif not columns_param:
            numeric_cols_all = self._numeric_cols(columns_schema)
            if not numeric_cols_all:
                raise ValueError("没有可用的数值列")
            columns_param = [numeric_cols_all[0]]
        valid_cols = []
        for c in columns_param:
            if c not in columns_schema:
                raise ValueError(f"列 '{c}' 不存在")
            dtype = str(columns_schema[c])
            if dtype.startswith(('int', 'float', 'bool')):
                valid_cols.append(c)
            elif dtype in ("object", "str"):
                # object/str 列无法在 CH 中做数值聚合，回退 pandas（pandas 会做等价判定）
                raise ValueError(f"列 '{c}' 为 object 类型，走 pandas 保底")
            else:
                raise ValueError(f"直方图需要数值列，'{c}' 不是数值列")
        if not valid_cols:
            raise ValueError("没有有效的数值列")

        exprs = []
        for col in valid_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            exprs.append(f"count(`{sc}`) AS `__nn_{sc}`")
            exprs.append(f"min(`{sc}`) AS `__mn_{sc}`")
            exprs.append(f"max(`{sc}`) AS `__mx_{sc}`")
        row = self._query_rows(f"SELECT {', '.join(exprs)} FROM {db}.{tbl}")[0]

        bins = int(params.get("bins", 0) or 0)
        if bins <= 0:
            first_sc = self._validate_identifier(str(valid_cols[0]), f"列名: {valid_cols[0]}")
            first_nn = int(row[f"__nn_{first_sc}"] or 0)
            bins = max(5, min(50, int(np.sqrt(first_nn))))
        mins, maxs = [], []
        for col in valid_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            if row[f"__mn_{sc}"] is not None:
                mins.append(float(row[f"__mn_{sc}"]))
            if row[f"__mx_{sc}"] is not None:
                maxs.append(float(row[f"__mx_{sc}"]))
        if not mins or not maxs:
            return {"labels": [], "series": [],
                    "show_data_labels": True, "show_legend": bool(params.get("show_legend", True))}
        bin_edges = np.linspace(min(mins), max(maxs), bins + 1)
        labels = [f"{round(bin_edges[i], 2)}-{round(bin_edges[i + 1], 2)}" for i in range(bins)]

        series = []
        for col in valid_cols:
            sc = self._validate_identifier(str(col), f"列名: {col}")
            nn = int(row[f"__nn_{sc}"] or 0)
            if nn == 0:
                series.append({"name": col, "values": [0] * bins})
                continue
            conds, params_map = [], {}
            for i in range(bins):
                if i == bins - 1:
                    conds.append(
                        f"countIf(toFloat64(`{sc}`) >= {{hlo_{i}:Float64}} "
                        f"AND toFloat64(`{sc}`) <= {{hhi_{i}:Float64}}) AS `__b_{i}`")
                else:
                    conds.append(
                        f"countIf(toFloat64(`{sc}`) >= {{hlo_{i}:Float64}} "
                        f"AND toFloat64(`{sc}`) < {{hhi_{i}:Float64}}) AS `__b_{i}`")
                params_map[f"hlo_{i}"] = float(bin_edges[i])
                params_map[f"hhi_{i}"] = float(bin_edges[i + 1])
            hrow = self._query_rows(
                f"SELECT {', '.join(conds)} FROM {db}.{tbl}", parameters=params_map)[0]
            series.append({"name": col, "values": [int(hrow[f"__b_{i}"] or 0) for i in range(bins)]})

        return {"labels": labels, "series": series,
                "show_data_labels": True, "show_legend": bool(params.get("show_legend", True))}

    def _chart_pie(self, db: str, tbl: str, dataset_id: int,
                   params: Dict[str, Any], columns_schema: Dict[str, str]) -> Dict[str, Any]:
        """饼图：分类列计数 topN（与 pandas value_counts().head(topN) 一致）"""
        column = params.get("column") or (params.get("columns") or [None])[0]
        if not column or column not in columns_schema:
            raise ValueError(f"列 '{column}' 不存在")
        dtype = str(columns_schema[column])
        if dtype.startswith(('int', 'float', 'bool')):
            raise ValueError(f"饼图需要分类列，'{column}' 是数值列")
        if dtype in ("object", "str"):
            # 抽样判定：object 数字字符串列在 pandas 视角是数值列（饼图应报错），回退 pandas
            if self.object_column_type(dataset_id, column) == "numeric":
                raise ValueError(f"饼图需要分类列，'{column}' 是数值列")
        top_n = int(params.get("topN", 10) or 10)
        if top_n <= 0:
            top_n = 10
        sc = self._validate_identifier(str(column), f"列名: {column}")
        rows = self._query_rows(
            f"SELECT toString(`{sc}`) AS `k`, count() AS `cnt` FROM {db}.{tbl} "
            f"WHERE `{sc}` IS NOT NULL GROUP BY `k` ORDER BY `cnt` DESC LIMIT {int(top_n)}")
        return {
            "labels": [str(r["k"]) for r in rows],
            "values": [int(r["cnt"]) for r in rows],
            "show_data_labels": True,
            "show_legend": bool(params.get("show_legend", True)),
        }

    def _chart_bar(self, db: str, tbl: str, dataset_id: int, params: Dict[str, Any],
                   columns_schema: Dict[str, str], stacked: bool = False) -> Dict[str, Any]:
        """柱状图（bar/stacked_bar）：按 X 分类聚合 sum，字符串序排序（与 pandas 一致）"""
        x_col = params.get("x_column")
        if not x_col or x_col not in columns_schema:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        x_sc = self._validate_identifier(str(x_col), f"列名: {x_col}")
        # X 轴列角色判定：object 抽样；数值列在 pandas 中会按字符串序排序，CH 用 toString 对齐
        if str(columns_schema[x_col]) in ("object", "str") and self.object_column_type(dataset_id, x_col) == "numeric":
            raise ValueError(f"X 轴列 '{x_col}' 为数字字符串，走 pandas 保底")

        if stacked:
            y_columns = params.get("columns") or []
            if not y_columns:
                y_columns = self._numeric_cols(columns_schema)
        else:
            y_col = params.get("y_column")
            y_columns = params.get("y_columns") or []
            if y_columns and not y_col:
                y_col = y_columns[0]
            y_columns = y_columns if y_columns else ([y_col] if y_col else [])
        y_cols_to_use = []
        for c in y_columns:
            if c not in columns_schema:
                raise ValueError(f"Y 轴列 '{c}' 不存在")
            dtype = str(columns_schema[c])
            if dtype.startswith(('int', 'float', 'bool')):
                y_cols_to_use.append(c)
            else:
                # object/时间列无法作为数值列（object 数字字符串列走 pandas 保底）
                raise ValueError(f"Y 轴需要数值列，'{c}' 不是数值列")
        if not y_cols_to_use:
            raise ValueError("请至少设置一个 Y 轴列")
        if x_col in y_cols_to_use:
            raise ValueError(f"{'堆叠柱状图' if stacked else '柱状图'} 中 X 轴列 '{x_col}' 不能同时作为 Y 轴列")

        sel = [f"toString(`{x_sc}`) AS `k`"]
        for c in y_cols_to_use:
            sc = self._validate_identifier(str(c), f"列名: {c}")
            sel.append(f"round(sum(toFloat64(`{sc}`)), 2) AS `v_{sc}`")
        where = [f"`{x_sc}` IS NOT NULL"]
        order, limit = "`k` ASC", ""
        if not stacked and len(y_cols_to_use) == 1:
            # 单列 bar：pandas 先对 x/y 两列 dropna，再分组求和
            y_sc = self._validate_identifier(str(y_cols_to_use[0]), f"列名: {y_cols_to_use[0]}")
            where.append(f"`{y_sc}` IS NOT NULL")
            top_n = int(params.get("topN", 0) or 0)
            if top_n > 0:
                # pandas nlargest：按求和值降序取前 N
                order = f"`v_{y_sc}` DESC, `k` ASC"
                limit = f" LIMIT {int(top_n)}"
        rows = self._query_rows(
            f"SELECT {', '.join(sel)} FROM {db}.{tbl} "
            f"WHERE {' AND '.join(where)} GROUP BY `k` ORDER BY {order}{limit}")
        labels = [str(r["k"]) for r in rows]

        if stacked:
            series = []
            for c in y_cols_to_use:
                sc = self._validate_identifier(str(c), f"列名: {c}")
                series.append({"name": c, "data": [_safe_val(r[f"v_{sc}"]) for r in rows]})
            return {
                "categories": labels,
                "series": series,
                "show_data_labels": True,
                "show_legend": bool(params.get("show_legend", True)),
            }
        if len(y_cols_to_use) > 1:
            series = []
            for c in y_cols_to_use:
                sc = self._validate_identifier(str(c), f"列名: {c}")
                series.append({"name": c, "values": [_safe_val(r[f"v_{sc}"]) for r in rows]})
            return {
                "labels": labels,
                "series": series,
                "show_data_labels": bool(params.get("show_data_labels", False)),
                "show_legend": bool(params.get("show_legend", True)),
                "dual_axis_needed": self._dual_axis_needed_ch(db, tbl, y_cols_to_use),
            }
        y_sc = self._validate_identifier(str(y_cols_to_use[0]), f"列名: {y_cols_to_use[0]}")
        return {
            "labels": labels,
            "values": [_safe_val(r[f"v_{y_sc}"]) for r in rows],
            "show_data_labels": bool(params.get("show_data_labels", False)),
            "show_legend": bool(params.get("show_legend", True)),
        }

    def _dual_axis_needed_ch(self, db: str, tbl: str, y_cols: List[str]) -> bool:
        """检测是否需要双 Y 轴（量纲差异 >10 倍，与 _detect_dual_axis_needed 一致）"""
        if len(y_cols) < 2:
            return False
        exprs = []
        for c in y_cols:
            sc = self._validate_identifier(str(c), f"列名: {c}")
            exprs.append(f"min(`{sc}`) AS `__mn_{sc}`")
            exprs.append(f"max(`{sc}`) AS `__mx_{sc}`")
        row = self._query_rows(f"SELECT {', '.join(exprs)} FROM {db}.{tbl}")[0]
        ranges = []
        for c in y_cols:
            sc = self._validate_identifier(str(c), f"列名: {c}")
            mn, mx = row[f"__mn_{sc}"], row[f"__mx_{sc}"]
            if mn is None or mx is None:
                continue
            r = float(mx) - float(mn)
            if r > 0:
                ranges.append(r)
        if len(ranges) < 2:
            return False
        min_r, max_r = min(ranges), max(ranges)
        if min_r == 0 or max_r == 0:
            return False
        return max_r / min_r > 10

    # ==================== 同步 ====================

    def sync_dataframe(self, dataset_id: int, dataset_name: str, df: pd.DataFrame,
                       columns_schema: Dict[str, str]) -> dict:
        """全量同步 DataFrame 到 ClickHouse（建表 + 分块 INSERT + 对拍 + 注册表）

        返回: {"status": "synced"|"failed", "row_count": int, "error": str|None}
        """
        try:
            if not self.is_enabled():
                return {"status": "failed", "row_count": 0, "error": "ClickHouse 未启用"}
            if not self.is_available(refresh=True):
                return {"status": "failed", "row_count": 0, "error": "ClickHouse 不可用"}

            self.registry_upsert(dataset_id, dataset_name=dataset_name,
                                 row_count=len(df), columns_json=json.dumps(columns_schema, ensure_ascii=False),
                                 data_version=1, status="syncing")

            self.ensure_dataset_table(dataset_id, columns_schema)
            db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
            tbl = self._validate_identifier(self.table_name(dataset_id), "表名")

            # 分块写入，控制内存峰值（插入前归一化，兼容 pandas 3.x 日期对象推断差异）
            self._normalize_for_insert(df)
            batch = max(1, int(settings.CLICKHOUSE_SYNC_BATCH))
            full_table = f"{db}.{tbl}"
            # 加锁：insert_df 复用同一 client，需串行化防止并发 session 冲突
            with self._lock:
                client = self._get_client()
                for start in range(0, len(df), batch):
                    chunk = df.iloc[start:start + batch]
                    client.insert_df(full_table, chunk)

            # 对拍校验：count/sum/mean/min/max 与 pandas 全量结果一致
            verify_error = self._verify_dataset(dataset_id, df, columns_schema)
            if verify_error:
                self.registry_upsert(dataset_id, dataset_name=dataset_name,
                                     row_count=len(df), columns_json=json.dumps(columns_schema, ensure_ascii=False),
                                     data_version=1, status="failed", last_error=verify_error)
                return {"status": "failed", "row_count": len(df), "error": verify_error}

            self.registry_upsert(dataset_id, dataset_name=dataset_name,
                                 row_count=len(df), columns_json=json.dumps(columns_schema, ensure_ascii=False),
                                 data_version=1, status="synced")
            return {"status": "synced", "row_count": len(df), "error": None}
        except Exception as e:
            print(f"⚠️ ClickHouse 同步失败 dataset={dataset_id}: {e}")
            try:
                self.registry_upsert(dataset_id, dataset_name=dataset_name,
                                     row_count=0, columns_json="{}",
                                     data_version=1, status="failed", last_error=str(e)[:500])
            except Exception:
                pass
            return {"status": "failed", "row_count": 0, "error": str(e)}

    def _verify_dataset(self, dataset_id: int, df: pd.DataFrame,
                        columns_schema: Dict[str, str]) -> Optional[str]:
        """同步对拍：CH 副本与 pandas 全量结果比对，返回 None=通过，否则失败原因"""
        db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
        tbl = self._validate_identifier(self.table_name(dataset_id), "表名")

        # 1. 行数
        rows = self._query_rows(f"SELECT count() AS cnt FROM {db}.{tbl}")
        ch_count = int(rows[0]["cnt"]) if rows else 0
        pd_count = int(len(df))
        if ch_count != pd_count:
            return f"行数不一致: CH={ch_count}, pandas={pd_count}"

        # 2. 数值列聚合对拍（仅 int/float 且非全 NaN 列）
        numeric_cols = [
            col for col, dtype in columns_schema.items()
            if str(dtype).startswith(('int', 'float'))
            and pd.to_numeric(df[col], errors='coerce').notna().any()
        ]
        for col in numeric_cols:
            safe_col = self._validate_identifier(str(col), f"列名: {col}")
            # 别名带统一前缀，避免与数据列名（如 a/s/mn/mx）冲突导致 CH ILLEGAL_AGGREGATION
            aggs = self._query_rows(
                f"SELECT sum(toFloat64(`{safe_col}`)) AS `__vs`, "
                f"avg(toFloat64(`{safe_col}`)) AS `__va`, "
                f"min(`{safe_col}`) AS `__vmn`, max(`{safe_col}`) AS `__vmx` FROM {db}.{tbl}"
            )[0]
            series = pd.to_numeric(df[col], errors='coerce').dropna()
            pd_sum = float(series.sum())
            pd_mean = float(series.mean())
            pd_min = float(series.min())
            pd_max = float(series.max())
            ch_sum = float(aggs["__vs"]) if aggs["__vs"] is not None else float('nan')
            ch_mean = float(aggs["__va"]) if aggs["__va"] is not None else float('nan')
            ch_min = float(aggs["__vmn"]) if aggs["__vmn"] is not None else float('nan')
            ch_max = float(aggs["__vmx"]) if aggs["__vmx"] is not None else float('nan')

            def _close(a: float, b: float, tol: float = 1e-6) -> bool:
                if a != a and b != b:  # 双方 NaN
                    return True
                if a != a or b != b:
                    return False
                if a == b:  # 含 ±inf 时直接相等（inf == inf）
                    return True
                return abs(a - b) <= tol * max(1.0, abs(b))

            if not (_close(ch_min, pd_min) and _close(ch_max, pd_max)):
                return f"列「{col}」min/max 不一致: CH=({ch_min},{ch_max}), pandas=({pd_min},{pd_max})"
            if not _close(ch_sum, pd_sum):
                return f"列「{col}」sum 不一致: CH={ch_sum}, pandas={pd_sum}"
            if not _close(ch_mean, pd_mean):
                return f"列「{col}」mean 不一致: CH={ch_mean}, pandas={pd_mean}"
        return None

    # ==================== 数据清理 ====================

    def drop_dataset(self, dataset_id: int) -> None:
        """删除数据集副本（表 + 注册记录），用于数据删除/清空时清理"""
        self.drop_dataset_table(dataset_id)
        self.registry_delete(dataset_id)

    def storage_stats(self) -> dict:
        """副本存储占用统计（管理端展示）"""
        try:
            db = self._validate_identifier(settings.CLICKHOUSE_DATABASE, "数据库名")
            rows = self._query_rows(
                f"SELECT table, formatReadableSize(total_bytes) AS size_readable, "
                f"total_bytes FROM system.tables WHERE database = '{db}' AND name LIKE '{_DATASET_TABLE_PREFIX}%'"
            )
            total = sum(int(r.get("total_bytes") or 0) for r in rows)
            return {"tables": rows, "total_bytes": total, "total_readable": _readable_size(total)}
        except Exception as e:
            return {"tables": [], "total_bytes": 0, "total_readable": "0 B", "error": str(e)}


def _round4(v):
    """round(v, 4)，None/NaN/±inf 统一返回 None（JSON 兼容，Starlette 不允许非有限值）"""
    if v is None:
        return None
    fv = float(v)
    if fv != fv or fv in (float('inf'), float('-inf')):
        return None
    return round(fv, 4)


def _f(v):
    """转 float，None/NaN/±inf 返回 None（JSON 兼容）"""
    if v is None:
        return None
    fv = float(v)
    if fv != fv or fv in (float('inf'), float('-inf')):
        return None
    return fv


def _safe_val(v):
    """数值安全转换：None/NaN/±inf 返回 None（JSON 兼容，与 _clean_json_data 对齐）"""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return v
    if fv != fv or fv in (float('inf'), float('-inf')):
        return None
    return fv


def _readable_size(num: int) -> str:
    """字节数转可读字符串"""
    size = float(num)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.2f} GB"


# ==================== Celery 同步任务 ====================

def _load_dataset_df(dataset_id: int):
    """从文件加载数据集 DataFrame（同步任务专用，含归属校验）

    返回 (dataset_info, df)：dataset_info 为普通 dict（在 session 关闭前提取，
    避免 DetachedInstanceError），含 id/name/row_count/artifact_type/schema。
    """
    from sqlalchemy.orm import Session
    from app.models import Dataset
    from app.utils.db import SessionLocal
    from app.services.data_service import DataService

    db: Session = SessionLocal()
    try:
        dataset = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.status == "active"
        ).first()
        if not dataset:
            raise ValueError(f"数据集不存在或非 active: {dataset_id}")
        if not dataset.file_path:
            raise ValueError(f"数据集无本地文件，跳过同步: {dataset_id}")
        df = DataService(db).load_dataset(dataset_id)
        # session 关闭前提取所需字段，返回普通 dict 避免 detached 属性刷新错误
        info = {
            "id": dataset.id,
            "name": dataset.name,
            "row_count": dataset.row_count,
            "artifact_type": dataset.artifact_type,
            "schema": dataset.schema,
        }
        return info, df
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


def _sync_dataset_impl(dataset_id: int) -> dict:
    """同步任务实现（供 Celery 与同步执行共用）"""
    if not (settings.CLICKHOUSE_SYNC_ENABLED and clickhouse_service.is_enabled()):
        return {"status": "skipped", "reason": "ClickHouse 同步未启用"}

    dataset, df = _load_dataset_df(dataset_id)
    # 仅同步原始数据（raw_data/analysis_data）且行数达阈值的数据集；产物（清洗结果/特征导出等）不同步
    if str(dataset["artifact_type"] or "") not in ("raw_data", "analysis_data"):
        return {"status": "skipped", "reason": f"非 raw_data 类型（{dataset['artifact_type']}）"}
    if (dataset["row_count"] or 0) < int(settings.CLICKHOUSE_MIN_ROWS):
        return {"status": "skipped", "reason": f"行数 {dataset['row_count']} < 阈值 {settings.CLICKHOUSE_MIN_ROWS}"}

    columns_schema = dataset["schema"] if isinstance(dataset["schema"], dict) else clickhouse_service._schema_from_df(df)
    return clickhouse_service.sync_dataframe(
        dataset_id=dataset_id,
        dataset_name=dataset["name"],
        df=df,
        columns_schema=columns_schema,
    )


from app.services.task_manager import task_manager  # noqa: E402  （置于底部避免循环导入）


@task_manager.register_task
def clickhouse_sync_task(dataset_id: int) -> dict:
    """Celery 异步任务：数据集同步到 ClickHouse 副本

    注册为 Celery 任务（Worker include 加载本模块触发注册）；
    Celery 不可用时由 task_manager.run_task 降级为同步执行。
    """
    return _sync_dataset_impl(dataset_id)


def trigger_sync(dataset_id: int) -> None:
    """触发数据集同步到 ClickHouse（Celery 异步优先；失败不阻塞主流程）

    调用场景：数据集上传成功、跨模块导入创建 raw_data 副本后。
    """
    if not (settings.CLICKHOUSE_SYNC_ENABLED and clickhouse_service.is_enabled()):
        return
    try:
        # no_degrade=True：Celery Worker 不可达时不得降级为同步执行
        # （本函数由 async 上传接口触发，同步执行大表同步会阻塞事件循环卡死 API）
        task_manager.run_task(clickhouse_sync_task, dataset_id, no_degrade=True)
    except Exception as e:
        print(f"⚠️ ClickHouse 同步触发失败（数据集 {dataset_id} 将走 pandas）: {e}")


# 全局单例
clickhouse_service = ClickHouseService()
