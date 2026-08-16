import pandas as pd
import numpy as np
import json
import math
import re
import io
import os
from datetime import datetime
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models import Dataset
from typing import Optional, List, Dict, Any, Tuple

try:
    from app.services.storage_manager import storage_manager
except ImportError:
    storage_manager = None


# 远程大表采样阈值：超过此行数的远程表在模块加载时自动采样，避免 OOM
# 注：采样取前 N 行（非随机），优先保证可用性；机器学习等精度敏感场景可在提示后改用本地数据
REMOTE_SAMPLE_THRESHOLD = 50000
REMOTE_SAMPLE_SIZE = 50000


class DataService:
    """数据服务类"""

    def __init__(self, db: Session):
        self.db = db
    
    def load_dataset(self, dataset_id: int, limit: int = None) -> pd.DataFrame:
        """加载数据集

        Args:
            dataset_id: 数据集ID
            limit: 限制加载行数（仅远程数据库源有效，用于 AI 提示词等场景避免全量加载）
        """
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError("数据集不存在")

        if dataset.file_path:
            return self._load_from_file(dataset.file_path)
        elif dataset.connection_id and dataset.table_name:
            return self._load_from_remote_db(dataset.connection_id, dataset.table_name, limit=limit)
        else:
            raise ValueError("数据源未指定")

    def load_dataset_page(self, dataset_id: int, page: int = 1, page_size: int = 100) -> Tuple[pd.DataFrame, int]:
        """分页加载数据集（避免全量构建 DataFrame，降低内存峰值）

        CSV/Excel 使用 pandas skiprows + nrows 只解析目标页数据行，
        不再将整个文件构建为 DataFrame；JSON 因格式限制回退到全量加载后切片。
        total 优先取 dataset.row_count（DB 已存储），避免全量加载计算 len(df)。

        Args:
            dataset_id: 数据集ID
            page: 页码，从1开始
            page_size: 每页行数

        Returns:
            (page_df, total): 当前页 DataFrame 和总行数
        """
        dataset = self.db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise ValueError("数据集不存在")

        total = dataset.row_count or 0
        start = (page - 1) * page_size

        # row_count 缺失（旧数据）：回退到全量加载，保证总数正确
        if not total:
            df = self.load_dataset(dataset_id)
            return df.iloc[start:start + page_size], len(df)

        # 数据库源：回退到全量加载后切片（暂未实现 SQL 分页）
        if not dataset.file_path:
            df = self.load_dataset(dataset_id)
            return df.iloc[start:start + page_size], total

        file_path = dataset.file_path
        use_storage = storage_manager is not None and not os.path.isabs(file_path)

        def _get_source():
            """获取可 seek 的数据源（BytesIO 或本地路径）"""
            if use_storage:
                if not storage_manager.exists(file_path):
                    raise FileNotFoundError(f"文件不存在: {file_path}")
                content = storage_manager.read(file_path)
                if isinstance(content, str):
                    content = content.encode('utf-8')
                return io.BytesIO(content)
            else:
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"文件不存在: {file_path}")
                return file_path

        # CSV：使用 skiprows 跳过 header 后的 start 行，nrows 只读取 page_size 行
        if file_path.endswith('.csv'):
            # skiprows 基于 0-based 行号；header（第0行）保留，跳过第 1..start 行
            skiprows = range(1, start + 1)
            for encoding in ['utf-8', 'gbk', 'gb2312', 'latin1']:
                try:
                    src = _get_source()
                    if use_storage:
                        src.seek(0)
                        df = pd.read_csv(src, encoding=encoding, skiprows=skiprows, nrows=page_size)
                    else:
                        df = pd.read_csv(src, encoding=encoding, skiprows=skiprows, nrows=page_size)
                    return df, total
                except UnicodeDecodeError:
                    continue
            raise ValueError("无法读取CSV文件，请检查文件编码")

        # Excel：同样使用 skiprows + nrows 分页
        elif file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            skiprows = range(1, start + 1)
            src = _get_source()
            if use_storage:
                src.seek(0)
                df = pd.read_excel(src, skiprows=skiprows, nrows=page_size)
            else:
                df = pd.read_excel(src, skiprows=skiprows, nrows=page_size)
            return df, total

        # JSON：格式限制无法高效分页，回退到全量加载后切片（JSON 通常较小）
        elif file_path.endswith('.json'):
            df = self._load_from_file(file_path)
            return df.iloc[start:start + page_size], total

        else:
            raise ValueError(f"不支持的文件格式: {file_path}")

    def _load_from_file(self, file_path: str) -> pd.DataFrame:
        """从文件加载数据（支持本地文件和 StorageManager）"""
        use_storage = storage_manager is not None and not os.path.isabs(file_path)
        
        if use_storage:
            if not storage_manager.exists(file_path):
                raise FileNotFoundError(f"文件不存在: {file_path}")
            content = storage_manager.read(file_path)
            if isinstance(content, str):
                content = content.encode('utf-8')
            data_bytes = io.BytesIO(content)
        else:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"文件不存在: {file_path}")
            data_bytes = file_path
        
        if file_path.endswith('.csv'):
            # 优先使用 PyArrow 列式加载：内存占用降低 60%，加载速度提升 50%
            # 失败时（未安装/编码问题）回退到 pandas，保证向后兼容
            try:
                import pyarrow.csv as pa_csv
                if use_storage:
                    data_bytes.seek(0)
                    table = pa_csv.read_csv(data_bytes)
                else:
                    table = pa_csv.read_csv(file_path)
                # split_blocks 零拷贝转 DataFrame，self_destruct 释放 Arrow 内存
                return table.to_pandas(split_blocks=True, self_destruct=True)
            except ImportError:
                pass  # pyarrow 未安装，回退到 pandas
            except Exception:
                # Arrow 解析失败（编码/格式问题），回退到 pandas 多编码尝试
                if use_storage:
                    data_bytes.seek(0)

            for encoding in ['utf-8', 'gbk', 'gb2312', 'latin1']:
                try:
                    if use_storage:
                        data_bytes.seek(0)
                        df = pd.read_csv(data_bytes, encoding=encoding)
                    else:
                        df = pd.read_csv(file_path, encoding=encoding)
                    return df
                except UnicodeDecodeError:
                    continue
            raise ValueError("无法读取CSV文件，请检查文件编码")
        elif file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            if use_storage:
                data_bytes.seek(0)
                df = pd.read_excel(data_bytes)
            else:
                df = pd.read_excel(file_path)
            return df
        elif file_path.endswith('.json'):
            try:
                if use_storage:
                    data_bytes.seek(0)
                    df = pd.read_json(data_bytes)
                else:
                    df = pd.read_json(file_path)
                return df
            except Exception:
                if use_storage:
                    data_bytes.seek(0)
                    data = json.loads(data_bytes.read().decode('utf-8'))
                else:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                
                # 常见的数据数组字段名，按优先级排序
                array_keys = ['rules', 'data', 'items', 'records', 'rows', 'list', 'results']
                for key in array_keys:
                    if isinstance(data, dict) and key in data and isinstance(data[key], list):
                        # 找到数组（即使为空），转为DataFrame
                        arr = data[key]
                        if len(arr) > 0 and isinstance(arr[0], dict):
                            return pd.DataFrame(arr)
                        else:
                            # 空数组，构造一条说明信息的DataFrame
                            info_rows = []
                            # 把parameters里的信息提取出来
                            params = data.get('parameters', {})
                            if isinstance(params, dict):
                                for pk, pv in params.items():
                                    info_rows.append({'项目': pk, '值': str(pv)})
                            info_rows.append({'项目': '说明', '值': f'未找到满足条件的{key}，请调整参数后重试'})
                            return pd.DataFrame(info_rows)
                
                # 如果是纯数组，直接转
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    return pd.DataFrame(data)
                
                # 如果是字典但没有找到数据数组，把整个字典转成单行DataFrame
                if isinstance(data, dict):
                    # 把嵌套结构转为字符串避免解析问题
                    flat_data = {}
                    for k, v in data.items():
                        if isinstance(v, (dict, list)):
                            flat_data[k] = json.dumps(v, ensure_ascii=False)
                        else:
                            flat_data[k] = v
                    return pd.DataFrame([flat_data])
                
                raise ValueError("无法解析JSON文件，请检查文件格式")
        else:
            raise ValueError(f"不支持的文件格式: {file_path}")
    
    def _load_from_remote_db(self, connection_id: int, table_name: str, limit: int = None) -> pd.DataFrame:
        """从远程数据库连接加载数据

        通过 DataSourceConnection 记录获取远程数据库连接信息，
        解密密码后创建 SQLAlchemy 引擎，执行 SELECT 查询加载数据。

        Args:
            connection_id: 数据源连接记录ID
            table_name: 远程表名
            limit: 限制加载行数，None 表示全量加载
        """
        from app.models import DataSourceConnection
        from app.utils.crypto import decrypt_password
        from sqlalchemy import create_engine as sa_create_engine

        # 表名白名单校验，防止 SQL 注入
        self._validate_identifier(table_name, "表名")

        conn_record = self.db.query(DataSourceConnection).filter(
            DataSourceConnection.id == connection_id
        ).first()
        if not conn_record:
            raise ValueError(f"数据源连接不存在: {connection_id}")

        password = decrypt_password(conn_record.password_encrypted)

        # 用户名/密码/库名 URL 编码后再拼入连接串，避免特殊字符破坏 URL 结构（修复）
        safe_user = quote(conn_record.username, safe="")
        safe_password = quote(password, safe="")
        safe_database = quote(conn_record.database, safe="/")

        # 根据数据库类型构建连接 URL
        if conn_record.db_type == "mysql":
            db_url = f"mysql+pymysql://{safe_user}:{safe_password}@{conn_record.host}:{conn_record.port}/{safe_database}"
        elif conn_record.db_type == "postgresql":
            db_url = f"postgresql+psycopg2://{safe_user}:{safe_password}@{conn_record.host}:{conn_record.port}/{safe_database}"
        else:
            raise ValueError(f"不支持的数据库类型: {conn_record.db_type}")

        if conn_record.extra_params:
            db_url += f"?{conn_record.extra_params.lstrip('?')}"

        engine = sa_create_engine(db_url)
        try:
            sql = f"SELECT * FROM {table_name}"
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            df = pd.read_sql(sql, engine)
            # 统一类型转换：将 object 列中超过 50% 可转为数值的列转换为数值类型
            # 与本地 read_csv 行为对齐，避免各模块重复处理 Decimal/object 类型
            # 解决问题：远程数值列被加载为 object，导致 select_dtypes(include=[np.number]) 漏掉数值列
            for col in df.columns:
                if df[col].dtype == 'object':
                    converted = pd.to_numeric(df[col], errors='coerce')
                    # 仅当超过半数值可转时才转换，避免误把字符串列（如身份证号）转成数值
                    if converted.notna().sum() > len(df[col]) * 0.5:
                        df[col] = converted
            return df
        finally:
            engine.dispose()

    def _resolve_remote_engine(self, connection_id: int, user_id: int = None):
        """解析远程数据源连接并构建带超时的引擎

        供 count_remote_table / query_remote_table 复用，避免重复的连接解析逻辑。
        返回 (engine, conn_record)；调用方负责 engine.dispose()。
        """
        from app.models import DataSourceConnection
        from app.utils.crypto import decrypt_password, InvalidTokenError
        from sqlalchemy import create_engine as sa_create_engine

        q = self.db.query(DataSourceConnection).filter(DataSourceConnection.id == connection_id)
        if user_id is not None:
            q = q.filter(DataSourceConnection.user_id == user_id)
        conn_record = q.first()
        if not conn_record:
            raise ValueError(f"数据源连接不存在或无权访问: {connection_id}")

        try:
            password = decrypt_password(conn_record.password_encrypted)
        except InvalidTokenError:
            raise ValueError("该数据源的密码无法解密（加密密钥已变更），请删除该数据源后重新创建")

        # 用户名/密码/库名 URL 编码后再拼入连接串，避免特殊字符破坏 URL 结构（修复）
        safe_user = quote(conn_record.username, safe="")
        safe_password = quote(password, safe="")
        safe_database = quote(conn_record.database, safe="/")

        if conn_record.db_type == "mysql":
            db_url = f"mysql+pymysql://{safe_user}:{safe_password}@{conn_record.host}:{conn_record.port}/{safe_database}"
        elif conn_record.db_type == "postgresql":
            db_url = f"postgresql+psycopg2://{safe_user}:{safe_password}@{conn_record.host}:{conn_record.port}/{safe_database}"
        else:
            raise ValueError(f"不支持的数据库类型: {conn_record.db_type}")

        if conn_record.extra_params:
            db_url += f"?{conn_record.extra_params.lstrip('?')}"

        # 统一使用 5 秒连接超时，避免数据库不可达时长时间挂起
        engine = sa_create_engine(db_url, connect_args={"connect_timeout": 5})
        return engine, conn_record

    def count_remote_table(self, connection_id: int, table_name: str, user_id: int = None) -> int:
        """预判远程表行数，用于加载前决策是否采样

        使用 SELECT COUNT(*) 查询，开销小于全量加载。
        """
        from sqlalchemy import text
        engine, _ = self._resolve_remote_engine(connection_id, user_id)
        try:
            with engine.connect() as c:
                # 表名做基础校验，防止拼接 SQL 注入（仅允许字母数字下划点）
                if not re.match(r'^[A-Za-z0-9_\.]+$', table_name):
                    raise ValueError(f"非法表名: {table_name}")
                result = c.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                return int(result.scalar())
        finally:
            engine.dispose()

    # 标识符白名单正则：表名/列名只允许字母数字下划点，防止 SQL 注入
    _IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z0-9_\.]+$')

    def _validate_identifier(self, name: str, label: str = "标识符"):
        """校验 SQL 标识符（表名/列名），拒绝非法字符防注入"""
        if not name or not self._IDENTIFIER_PATTERN.match(name):
            raise ValueError(f"非法{label}: {name}")
        return name

    def query_remote_aggregate(self, connection_id: int, table_name: str,
                                user_id: int = None, metrics: list = None) -> dict:
        """SQL 下推聚合查询：在远程数据库侧执行聚合，只返回结果不拉明细

        用于统计/质量/图表推荐等场景，避免大表全量加载导致 OOM。

        Args:
            connection_id: 数据源连接 ID
            table_name: 远程表名
            user_id: 当前用户 ID（权限验证）
            metrics: 聚合配置列表，每项格式：
                - {"type": "count"} — 全表行数
                - {"type": "numeric_stats", "columns": ["age", "salary"]} — 数值列统计
                - {"type": "categorical_stats", "columns": ["city"], "top_n": 10} — 分类列 top N
                - {"type": "null_count", "columns": [...]} — 各列缺失值数
                - {"type": "unique_count", "columns": [...]} — 各列唯一值数
                - {"type": "duplicate_count", "columns": [...]} — 重复行数（基于指定列）

        Returns:
            {"count": N, "numeric_stats": {col: {count,mean,std,min,max,...}},
             "categorical_stats": {col: {top_values: [...], unique_count: N}}, ...}
        """
        from sqlalchemy import text
        self._validate_identifier(table_name, "表名")
        engine, _ = self._resolve_remote_engine(connection_id, user_id)
        result = {}
        try:
            with engine.connect() as c:
                for metric in metrics or []:
                    mtype = metric.get("type")
                    if mtype == "count":
                        r = c.execute(text(f"SELECT COUNT(*) AS cnt FROM {table_name}"))
                        result["count"] = int(r.scalar())

                    elif mtype == "numeric_stats":
                        cols = metric.get("columns", [])
                        num_result = {}
                        for col in cols:
                            self._validate_identifier(col, "列名")
                            sql = (
                                f"SELECT COUNT({col}) AS count, "
                                f"COUNT(DISTINCT {col}) AS unique_count, "
                                f"AVG({col}) AS mean, "
                                f"STDDEV({col}) AS std, "
                                f"MIN({col}) AS min, "
                                f"MAX({col}) AS max, "
                                f"SUM({col}) AS sum "
                                f"FROM {table_name}"
                            )
                            r = c.execute(text(sql))
                            row = r.fetchone()
                            if row:
                                num_result[col] = {
                                    "count": int(row[0] or 0),
                                    "unique_count": int(row[1] or 0),
                                    "mean": float(row[2]) if row[2] is not None else None,
                                    "std": float(row[3]) if row[3] is not None else None,
                                    "min": float(row[4]) if row[4] is not None else None,
                                    "max": float(row[5]) if row[5] is not None else None,
                                    "sum": float(row[6]) if row[6] is not None else None,
                                }
                        result["numeric_stats"] = num_result

                    elif mtype == "categorical_stats":
                        cols = metric.get("columns", [])
                        top_n = metric.get("top_n", 10)
                        cat_result = {}
                        for col in cols:
                            self._validate_identifier(col, "列名")
                            # 唯一值数
                            r_unique = c.execute(
                                text(f"SELECT COUNT(DISTINCT {col}) AS uc FROM {table_name}")
                            )
                            unique_count = int(r_unique.scalar() or 0)
                            # top N 值
                            r_top = c.execute(text(
                                f"SELECT {col} AS val, COUNT(*) AS cnt "
                                f"FROM {table_name} "
                                f"GROUP BY {col} "
                                f"ORDER BY cnt DESC "
                                f"LIMIT :top_n"
                            ), {"top_n": top_n})
                            top_values = [
                                {"value": str(row[0]) if row[0] is not None else None, "count": int(row[1])}
                                for row in r_top.fetchall()
                            ]
                            cat_result[col] = {
                                "unique_count": unique_count,
                                "top_values": top_values
                            }
                        result["categorical_stats"] = cat_result

                    elif mtype == "null_count":
                        cols = metric.get("columns", [])
                        null_result = {}
                        for col in cols:
                            self._validate_identifier(col, "列名")
                            r = c.execute(text(
                                f"SELECT SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS nc "
                                f"FROM {table_name}"
                            ))
                            null_result[col] = int(r.scalar() or 0)
                        result["null_count"] = null_result

                    elif mtype == "unique_count":
                        cols = metric.get("columns", [])
                        uc_result = {}
                        for col in cols:
                            self._validate_identifier(col, "列名")
                            r = c.execute(
                                text(f"SELECT COUNT(DISTINCT {col}) AS uc FROM {table_name}")
                            )
                            uc_result[col] = int(r.scalar() or 0)
                        result["unique_count"] = uc_result

                    elif mtype == "duplicate_count":
                        # 基于指定列的重复行数：总行数 - DISTINCT 行数
                        # 注意：MySQL/PostgreSQL 的 COUNT(DISTINCT ...) 不支持多列，
                        # 必须用子查询 SELECT COUNT(*) FROM (SELECT DISTINCT ... ) t
                        cols = metric.get("columns", [])
                        if cols:
                            for col in cols:
                                self._validate_identifier(col, "列名")
                            cols_concat = ", ".join(cols)
                            sql = (
                                f"SELECT COUNT(*) - "
                                f"(SELECT COUNT(*) FROM (SELECT DISTINCT {cols_concat} FROM {table_name}) AS _t) AS dup "
                                f"FROM {table_name}"
                            )
                            r = c.execute(text(sql))
                            result["duplicate_count"] = int(r.scalar() or 0)

        finally:
            engine.dispose()
        return result

    def query_remote_table(self, connection_id: int, table_name: str, user_id: int = None,
                            limit: int = None, offset: int = None,
                            columns: list = None) -> pd.DataFrame:
        """模块直接查询远程数据库表（不依赖 Dataset 代理记录）

        用于模块选择"远程数据库"数据源后直接加载数据。
        验证用户对连接的归属权。

        Args:
            connection_id: 数据源连接 ID
            table_name: 远程表名
            user_id: 当前用户 ID（用于权限验证）
            limit: 限制加载行数
            offset: 偏移量（与 limit 配合实现分页/随机采样）
            columns: 指定查询的列名列表（None 表示 SELECT *），用于抽样计算时只加载需要的列
        """
        from app.models import DataSourceConnection
        from app.utils.crypto import decrypt_password, InvalidTokenError
        from sqlalchemy import create_engine as sa_create_engine

        # 表名白名单校验，防止 SQL 注入（与 count_remote_table 保持一致）
        self._validate_identifier(table_name, "表名")

        # 验证连接归属
        q = self.db.query(DataSourceConnection).filter(DataSourceConnection.id == connection_id)
        if user_id is not None:
            q = q.filter(DataSourceConnection.user_id == user_id)
        conn_record = q.first()
        if not conn_record:
            raise ValueError(f"数据源连接不存在或无权访问: {connection_id}")

        try:
            password = decrypt_password(conn_record.password_encrypted)
        except InvalidTokenError:
            raise ValueError("该数据源的密码无法解密（加密密钥已变更），请删除该数据源后重新创建")

        if conn_record.db_type == "mysql":
            db_url = f"mysql+pymysql://{conn_record.username}:{password}@{conn_record.host}:{conn_record.port}/{conn_record.database}"
        elif conn_record.db_type == "postgresql":
            db_url = f"postgresql+psycopg2://{conn_record.username}:{password}@{conn_record.host}:{conn_record.port}/{conn_record.database}"
        else:
            raise ValueError(f"不支持的数据库类型: {conn_record.db_type}")

        if conn_record.extra_params:
            db_url += f"?{conn_record.extra_params.lstrip('?')}"

        engine = sa_create_engine(db_url)
        try:
            # columns 参数支持：只查询指定列，减少数据传输量
            if columns:
                # 列名白名单校验，防止 SQL 注入
                safe_cols = []
                for col in columns:
                    self._validate_identifier(col, "列名")
                    safe_cols.append(col)
                col_sql = ", ".join(safe_cols)
                sql = f"SELECT {col_sql} FROM {table_name}"
            else:
                sql = f"SELECT * FROM {table_name}"
            # LIMIT 和 OFFSET 组合实现分页/随机采样
            # MySQL 和 PostgreSQL 均支持 LIMIT N OFFSET M 语法
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            if offset is not None and offset > 0:
                sql += f" OFFSET {int(offset)}"
            df = pd.read_sql(sql, engine)
            # 统一类型转换：将 object 列中超过 50% 可转为数值的列转换为数值类型
            # 与本地 read_csv 行为对齐，避免各模块重复处理 Decimal/object 类型
            # 解决问题：远程数值列被加载为 object，导致 select_dtypes(include=[np.number]) 漏掉数值列
            for col in df.columns:
                if df[col].dtype == 'object':
                    converted = pd.to_numeric(df[col], errors='coerce')
                    # 仅当超过半数值可转时才转换，避免误把字符串列（如身份证号）转成数值
                    if converted.notna().sum() > len(df[col]) * 0.5:
                        df[col] = converted
            return df
        finally:
            engine.dispose()

    def get_remote_table_schema(self, connection_id: int, table_name: str,
                                 user_id: int = None) -> list:
        """获取远程表的列结构（不拉数据，只读元数据）

        用于需要列类型但不需数据的场景（如图表推荐 SQL 下推），
        避免 LIMIT 0/1 返回空 DataFrame 导致类型推断失败。

        Args:
            connection_id: 数据源连接 ID
            table_name: 远程表名
            user_id: 当前用户 ID（用于权限验证）

        Returns:
            [{"name": col_name, "type": type_str, "nullable": bool}, ...]
        """
        from app.models import DataSourceConnection
        from app.utils.crypto import decrypt_password, InvalidTokenError
        from sqlalchemy import create_engine as sa_create_engine
        from sqlalchemy import inspect as sa_inspect

        # 表名白名单校验，防止 SQL 注入
        self._validate_identifier(table_name, "表名")

        # 验证连接归属
        q = self.db.query(DataSourceConnection).filter(DataSourceConnection.id == connection_id)
        if user_id is not None:
            q = q.filter(DataSourceConnection.user_id == user_id)
        conn_record = q.first()
        if not conn_record:
            raise ValueError(f"数据源连接不存在或无权访问: {connection_id}")

        try:
            password = decrypt_password(conn_record.password_encrypted)
        except InvalidTokenError:
            raise ValueError("该数据源的密码无法解密（加密密钥已变更），请删除该数据源后重新创建")

        if conn_record.db_type == "mysql":
            db_url = f"mysql+pymysql://{conn_record.username}:{password}@{conn_record.host}:{conn_record.port}/{conn_record.database}"
        elif conn_record.db_type == "postgresql":
            db_url = f"postgresql+psycopg2://{conn_record.username}:{password}@{conn_record.host}:{conn_record.port}/{conn_record.database}"
        else:
            raise ValueError(f"不支持的数据库类型: {conn_record.db_type}")

        if conn_record.extra_params:
            db_url += f"?{conn_record.extra_params.lstrip('?')}"

        engine = sa_create_engine(db_url)
        try:
            inspector = sa_inspect(engine)
            columns = inspector.get_columns(table_name)
            return [{"name": col["name"], "type": str(col["type"]), "nullable": col.get("nullable", True)}
                    for col in columns]
        finally:
            engine.dispose()

    def has_remote_workcopy(self, user_id: int, connection_id: int, table_name: str) -> bool:
        """判断远程表是否存在特征工程工作副本

        存在工作副本时，远程表数据包含特征工程动态新增的构造列，
        各模块的 SQL 下推（直接从数据库聚合）应跳过，改走 load_module_data 内存计算。
        """
        if not connection_id or not table_name:
            return False
        return self.db.query(Dataset.id).filter(
            Dataset.user_id == user_id,
            Dataset.connection_id == connection_id,
            Dataset.table_name == table_name,
            Dataset.source_type == "derived",
            Dataset.module_source == "feature_engineering",
            Dataset.artifact_type == "feature_workcopy",
            Dataset.status == "active"
        ).first() is not None

    def load_module_data(
        self, dataset_id: int = None, remote_config: dict = None, user_id: int = None
    ) -> Tuple[pd.DataFrame, Optional[Dataset]]:
        """模块统一数据加载入口：优先 dataset_id，否则使用远程连接

        Args:
            dataset_id: 本地数据集 ID
            remote_config: 远程数据源配置 {"use_remote": True, "connection_id": N, "table_name": "..."}
            user_id: 当前用户 ID（远程模式下的权限验证）

        Returns:
            (DataFrame, Optional[Dataset对象]) — 远程模式时 Dataset 为 None
        """
        from app.models import DataSourceConnection

        # 优先使用本地数据集
        if dataset_id:
            dataset = self.db.query(Dataset).filter(
                Dataset.id == dataset_id,
                Dataset.user_id == user_id,
                Dataset.status == "active"
            ).first()
            if not dataset:
                raise ValueError(f"数据集不存在: {dataset_id}")
            df = self.load_dataset(dataset_id)
            return df, dataset

        # 远程数据源模式
        if remote_config and remote_config.get("use_remote"):
            conn_id = remote_config.get("connection_id")
            tbl_name = remote_config.get("table_name")
            if not conn_id or not tbl_name:
                raise ValueError("远程数据源配置不完整：缺少 connection_id 或 table_name")
            # 验证连接归属权
            conn = self.db.query(DataSourceConnection).filter(
                DataSourceConnection.id == conn_id,
                DataSourceConnection.user_id == user_id
            ).first()
            if not conn:
                raise ValueError(f"数据源连接不存在或无权访问: {conn_id}")

            # 远程表工作副本机制：若该远程表存在特征工程工作副本（远程构造/编码/缩放/降维
            # 产生的新列已累积保存在工作副本中），则优先加载工作副本，
            # 使所有模块都能使用动态新增的列（模拟本地数据集"原地更新"的行为）
            workcopy = self.db.query(Dataset).filter(
                Dataset.user_id == user_id,
                Dataset.connection_id == conn_id,
                Dataset.table_name == tbl_name,
                Dataset.source_type == "derived",
                Dataset.module_source == "feature_engineering",
                Dataset.artifact_type == "feature_workcopy",
                Dataset.status == "active"
            ).order_by(Dataset.id.desc()).first()
            if workcopy:
                try:
                    df = self.load_dataset(workcopy.id)
                    # 从工作副本 tags 恢复采样状态（大表采样得到的构造列不应被当作全量数据）
                    is_sampled = False
                    sample_size = None
                    if workcopy.tags:
                        try:
                            tags_data = json.loads(workcopy.tags)
                            is_sampled = bool(tags_data.get('is_sampled', False))
                            sample_size = tags_data.get('sample_size')
                        except (json.JSONDecodeError, TypeError):
                            pass
                    df.attrs['remote_row_count'] = workcopy.row_count
                    df.attrs['is_sampled'] = is_sampled
                    df.attrs['sample_size'] = sample_size
                    df.attrs['workcopy_dataset_id'] = workcopy.id
                    return df, None
                except Exception:
                    # 工作副本读取失败（如文件损坏）时降级为直接查库
                    pass

            # P1-1/P1-2：加载前预判行数，超过阈值则采样，避免大表 OOM
            # 采样取前 N 行（LIMIT N），非随机但开销最小；元信息通过 df.attrs 传递给调用方
            remote_row_count = None
            is_sampled = False
            sample_size = None
            try:
                remote_row_count = self.count_remote_table(conn_id, tbl_name, user_id=user_id)
            except Exception:
                # COUNT 查询失败时不阻断加载，降级为全量加载（可能 OOM，但保持原行为）
                remote_row_count = None

            if remote_row_count is not None and remote_row_count > REMOTE_SAMPLE_THRESHOLD:
                # 大表采样：方案B 随机 OFFSET
                # 在 [0, total - sample_size] 区间内取随机起始位置，取连续 N 行
                # 优点：性能与 LIMIT 相当（无 ORDER BY）；随机性显著优于固定取前N行
                # 缺点：仍是连续片段，不是真正随机；但远比固定 OFFSET 偏差小
                import random
                max_offset = max(0, remote_row_count - REMOTE_SAMPLE_SIZE)
                random_offset = random.randint(0, max_offset) if max_offset > 0 else 0
                df = self.query_remote_table(
                    conn_id, tbl_name, user_id=user_id,
                    limit=REMOTE_SAMPLE_SIZE, offset=random_offset
                )
                is_sampled = True
                sample_size = len(df)
            else:
                df = self.query_remote_table(conn_id, tbl_name, user_id=user_id)

            # 通过 df.attrs 携带远程加载元信息，各模块端点可读取以提示用户
            df.attrs['remote_row_count'] = remote_row_count
            df.attrs['is_sampled'] = is_sampled
            df.attrs['sample_size'] = sample_size
            return df, None  # 远程模式无 Dataset 对象

        raise ValueError("未指定数据源：需要 dataset_id 或 remote_config")

    def get_schema(self, df: pd.DataFrame) -> Dict[str, str]:
        """获取数据模式"""
        schema = {}
        for col in df.columns:
            schema[col] = str(df[col].dtype)
        return schema
    
    def get_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """获取数据统计信息"""
        stats = {}
        
        # 数值列统计 - 转换 numpy 类型为 Python 原生类型
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            numeric_stats = df[numeric_cols].describe().to_dict()
            # 递归转换 numpy 类型
            def convert_numpy_types(obj):
                if isinstance(obj, dict):
                    return {k: convert_numpy_types(v) for k, v in obj.items()}
                elif isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                else:
                    return obj
            stats['numeric'] = convert_numpy_types(numeric_stats)
        
        # 分类列统计
        cat_cols = df.select_dtypes(include=['object']).columns
        if len(cat_cols) > 0:
            cat_stats = {}
            for col in cat_cols:
                cat_stats[col] = {
                    'unique_count': int(df[col].nunique()),
                    'top_values': {k: int(v) for k, v in df[col].value_counts().head(5).to_dict().items()}
                }
            stats['categorical'] = cat_stats
        
        return stats
    
    def get_sample_data(self, df: pd.DataFrame, limit: int = 100) -> List[Dict[str, Any]]:
        """获取样本数据"""
        return df.head(limit).replace({np.nan: None}).to_dict('records')
    
    def get_data_quality_report(self, df: pd.DataFrame) -> Dict[str, Any]:
        """获取数据质量报告"""
        report = {
            'total_rows': int(len(df)),
            'total_columns': int(len(df.columns)),
            'missing_values': {},
            'duplicate_rows': int(df.duplicated().sum()),
            'column_types': {}
        }
        
        # 缺失值统计
        for col in df.columns:
            missing_count = int(df[col].isna().sum())
            if missing_count > 0:
                report['missing_values'][col] = {
                    'count': missing_count,
                    'percentage': round(float(missing_count) / float(len(df)) * 100, 2)
                }
            report['column_types'][col] = str(df[col].dtype)
        
        return report


class DataCleaningService:
    """数据清洗服务"""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self._last_warnings = []

    @staticmethod
    def _safe_float(value, is_lower: bool = True) -> float:
        """将范围边界值转为 float，None 表示无界限

        Args:
            value: 范围边界值（数值或 None）
            is_lower: True 表示下边界，None → -inf；False 表示上边界，None → inf

        Returns:
            float 边界值；None 转为 ±inf
        """
        if value is None:
            return float('-inf') if is_lower else float('inf')
        return float(value)

    @staticmethod
    def _range_to_json(ranges: List) -> List[List]:
        """将范围列表转为可 JSON 序列化的格式

        inf/-inf 转回 None，因为 JSON 标准不支持无穷大值。
        用于返回给前端的 contract_ranges 字段。
        """
        result = []
        for r in ranges:
            lower = DataCleaningService._safe_float(r[0], True)
            upper = DataCleaningService._safe_float(r[1], False)
            # inf/-inf 转回 None，避免 JSON 序列化失败
            lower_json = None if lower == float('-inf') else lower
            upper_json = None if upper == float('inf') else upper
            result.append([lower_json, upper_json])
        return result
    
    def handle_missing_values(self, strategy: str = 'auto', fill_value: Any = None,
                              columns: List[str] = None,
                              expected_types: Dict[str, str] = None) -> pd.DataFrame:
        """处理缺失值
        
        Args:
            strategy: 处理策略 (auto/mean/median/mode/drop/fill)
            fill_value: 填充值（strategy='fill' 时使用）
            columns: 指定列，None表示所有列
            expected_types: 列的期望类型 {col: 'integer'|'number'|'string'|'boolean'|'date'|'email'|'url'}
        """
        df = self.df.copy()
        cols = columns if columns else df.columns
        etypes = expected_types or {}

        # 定义不允许 mean/median 填充的类型
        non_numeric_types = {'string', 'boolean', 'date', 'email', 'url'}

        # 辅助函数：判断是否应该作为数值列处理
        def should_treat_as_numeric(col):
            """判断列是否应该作为数值列处理"""
            # 如果期望类型是数值类型，应该作为数值处理
            if etypes.get(col) in ('number', 'integer'):
                return True
            # 如果当前类型是数值类型，应该作为数值处理
            # 使用 pd.api.types.is_numeric_dtype 兼容 pandas 3.x 的 StringDtype
            if pd.api.types.is_numeric_dtype(df[col]):
                return True
            # 自动类型推断：object 列尝试转数值，成功率 > 80% 视为数值列
            if df[col].dtype == 'object':
                non_na = df[col].notna().sum()
                if non_na > 0:
                    numeric_vals = pd.to_numeric(df[col], errors='coerce')
                    if numeric_vals.notna().sum() / non_na > 0.8:
                        return True
            return False

        # 辅助函数：校验填充值格式
        def validate_fill_value(col, value):
            """校验填充值是否符合列的期望类型，失败抛出 ValueError"""
            expected = etypes.get(col)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return
            if expected == 'email':
                if not re.match(r'^[\w.+-]+@[\w-]+\.[\w.-]+$', str(value)):
                    raise ValueError(f"列[{col}]为email类型，填充值[{value}]不是合法邮箱地址")
            elif expected == 'url':
                if not re.match(r'^https?://[\w.-]+(?::\d+)?(?:/.*)?$', str(value)):
                    raise ValueError(f"列[{col}]为url类型，填充值[{value}]不是合法URL")
            elif expected == 'date':
                try:
                    pd.to_datetime(str(value))
                except Exception:
                    raise ValueError(f"列[{col}]为date类型，填充值[{value}]不是合法日期")
            elif expected == 'boolean':
                if str(value).lower() not in ('true', 'false', '0', '1', 'yes', 'no'):
                    raise ValueError(f"列[{col}]为boolean类型，填充值[{value}]不是合法布尔值")
            elif expected == 'integer':
                try:
                    int(float(value))
                except (ValueError, TypeError):
                    raise ValueError(f"列[{col}]为integer类型，填充值[{value}]不是合法整数")
        
        # 辅助函数：获取数值列的均值
        def get_numeric_mean(col):
            """获取列的均值，处理object类型"""
            # 使用 pd.api.types.is_numeric_dtype 兼容 pandas 3.x 的 StringDtype
            if pd.api.types.is_numeric_dtype(df[col]):
                return df[col].mean()
            else:
                # 尝试转换为数值后计算均值
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                return numeric_col.mean()
        
        # 辅助函数：获取数值列的中位数
        def get_numeric_median(col):
            """获取列的中位数，处理object类型"""
            # 使用 pd.api.types.is_numeric_dtype 兼容 pandas 3.x 的 StringDtype
            if pd.api.types.is_numeric_dtype(df[col]):
                return df[col].median()
            else:
                # 尝试转换为数值后计算中位数
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                return numeric_col.median()
        
        # 辅助函数：安全地尝试转换为整数类型
        def try_convert_to_int(col):
            """尝试转换列为整数类型，如果有无法转换的非NaN值则跳过"""
            try:
                orig_non_nan = df[col].notna()
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                type_error_mask = orig_non_nan & numeric_col.isna()
                if type_error_mask.any():
                    return
                if (numeric_col.dropna() % 1 == 0).all():
                    df[col] = pd.array(numeric_col, dtype=pd.Int64Dtype())
            except Exception:
                pass

        # 辅助函数：安全地对填充值取整，处理NaN情况
        def safe_round(val):
            """安全取整，如果val为NaN则返回None"""
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            return round(val)

        if strategy == 'auto':
            # 自动策略：数值列用均值，分类列用众数
            for col in cols:
                if col in df.columns:
                    if should_treat_as_numeric(col):
                        fill_val = get_numeric_mean(col)
                        if fill_val is None or (isinstance(fill_val, float) and pd.isna(fill_val)):
                            continue  # 跳过无法计算均值的列
                        if etypes.get(col) == 'integer':
                            fill_val = safe_round(fill_val)
                            if fill_val is None:
                                continue
                        df[col].fillna(fill_val, inplace=True)
                        if etypes.get(col) == 'integer':
                            try_convert_to_int(col)
                    else:
                        df[col].fillna(df[col].mode()[0] if len(df[col].mode()) > 0 else 'Unknown', inplace=True)

        elif strategy == 'mean':
            for col in cols:
                if col in df.columns:
                    # 智能模式：非数值列自动用众数填充（不阻断）
                    if etypes.get(col) in non_numeric_types or not should_treat_as_numeric(col):
                        # 非数值列：用众数填充，记录警告
                        mode_val = df[col].mode()
                        if len(mode_val) > 0:
                            df[col].fillna(mode_val[0], inplace=True)
                            self._last_warnings.append(
                                f"列[{col}]为非数值类型，已自动改用众数填充（均值/中位数仅适用于数值列）"
                            )
                        continue
                    # 处理数值列（包括期望类型为数值的object列）
                    fill_val = get_numeric_mean(col)
                    if fill_val is None or (isinstance(fill_val, float) and pd.isna(fill_val)):
                        self._last_warnings.append(
                            f"列[{col}]无法计算均值（可能数据为空或全为缺失值），已跳过"
                        )
                        continue
                    if etypes.get(col) == 'integer':
                        fill_val = safe_round(fill_val)
                        if fill_val is None:
                            continue
                    df[col].fillna(fill_val, inplace=True)
                    if etypes.get(col) == 'integer':
                        try_convert_to_int(col)

        elif strategy == 'median':
            for col in cols:
                if col in df.columns:
                    # 智能模式：非数值列自动用众数填充
                    if etypes.get(col) in non_numeric_types or not should_treat_as_numeric(col):
                        mode_val = df[col].mode()
                        if len(mode_val) > 0:
                            df[col].fillna(mode_val[0], inplace=True)
                            self._last_warnings.append(
                                f"列[{col}]为非数值类型，已自动改用众数填充（中位数仅适用于数值列）"
                            )
                        continue
                    fill_val = get_numeric_median(col)
                    if fill_val is None or (isinstance(fill_val, float) and pd.isna(fill_val)):
                        self._last_warnings.append(
                            f"列[{col}]无法计算中位数（可能数据为空或全为缺失值），已跳过"
                        )
                        continue
                    if etypes.get(col) == 'integer':
                        fill_val = safe_round(fill_val)
                        if fill_val is None:
                            continue
                    df[col].fillna(fill_val, inplace=True)
                    if etypes.get(col) == 'integer':
                        try_convert_to_int(col)
        
        elif strategy == 'mode':
            for col in cols:
                if col in df.columns:
                    mode_val = df[col].mode()[0] if len(df[col].mode()) > 0 else fill_value
                    # integer 列取整
                    if etypes.get(col) == 'integer' and mode_val is not None:
                        try:
                            mode_val = int(round(float(mode_val)))
                        except (ValueError, TypeError):
                            pass
                    df[col].fillna(mode_val, inplace=True)
                    if etypes.get(col) == 'integer':
                        try_convert_to_int(col)
        
        elif strategy == 'drop':
            df.dropna(subset=cols, inplace=True)
        
        elif strategy == 'fill' and fill_value is not None:
            for col in cols:
                if col in df.columns:
                    if isinstance(fill_value, dict):
                        # 字典按列取值；缺列时 col_fill 为 None，跳过该列填充
                        # （修复：原回退为整个 dict 作为填充值，fillna 静默失效）
                        col_fill = fill_value.get(col)
                    else:
                        col_fill = fill_value
                    if col_fill is None:
                        continue
                    # 校验填充值格式（不阻断，只警告）
                    try:
                        validate_fill_value(col, col_fill)
                    except ValueError as e:
                        self._last_warnings.append(str(e))
                    df[col].fillna(col_fill, inplace=True)
                    if etypes.get(col) == 'integer':
                        # 用 pd.array 安全转换，避免 float NaN 报错
                        try:
                            df[col] = pd.array(df[col], dtype=pd.Int64Dtype())
                        except (TypeError, ValueError):
                            pass
        
        return df
    
    def remove_duplicates(self, subset: List[str] = None, keep: str = 'first',
                          keep_rows: List[int] = None, value: Any = None,
                          group_rows: List[int] = None) -> pd.DataFrame:
        """删除重复行

        Args:
            subset: 用于识别重复的列，None表示所有列（行级完全重复）
            keep: 保留策略 (first/last/False)
            keep_rows: 指定保留的行索引列表（优先级最高，覆盖 keep 参数）
            value: 指定重复值，只处理该值的重复（用于分开模式中同列不同重复值分别处理）
            group_rows: 指定要处理的重复组的行索引列表（用于行重复分开模式，只处理这些行所在的重复组）
        """
        df = self.df.copy()
        
        # 如果指定了 value，则只处理该值的重复
        if value is not None and subset is not None and len(subset) > 0:
            mask = df[subset[0]] == value
            value_df = df[mask].copy()
            
            if keep_rows is not None and len(keep_rows) > 0:
                keep_set = set(keep_rows)
                drop_indices = [idx for idx in value_df.index if idx not in keep_set]
                if drop_indices:
                    df = df.drop(index=drop_indices)
                return df
            
            if keep is False or keep == 'False' or keep == 'false':
                df = df[~mask]
                return df
            
            dup_mask = value_df.duplicated(subset=subset, keep=keep)
            drop_indices = value_df[dup_mask].index.tolist()
            if drop_indices:
                df = df.drop(index=drop_indices)
            return df
        
        # 如果指定了 group_rows，则只处理这些行所在的重复组
        if group_rows is not None and len(group_rows) > 0:
            group_set = set(group_rows)
            # 找出所有重复组
            dup_mask = df.duplicated(subset=subset, keep=False)
            
            # 找出 group_rows 中哪些行属于重复行
            group_dup_indices = []
            for idx in group_rows:
                # idx 为行标签，dup_mask.loc[idx] 按标签取值（修复：原 iloc 按位置取值，
                # 索引非连续时会越界或取到错误行）
                if idx in df.index and dup_mask.loc[idx]:
                    group_dup_indices.append(idx)
            
            if not group_dup_indices:
                return df
            
            if keep_rows is not None and len(keep_rows) > 0:
                keep_set = set(keep_rows)
                drop_indices = [idx for idx in group_dup_indices if idx not in keep_set]
                if drop_indices:
                    df = df.drop(index=drop_indices)
                return df
            
            if keep is False or keep == 'False' or keep == 'false':
                df = df.drop(index=group_dup_indices)
                return df
            
            # 获取这些行所在的重复组的所有行
            all_dup_indices = set()
            for idx in group_dup_indices:
                # df.loc[idx] 按行标签取内容（修复：原 df.iloc[idx] 按位置取值，索引非连续时错位）
                row_content = df.loc[idx].tolist()
                for i, row in df.iterrows():
                    if row.tolist() == row_content:
                        all_dup_indices.add(i)
            
            # 在这些重复行中应用 keep 策略
            temp_df = df.loc[list(all_dup_indices)].copy()
            dup_mask_in_group = temp_df.duplicated(subset=subset, keep=keep)
            drop_indices = temp_df[dup_mask_in_group].index.tolist()
            if drop_indices:
                df = df.drop(index=drop_indices)
            return df
        
        # 如果指定了 keep_rows，则保留这些行，删除其余重复行
        if keep_rows is not None and len(keep_rows) > 0:
            dup_mask = df.duplicated(subset=subset, keep=False)
            if not dup_mask.any():
                return df
            dup_indices = set(df[dup_mask].index.tolist())
            keep_set = set(keep_rows)
            drop_indices = dup_indices - keep_set
            if drop_indices:
                df = df.drop(index=list(drop_indices))
            return df

        # keep=False 表示删除所有重复行
        if keep is False or keep == 'False' or keep == 'false':
            return df.drop_duplicates(subset=subset, keep=False)
        return df.drop_duplicates(subset=subset, keep=keep)
    
    def handle_outliers(self, method: str = 'remove', detection_method: str = 'iqr',
                        threshold: float = 1.5, columns: List[str] = None,
                        detection_methods: Dict[str, str] = None) -> pd.DataFrame:
        """处理异常值

        Args:
            method: 处理方法 (remove/drop/clip/cap/mark_missing)，drop 为 remove 别名，cap 为 clip 别名
            detection_method: 默认检测方法 (iqr/zscore/grubbs)，当detection_methods未指定时使用
            threshold: 阈值（IQR系数、Z-Score阈值、Grubbs显著性水平）
            columns: 指定列
            detection_methods: 每列的检测方法映射 {列名: 检测方法}，优先级高于detection_method
        """
        import scipy.stats as stats

        df = self.df.copy()
        cols = columns if columns else df.select_dtypes(include=[np.number]).columns

        for col in cols:
            if col not in df.columns:
                continue

            # 确定该列的检测方法：优先使用detection_methods中的映射
            col_detection = detection_method
            if detection_methods and col in detection_methods:
                col_detection = detection_methods[col]

            # 尝试将列转换为数值，无法转换的标记为 NaN
            numeric_col = pd.to_numeric(df[col], errors='coerce')
            # 忽略 NaN 值
            valid_mask = numeric_col.notna()
            valid_values = numeric_col[valid_mask]

            if len(valid_values) < 4:
                continue  # 数据太少不检测

            # 根据检测方法计算异常值边界
            if col_detection == 'zscore':
                z_scores = np.abs((valid_values - valid_values.mean()) / valid_values.std())
                outlier_mask = z_scores > threshold
                lower_bound = None
                upper_bound = None
            elif col_detection == 'grubbs':
                # Grubbs检验：每次检测一个最极端的异常值
                outlier_mask = pd.Series([False] * len(valid_values), index=valid_values.index)
                remaining = valid_values.copy()
                remaining_idx = list(remaining.index)
                while len(remaining) >= 3:
                    mean_val = remaining.mean()
                    std_val = remaining.std()
                    if std_val == 0:
                        break
                    g_scores = np.abs((remaining - mean_val) / std_val)
                    max_g = g_scores.max()
                    # 计算临界值
                    n = len(remaining)
                    t_val = stats.t.ppf(1 - threshold / (2 * n), n - 2)
                    g_crit = (n - 1) * t_val / np.sqrt(n * (n - 2 + t_val ** 2))
                    if max_g > g_crit:
                        max_idx = g_scores.idxmax()
                        outlier_mask[max_idx] = True
                        remaining = remaining.drop(max_idx)
                    else:
                        break
                lower_bound = None
                upper_bound = None
            else:
                # 默认 IQR
                Q1 = valid_values.quantile(0.25)
                Q3 = valid_values.quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - threshold * IQR
                upper_bound = Q3 + threshold * IQR
                outlier_mask = (valid_values < lower_bound) | (valid_values > upper_bound)

            # 获取全局异常值掩码
            global_outlier_mask = pd.Series([False] * len(df), index=df.index)
            if col_detection in ('zscore', 'grubbs'):
                global_outlier_mask[outlier_mask.index] = outlier_mask
            else:
                global_outlier_mask[valid_values.index] = outlier_mask

            # 应用处理方法
            if method in ('remove', 'drop'):
                df = df[~global_outlier_mask]
            elif method in ('cap', 'clip'):
                if lower_bound is not None and upper_bound is not None:
                    df.loc[global_outlier_mask, col] = numeric_col[global_outlier_mask].clip(lower_bound, upper_bound)
                else:
                    mean_val = valid_values.mean()
                    std_val = valid_values.std()
                    lb = mean_val - 3 * std_val
                    ub = mean_val + 3 * std_val
                    df.loc[global_outlier_mask, col] = numeric_col[global_outlier_mask].clip(lb, ub)
            elif method == 'mark_missing':
                df.loc[global_outlier_mask, col] = np.nan

        return df
    
    def handle_range_errors(self, method: str = 'clip', columns: List[str] = None,
                           ranges: Dict[str, List] = None, fill_value: Any = None) -> pd.DataFrame:
        """处理范围错误

        Args:
            method: 处理方法 (clip/drop/mean/median/mode/mark_missing/fill)
            columns: 指定列
            ranges: 列的范围定义 {col: [(min, max), ...]}
            fill_value: 自定义填充值（当method='fill'时使用）
        """
        df = self.df.copy()
        cols = columns if columns else df.select_dtypes(include=[np.number]).columns

        for col in cols:
            if col not in df.columns:
                continue

            # 获取该列的范围定义
            col_ranges = ranges.get(col, []) if ranges else []
            if not col_ranges:
                continue

            # None 表示无界限，上界 None → inf，下界 None → -inf
            col_ranges = [
                (float(min_v) if min_v is not None else float('-inf'),
                 float(max_v) if max_v is not None else float('inf'))
                for min_v, max_v in col_ranges
            ]

            # 尝试将列转换为数值，失败的转为 NaN
            numeric_col = pd.to_numeric(df[col], errors='coerce')

            # 保存原始 NaN 位置，这些不是范围错误，不应被处理
            orig_nan_mask = numeric_col.isna()

            if method == 'clip':
                # 截断到范围内（使用第一个范围），只截断非 NaN 的值
                min_val, max_val = col_ranges[0]
                # 只 clip 非 NaN 且超出范围的值，保持类型错误的值不变
                in_range_mask = (numeric_col >= min_val) & (numeric_col <= max_val) & ~orig_nan_mask
                out_of_range = ~in_range_mask & ~orig_nan_mask
                df.loc[out_of_range, col] = numeric_col[out_of_range].clip(min_val, max_val)

            elif method == 'drop':
                # 删除超出范围的行（只检查非NaN的行，NaN行保留）
                # 构建"在范围内"的 mask，NaN 行也算在范围内（不删除）
                in_range_mask = orig_nan_mask.copy()  # NaN 行暂时保留
                for min_val, max_val in col_ranges:
                    # 非NaN且在范围内
                    in_range_mask |= (numeric_col >= min_val) & (numeric_col <= max_val)
                df = df[in_range_mask]

            elif method == 'mean':
                # 用范围内有效值的均值填充超出范围的值（不处理NaN和类型错误）
                in_range_mask = pd.Series([False] * len(df), index=df.index)
                for min_val, max_val in col_ranges:
                    in_range_mask |= (numeric_col >= min_val) & (numeric_col <= max_val)
                if in_range_mask.any():
                    mean_val = numeric_col[in_range_mask].mean()
                    out_of_range = ~in_range_mask & ~orig_nan_mask
                    df.loc[out_of_range, col] = mean_val

            elif method == 'median':
                # 用范围内有效值的中位数填充超出范围的值（不处理NaN和类型错误）
                in_range_mask = pd.Series([False] * len(df), index=df.index)
                for min_val, max_val in col_ranges:
                    in_range_mask |= (numeric_col >= min_val) & (numeric_col <= max_val)
                if in_range_mask.any():
                    median_val = numeric_col[in_range_mask].median()
                    out_of_range = ~in_range_mask & ~orig_nan_mask
                    df.loc[out_of_range, col] = median_val

            elif method == 'mode':
                # 用范围内有效值的众数填充超出范围的值（不处理NaN和类型错误）
                in_range_mask = pd.Series([False] * len(df), index=df.index)
                for min_val, max_val in col_ranges:
                    in_range_mask |= (numeric_col >= min_val) & (numeric_col <= max_val)
                mode_vals = numeric_col[in_range_mask].mode()
                if len(mode_vals) > 0:
                    out_of_range = ~in_range_mask & ~orig_nan_mask
                    df.loc[out_of_range, col] = mode_vals[0]

            elif method == 'mark_missing':
                # 将超出范围的值标记为NaN（不处理原本就是NaN的值和类型错误）
                in_range_mask = pd.Series([False] * len(df), index=df.index)
                for min_val, max_val in col_ranges:
                    in_range_mask |= (numeric_col >= min_val) & (numeric_col <= max_val)
                out_of_range = ~in_range_mask & ~orig_nan_mask
                df.loc[out_of_range, col] = np.nan

            elif method == 'fill':
                # 用自定义值填充超出范围的值（不处理NaN和类型错误）
                if fill_value is not None:
                    in_range_mask = pd.Series([False] * len(df), index=df.index)
                    for min_val, max_val in col_ranges:
                        in_range_mask |= (numeric_col >= min_val) & (numeric_col <= max_val)
                    out_of_range = ~in_range_mask & ~orig_nan_mask
                    df.loc[out_of_range, col] = fill_value

        return df
    
    def handle_type_errors(self, method: str = 'keep', columns: List[str] = None,
                           expected_types: Dict[str, str] = None) -> pd.DataFrame:
        """处理类型错误

        Args:
            method: 处理方法 (keep/delete/mark_missing)
            columns: 指定列
            expected_types: 列的期望类型 {col: 'number'|'integer'|...}
        """
        df = self.df.copy()
        cols = columns if columns else df.columns

        if method == 'keep':
            return df

        for col in cols:
            if col not in df.columns:
                continue

            expected = (expected_types or {}).get(col)

            # 数值/整数列：尝试转换为数值，失败项按策略处理
            if expected in ('number', 'integer') or (
                expected is None and pd.api.types.is_numeric_dtype(df[col])
            ):
                converted = pd.to_numeric(df[col], errors='coerce')
                invalid_mask = converted.isna() & df[col].notna()
                if method == 'delete':
                    df = df[~invalid_mask]
                elif method == 'mark_missing':
                    df.loc[invalid_mask, col] = np.nan
                else:
                    df[col] = converted

            # 整数列额外检查小数
            if expected == 'integer':
                numeric = pd.to_numeric(df[col], errors='coerce')
                non_integer_mask = numeric.notna() & (~numeric.apply(lambda x: float(x).is_integer() if pd.notna(x) else False))
                if method == 'delete':
                    df = df[~non_integer_mask]
                elif method == 'mark_missing':
                    df.loc[non_integer_mask, col] = np.nan

            elif expected == 'boolean':
                bool_values = {'true', 'false', '0', '1', '是', '否', 'yes', 'no', 't', 'f', 'y', 'n'}
                invalid_mask = df[col].notna() & ~df[col].astype(str).str.lower().isin(bool_values)
                if method == 'delete':
                    df = df[~invalid_mask]
                elif method == 'mark_missing':
                    df.loc[invalid_mask, col] = np.nan

            elif expected in ('email', 'url', 'date'):
                if expected == 'email':
                    import re
                    pattern = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
                    invalid_mask = df[col].notna() & ~df[col].astype(str).apply(lambda x: bool(pattern.match(x)))
                elif expected == 'url':
                    import re
                    pattern = re.compile(r'^https?:\/\/[^\s]+$', re.I)
                    invalid_mask = df[col].notna() & ~df[col].astype(str).apply(lambda x: bool(pattern.match(x)))
                else:  # date
                    invalid_mask = df[col].notna() & ~pd.to_datetime(df[col], errors='coerce').notna()

                if method == 'delete':
                    df = df[~invalid_mask]
                elif method == 'mark_missing':
                    df.loc[invalid_mask, col] = np.nan

            # 对于字符串列，标记空字符串为NaN（可选，保持原有行为）
            if method == 'mark_missing' and expected is None and df[col].dtype == object:
                df[col] = df[col].replace('', np.nan)

        return df

    def apply_type_constraints(self, expected_types: Dict[str, str] = None, warn_only: bool = True) -> pd.DataFrame:
        """类型校正：将列强制转换为期望类型

        Args:
            expected_types: {列名: 类型}，类型取值 'integer'|'number'|'string'|'boolean'|'date'|'email'|'url'
            warn_only: True=警告模式（有 NaN/类型错误不阻断，返回警告）；False=严格模式（报错）

        Raises:
            ValueError: warn_only=False 时任何错误抛出；warn_only=True 时只跳过错误列
        """
        df = self.df.copy()
        etypes = expected_types or {}
        # 返回所有警告信息（调用方可读 warnings）
        self._last_warnings = []

        for col, expected in etypes.items():
            if col not in df.columns:
                continue
            if expected == 'integer':
                orig_non_nan = df[col].notna()
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                bad_mask = orig_non_nan & numeric_col.isna()
                if bad_mask.any():
                    if warn_only:
                        bad_idx = df.index[bad_mask].tolist()[:5]
                        bad_vals = df.loc[bad_idx, col].tolist()
                        self._last_warnings.append(
                            f"【类型错误】列[{col}]有{int(bad_mask.sum())}个值无法转换为integer（行: {bad_idx}, 值: {bad_vals}）"
                        )
                        continue
                    else:
                        bad_idx = df.index[bad_mask].tolist()[:5]
                        bad_vals = df.loc[bad_idx, col].tolist()
                        raise ValueError(
                            f"【类型错误】列[{col}]在表单中限制为integer类型，但存在无法转换为整数的值。\n"
                            f"  - 问题行索引: {bad_idx}\n"
                            f"  - 不合法的值: {bad_vals}\n"
                            f"  - 原因: 这些值属于「类型错误」，不是缺失值，均值填充无法处理它们\n"
                            f"  - 建议: 回到「类型错误」区域，选择「删除该行」或「标记为缺失值」后再清洗"
                        )
                # 有 NaN 时跳过（不阻断），警告
                if numeric_col.isna().any():
                    if warn_only:
                        nan_count = int(numeric_col.isna().sum())
                        self._last_warnings.append(
                            f"【缺失值残留】列[{col}]还有{nan_count}个NaN，无法转换为integer"
                        )
                        continue
                    else:
                        raise ValueError(
                            f"【缺失值残留】列[{col}]在转换为integer类型前仍有{int(numeric_col.isna().sum())}个NaN\n"
                            f"  - 原因: 缺失值处理不完整\n"
                            f"  - 建议: 回到「缺失值」区域，选择合适的填充策略"
                        )
                # 检查小数（先 dropna 避免 NaN 触发 % 1 报错）
                non_na_numeric = numeric_col.dropna()
                if len(non_na_numeric) > 0:
                    has_decimal = (non_na_numeric % 1 != 0)
                    if has_decimal.any():
                        if warn_only:
                            bad_idx = non_na_numeric.index[has_decimal].tolist()[:5]
                            bad_vals = non_na_numeric[bad_idx].tolist()
                            self._last_warnings.append(
                                f"【类型错误】列[{col}]有{int(has_decimal.sum())}个小数无法转换为integer（行: {bad_idx}, 值: {bad_vals}）"
                            )
                            continue
                        else:
                            bad_idx = non_na_numeric.index[has_decimal].tolist()[:5]
                            bad_vals = non_na_numeric[bad_idx].tolist()
                            raise ValueError(
                                f"【类型错误】列[{col}]在表单中限制为integer类型，但存在小数值。\n"
                                f"  - 问题行索引: {bad_idx}\n"
                                f"  - 不合法的值: {bad_vals}\n"
                                f"  - 建议: 将该列类型改为number，或在「类型错误」中选择处理方式"
                            )
                # 用 pd.array 安全转换（即使全部非NaN也用这个）
                try:
                    df[col] = pd.array(numeric_col, dtype=pd.Int64Dtype())
                except (TypeError, ValueError):
                    # 转不了就跳过（保留原值），加警告
                    self._last_warnings.append(
                        f"【类型转换】列[{col}]存在无法转换为integer的值，已跳过"
                    )

            elif expected == 'number':
                orig_non_nan = df[col].notna()
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                bad_mask = orig_non_nan & numeric_col.isna()
                if bad_mask.any():
                    if warn_only:
                        bad_idx = df.index[bad_mask].tolist()[:5]
                        bad_vals = df.loc[bad_idx, col].tolist()
                        self._last_warnings.append(
                            f"【类型错误】列[{col}]有{int(bad_mask.sum())}个值无法转换为number（行: {bad_idx}, 值: {bad_vals}）"
                        )
                        continue
                    else:
                        bad_idx = df.index[bad_mask].tolist()[:5]
                        bad_vals = df.loc[bad_idx, col].tolist()
                        raise ValueError(
                            f"【类型错误】列[{col}]在表单中限制为number类型，但存在无法转换为数值的值。\n"
                            f"  - 问题行索引: {bad_idx}\n"
                            f"  - 不合法的值: {bad_vals}\n"
                            f"  - 原因: 这些值属于「类型错误」，不是缺失值，均值填充无法处理它们\n"
                            f"  - 建议: 回到「类型错误」区域，选择「删除该行」或「标记为缺失值」后再清洗"
                        )
                df[col] = numeric_col.astype('float64')

            elif expected == 'email':
                email_re = re.compile(r'^[\w.+-]+@[\w-]+\.[\w.-]+$')
                non_na_mask = df[col].notna()
                if non_na_mask.any():
                    bad = df.loc[non_na_mask, col].astype(str).apply(lambda x: not email_re.match(x))
                    if bad.any():
                        if warn_only:
                            bad_idx = df.index[non_na_mask][bad].tolist()[:5]
                            bad_vals = df.loc[bad_idx, col].tolist()
                            self._last_warnings.append(
                                f"【类型错误】列[{col}]有{int(bad.sum())}个不合法邮箱（行: {bad_idx}, 值: {bad_vals}）"
                            )
                            continue
                        else:
                            bad_idx = df.index[non_na_mask][bad].tolist()[:5]
                            bad_vals = df.loc[bad_idx, col].tolist()
                            raise ValueError(
                                f"【类型错误】列[{col}]在表单中限制为email类型，但存在不合法的邮箱地址。\n"
                                f"  - 问题行索引: {bad_idx}\n"
                                f"  - 不合法的值: {bad_vals}\n"
                                f"  - 原因: 这些值属于「类型错误」，不是缺失值，填充方法无法处理它们\n"
                                f"  - 建议: 回到「类型错误」区域，选择「删除该行」或「标记为缺失值」后再清洗"
                            )
                df[col] = df[col].astype('object')

            elif expected == 'url':
                url_re = re.compile(r'^https?://[\w.-]+(?::\d+)?(?:/.*)?$')
                non_na_mask = df[col].notna()
                if non_na_mask.any():
                    bad = df.loc[non_na_mask, col].astype(str).apply(lambda x: not url_re.match(x))
                    if bad.any():
                        if warn_only:
                            bad_idx = df.index[non_na_mask][bad].tolist()[:5]
                            bad_vals = df.loc[bad_idx, col].tolist()
                            self._last_warnings.append(
                                f"【类型错误】列[{col}]有{int(bad.sum())}个不合法URL（行: {bad_idx}, 值: {bad_vals}）"
                            )
                            continue
                        else:
                            bad_idx = df.index[non_na_mask][bad].tolist()[:5]
                            bad_vals = df.loc[bad_idx, col].tolist()
                            raise ValueError(
                                f"【类型错误】列[{col}]在表单中限制为url类型，但存在不合法的URL。\n"
                                f"  - 问题行索引: {bad_idx}\n"
                                f"  - 不合法的值: {bad_vals}\n"
                                f"  - 原因: 这些值属于「类型错误」，不是缺失值，填充方法无法处理它们\n"
                                f"  - 建议: 回到「类型错误」区域，选择「删除该行」或「标记为缺失值」后再清洗"
                            )
                df[col] = df[col].astype('object')

            elif expected == 'date':
                non_na_mask = df[col].notna()
                if non_na_mask.any():
                    try:
                        parsed = pd.to_datetime(df.loc[non_na_mask, col], errors='raise')
                        df.loc[non_na_mask, col] = parsed.dt.strftime('%Y-%m-%d')
                    except Exception:
                        if warn_only:
                            bad_idx = df.index[non_na_mask].tolist()[:5]
                            bad_vals = df.loc[bad_idx, col].tolist()
                            self._last_warnings.append(
                                f"【类型错误】列[{col}]有不合法的日期（行: {bad_idx}, 值: {bad_vals}）"
                            )
                        else:
                            bad_idx = df.index[non_na_mask].tolist()[:5]
                            bad_vals = df.loc[bad_idx, col].tolist()
                            raise ValueError(
                                f"【类型错误】列[{col}]在表单中限制为date类型，但存在不合法的日期。\n"
                                f"  - 问题行索引: {bad_idx}\n"
                                f"  - 不合法的值: {bad_vals}\n"
                                f"  - 原因: 这些值属于「类型错误」，不是缺失值，填充方法无法处理它们\n"
                                f"  - 建议: 回到「类型错误」区域，选择「删除该行」或「标记为缺失值」后再清洗"
                            )

            elif expected == 'boolean':
                non_na_mask = df[col].notna()
                if non_na_mask.any():
                    bool_map = {'true': 'true', 'false': 'false', '1': 'true', '0': 'false',
                                'yes': 'true', 'no': 'false', '是': 'true', '否': 'false'}
                    bad_vals_found = []
                    def to_bool(v):
                        s = str(v).strip().lower()
                        if s in bool_map:
                            return bool_map[s]
                        bad_vals_found.append(v)
                        return v  # 警告模式保留原值
                    df.loc[non_na_mask, col] = df.loc[non_na_mask, col].apply(to_bool)
                    if bad_vals_found:
                        if warn_only:
                            self._last_warnings.append(
                                f"【类型错误】列[{col}]有{len(bad_vals_found)}个不合法布尔值: {bad_vals_found[:5]}"
                            )
                        else:
                            raise ValueError(
                                f"【类型错误】列[{col}]为boolean类型，存在不合法值: {bad_vals_found[:5]}"
                            )

            elif expected == 'string':
                df[col] = df[col].astype('object')

        return df

    def precheck(self, df: pd.DataFrame) -> Dict[str, Any]:
        """清洗前数据预检：自动检测数据问题，返回问题清单

        Args:
            df: 待检测的数据框

        Returns:
            包含缺失值、重复行、类型识别、异常值、类型错误等检测结果的字典
        """
        data = df

        result = {
            "missing_values": {},
            "duplicate_rows": {},
            "type_detection": {},
            "outliers": {},
            "type_errors": {}
        }

        total_rows = len(data)

        # 复用与 handle_missing_values 一致的正则，保证推断与后续校验规则统一
        email_pattern = re.compile(r'^[\w.+-]+@[\w-]+\.[\w.-]+$')
        url_pattern = re.compile(r'^https?://[\w.-]+(?::\d+)?(?:/.*)?$')
        # 布尔语义值集合：0/1 与 true/false 等同列出现时才视为布尔语义
        bool_value_set = {'true', 'false', '0', '1', 'yes', 'no', '是', '否'}
        # 明确的布尔语义值（非 0/1），用于消除纯 0/1 列与布尔列的歧义
        explicit_bool_values = {'true', 'false', 'yes', 'no', '是', '否'}

        # ============ 缺失值统计 ============
        # 返回结构：{count, percentage, row_indices}
        # row_indices 为缺失值所在行索引列表；超过100条时截断并增加 total_count 记录真实总数
        for col in data.columns:
            missing_count = int(data[col].isna().sum())
            # 仅包含有缺失值的列，避免返回冗余信息
            if missing_count > 0:
                # 获取缺失值所在的行索引列表
                missing_indices = data.index[data[col].isna()].tolist()
                missing_entry = {
                    "count": missing_count,
                    "percentage": round(float(missing_count) / float(total_rows) * 100, 2) if total_rows > 0 else 0.0,
                    "row_indices": [int(i) for i in missing_indices[:100]]
                }
                # 行号列表超过100条时截断，并记录真实总数
                if len(missing_indices) > 100:
                    missing_entry["total_count"] = len(missing_indices)
                result["missing_values"][col] = missing_entry

        # ============ 重复行统计 ============
        # 返回结构：{full_row_count, groups, suggestion}
        # groups 为重复行组数组，每组包含 row_indices 与 row_values
        # 重复行组最多返回前5组，超过时增加 total_groups 字段
        full_row_count = int(data.duplicated().sum())
        duplicate_groups = []
        # 使用 duplicated(keep=False) 获取所有重复行（包含首次出现的行），再按行内容分组
        duplicated_data = data[data.duplicated(keep=False)]
        if len(duplicated_data) > 0:
            # 按所有列分组，每组即为一组重复行
            grouped = duplicated_data.groupby(list(data.columns), dropna=False)
            for _, group in grouped:
                # 仅当组内行数大于1时才视为真正的重复行组
                if len(group) > 1:
                    row_indices = [int(i) for i in group.index.tolist()]
                    # row_values 取该组第一行作为代表，所有值用 _to_serializable 转换
                    first_row = group.iloc[0]
                    row_values = {col: self._to_serializable(first_row[col]) for col in data.columns}
                    duplicate_groups.append({
                        "row_indices": row_indices,
                        "row_values": row_values
                    })

        duplicate_result = {
            "full_row_count": full_row_count,
            "total_rows": total_rows,
            "percentage": round(float(full_row_count) / float(total_rows) * 100, 2) if total_rows > 0 else 0.0,
            "groups": duplicate_groups[:5],
            "suggestion": "可指定列进行列级去重"
        }
        # 重复行组超过5组时，记录真实总组数
        if len(duplicate_groups) > 5:
            duplicate_result["total_groups"] = len(duplicate_groups)
        result["duplicate_rows"] = duplicate_result

        # ============ 类型识别 ============
        inferred_types: Dict[str, str] = {}

        for col in data.columns:
            col_series = data[col]
            inferred_type = 'string'
            # 提取前5个非空值作为样本，便于用户判断推断是否合理
            non_null_samples = col_series.dropna().head(5).tolist()
            samples = [self._to_serializable(v) for v in non_null_samples]

            # 使用 pd.api.types.is_numeric_dtype 判断数值列，兼容 pandas 2.x/3.x
            # pandas 3.x 中字符串列 dtype 为 StringDtype，np.issubdtype 会抛 TypeError，需用 pandas API
            if pd.api.types.is_numeric_dtype(col_series):
                # 数值列：所有非空值为整数则 integer，否则 number
                non_null = col_series.dropna()
                if len(non_null) > 0 and (non_null % 1 == 0).all():
                    inferred_type = 'integer'
                else:
                    inferred_type = 'number'
            elif col_series.dtype == 'object' or pd.api.types.is_string_dtype(col_series):
                # object 列：采样前100个非空值，按优先级匹配 email/url/date/boolean/integer/number/string
                non_null_100 = col_series.dropna().head(100)
                if len(non_null_100) == 0:
                    inferred_type = 'string'
                else:
                    str_values = non_null_100.astype(str)
                    inferred_type = self._infer_object_column_type(
                        str_values, email_pattern, url_pattern,
                        bool_value_set, explicit_bool_values
                    )

            inferred_types[col] = inferred_type
            result["type_detection"][col] = {
                "inferred_type": inferred_type,
                "samples": samples
            }

        # ============ 异常值检测 ============
        # 仅对推断为 integer/number 类型的列使用 IQR 检测，避免对类别/字符串列误报
        for col, inferred_type in inferred_types.items():
            if inferred_type not in ('integer', 'number'):
                continue

            # 列可能仍为 object 类型，统一转为数值进行检测
            numeric_col = pd.to_numeric(data[col], errors='coerce')
            valid_values = numeric_col.dropna()
            # 数据太少时 IQR 不稳定，跳过避免误判
            if len(valid_values) < 4:
                continue

            Q1 = valid_values.quantile(0.25)
            Q3 = valid_values.quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR

            # NaN 比较结果为 False，fillna(False) 仅为防御性写法
            outlier_mask = (numeric_col < lower_bound) | (numeric_col > upper_bound)
            outlier_mask = outlier_mask.fillna(False)
            outlier_indices = data.index[outlier_mask].tolist()

            # 仅包含有异常值的列；行索引最多返回100个，避免数据过大
            # 返回结构：{count, row_indices, values, bounds}
            # values 与 row_indices 一一对应（最多100个）；bounds 为 IQR 边界
            if outlier_indices:
                # 截取前100个异常值的索引，并按索引取对应的具体值
                top_indices = outlier_indices[:100]
                outlier_values = [
                    self._to_serializable(numeric_col.loc[idx])
                    for idx in top_indices
                ]
                result["outliers"][col] = {
                    "count": len(outlier_indices),
                    "row_indices": [int(i) for i in top_indices],
                    "values": outlier_values,
                    "bounds": {
                        "lower": float(lower_bound),
                        "upper": float(upper_bound)
                    }
                }

        # ============ 类型错误检测 ============
        # 仅对推断为 integer/number/date/email/url 类型的 object 列检测
        # 数值 dtype 列已被 pandas 强类型保证，不存在"形式上的"类型错误
        for col, inferred_type in inferred_types.items():
            if inferred_type not in ('integer', 'number', 'date', 'email', 'url'):
                continue
            # 使用 pd.api.types.is_numeric_dtype 替代 np.issubdtype，兼容 pandas 3.x
            if pd.api.types.is_numeric_dtype(data[col]):
                continue

            non_null_mask = data[col].notna()
            non_null_values = data[col][non_null_mask]
            if len(non_null_values) == 0:
                continue

            # 根据推断类型校验每个非空值，无法转换/不匹配的即为类型错误
            if inferred_type in ('integer', 'number'):
                converted = pd.to_numeric(non_null_values, errors='coerce')
                invalid_mask = converted.isna()
            elif inferred_type == 'date':
                converted = pd.to_datetime(non_null_values, errors='coerce')
                invalid_mask = converted.isna()
            elif inferred_type == 'email':
                invalid_mask = ~non_null_values.astype(str).apply(lambda x: bool(email_pattern.match(x)))
            else:  # url
                invalid_mask = ~non_null_values.astype(str).apply(lambda x: bool(url_pattern.match(x)))

            error_count = int(invalid_mask.sum())
            # 仅包含有类型错误的列；取前5个错误值作为样本供用户判断
            # 返回结构：{count, samples, error_rows, expected_type}
            # error_rows 为错误行详细信息（最多100条）；expected_type 即推断的期望类型
            if error_count > 0:
                error_samples = non_null_values[invalid_mask].head(5).tolist()
                # 错误行详细信息，最多100条
                error_rows_series = non_null_values[invalid_mask].head(100)
                error_rows = [
                    {"row_index": int(idx), "value": self._to_serializable(val)}
                    for idx, val in error_rows_series.items()
                ]
                result["type_errors"][col] = {
                    "count": error_count,
                    "samples": [self._to_serializable(v) for v in error_samples],
                    "error_rows": error_rows,
                    "expected_type": inferred_type
                }

        return result

    def _infer_object_column_type(self, str_values: pd.Series,
                                   email_pattern: re.Pattern,
                                   url_pattern: re.Pattern,
                                   bool_value_set: set,
                                   explicit_bool_values: set) -> str:
        """根据采样字符串值推断 object 列的类型

        按优先级依次匹配：email > url > date > boolean > integer > number > string

        Args:
            str_values: 采样后的字符串 Series（已 dropna、head(100)、astype(str)）
            email_pattern: 邮箱正则
            url_pattern: URL 正则
            bool_value_set: 布尔语义值集合
            explicit_bool_values: 明确的布尔语义值集合（用于消除 0/1 歧义）

        Returns:
            推断的类型字符串
        """
        # 邮箱：全部匹配 email 正则
        if str_values.apply(lambda x: bool(email_pattern.match(x))).all():
            return 'email'

        # URL：全部匹配 url 正则
        if str_values.apply(lambda x: bool(url_pattern.match(x))).all():
            return 'url'

        # 日期：全部可被 pd.to_datetime 解析
        try:
            parsed = pd.to_datetime(str_values, errors='coerce')
            if parsed.notna().all():
                return 'date'
        except Exception:
            pass

        # 布尔：全部在布尔值集合内，且至少存在一个明确的布尔语义值
        # 纯 0/1 列不视为布尔，避免与整数列混淆
        lowered = str_values.str.lower()
        if lowered.isin(bool_value_set).all() and lowered.isin(explicit_bool_values).any():
            return 'boolean'

        # 数值：全部可被 pd.to_numeric 转换
        numeric_converted = pd.to_numeric(str_values, errors='coerce')
        if numeric_converted.notna().all():
            # 全部为整数则为 integer，否则为 number
            if (numeric_converted % 1 == 0).all():
                return 'integer'
            return 'number'

        return 'string'

    def _to_serializable(self, value: Any) -> Any:
        """将 numpy 类型转换为 Python 原生类型，避免 JSON 序列化失败"""
        if value is None:
            return None
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            # NaN 也走此分支，转换为 None 避免 JSON 序列化失败
            if pd.isna(value):
                return None
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.str_):
            return str(value)
        # 处理 Python 原生 float 的 inf/-inf/NaN，JSON 标准不支持这些值
        if isinstance(value, float):
            if math.isinf(value) or math.isnan(value):
                return None
        # 兜底：处理 pandas.NA 等其他缺失值表示
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value

    def analyze_problems(self, df: pd.DataFrame, contract: Dict[str, Any]) -> Dict[str, Any]:
        """根据契约动态计算数据问题清单

        根据规范化后的契约对原始数据进行六类问题检测：
        缺失值、类型错误、范围错误、异常值、行重复、列重复。

        检测顺序与优先级：
        1. 缺失值：契约中所有列的 NaN/空值
        2. 类型错误：integer/number/date/email/url 列的类型不符值
           - integer 类型：值不能含小数（如 25.5 是类型错误），但 "25" 字符串可转换不算错误
           - number 类型：值必须能转数值，"25"可转不算错误
        3. 范围错误：配置了 ranges 的数值列的超出范围值（优先于异常值）
        4. 异常值：数值列中超出 IQR 边界的值（排除已标记为范围错误的值）
        5. 行重复：所有列完全相同的重复行
        6. 列重复：契约中 allow_duplicate=false 的列的重复值

        范围错误优先于异常值：一个值不会同时出现在两个问题组中。

        Args:
            df: 原始数据框
            contract: 规范化后的契约字典

        Returns:
            包含 summary 和 problems 的问题清单字典
        """
        # 复用 precheck 中的正则，保证类型判断逻辑统一
        email_pattern = re.compile(r'^[\w.+-]+@[\w-]+\.[\w.-]+$')
        url_pattern = re.compile(r'^https?://[\w.-]+(?::\d+)?(?:/.*)?$')

        problems: Dict[str, List[Any]] = {
            "missing_values": [],
            "type_errors": [],
            "range_errors": [],
            "outliers": [],
            "row_duplicates": [],
            "column_duplicates": []
        }

        # 真实总数（不受 problems 列表上限影响）
        total_missing = 0
        total_type_errors = 0
        total_range_errors = 0
        total_outliers = 0
        total_column_dup_groups = 0

        # 记录每列已标记为范围错误的行索引，用于异常值检测时排除
        range_error_rows_by_col: Dict[str, set] = {}

        # 单列问题清单上限（性能保护）
        per_column_limit = 100
        row_dup_limit = 5
        col_dup_limit = 10

        # ============ 1. 缺失值检测 ============
        # 遍历契约中所有列，对每列检测 NaN/空值
        # 推荐策略：数值列(integer/number)用 "mean"，其他列用 "mode"
        for col, rules in contract.items():
            if col not in df.columns or not isinstance(rules, dict):
                continue
            # 用户契约声明"允许缺失"（allow_missing=true）的列不列为缺失问题（修复：此前该开关完全失效）
            if rules.get('allow_missing', False) is True:
                continue
            expected_type = rules.get('expected_type')
            missing_mask = df[col].isna()
            missing_count = int(missing_mask.sum())
            total_missing += missing_count
            if missing_count == 0:
                continue
            # 推荐处理策略：数值列用均值，其他列用众数
            suggested = 'mean' if expected_type in ('integer', 'number') else 'mode'
            missing_indices = df.index[missing_mask].tolist()
            col_added = 0
            for idx in missing_indices:
                problems["missing_values"].append({
                    "row_index": int(idx),
                    "column": col,
                    "current_value": None,
                    "column_type": expected_type,
                    "suggested_strategy": suggested
                })
                col_added += 1
                if col_added >= per_column_limit:
                    break

        # ============ 2. 类型错误检测 ============
        # 仅检测 expected_type 为 integer/number/date/email/url 的列
        # 数值 dtype 列：integer 额外检查小数；number 不存在形式上的类型错误
        # object 列：先用 pd.to_numeric(errors='coerce') 尝试转换，转换失败的为类型错误
        for col, rules in contract.items():
            if col not in df.columns or not isinstance(rules, dict):
                continue
            expected_type = rules.get('expected_type')
            if expected_type not in ('integer', 'number', 'date', 'email', 'url'):
                continue

            non_na_mask = df[col].notna()
            non_na_values = df[col][non_na_mask]
            if len(non_na_values) == 0:
                continue

            # 数值 dtype 列：仅 integer 需要检查小数
            if pd.api.types.is_numeric_dtype(df[col]):
                if expected_type == 'integer':
                    # 检查小数（如 25.5 是类型错误）
                    has_decimal = non_na_values.apply(
                        lambda x: not float(x).is_integer() if pd.notna(x) else False
                    )
                    total_type_errors += int(has_decimal.sum())
                    error_indices = non_na_values.index[has_decimal].tolist()
                    col_added = 0
                    for idx in error_indices:
                        problems["type_errors"].append({
                            "row_index": int(idx),
                            "column": col,
                            "current_value": self._to_serializable(df.at[idx, col]),
                            "expected_type": expected_type,
                            "suggested_strategy": "coerce_or_mark"
                        })
                        col_added += 1
                        if col_added >= per_column_limit:
                            break
                continue

            # object 列：先尝试转换，转换失败的标记为类型错误
            if expected_type in ('integer', 'number'):
                converted = pd.to_numeric(non_na_values, errors='coerce')
                invalid_mask = converted.isna()
                # integer 类型额外检查小数：转换成功但有小数也算类型错误
                if expected_type == 'integer':
                    decimal_mask = converted.notna() & converted.apply(
                        lambda x: not float(x).is_integer() if pd.notna(x) else False
                    )
                    invalid_mask = invalid_mask | decimal_mask
            elif expected_type == 'date':
                converted = pd.to_datetime(non_na_values, errors='coerce')
                invalid_mask = converted.isna()
            elif expected_type == 'email':
                invalid_mask = ~non_na_values.astype(str).apply(
                    lambda x: bool(email_pattern.match(x))
                )
            else:  # url
                invalid_mask = ~non_na_values.astype(str).apply(
                    lambda x: bool(url_pattern.match(x))
                )

            total_type_errors += int(invalid_mask.sum())
            error_indices = non_na_values.index[invalid_mask].tolist()
            col_added = 0
            for idx in error_indices:
                problems["type_errors"].append({
                    "row_index": int(idx),
                    "column": col,
                    "current_value": self._to_serializable(df.at[idx, col]),
                    "expected_type": expected_type,
                    "suggested_strategy": "coerce_or_mark"
                })
                col_added += 1
                if col_added >= per_column_limit:
                    break

        # ============ 3. 范围错误检测（优先于异常值） ============
        # 仅对配置了 ranges 的数值列检测
        # 值超出所有 ranges 的为范围错误
        for col, rules in contract.items():
            if col not in df.columns or not isinstance(rules, dict):
                continue
            expected_type = rules.get('expected_type')
            if expected_type not in ('integer', 'number'):
                continue
            col_ranges = rules.get('ranges')
            if not col_ranges:
                continue

            # 尝试将列转换为数值，失败的转为 NaN（即类型错误，不属于范围错误）
            numeric_col = pd.to_numeric(df[col], errors='coerce')
            valid_mask = numeric_col.notna()

            # 找出最大上边界和最小下边界，用于决定 suggested_strategy
            # None 表示无界限，上界 None → inf，下界 None → -inf
            max_upper = max(float(r[1]) if r[1] is not None else float('inf') for r in col_ranges)
            min_lower = min(float(r[0]) if r[0] is not None else float('-inf') for r in col_ranges)

            # 向量化计算：值是否在任一范围内
            in_range_mask = pd.Series(False, index=df.index)
            for min_v, max_v in col_ranges:
                lower = float(min_v) if min_v is not None else float('-inf')
                upper = float(max_v) if max_v is not None else float('inf')
                in_range_mask |= (numeric_col >= lower) & (numeric_col <= upper)
            # 范围错误 = 不在任何范围内 & 非空值
            out_of_range_mask = (~in_range_mask) & valid_mask

            range_error_indices = df.index[out_of_range_mask].tolist()
            range_error_rows_by_col[col] = set(range_error_indices)
            total_range_errors += len(range_error_indices)
            col_added = 0
            for idx in range_error_indices:
                val = float(numeric_col[idx])
                # 决定 suggested_strategy
                if val > max_upper:
                    strategy = "clip_upper"
                elif val < min_lower:
                    strategy = "clip_lower"
                else:
                    strategy = "clip_nearest"
                problems["range_errors"].append({
                    "row_index": int(idx),
                    "column": col,
                    "current_value": self._to_serializable(df.at[idx, col]),
                    "contract_ranges": self._range_to_json(col_ranges),
                    "suggested_strategy": strategy
                })
                col_added += 1
                if col_added >= per_column_limit:
                    break

        # ============ 4. 异常值检测（仅在契约范围内的值中检测） ============
        # 仅对数值列(integer/number)检测
        # 先排除已标记为范围错误的值，再使用 IQR 方法检测剩余值的异常值
        for col, rules in contract.items():
            if col not in df.columns or not isinstance(rules, dict):
                continue
            expected_type = rules.get('expected_type')
            if expected_type not in ('integer', 'number'):
                continue

            numeric_col = pd.to_numeric(df[col], errors='coerce')
            valid_values = numeric_col.dropna()
            # 排除已标记为范围错误的行
            range_error_set = range_error_rows_by_col.get(col, set())
            if range_error_set:
                valid_values = valid_values.drop(
                    index=[idx for idx in range_error_set if idx in valid_values.index]
                )
            # 数据太少时 IQR 不稳定，跳过避免误判
            if len(valid_values) < 4:
                continue

            Q1 = valid_values.quantile(0.25)
            Q3 = valid_values.quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR

            # 在所有非空值上判断异常值
            outlier_mask = (numeric_col < lower_bound) | (numeric_col > upper_bound)
            outlier_mask = outlier_mask.fillna(False)
            # 排除已标记为范围错误的行
            for idx in range_error_set:
                if idx in outlier_mask.index:
                    outlier_mask[idx] = False

            outlier_indices = df.index[outlier_mask].tolist()
            total_outliers += len(outlier_indices)
            col_added = 0
            for idx in outlier_indices:
                problems["outliers"].append({
                    "row_index": int(idx),
                    "column": col,
                    "current_value": self._to_serializable(df.at[idx, col]),
                    "iqr_bounds": {"lower": float(lower_bound), "upper": float(upper_bound)},
                    "suggested_strategy": "clip"
                })
                col_added += 1
                if col_added >= per_column_limit:
                    break

        # ============ 5. 行重复检测 ============
        # 使用 df.duplicated(keep=False) 获取所有重复行（包含首次出现的行）
        # 按行内容分组，返回每组的 row_indices 和 row_values
        # 最多返回前5组
        duplicated_data = df[df.duplicated(keep=False)]
        # 记录所有行重复的行索引，用于列重复检测时排除
        row_duplicate_indices = set()
        # 统计重复组数（真实总数，不受返回上限影响）
        total_row_dup_groups = 0
        if len(duplicated_data) > 0:
            # 使用 dropna=False 确保包含 NaN 值的行也能正确分组
            grouped = duplicated_data.groupby(list(df.columns), dropna=False)
            for _, group in grouped:
                if len(group) > 1:
                    total_row_dup_groups += 1
                    row_indices = [int(i) for i in group.index.tolist()]
                    row_duplicate_indices.update(row_indices)
                    # 仅向前端返回前 row_dup_limit 组（行索引已全部收集用于列重复排除）
                    if len(problems["row_duplicates"]) < row_dup_limit:
                        first_row = group.iloc[0]
                        row_values = {c: self._to_serializable(first_row[c]) for c in df.columns}
                        problems["row_duplicates"].append({
                            "row_indices": row_indices,
                            "row_values": row_values,
                            "suggested_strategy": "keep_first"
                        })

        # ============ 6. 列重复检测 ============
        # 仅检测契约中 allow_duplicate=false 的列
        # 使用 value_counts() 找出重复值，对每个重复值获取所有重复行
        # row_details 包含每行的其他列值
        # 关键：排除已经被标记为行重复的行（行重复是所有列都重复，不应再作为列重复处理）
        # 最多返回前10组
        for col, rules in contract.items():
            if col not in df.columns or not isinstance(rules, dict):
                continue
            if rules.get('allow_duplicate', True) is not False:
                continue
            
            non_row_dup_df = df.copy()
            if len(row_duplicate_indices) > 0:
                non_row_dup_df = non_row_dup_df.drop(index=list(row_duplicate_indices), errors='ignore')
            
            if len(non_row_dup_df) == 0:
                continue
            
            value_counts = non_row_dup_df[col].value_counts(dropna=False)
            duplicate_values = value_counts[value_counts > 1].index.tolist()
            total_column_dup_groups += len(duplicate_values)

            col_added = 0
            for dup_value in duplicate_values:
                if pd.isna(dup_value):
                    dup_rows = non_row_dup_df[non_row_dup_df[col].isna()]
                else:
                    dup_rows = non_row_dup_df[non_row_dup_df[col] == dup_value]
                
                row_indices = [int(i) for i in dup_rows.index.tolist()]
                
                row_details = []
                for idx in dup_rows.index:
                    other_values = {
                        c: self._to_serializable(df.at[idx, c])
                        for c in df.columns if c != col
                    }
                    row_details.append({
                        "row_index": int(idx),
                        "other_values": other_values
                    })
                
                problems["column_duplicates"].append({
                    "column": col,
                    "duplicate_value": self._to_serializable(dup_value),
                    "row_indices": row_indices,
                    "row_details": row_details,
                    "suggested_strategy": "keep_first"
                })
                
                col_added += 1
                if col_added >= col_dup_limit:
                    break
            
            if len(problems["column_duplicates"]) >= col_dup_limit:
                break

        # ============ 汇总统计 ============
        # summary 中为各类问题的真实总数（不受 problems 列表上限影响）
        # row_duplicates 和 column_duplicates 均为组数，保持语义一致
        summary = {
            "missing_values": total_missing,
            "type_errors": total_type_errors,
            "range_errors": total_range_errors,
            "outliers": total_outliers,
            "row_duplicates": total_row_dup_groups,
            "column_duplicates": total_column_dup_groups
        }

        return {
            "summary": summary,
            "problems": problems
        }

    # ============================================================
    # 契约规范化 / 契约校验 / 管道执行 / 预检 / 审计报告（按用户定义顺序执行，配合 dry-run 预检警告）
    # 标准化/归一化已移至特征工程模块，本模块不再提供 scaling 分支
    # 契约结构详见 normalize_contract / validate_contract 文档
    # ============================================================

    # 各 expected_type 对应的字段白名单（不含通用字段 expected_type/allow_missing/allow_duplicate）
    # 用于 normalize_contract 中根据类型清理无关字段，避免无关字段干扰清洗逻辑
    _CONTRACT_TYPE_FIELDS: Dict[str, set] = {
        'integer': {'ranges'},
        'number': {'ranges', 'decimal_places'},
        'string': {'enum_values', 'min_length', 'max_length'},
        'boolean': {'bool_representation'},
        'date': {'min_date', 'max_date'},
        'email': set(),
        'url': set(),
    }

    def normalize_contract(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        """规范化契约数据结构，兼容旧格式并补充默认值

        规范化规则：
        1. 旧字段兼容：min_value/max_value（或旧版 min/max）转换为 ranges: [[min_value, max_value]]
        2. 通用默认值：allow_missing=True、allow_duplicate=True；number 类型补充 decimal_places=1
        3. 类型清理：根据 expected_type 移除无关字段（如 integer 列不需要 decimal_places、string 列不需要 ranges）
        4. 保留 expected_type（若缺失则不补默认值，留给 validate_contract 报错）

        Args:
            contract: 原始契约字典 {
                列名: {
                    "expected_type": "integer|number|string|boolean|date|email|url",
                    "min_value": 数值, "max_value": 数值,  # 旧字段，将被转换
                    "ranges": [[min, max], ...],
                    "decimal_places": int,
                    "min_date": "YYYY-MM-DD", "max_date": "YYYY-MM-DD",
                    "enum_values": [...], "min_length": int, "max_length": int,
                    "bool_representation": "0/1|是/否|true/false|True/False",
                    "allow_missing": bool, "allow_duplicate": bool
                }
            }

        Returns:
            规范化后的契约字典，包含所有必要字段和默认值；非字典输入返回空字典
        """
        if not isinstance(contract, dict):
            return {}

        # 兼容嵌套契约格式 {'columns': {列名: 规则}}
        # 标准契约格式为扁平结构 {列名: 规则}，但部分前端/旧版调用方会包裹一层 columns
        # 判断 'columns' 是否为嵌套包裹：其值是 dict，且不包含 expected_type 等契约字段
        # （若 'columns' 是真实列名，其值会包含 expected_type 等字段，此时不应解包）
        # 不解包会导致 'columns' 被误判为列名，后续所有契约相关检测全部跳过
        if 'columns' in contract and isinstance(contract['columns'], dict):
            inner = contract['columns']
            inner_keys = set(inner.keys())
            # 契约字段白名单，与下方 _CONTRACT_TYPE_FIELDS 及旧字段保持一致
            contract_field_keys = {
                'expected_type', 'ranges', 'decimal_places', 'min_date', 'max_date',
                'enum_values', 'min_length', 'max_length', 'bool_representation',
                'allow_missing', 'allow_duplicate', 'min_value', 'max_value',
                'min', 'max', 'bool_repr'
            }
            # inner 不包含任何契约字段时，判定为嵌套包裹并解包
            if not (inner_keys & contract_field_keys):
                contract = inner

        normalized: Dict[str, Any] = {}
        for col, rules in contract.items():
            if not isinstance(rules, dict):
                # 非字典规则无法规范化，原样保留以触发后续校验报错
                normalized[col] = rules
                continue

            # 拷贝原始规则，避免修改入参
            norm_rules = dict(rules)

            # 1. 旧字段 min_value/max_value（或旧版 min/max）转换为 ranges
            if not norm_rules.get('ranges'):
                min_v = norm_rules.get('min_value')
                max_v = norm_rules.get('max_value')
                # 兼容更早版本曾使用过的 min/max 字段名
                if min_v is None and 'min' in norm_rules:
                    min_v = norm_rules.get('min')
                if max_v is None and 'max' in norm_rules:
                    max_v = norm_rules.get('max')
                if min_v is not None or max_v is not None:
                    # 仅指定一边时，另一边用 ±inf 兜底，表示无界
                    if min_v is None:
                        min_v = float('-inf')
                    if max_v is None:
                        max_v = float('inf')
                    norm_rules['ranges'] = [[min_v, max_v]]

            # 2. 补充默认值（仅在 expected_type 明确时补充，避免对未知类型预设 decimal_places）
            # allow_missing 默认 false：缺失值默认作为问题处理，用户显式开启"允许缺失"才跳过（修复）
            norm_rules.setdefault('allow_missing', False)
            norm_rules.setdefault('allow_duplicate', True)
            if norm_rules.get('expected_type') == 'number':
                norm_rules.setdefault('decimal_places', 1)

            # 3. 根据 expected_type 清理无关字段（移除旧字段 min_value/max_value/min/max/bool_repr 等）
            expected_type = norm_rules.get('expected_type')
            if expected_type in self._CONTRACT_TYPE_FIELDS:
                allowed_fields = self._CONTRACT_TYPE_FIELDS[expected_type] | {
                    'expected_type', 'allow_missing', 'allow_duplicate'
                }
                norm_rules = {k: v for k, v in norm_rules.items() if k in allowed_fields}

            normalized[col] = norm_rules

        return normalized

    def validate_contract(self, df: pd.DataFrame, contract: Dict) -> Dict[str, Any]:
        """校验数据契约格式，避免契约本身存在矛盾导致后续清洗失败

        支持的契约结构（每列）：
        {
            "expected_type": "integer|number|string|boolean|date|email|url",  # 必填
            "ranges": [[min, max], ...],            # 数值列(integer/number)范围配置，多区间满足任一即可
            "decimal_places": int,                  # number类型专用，默认1，清洗结果按此位数四舍五入
            "min_date": "YYYY-MM-DD",               # 日期列(date)最小日期
            "max_date": "YYYY-MM-DD",               # 日期列(date)最大日期
            "enum_values": ["值1", "值2", ...],     # 字符串列(string)枚举值列表
            "min_length": int,                      # 字符串列(string)最小长度
            "max_length": int,                      # 字符串列(string)最大长度
            "bool_representation": "0/1|是/否|true/false|True/False",  # 布尔列(boolean)表示方式
            "allow_missing": bool,                  # 是否允许缺失，默认 true
            "allow_duplicate": bool                 # 是否允许重复，默认 true
        }

        向后兼容：旧字段 min_value/max_value（或旧版 min/max）会被规范化为 ranges: [[min_value, max_value]]

        Args:
            df: 数据框（仅作为契约引用的数据源占位，不参与校验逻辑）
            contract: 数据契约 {列名: {契约规则}}

        Returns:
            {
                "valid": bool,                       # 契约是否通过校验
                "errors": [错误信息列表],            # 校验失败时的具体错误信息
                "normalized_contract": dict          # 规范化后的契约（含默认值、旧字段转换、类型清理）
            }
        """
        # 7 种合法类型，覆盖数值/文本/时间/布尔/网络标识等场景
        valid_types = {'integer', 'number', 'string', 'boolean', 'date', 'email', 'url'}
        # 布尔表示方式白名单，与 apply_type_constraints 的取值集合保持一致
        valid_bool_reprs = {'0/1', '是/否', 'true/false', 'True/False'}
        # YYYY-MM-DD 严格格式正则，避免 pd.to_datetime 自动宽松解析多变的日期写法
        date_format_re = re.compile(r'^\d{4}-\d{2}-\d{2}$')

        errors: List[str] = []

        if not isinstance(contract, dict):
            return {"valid": False, "errors": ["契约必须是字典格式"], "normalized_contract": {}}

        # 先规范化契约：旧字段转换、默认值补充、无关字段清理
        # 这样后续校验只需面对统一格式，简化分支逻辑
        normalized_contract = self.normalize_contract(contract)

        def _is_valid_date(date_val: Any) -> bool:
            """验证日期字符串是否为合法的 YYYY-MM-DD 格式"""
            if date_val is None:
                return False
            s = str(date_val)
            if not date_format_re.match(s):
                return False
            try:
                datetime.strptime(s, '%Y-%m-%d')
                return True
            except ValueError:
                return False

        for col, rules in normalized_contract.items():
            if not isinstance(rules, dict):
                errors.append(f"列[{col}]的契约规则必须是字典")
                continue

            # ============ expected_type 校验（必填） ============
            # 类型不合法会导致后续类型错误处理无从判断
            expected_type = rules.get('expected_type')
            if expected_type is None:
                errors.append(f"列[{col}]未指定expected_type")
                # 缺少类型时无法做后续类型相关校验，直接跳过
                continue
            elif expected_type not in valid_types:
                errors.append(
                    f"列[{col}]的expected_type[{expected_type}]不合法，"
                    f"支持类型: {sorted(valid_types)}"
                )
                # 类型不合法时同样跳过后续按类型分支的校验
                continue

            # ============ dtype 兼容性校验（方向B） ============
            # 数值 dtype 列配 date/email/url 属于配置错误：
            # 这三种类型要求字符串形式，数值列无法满足，且 analyze_problems 的类型错误检测
            # 会对数值 dtype 列短路跳过（仅查 integer 小数），导致用户契约静默失效。
            # 在契约校验阶段直接拦截，让用户尽早发现配置错误而非看到空的问题清单。
            # integer/number 天然匹配数值列；string/boolean 合理（数值可作文本或 0/1 布尔）。
            if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                if expected_type in ('date', 'email', 'url'):
                    errors.append(
                        f"列[{col}]实际为数值类型，不能配置为{expected_type}类型，"
                        f"请改为 integer/number/string/boolean 或更换目标列"
                    )
                    continue

            # ============ ranges 校验（数值列 integer/number） ============
            # 必须是列表的列表，每个子列表有2个数字 [min, max]，min 不能大于 max
            ranges_val = rules.get('ranges')
            if ranges_val is not None:
                if not isinstance(ranges_val, list):
                    errors.append(f"列[{col}]的ranges必须是列表")
                else:
                    for i, r in enumerate(ranges_val):
                        if not isinstance(r, list) or len(r) != 2:
                            errors.append(
                                f"列[{col}]的ranges[{i}]必须是长度为2的列表[min, max]"
                            )
                            continue
                        try:
                            # None 表示无界限，下界 None → -inf，上界 None → inf
                            min_v = self._safe_float(r[0], True)
                            max_v = self._safe_float(r[1], False)
                            if min_v > max_v:
                                errors.append(
                                    f"列[{col}]的ranges[{i}]的min({r[0]})大于max({r[1]})"
                                )
                        except (TypeError, ValueError):
                            errors.append(
                                f"列[{col}]的ranges[{i}]的min/max必须为数值，实际为[{r[0]}, {r[1]}]"
                            )

            # ============ decimal_places 校验（number 类型专用） ============
            # 必须是非负整数；默认值在 normalize_contract 中已设为 1
            dp = rules.get('decimal_places')
            if dp is not None:
                # 注意：bool 是 int 的子类，需要单独排除避免接受 True/False
                if isinstance(dp, bool) or not isinstance(dp, int) or dp < 0:
                    errors.append(f"列[{col}]的decimal_places必须是非负整数，实际为[{dp}]")

            # ============ min_date / max_date 校验（date 类型） ============
            # 必须是有效的 YYYY-MM-DD 日期字符串
            for date_field in ('min_date', 'max_date'):
                date_val = rules.get(date_field)
                if date_val is not None and not _is_valid_date(date_val):
                    errors.append(
                        f"列[{col}]的{date_field}[{date_val}]不是有效的日期(YYYY-MM-DD格式)"
                    )
            # 校验 min_date 不大于 max_date
            min_d = rules.get('min_date')
            max_d = rules.get('max_date')
            if min_d is not None and max_d is not None:
                if _is_valid_date(min_d) and _is_valid_date(max_d):
                    if datetime.strptime(str(min_d), '%Y-%m-%d') > datetime.strptime(str(max_d), '%Y-%m-%d'):
                        errors.append(
                            f"列[{col}]的min_date({min_d})大于max_date({max_d})"
                        )

            # ============ enum_values 校验（string 类型） ============
            # 必须是列表，元素类型不限（允许字符串/数值等混用）
            ev = rules.get('enum_values')
            if ev is not None and not isinstance(ev, list):
                errors.append(f"列[{col}]的enum_values必须是列表")

            # ============ min_length / max_length 校验（string 类型） ============
            # 必须是非负整数
            for len_field in ('min_length', 'max_length'):
                lv = rules.get(len_field)
                if lv is not None:
                    if isinstance(lv, bool) or not isinstance(lv, int) or lv < 0:
                        errors.append(
                            f"列[{col}]的{len_field}必须是非负整数，实际为[{lv}]"
                        )
            # 校验 min_length 不大于 max_length
            min_l = rules.get('min_length')
            max_l = rules.get('max_length')
            if (
                min_l is not None and max_l is not None
                and isinstance(min_l, int) and isinstance(max_l, int)
                and not isinstance(min_l, bool) and not isinstance(max_l, bool)
                and min_l > max_l
            ):
                errors.append(
                    f"列[{col}]的min_length({min_l})大于max_length({max_l})"
                )

            # ============ bool_representation 校验（boolean 类型） ============
            # 必须是预定义的 4 种取值之一
            br = rules.get('bool_representation')
            if br is not None and br not in valid_bool_reprs:
                errors.append(
                    f"列[{col}]的bool_representation[{br}]不合法，"
                    f"支持取值: {sorted(valid_bool_reprs)}"
                )

            # ============ allow_missing / allow_duplicate 校验（通用） ============
            # 必须是布尔值，非布尔值会让缺失值/重复值处理策略判断产生歧义
            for bool_field in ('allow_missing', 'allow_duplicate'):
                bv = rules.get(bool_field)
                if bv is not None and not isinstance(bv, bool):
                    errors.append(f"列[{col}]的{bool_field}必须是布尔值")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "normalized_contract": normalized_contract
        }

    def execute_pipeline(self, df: pd.DataFrame, operations: List[Dict],
                        contract: Dict) -> Tuple[pd.DataFrame, List[Dict]]:
        """按用户定义的顺序执行清洗操作（不再使用固定阶段顺序）

        Args:
            df: 原始数据框
            operations: 操作列表，每项为 {
                "type": 操作类型, "method": 方法,
                "columns": 列表, ...其他参数
            }
            contract: 数据契约，用于类型错误处理和缺失值智能填充

        Returns:
            (cleaned_df, operations_log)：清洗后数据框与操作日志
        """
        cleaned_df = df.copy()
        # 同步 self.df 以便复用现有 handle_* 系列方法
        self.df = cleaned_df
        operations_log = []

        # 从契约中提取 expected_types，供后续类型相关操作复用
        expected_types = {}
        if isinstance(contract, dict):
            for col, rules in contract.items():
                if isinstance(rules, dict) and rules.get('expected_type'):
                    expected_types[col] = rules['expected_type']

        for step_idx, op in enumerate(operations, 1):
            op_type = op.get('type', '')
            method = op.get('method', '')
            columns = op.get('columns', []) or []
            before_rows = len(cleaned_df)
            before_df = cleaned_df.copy()
            details = f"执行{op_type}操作"

            try:
                if op_type == 'deduplication':
                    # 复用现有去重逻辑：subset 指定列级去重，未指定则全行去重
                    cleaned_df = self.remove_duplicates(
                        subset=op.get('subset'),
                        keep=op.get('keep', 'first'),
                        keep_rows=op.get('keep_rows'),
                        value=op.get('value'),
                        group_rows=op.get('group_rows')
                    )

                elif op_type == 'missing_values':
                    # 复用 handle_missing_values：契约类型用于智能填充策略选择
                    cleaned_df = self.handle_missing_values(
                        strategy=method or 'auto',
                        fill_value=op.get('fill_value'),
                        columns=columns if columns else None,
                        expected_types=expected_types
                    )

                elif op_type == 'outlier':
                    # 四种异常值策略：remove/replace/mark/clip
                    cols = columns if columns else None
                    if method == 'remove':
                        cleaned_df = self.handle_outliers(method='remove', columns=cols)
                    elif method == 'replace':
                        # 用均值/中位数替换：先标记为缺失再填充，避免直接修改引入偏差
                        replace_strategy = op.get('replace_value', 'mean')
                        self.df = self.handle_outliers(method='mark_missing', columns=cols)
                        cleaned_df = self.handle_missing_values(
                            strategy=replace_strategy, columns=cols
                        )
                    elif method == 'mark':
                        # 新增 _is_outlier_{列名} 标记列，原列保持不变便于审计
                        target_cols = cols if cols else list(
                            cleaned_df.select_dtypes(include=[np.number]).columns
                        )
                        for col in target_cols:
                            if col not in cleaned_df.columns:
                                continue
                            numeric_col = pd.to_numeric(cleaned_df[col], errors='coerce')
                            valid_values = numeric_col.dropna()
                            if len(valid_values) < 4:
                                continue
                            Q1 = valid_values.quantile(0.25)
                            Q3 = valid_values.quantile(0.75)
                            IQR = Q3 - Q1
                            lower = Q1 - 1.5 * IQR
                            upper = Q3 + 1.5 * IQR
                            cleaned_df[f'_is_outlier_{col}'] = (
                                (numeric_col < lower) | (numeric_col > upper)
                            ).fillna(False)
                    elif method == 'clip':
                        # 裁剪到 IQR 边界值
                        cleaned_df = self.handle_outliers(method='clip', columns=cols)

                elif op_type == 'type_error':
                    # 类型错误处理：delete 删除错误行 / convert 按契约类型转换
                    if method == 'delete':
                        cleaned_df = self.handle_type_errors(
                            method='delete', columns=columns, expected_types=expected_types
                        )
                    elif method == 'convert':
                        cleaned_df = self.apply_type_constraints(
                            expected_types=expected_types, warn_only=True
                        )

                elif op_type == 'range_error':
                    # 范围错误处理：clip/drop/mark
                    ranges = op.get('ranges', {})
                    if method in ('clip', 'drop'):
                        cleaned_df = self.handle_range_errors(
                            method=method, columns=columns, ranges=ranges
                        )
                    elif method == 'mark':
                        # 新增 _out_of_range_{列名} 标记列，便于审计追踪
                        for col in columns:
                            if col not in cleaned_df.columns:
                                continue
                            col_ranges = ranges.get(col, []) if ranges else []
                            if not col_ranges:
                                continue
                            # 预处理 None：下界 None → -inf，上界 None → inf
                            col_ranges = [
                                (self._safe_float(min_v, True), self._safe_float(max_v, False))
                                for min_v, max_v in col_ranges
                            ]
                            numeric_col = pd.to_numeric(cleaned_df[col], errors='coerce')
                            out_of_range = pd.Series(False, index=cleaned_df.index)
                            for min_val, max_val in col_ranges:
                                out_of_range |= (numeric_col < min_val) | (numeric_col > max_val)
                            cleaned_df[f'_out_of_range_{col}'] = out_of_range.fillna(False)

                elif op_type == 'column_op':
                    # 列操作：rename/delete/convert_type，不新增列（区别于特征工程模块）
                    if method == 'rename':
                        rename_map = op.get('rename_map', {})
                        cleaned_df = cleaned_df.rename(columns=rename_map)
                    elif method == 'delete':
                        cols_to_delete = op.get('columns_to_delete', columns)
                        cleaned_df = cleaned_df.drop(
                            columns=cols_to_delete, errors='ignore'
                        )
                    elif method == 'convert_type':
                        convert_map = op.get('convert_map', {})
                        for col, target_type in convert_map.items():
                            if col not in cleaned_df.columns:
                                continue
                            if target_type == 'integer':
                                cleaned_df[col] = pd.to_numeric(
                                    cleaned_df[col], errors='coerce'
                                ).astype('Int64')
                            elif target_type == 'number':
                                cleaned_df[col] = pd.to_numeric(
                                    cleaned_df[col], errors='coerce'
                                )
                            elif target_type == 'string':
                                cleaned_df[col] = cleaned_df[col].astype(str)
                            elif target_type == 'date':
                                cleaned_df[col] = pd.to_datetime(
                                    cleaned_df[col], errors='coerce'
                                )

                elif op_type == 'row_filter':
                    # 行过滤：按表达式（如 "age > 18"）保留满足条件的行
                    condition = op.get('condition', '')
                    if condition:
                        try:
                            mask = cleaned_df.eval(condition)
                            # 确保 mask 是 boolean Series
                            if not isinstance(mask, pd.Series):
                                mask = pd.Series(bool(mask), index=cleaned_df.index)
                            mask = mask.fillna(False).astype(bool)
                            cleaned_df = cleaned_df[mask]
                        except Exception as e:
                            details = f"行过滤表达式无效: {str(e)}"
                            # 失败时回滚到之前的状态
                            cleaned_df = before_df

                # 标准化/归一化已移至特征工程模块，本管道不再支持 scaling 分支

                self.df = cleaned_df
                affected_rows = before_rows - len(cleaned_df)
                operations_log.append({
                    "step": step_idx,
                    "type": op_type,
                    "method": method,
                    "columns": list(columns) if columns else [],
                    "affected_rows": affected_rows,
                    "details": details
                })
            except Exception as e:
                # 出错时回滚到本步骤开始前的状态，避免后续操作基于错误状态
                cleaned_df = before_df
                self.df = before_df
                operations_log.append({
                    "step": step_idx,
                    "type": op_type,
                    "method": method,
                    "columns": list(columns) if columns else [],
                    "affected_rows": 0,
                    "details": f"执行失败: {str(e)}"
                })

        return cleaned_df, operations_log

    def execute_cleaning_with_strategies(self, df: pd.DataFrame, contract: Dict[str, Any],
                                         problem_strategies: Dict[str, Any],
                                         pipeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        """根据问题清单策略执行清洗

        按管道顺序对数据执行清洗，每个 operation 对应 problem_strategies 中的一类问题处理。
        支持的 operation 类型：
        - row_duplicates: 行重复处理 (keep_first / keep_last / delete_all)
        - column_duplicates: 列重复处理 (keep_first / keep_last / delete_all / manual_select)
        - type_errors: 类型错误处理 (delete_row / mark_missing / coerce_or_mark)
        - range_errors: 范围错误处理 (clip_upper / clip_lower / clip_nearest / delete_row / mark / mean / median / custom)
        - outliers: 异常值处理 (clip / mean / median / mode / delete_row / mark / custom)
        - missing_values: 缺失值处理 (mean / median / mode / delete / custom / mark)
        - column_ops: 列操作 (rename / delete)
        - row_filter: 行过滤

        Args:
            df: 原始数据框
            contract: 规范化后的契约（由 normalize_contract 处理过）
            problem_strategies: 问题处理策略，键为问题类型，值为策略列表
            pipeline: 管道配置（决定执行顺序），每项 {"operation": 类型, "params": {...}}

        Returns:
            {
                "cleaned_df": 清洗后的数据框,
                "audit": {
                    "original_rows": 原始行数,
                    "cleaned_rows": 清洗后行数,
                    "original_columns": 原始列数,
                    "cleaned_columns": 清洗后列数（含标记列）,
                    "operations": 各操作的审计信息列表,
                    "quality_scores": {completeness, uniqueness, consistency, validity}
                }
            }

        Raises:
            ValueError: 自定义值校验失败（类型不符或超出契约范围）时抛出
        """
        cleaned_df = df.copy()
        # 同步 self.df 以便复用现有 handle_* 系列方法
        self.df = cleaned_df
        # 兼容嵌套契约：若传入 {'columns': {...}} 则解包
        if isinstance(contract, dict) and 'columns' in contract and isinstance(contract['columns'], dict):
            inner = contract['columns']
            # 仅当 inner 不含契约字段时才视为嵌套包裹
            contract_field_keys = {
                'expected_type', 'ranges', 'decimal_places', 'min_date', 'max_date',
                'enum_values', 'min_length', 'max_length', 'bool_representation',
                'allow_missing', 'allow_duplicate'
            }
            if not (set(inner.keys()) & contract_field_keys):
                contract = inner

        original_rows = len(cleaned_df)
        original_cols = len(cleaned_df.columns)
        operations_audit: List[Dict[str, Any]] = []

        # 防御性问题策略字典，避免 KeyError
        strategies_map = problem_strategies or {}

        # ============ 工具函数 ============
        def to_native(value: Any) -> Any:
            """将 numpy 类型转换为 Python 原生类型，便于审计序列化"""
            return self._to_serializable(value)

        def get_column_bounds(col: str) -> Tuple[Any, Any]:
            """获取列契约范围的最小下边界和最大上边界"""
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            ranges = rules.get('ranges', []) if isinstance(rules, dict) else []
            if not ranges:
                return None, None
            try:
                # None 表示无界限，下界 None → -inf，上界 None → inf
                min_lower = min(self._safe_float(r[0], True) for r in ranges)
                max_upper = max(self._safe_float(r[1], False) for r in ranges)
                return min_lower, max_upper
            except (TypeError, ValueError, IndexError):
                return None, None

        def get_nearest_bound(col: str, val: float) -> Any:
            """获取距离 val 最近的契约边界值"""
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            ranges = rules.get('ranges', []) if isinstance(rules, dict) else []
            if not ranges:
                return None
            nearest = None
            nearest_dist = float('inf')
            for r in ranges:
                try:
                    # None 表示无界限，下界 None → -inf，上界 None → inf
                    min_v = self._safe_float(r[0], True)
                    max_v = self._safe_float(r[1], False)
                except (TypeError, ValueError, IndexError):
                    continue
                # 同时比较下边界和上边界，取距离最近者
                for bound in (min_v, max_v):
                    dist = abs(val - bound)
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest = bound
            return nearest

        def validate_custom_value(col: str, value: Any) -> None:
            """校验自定义值是否符合列的契约类型与范围

            Raises:
                ValueError: 类型不符或超出范围时抛出，包含详细的错误信息
            """
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            expected_type = rules.get('expected_type') if isinstance(rules, dict) else None

            if expected_type == 'integer':
                # integer 列：必须是整数（允许 "5"、5.0、5 等可整数化的形式）
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"列[{col}]为integer类型，自定义值[{value}]不是合法数值"
                    )
                if not num.is_integer():
                    raise ValueError(
                        f"列[{col}]为integer类型，自定义值[{value}]不是整数"
                    )
                int_val = int(num)
                min_lower, max_upper = get_column_bounds(col)
                if min_lower is not None and max_upper is not None:
                    if not (min_lower <= int_val <= max_upper):
                        raise ValueError(
                            f"列[{col}]的自定义值[{int_val}]不在契约范围"
                            f"[{min_lower}, {max_upper}]内"
                        )
            elif expected_type == 'number':
                # number 列：必须是数值
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"列[{col}]为number类型，自定义值[{value}]不是合法数值"
                    )
                min_lower, max_upper = get_column_bounds(col)
                if min_lower is not None and max_upper is not None:
                    if not (min_lower <= num <= max_upper):
                        raise ValueError(
                            f"列[{col}]的自定义值[{num}]不在契约范围"
                            f"[{min_lower}, {max_upper}]内"
                        )

        def coerce_value_by_type(col: str, value: Any) -> Any:
            """根据契约类型对值进行类型一致性处理

            integer 列：round() 取整为 int
            number 列：按 decimal_places 四舍五入
            其他类型：原值返回
            """
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            expected_type = rules.get('expected_type') if isinstance(rules, dict) else None
            try:
                if expected_type == 'integer':
                    return int(round(float(value)))
                elif expected_type == 'number':
                    decimal_places = rules.get('decimal_places', 1) if isinstance(rules, dict) else 1
                    return round(float(value), decimal_places)
            except (TypeError, ValueError):
                return value
            return value

        def get_column_mean(col: str) -> Any:
            """计算列的均值，按契约类型一致性返回"""
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            expected_type = rules.get('expected_type') if isinstance(rules, dict) else None
            if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                mean_val = cleaned_df[col].mean()
            else:
                numeric_col = pd.to_numeric(cleaned_df[col], errors='coerce')
                mean_val = numeric_col.mean()
            if mean_val is None or (isinstance(mean_val, float) and pd.isna(mean_val)):
                return None
            return coerce_value_by_type(col, mean_val)

        def get_column_median(col: str) -> Any:
            """计算列的中位数，按契约类型一致性返回"""
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            expected_type = rules.get('expected_type') if isinstance(rules, dict) else None
            if pd.api.types.is_numeric_dtype(cleaned_df[col]):
                median_val = cleaned_df[col].median()
            else:
                numeric_col = pd.to_numeric(cleaned_df[col], errors='coerce')
                median_val = numeric_col.median()
            if median_val is None or (isinstance(median_val, float) and pd.isna(median_val)):
                return None
            return coerce_value_by_type(col, median_val)

        def get_column_mode(col: str) -> Any:
            """计算列的众数，按契约类型一致性返回"""
            rules = contract.get(col, {}) if isinstance(contract, dict) else {}
            mode_vals = cleaned_df[col].mode()
            if len(mode_vals) == 0:
                return None
            mode_val = mode_vals[0]
            # NaN 众数视为无效
            try:
                if pd.isna(mode_val):
                    return None
            except (TypeError, ValueError):
                pass
            return coerce_value_by_type(col, mode_val)

        def get_iqr_bounds(col: str) -> Tuple[Any, Any]:
            """计算列的 IQR 边界 (lower, upper)，数据不足4个返回 (None, None)"""
            numeric_col = pd.to_numeric(cleaned_df[col], errors='coerce')
            valid_values = numeric_col.dropna()
            if len(valid_values) < 4:
                return None, None
            Q1 = valid_values.quantile(0.25)
            Q3 = valid_values.quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR
            return float(lower), float(upper)

        def ensure_mark_column(mark_col: str) -> None:
            """确保标记列存在，初始化为 False。

            保护：若源列名已包含 ``_标记_``（即 mark_col 中出现多次 ``_标记_``），
            说明源列本身已是标记列，此时不再创建新的标记列，
            避免出现"X_标记_Y_标记_Z"这种重复标记列名。
            """
            # 保护：源列已经是标记列时不再生成新的标记列
            if mark_col.count('_标记_') > 1:
                return
            if mark_col not in cleaned_df.columns:
                # 使用 .assign 避免 SettingWithCopyWarning
                cleaned_df[mark_col] = False

        def get_row_numeric_value(row_index: int, col: str) -> Any:
            """获取指定行/列的数值，无法转换返回 None"""
            try:
                raw = cleaned_df.at[row_index, col]
                val = pd.to_numeric(raw, errors='coerce')
                if pd.isna(val):
                    return None
                return float(val)
            except (TypeError, ValueError, KeyError):
                return None

        # ============ 按管道顺序执行 ============
        for step in pipeline:
            operation = step.get('operation', '')
            params = step.get('params', {}) or {}

            # ---------- 行重复处理 ----------
            if operation == 'row_duplicates':
                strategies = strategies_map.get('row_duplicates', [])
                deleted_rows: List[int] = []
                for item in strategies:
                    row_indices = item.get('row_indices', []) or []
                    strategy = item.get('strategy', 'keep_first')
                    if not row_indices:
                        continue
                    if strategy == 'keep_first':
                        to_delete = row_indices[1:]
                    elif strategy == 'keep_last':
                        to_delete = row_indices[:-1]
                    elif strategy == 'delete_all':
                        to_delete = list(row_indices)
                    else:
                        continue
                    # 仅删除当前仍存在的行（前面步骤可能已删除部分行）
                    to_delete = [idx for idx in to_delete if idx in cleaned_df.index]
                    if to_delete:
                        cleaned_df = cleaned_df.drop(index=to_delete)
                        deleted_rows.extend(to_delete)

                operations_audit.append({
                    "operation": "row_duplicates",
                    "details": f"删除了{len(deleted_rows)}行重复行",
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

            # ---------- 列重复处理 ----------
            elif operation == 'column_duplicates':
                strategies = strategies_map.get('column_duplicates', [])
                deleted_rows = []
                for item in strategies:
                    row_indices = item.get('row_indices', []) or []
                    strategy = item.get('strategy', 'keep_first')
                    if not row_indices:
                        continue
                    if strategy == 'keep_first':
                        to_delete = row_indices[1:]
                    elif strategy == 'keep_last':
                        to_delete = row_indices[:-1]
                    elif strategy == 'delete_all':
                        to_delete = list(row_indices)
                    elif strategy == 'manual_select':
                        # 保留用户指定的第一行，删除其余
                        keep_idx = row_indices[0] if row_indices else None
                        to_delete = [idx for idx in row_indices if idx != keep_idx]
                    else:
                        continue
                    to_delete = [idx for idx in to_delete if idx in cleaned_df.index]
                    if to_delete:
                        cleaned_df = cleaned_df.drop(index=to_delete)
                        deleted_rows.extend(to_delete)

                operations_audit.append({
                    "operation": "column_duplicates",
                    "details": f"删除了{len(deleted_rows)}行列重复行",
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

            # ---------- 类型错误处理 ----------
            elif operation == 'type_errors':
                strategies = strategies_map.get('type_errors', [])
                changes: List[Dict[str, Any]] = []
                deleted_rows = []
                for item in strategies:
                    row_index = item.get('row_index')
                    column = item.get('column')
                    strategy = item.get('strategy', 'coerce_or_mark')
                    if column is None or row_index is None:
                        continue
                    if column not in cleaned_df.columns:
                        continue
                    if row_index not in cleaned_df.index:
                        continue

                    old_value = cleaned_df.at[row_index, column]
                    rules = contract.get(column, {}) if isinstance(contract, dict) else {}
                    expected_type = rules.get('expected_type') if isinstance(rules, dict) else None

                    if strategy == 'delete_row':
                        deleted_rows.append(row_index)
                    elif strategy == 'mark_missing':
                        cleaned_df.at[row_index, column] = np.nan
                        changes.append({
                            "row_index": int(row_index), "column": column,
                            "old_value": to_native(old_value), "new_value": None,
                            "strategy": strategy
                        })
                    elif strategy == 'coerce_or_mark':
                        # 尝试强制转换，失败时保留原值并在审计报告中标记"转换失败"
                        # 用户可根据审计报告决定后续处理（删除行/手动填充/保留原值）
                        new_val = None
                        try:
                            if expected_type in ('integer', 'number'):
                                converted = pd.to_numeric(
                                    cleaned_df.at[row_index, column], errors='raise'
                                )
                                if expected_type == 'integer':
                                    if float(converted).is_integer():
                                        new_val = int(float(converted))
                                    else:
                                        # 小数转 integer 视为转换失败，保留原值并标记
                                        changes.append({
                                            "row_index": int(row_index), "column": column,
                                            "old_value": to_native(old_value),
                                            "new_value": to_native(old_value),
                                            "strategy": strategy,
                                            "status": "转换失败：小数无法转为整数，已保留原值"
                                        })
                                        continue
                                else:
                                    # number 类型按 decimal_places 四舍五入
                                    decimal_places = rules.get('decimal_places', 1)
                                    new_val = round(float(converted), decimal_places)
                            elif expected_type == 'date':
                                converted = pd.to_datetime(
                                    cleaned_df.at[row_index, column], errors='raise'
                                )
                                new_val = converted.strftime('%Y-%m-%d')
                            else:
                                # email/url 无法强制转换，保留原值并标记
                                changes.append({
                                    "row_index": int(row_index), "column": column,
                                    "old_value": to_native(old_value),
                                    "new_value": to_native(old_value),
                                    "strategy": strategy,
                                    "status": "转换失败：不支持email/url强制转换，已保留原值"
                                })
                                continue
                            # 转换后检查是否为 NaN（原始值可能是 "N/A"、"NA" 等被 pandas
                            # 自动解析为 NaN 的字符串，pd.to_numeric(NaN) 不报错但结果无意义）
                            if new_val is not None and pd.isna(new_val):
                                changes.append({
                                    "row_index": int(row_index), "column": column,
                                    "old_value": to_native(old_value),
                                    "new_value": to_native(old_value),
                                    "strategy": strategy,
                                    "status": f"转换失败：原始值为缺失值(N/A)，无法转为{expected_type or '目标类型'}，已保留原值"
                                })
                                continue
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy,
                                "status": f"已强制转换为{expected_type or '目标类型'}"
                            })
                        except (ValueError, TypeError):
                            # 转换失败时保留原值，不静默填NaN，让用户在审计报告中看到失败记录
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(old_value),
                                "strategy": strategy,
                                "status": f"转换失败：无法转为{expected_type or '目标类型'}，已保留原值"
                            })

                if deleted_rows:
                    cleaned_df = cleaned_df.drop(index=deleted_rows)
                operations_audit.append({
                    "operation": "type_errors",
                    "details": f"处理了{len(changes)}个类型错误，删除{len(deleted_rows)}行",
                    "changes": changes,
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

            # ---------- 范围错误处理 ----------
            elif operation == 'range_errors':
                strategies = strategies_map.get('range_errors', [])
                changes = []
                deleted_rows = []
                for item in strategies:
                    row_index = item.get('row_index')
                    column = item.get('column')
                    strategy = item.get('strategy', 'clip_upper')
                    custom_value = item.get('value')
                    if column is None or row_index is None:
                        continue
                    if column not in cleaned_df.columns:
                        continue
                    if row_index not in cleaned_df.index:
                        continue

                    val = get_row_numeric_value(row_index, column)
                    if val is None:
                        continue

                    old_value = cleaned_df.at[row_index, column]
                    min_lower, max_upper = get_column_bounds(column)

                    if strategy == 'clip_upper':
                        if max_upper is not None:
                            new_val = coerce_value_by_type(column, min(val, max_upper))
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })
                    elif strategy == 'clip_lower':
                        if min_lower is not None:
                            new_val = coerce_value_by_type(column, max(val, min_lower))
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })
                    elif strategy == 'clip_nearest':
                        nearest = get_nearest_bound(column, val)
                        if nearest is not None:
                            new_val = coerce_value_by_type(column, nearest)
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })
                    elif strategy == 'delete_row':
                        deleted_rows.append(row_index)
                    elif strategy == 'mark':
                        # 保护：标记列不再生成新的标记列，避免重复
                        if '_标记_' in str(column):
                            continue
                        cleaned_df.at[row_index, column] = np.nan
                        mark_col = f"{column}_标记_范围错误"
                        ensure_mark_column(mark_col)
                        cleaned_df.at[row_index, mark_col] = True
                        changes.append({
                            "row_index": int(row_index), "column": column,
                            "old_value": to_native(old_value),
                            "new_value": None, "strategy": strategy
                        })
                    elif strategy == 'mean':
                        # 用范围内值的均值替换
                        mask = pd.Series(True, index=cleaned_df.index)
                        if min_lower is not None and max_upper is not None:
                            numeric_series = pd.to_numeric(cleaned_df[column], errors='coerce')
                            mask = (numeric_series >= min_lower) & (numeric_series <= max_upper)
                        mean_val = pd.to_numeric(
                            cleaned_df.loc[mask, column], errors='coerce'
                        ).mean()
                        if mean_val is not None and not pd.isna(mean_val):
                            new_val = coerce_value_by_type(column, mean_val)
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })
                    elif strategy == 'median':
                        mask = pd.Series(True, index=cleaned_df.index)
                        if min_lower is not None and max_upper is not None:
                            numeric_series = pd.to_numeric(cleaned_df[column], errors='coerce')
                            mask = (numeric_series >= min_lower) & (numeric_series <= max_upper)
                        median_val = pd.to_numeric(
                            cleaned_df.loc[mask, column], errors='coerce'
                        ).median()
                        if median_val is not None and not pd.isna(median_val):
                            new_val = coerce_value_by_type(column, median_val)
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })
                    elif strategy == 'custom':
                        if custom_value is not None:
                            validate_custom_value(column, custom_value)
                            new_val = coerce_value_by_type(column, custom_value)
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })

                if deleted_rows:
                    cleaned_df = cleaned_df.drop(index=deleted_rows)
                operations_audit.append({
                    "operation": "range_errors",
                    "details": f"处理了{len(changes)}个范围错误，删除{len(deleted_rows)}行",
                    "changes": changes,
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

            # ---------- 异常值处理 ----------
            elif operation == 'outliers':
                strategies = strategies_map.get('outliers', [])
                changes = []
                deleted_rows = []
                for item in strategies:
                    row_index = item.get('row_index')
                    column = item.get('column')
                    strategy = item.get('strategy', 'clip')
                    custom_value = item.get('value')
                    if column is None or row_index is None:
                        continue
                    if column not in cleaned_df.columns:
                        continue
                    if row_index not in cleaned_df.index:
                        continue

                    val = get_row_numeric_value(row_index, column)
                    if val is None:
                        continue

                    old_value = cleaned_df.at[row_index, column]
                    # 优先使用问题清单中记录的原始 IQR 边界，避免缺失值填充后边界变化导致异常值漏处理
                    iqr_bounds = item.get('iqr_bounds', {})
                    lower_bound = iqr_bounds.get('lower')
                    upper_bound = iqr_bounds.get('upper')
                    # 如果问题清单中没有记录边界，则回退到重新计算
                    if lower_bound is None or upper_bound is None:
                        lower_bound, upper_bound = get_iqr_bounds(column)
                    if lower_bound is None or upper_bound is None:
                        continue

                    if strategy == 'clip':
                        # 截断到原始 IQR 边界
                        if val < lower_bound:
                            new_val = coerce_value_by_type(column, lower_bound)
                        elif val > upper_bound:
                            new_val = coerce_value_by_type(column, upper_bound)
                        else:
                            continue
                        cleaned_df.at[row_index, column] = new_val
                        changes.append({
                            "row_index": int(row_index), "column": column,
                            "old_value": to_native(old_value),
                            "new_value": to_native(new_val), "strategy": strategy
                        })
                    elif strategy == 'mean':
                        mean_val = get_column_mean(column)
                        if mean_val is not None:
                            cleaned_df.at[row_index, column] = mean_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(mean_val), "strategy": strategy
                            })
                    elif strategy == 'median':
                        median_val = get_column_median(column)
                        if median_val is not None:
                            cleaned_df.at[row_index, column] = median_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(median_val), "strategy": strategy
                            })
                    elif strategy == 'mode':
                        mode_val = get_column_mode(column)
                        if mode_val is not None:
                            cleaned_df.at[row_index, column] = mode_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(mode_val), "strategy": strategy
                            })
                    elif strategy == 'delete_row':
                        deleted_rows.append(row_index)
                    elif strategy == 'mark':
                        # 保护：标记列不再生成新的标记列，避免重复
                        if '_标记_' in str(column):
                            continue
                        cleaned_df.at[row_index, column] = np.nan
                        mark_col = f"{column}_标记_异常值"
                        ensure_mark_column(mark_col)
                        cleaned_df.at[row_index, mark_col] = True
                        changes.append({
                            "row_index": int(row_index), "column": column,
                            "old_value": to_native(old_value),
                            "new_value": None, "strategy": strategy
                        })
                    elif strategy == 'custom':
                        if custom_value is not None:
                            validate_custom_value(column, custom_value)
                            new_val = coerce_value_by_type(column, custom_value)
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": to_native(old_value),
                                "new_value": to_native(new_val), "strategy": strategy
                            })

                if deleted_rows:
                    cleaned_df = cleaned_df.drop(index=deleted_rows)
                operations_audit.append({
                    "operation": "outliers",
                    "details": f"处理了{len(changes)}个异常值，删除{len(deleted_rows)}行",
                    "changes": changes,
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

            # ---------- 缺失值处理 ----------
            elif operation == 'missing_values':
                strategies = strategies_map.get('missing_values', [])
                changes = []
                deleted_rows = []
                for item in strategies:
                    row_index = item.get('row_index')
                    column = item.get('column')
                    strategy = item.get('strategy', 'mean')
                    custom_value = item.get('value')
                    if column is None or row_index is None:
                        continue
                    if column not in cleaned_df.columns:
                        continue
                    if row_index not in cleaned_df.index:
                        continue

                    old_value = cleaned_df.at[row_index, column]
                    # 若该位置已非空（可能被前序操作填充），跳过
                    try:
                        is_missing = pd.isna(old_value)
                    except (TypeError, ValueError):
                        is_missing = False
                    if not is_missing:
                        continue

                    rules = contract.get(column, {}) if isinstance(contract, dict) else {}
                    expected_type = rules.get('expected_type') if isinstance(rules, dict) else None

                    if strategy == 'mean':
                        mean_val = get_column_mean(column)
                        if mean_val is not None:
                            cleaned_df.at[row_index, column] = mean_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": None,
                                "new_value": to_native(mean_val), "strategy": strategy
                            })
                    elif strategy == 'median':
                        median_val = get_column_median(column)
                        if median_val is not None:
                            cleaned_df.at[row_index, column] = median_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": None,
                                "new_value": to_native(median_val), "strategy": strategy
                            })
                    elif strategy == 'mode':
                        mode_val = get_column_mode(column)
                        if mode_val is not None:
                            cleaned_df.at[row_index, column] = mode_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": None,
                                "new_value": to_native(mode_val), "strategy": strategy
                            })
                    elif strategy == 'delete':
                        deleted_rows.append(row_index)
                    elif strategy == 'custom':
                        if custom_value is not None:
                            validate_custom_value(column, custom_value)
                            new_val = coerce_value_by_type(column, custom_value)
                            cleaned_df.at[row_index, column] = new_val
                            changes.append({
                                "row_index": int(row_index), "column": column,
                                "old_value": None,
                                "new_value": to_native(new_val), "strategy": strategy
                            })
                    elif strategy == 'mark':
                        # 保护：标记列不再生成新的标记列，避免重复
                        if '_标记_' in str(column):
                            continue
                        # 保持 NaN，新增标记列
                        mark_col = f"{column}_标记_缺失值"
                        ensure_mark_column(mark_col)
                        cleaned_df.at[row_index, mark_col] = True
                        changes.append({
                            "row_index": int(row_index), "column": column,
                            "old_value": None, "new_value": None,
                            "strategy": strategy
                        })

                if deleted_rows:
                    cleaned_df = cleaned_df.drop(index=deleted_rows)
                operations_audit.append({
                    "operation": "missing_values",
                    "details": f"填充了{len(changes)}个缺失值，删除{len(deleted_rows)}行",
                    "changes": changes,
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

            # ---------- 列操作 ----------
            elif operation == 'column_ops':
                action = params.get('action')
                col_changes: List[Dict[str, Any]] = []
                if action == 'rename':
                    rename_map = params.get('rename_map', {})
                    # 兼容前端单字段格式：前端 column_ops 默认参数为
                    # {action: 'rename', column: 'xxx', new_name: 'yyy'}（见 DataCleaning.vue getDefaultParams）
                    # 同时兼容旧版 old_name/new_name 格式，优先 column 字段
                    if not rename_map:
                        old_name = params.get('column') or params.get('old_name')
                        new_name = params.get('new_name')
                        if old_name and new_name:
                            rename_map = {old_name: new_name}
                    # 仅重命名仍存在的列
                    rename_map = {k: v for k, v in rename_map.items() if k in cleaned_df.columns}
                    cleaned_df = cleaned_df.rename(columns=rename_map)
                    col_changes.append({"action": "rename", "rename_map": rename_map})
                elif action == 'delete':
                    # 兼容前端单字段格式：column 字段指定要删除的列
                    cols_to_delete = params.get('columns', []) or []
                    if not cols_to_delete and params.get('column'):
                        cols_to_delete = [params.get('column')]
                    cols_to_delete = [c for c in cols_to_delete if c in cleaned_df.columns]
                    if cols_to_delete:
                        cleaned_df = cleaned_df.drop(columns=cols_to_delete)
                    col_changes.append({"action": "delete", "columns": cols_to_delete})

                operations_audit.append({
                    "operation": "column_ops",
                    "details": f"执行列操作: {action}" + (
                        f"，重命名{len(rename_map)}列" if action == 'rename' and rename_map else
                        (f"，删除{len(cols_to_delete)}列" if action == 'delete' and cols_to_delete else "")
                    ),
                    "changes": col_changes,
                    "affected_rows": []
                })

            # ---------- 行过滤 ----------
            elif operation == 'row_filter':
                condition = params.get('condition', '')
                deleted_rows = []
                if condition:
                    try:
                        mask = cleaned_df.eval(condition)
                        # 确保 mask 是布尔 Series：
                        # 若条件退化为标量（如恒真表达式），转为与 df 等长的 Series，避免 cleaned_df[mask] 误按列索引
                        if not isinstance(mask, pd.Series):
                            mask = pd.Series(bool(mask), index=cleaned_df.index)
                        mask = mask.fillna(False).astype(bool)
                        deleted_rows = cleaned_df[~mask].index.tolist()
                        cleaned_df = cleaned_df[mask]
                    except Exception as e:
                        operations_audit.append({
                            "operation": "row_filter",
                            "details": f"行过滤表达式无效（条件: {condition}）: {str(e)}",
                            "affected_rows": []
                        })
                        continue

                operations_audit.append({
                    "operation": "row_filter",
                    "details": f"过滤掉{len(deleted_rows)}行" + (f"（条件: {condition}）" if condition else "（未设置条件）"),
                    "affected_rows": [int(idx) for idx in deleted_rows]
                })

        # 同步 self.df，便于复用现有 handle_* 方法
        self.df = cleaned_df

        # ============ 质量评分计算辅助函数 ============
        def calc_quality_scores(data_df: pd.DataFrame) -> Dict[str, float]:
            """计算数据的4维度质量评分"""
            total_cells = len(data_df) * len(data_df.columns) if len(data_df.columns) > 0 else 0
            total_missing = int(data_df.isna().sum().sum())
            completeness = (1 - total_missing / total_cells) * 100 if total_cells > 0 else 100.0

            duplicate_rows_count = int(data_df.duplicated().sum())
            total_rows = len(data_df)
            uniqueness = (1 - duplicate_rows_count / total_rows) * 100 if total_rows > 0 else 100.0

            # 一致性：基于类型错误数估算
            type_error_count = 0
            for col in data_df.columns:
                if isinstance(contract, dict) and col in contract:
                    expected_type = contract[col].get('expected_type') if isinstance(contract[col], dict) else None
                    if expected_type in ('integer', 'number'):
                        numeric_series = pd.to_numeric(data_df[col], errors='coerce')
                        type_error_count += int(
                            (numeric_series.isna() & data_df[col].notna()).sum()
                        )
            consistency = max(0.0, 100.0 - (type_error_count / max(total_cells, 1)) * 100)

            # 有效性：基于异常值数估算（IQR）
            total_outliers = 0
            for col in data_df.columns:
                if isinstance(contract, dict) and col in contract:
                    expected_type = contract[col].get('expected_type') if isinstance(contract[col], dict) else None
                    if expected_type in ('integer', 'number'):
                        numeric_series = pd.to_numeric(data_df[col], errors='coerce').dropna()
                        if len(numeric_series) >= 4:
                            Q1 = numeric_series.quantile(0.25)
                            Q3 = numeric_series.quantile(0.75)
                            IQR = Q3 - Q1
                            lower = Q1 - 1.5 * IQR
                            upper = Q3 + 1.5 * IQR
                            total_outliers += int(
                                ((numeric_series < lower) | (numeric_series > upper)).sum()
                            )
            validity = (1 - total_outliers / total_cells) * 100 if total_cells > 0 else 100.0

            return {
                "completeness": round(float(completeness), 2),
                "uniqueness": round(float(uniqueness), 2),
                "consistency": round(float(consistency), 2),
                "validity": round(float(validity), 2)
            }

        # 计算清洗前的质量评分
        quality_before = calc_quality_scores(df)
        # 计算清洗后的质量评分
        quality_after = calc_quality_scores(cleaned_df)

        # ============ 列级统计对比 ============
        column_stats = {}
        for col in df.columns:
            if col in cleaned_df.columns:
                numeric_col_before = pd.to_numeric(df[col], errors='coerce')
                numeric_col_after = pd.to_numeric(cleaned_df[col], errors='coerce')
                
                # 缺失值统计
                missing_before = int(df[col].isna().sum())
                missing_after = int(cleaned_df[col].isna().sum())
                
                # 异常值统计（仅数值列）
                outlier_before = 0
                outlier_after = 0
                if len(numeric_col_before.dropna()) >= 4:
                    Q1 = numeric_col_before.dropna().quantile(0.25)
                    Q3 = numeric_col_before.dropna().quantile(0.75)
                    IQR = Q3 - Q1
                    outlier_before = int(
                        ((numeric_col_before < (Q1 - 1.5 * IQR)) | (numeric_col_before > (Q3 + 1.5 * IQR))).sum()
                    )
                if len(numeric_col_after.dropna()) >= 4:
                    Q1 = numeric_col_after.dropna().quantile(0.25)
                    Q3 = numeric_col_after.dropna().quantile(0.75)
                    IQR = Q3 - Q1
                    outlier_after = int(
                        ((numeric_col_after < (Q1 - 1.5 * IQR)) | (numeric_col_after > (Q3 + 1.5 * IQR))).sum()
                    )
                
                # 重复值统计（该列值重复的行数）
                duplicate_before = int(df[col].duplicated(keep=False).sum())
                duplicate_after = int(cleaned_df[col].duplicated(keep=False).sum())
                
                column_stats[col] = {
                    "missing_before": missing_before,
                    "missing_after": missing_after,
                    "outlier_before": outlier_before,
                    "outlier_after": outlier_after,
                    "duplicate_before": duplicate_before,
                    "duplicate_after": duplicate_after
                }
        
        # ============ 标记列信息 ============
        marked_columns = []
        mark_label_map = {
            'outliers': '异常值',
            'range_errors': '范围错误',
            'type_errors': '类型错误',
            'missing_values': '缺失值'
        }
        for op in operations_audit:
            op_type = op.get('operation', '')
            if op_type in mark_label_map:
                changes = op.get('changes', [])
                for ch in changes:
                    col = ch.get('column')
                    strategy = ch.get('strategy', '')
                    if col and strategy == 'mark':
                        # 保护：跳过已是标记列的源列，避免在审计阶段重复登记
                        if '_标记_' in str(col):
                            continue
                        mark_col = f"{col}_标记_{mark_label_map[op_type]}"
                        if mark_col not in [mc['column'] for mc in marked_columns]:
                            marked_columns.append({
                                "column": mark_col,
                                "operation": op_type,
                                "label": mark_col,
                                "description": f"标记 {col} 列的{mark_label_map[op_type]}（是/否）"
                            })
        
        audit = {
            "original_rows": int(original_rows),
            "cleaned_rows": int(len(cleaned_df)),
            "original_columns": int(original_cols),
            "cleaned_columns": int(len(cleaned_df.columns)),
            "operations": operations_audit,
            "quality_scores": quality_after,
            "quality_before": quality_before,
            "quality_after": quality_after,
            "column_stats": column_stats,
            "marked_columns": marked_columns
        }

        return {
            "cleaned_df": cleaned_df,
            "audit": audit
        }

    def dry_run_pipeline(self, df: pd.DataFrame, contract: Dict[str, Any],
                         problem_strategies: Dict[str, Any],
                         pipeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        """检查管道配置的合理性，返回警告和建议（不实际执行清洗）

        Task 8：对用户配置的清洗管道进行 dry-run 预检，覆盖以下规则：
        1. 必要操作缺失检查：problem_strategies 中有问题但 pipeline 缺对应 operation
        2. 操作顺序合理性检查：缺失值处理位置、列操作/行过滤必须末尾、列操作在行过滤之前
        3. 列引用冲突检查：column_ops 删除/重命名列后，后续操作引用了旧列名
        4. 数据量不足检查：多个 delete_row 操作叠加可能删除过多数据

        Args:
            df: 原始数据框（用于数据量不足检查时计算阈值）
            contract: 规范化后的契约（保留参数以兼容上层调用，本方法未深度使用）
            problem_strategies: 问题处理策略，键为问题类型，值为策略列表
            pipeline: 管道配置，每项 {"operation": 类型, "params": {...}}

        Returns:
            {
                "valid": 是否可以执行（errors 为空即 True，warnings 不阻断执行）,
                "warnings": 警告列表（严重程度 warning）,
                "errors": 错误列表（严重程度 error）,
                "suggested_order": 推荐的操作顺序
            }
        """
        warnings: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        # 推荐顺序固定，始终返回给前端用于顺序建议展示
        suggested_order = [
            'row_duplicates', 'column_duplicates', 'type_errors',
            'range_errors', 'outliers', 'missing_values',
            'column_ops', 'row_filter'
        ]

        # 防御性处理：允许 pipeline/problem_strategies 为 None
        pipeline = pipeline or []
        problem_strategies = problem_strategies or {}
        # 提取管道中所有 operation 名称，用于缺失/顺序检查
        operations = [p.get('operation', '') for p in pipeline]

        # ============ 1. 必要操作缺失检查 ============
        # 如果 problem_strategies 中有某类问题，但 pipeline 中没有对应 operation，发出警告
        for problem_type in [
            'missing_values', 'type_errors', 'range_errors',
            'outliers', 'row_duplicates', 'column_duplicates'
        ]:
            if problem_strategies.get(problem_type) and problem_type not in operations:
                warnings.append({
                    'type': 'missing_operation',
                    'message': f'问题清单中有{problem_type}问题，但管道中缺少{problem_type}处理操作',
                    'severity': 'warning',
                    'suggestion': f'建议添加{problem_type}处理操作'
                })

        # ============ 2. 操作顺序合理性检查 ============
        # 缺失值处理不应在类型错误/范围错误/异常值处理之前
        # 原因：缺失值填充可能产生不符合类型要求、超出范围或异常的值
        if 'missing_values' in operations:
            mv_idx = operations.index('missing_values')
            for op in ['type_errors', 'range_errors', 'outliers']:
                if op in operations:
                    op_idx = operations.index(op)
                    if mv_idx < op_idx:
                        warnings.append({
                            'type': 'order_issue',
                            'message': f'缺失值处理在{op}处理之前，可能导致填充值不符合要求',
                            'severity': 'warning',
                            'suggestion': f'建议将{op}处理移到缺失值处理之前'
                        })

        # 列操作和行过滤必须在最后：它们只能添加到管道末尾
        # 检查除最后两个位置之外的元素是否出现了 column_ops/row_filter
        for i, op in enumerate(operations[:-2]):
            if op in ['column_ops', 'row_filter']:
                warnings.append({
                    'type': 'order_issue',
                    'message': f'{op}不在管道末尾，可能导致后续操作异常',
                    'severity': 'warning',
                    'suggestion': '建议将列操作和行过滤移到管道末尾'
                })

        # 列操作必须在行过滤之前：行过滤可能引用列操作删除/重命名后的列
        if 'column_ops' in operations and 'row_filter' in operations:
            if operations.index('column_ops') > operations.index('row_filter'):
                errors.append({
                    'type': 'order_issue',
                    'message': '列操作在行过滤之后，可能导致行过滤引用已删除的列',
                    'severity': 'error',
                    'suggestion': '建议将列操作移到行过滤之前'
                })

        # ============ 3. 列引用冲突检查 ============
        # 收集 column_ops 中删除/重命名的列信息
        deleted_columns = set()
        renamed_columns = {}
        for p in pipeline:
            if p.get('operation') == 'column_ops':
                params = p.get('params', {}) or {}
                action = params.get('action')
                if action == 'delete':
                    col = params.get('column')
                    if col:
                        deleted_columns.add(col)
                elif action == 'rename':
                    old_name = params.get('old_name')
                    new_name = params.get('new_name')
                    if old_name and new_name:
                        renamed_columns[old_name] = new_name

        # 检查行过滤条件是否引用了已删除的列
        for p in pipeline:
            if p.get('operation') == 'row_filter':
                condition = (p.get('params', {}) or {}).get('condition', '') or ''
                for col in deleted_columns:
                    if col and col in condition:
                        errors.append({
                            'type': 'column_conflict',
                            'message': f'列操作删除了列[{col}]，但后续行过滤引用了该列',
                            'severity': 'error',
                            'suggestion': '建议在删除列之前执行行过滤，或修改过滤条件'
                        })

        # ============ 4. 数据量不足检查 ============
        # 统计问题清单中删除类策略的累计行数，超过原始数据 50% 时发出警告
        # 涵盖 missing_values(delete)、type_errors/range_errors/outliers(delete_row)
        # 修复：策略列表按"单元格/问题"逐条生成（同一列可能上百条），原实现每条都累加整列
        # 删除量导致计数放大数百倍、几乎必然误报 50% 警告；改为按列去重后每列只累加一次。
        delete_count = 0
        missing_delete_cols = set()
        for ps in (problem_strategies.get('missing_values') or []):
            if ps.get('strategy') == 'delete' and ps.get('column'):
                missing_delete_cols.add(ps.get('column'))
        for col in missing_delete_cols:
            if col in df.columns:
                # 缺失值删除按列计算，该列的删除行数估算为该列的缺失值数量
                delete_count += int(df[col].isna().sum())
            else:
                delete_count += 1
        for problem_type in ['type_errors', 'range_errors', 'outliers']:
            delete_row_cols = set()
            for ps in (problem_strategies.get(problem_type) or []):
                if ps.get('strategy') == 'delete_row' and ps.get('column'):
                    delete_row_cols.add(ps.get('column'))
            for col in delete_row_cols:
                if col in df.columns:
                    # 按该列的非空值数量估算最坏情况下的删除行数
                    delete_count += int(df[col].notna().sum())
                else:
                    delete_count += 1

        total_rows = len(df)
        if total_rows > 0 and delete_count > total_rows * 0.5:
            warnings.append({
                'type': 'data_loss',
                'message': f'删除操作可能删除超过50%的数据（估算{delete_count}行）',
                'severity': 'warning',
                'suggestion': '建议使用填充或截断代替删除'
            })

        # row_filter 严格条件可能导致数据量不足，给出提示
        if 'row_filter' in operations:
            for p in pipeline:
                if p.get('operation') == 'row_filter':
                    condition = (p.get('params', {}) or {}).get('condition', '') or ''
                    if condition:
                        warnings.append({
                            'type': 'data_loss',
                            'message': f'行过滤条件[{condition}]可能导致数据量不足，建议执行后检查剩余行数',
                            'severity': 'warning',
                            'suggestion': '建议放宽过滤条件或确认过滤后数据量满足业务需求'
                        })

        # ============ 5. 警告/错误 type 转中文（供前端"类型"列直接展示） ============
        # message/suggestion 本身已是中文，仅 type 是英文 code，统一在此转换
        dry_run_type_labels = {
            'missing_operation': '缺少必要操作',
            'order_issue': '执行顺序问题',
            'column_conflict': '列引用冲突',
            'data_loss': '数据丢失风险',
        }
        for item in warnings:
            item['type'] = dry_run_type_labels.get(item.get('type'), item.get('type'))
        for item in errors:
            item['type'] = dry_run_type_labels.get(item.get('type'), item.get('type'))

        return {
            'valid': len(errors) == 0,
            'warnings': warnings,
            'errors': errors,
            'suggested_order': suggested_order
        }

    def generate_audit_report(self, original_df: pd.DataFrame,
                              cleaned_df: pd.DataFrame,
                              operations_log: List[Dict],
                              contract: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成审计报告，对比清洗前后数据差异并计算质量评分

        Args:
            original_df: 原始数据框
            cleaned_df: 清洗后数据框
            operations_log: 操作日志
            contract: 规范化后的契约字典（用于质量评分计算）

        Returns:
            包含 row_level_diff/column_level_stats/quality_scores/summary 的审计报告
        """
        # ============ 提取列重命名映射 ============
        rename_map = {}
        for log in operations_log:
            if log.get('type') == 'column_ops':
                changes = log.get('changes', []) or []
                for change in changes:
                    if change.get('action') == 'rename':
                        rm = change.get('rename_map', {})
                        for old_name, new_name in rm.items():
                            rename_map[old_name] = new_name
        
        # ============ 行级差异：找出值发生变化的单元格 ============
        # 构建 (row_index, column) -> change 映射，用于在 row_level_diff 中显示详细 status
        # coerce_or_mark 策略的 status 字段记录了"转换成功"/"转换失败：xxx"等详细信息
        # operations_log 中 type=column_ops 的条目带有 changes 数组（来自 coerce_or_mark 等策略）
        change_detail_map = {}
        for op in operations_log:
            for ch in (op.get('changes') or []):
                key = (ch.get('row_index'), ch.get('column'))
                if key:
                    change_detail_map[key] = ch

        row_level_diff = []
        common_rows = list(set(original_df.index) & set(cleaned_df.index))
        # 构建列名映射：旧列名 -> 新列名，用于匹配重命名后的列
        common_cols = []
        for orig_col in original_df.columns:
            clean_col = rename_map.get(orig_col, orig_col)
            if clean_col in cleaned_df.columns:
                common_cols.append((orig_col, clean_col))

        for row_idx in common_rows:
            for (orig_col, clean_col) in common_cols:
                orig_val = original_df.at[row_idx, orig_col]
                clean_val = cleaned_df.at[row_idx, clean_col]
                orig_is_nan = pd.isna(orig_val)
                clean_is_nan = pd.isna(clean_val)

                # 两侧都是 NaN 视为无变化
                if orig_is_nan and clean_is_nan:
                    continue

                # 仅一侧为 NaN 或值字符串不一致视为变化
                value_changed = (
                    orig_is_nan != clean_is_nan or
                    str(orig_val) != str(clean_val)
                )
                if value_changed:
                    error_type, method = self._infer_change_type(
                        orig_col, orig_val, clean_val, orig_is_nan, clean_is_nan, operations_log
                    )
                    # 优先使用 changes 中的 status 字段（含"转换成功"/"转换失败：xxx"等详细信息），
                    # 其次使用 strategy 精确策略名（避免同一列存在多种策略时 _infer_change_type 匹配错位）
                    strategy_cn = {
                        'mean': '均值填充', 'median': '中位数填充', 'mode': '众数填充',
                        'delete': '删除行', 'delete_row': '删除行', 'drop': '删除行',
                        'custom': '自定义值填充', 'fill': '自定义值填充', 'mark': '标记缺失',
                        'mark_missing': '标记缺失', 'coerce_or_mark': '强制转换',
                        'clip': '截断', 'clip_upper': '截断上限', 'clip_lower': '截断下限',
                        'clip_nearest': '就近截断', 'keep_first': '保留首条',
                        'keep_last': '保留末条', 'delete_all': '删除全部'
                    }
                    matching_change = change_detail_map.get((row_idx, clean_col))
                    if matching_change:
                        method_display = (
                            matching_change.get('status')
                            or strategy_cn.get(matching_change.get('strategy'))
                            or method
                        )
                    else:
                        method_display = method
                    row_level_diff.append({
                        "row_index": int(row_idx),
                        "column": str(clean_col),
                        "original_value": "NaN" if orig_is_nan else str(orig_val),
                        "cleaned_value": "NaN" if clean_is_nan else str(clean_val),
                        "error_type": error_type,
                        "method": method_display,
                        "description": (
                            f"列[{clean_col}]在行[{row_idx}]的值由"
                            f"[{'NaN' if orig_is_nan else orig_val}]变为"
                            f"[{'NaN' if clean_is_nan else clean_val}]"
                        )
                    })

        # 限制差异条目数量，避免数据量过大导致报告难以阅读
        row_level_diff = row_level_diff[:1000]

        # 补充 changes 中未在 row_level_diff 中显示的记录
        # 场景：coerce_or_mark 转换失败时保留原值，orig_val == clean_val，
        # value_changed=False，不会出现在上面的 row_level_diff 中
        # 但 changes 中记录了 status="转换失败：xxx"，用户需要看到这些标记
        existing_keys = {(d['row_index'], d['column']) for d in row_level_diff}
        for op in operations_log:
            # 兼容两种键名：扁平日志用 type，原始审计用 operation
            op_type = op.get('operation') or op.get('type', '')
            # 映射操作类型到错误类型（与 _infer_change_type 的 type_mapping 一致）
            type_mapping = {
                'missing_values': '缺失值', 'outlier': '异常值', 'outliers': '异常值',
                'type_error': '类型错误', 'type_errors': '类型错误',
                'range_error': '范围错误', 'range_errors': '范围错误',
                'deduplication': '去重', 'column_op': '列操作', 'column_ops': '列操作',
                'row_filter': '行过滤'
            }
            error_type = type_mapping.get(op_type, op_type or '其他')
            for ch in op.get('changes', []):
                ch_row = ch.get('row_index')
                ch_col = ch.get('column')
                # 防御：changes 条目可能缺少 row_index/column（如仅标记列等操作），跳过
                if ch_row is None or ch_col is None:
                    continue
                key = (ch_row, ch_col)
                if key not in existing_keys:
                    row_level_diff.append({
                        "row_index": int(ch_row),
                        "column": str(ch_col),
                        "original_value": str(ch.get('old_value', '')),
                        "cleaned_value": str(ch.get('new_value', '')),
                        "error_type": error_type,
                        "method": ch.get('status') or ch.get('strategy') or '未知',
                        "description": ch.get('status') or f"列[{ch_col}]在行[{ch_row}]的处理"
                    })
                    existing_keys.add(key)

        # ============ 列级统计：对比缺失值/异常值/唯一值数量 ============
        column_level_stats = {}
        # 构建列名映射：从原始列到清洗后列（处理重命名）
        col_mapping = {}
        for orig_col in original_df.columns:
            col_mapping[orig_col] = rename_map.get(orig_col, orig_col)
        # 添加清洗后新增的列（如标记列）
        for clean_col in cleaned_df.columns:
            if clean_col not in col_mapping.values():
                col_mapping[clean_col] = clean_col

        def count_outliers(series: pd.Series) -> int:
            """统计数值列的异常值数量（IQR 方法）"""
            if len(series) == 0:
                return 0
            numeric_series = pd.to_numeric(series, errors='coerce').dropna()
            if len(numeric_series) < 4:
                return 0
            numeric_series = numeric_series.astype(float)
            Q1 = float(numeric_series.quantile(0.25))
            Q3 = float(numeric_series.quantile(0.75))
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR
            return int(((numeric_series < lower) | (numeric_series > upper)).sum())

        # 使用传入的 contract 计算一致性和有效性，若未提供则使用空字典
        contract_for_scoring = contract if isinstance(contract, dict) else {}

        for orig_col, clean_col in col_mapping.items():
            orig_series = original_df[orig_col] if orig_col in original_df.columns else pd.Series([])
            clean_series = cleaned_df[clean_col] if clean_col in cleaned_df.columns else pd.Series([])
            orig_len = len(orig_series) if len(orig_series) > 0 else 1
            clean_len = len(clean_series) if len(clean_series) > 0 else 1
            
            # 优先使用契约中定义的期望类型，回退到 pandas 推断类型
            def get_contract_dtype(col_name):
                if isinstance(contract_for_scoring, dict) and col_name in contract_for_scoring:
                    col_contract = contract_for_scoring[col_name]
                    if isinstance(col_contract, dict):
                        expected = col_contract.get('expected_type')
                        if expected:
                            return expected
                # 回退到 pandas 推断
                if pd.api.types.is_numeric_dtype(orig_series):
                    return 'number'
                if pd.api.types.is_datetime64_any_dtype(orig_series):
                    return 'date'
                if pd.api.types.is_bool_dtype(orig_series):
                    return 'boolean'
                return 'string'
            
            # 计算重复行数：总行数 - 唯一值数（针对完全重复行）
            orig_unique = int(orig_series.nunique())
            clean_unique = int(clean_series.nunique())
            orig_duplicate = max(0, len(orig_series) - orig_unique)
            clean_duplicate = max(0, len(clean_series) - clean_unique)
            
            column_level_stats[clean_col] = {
                "original_missing": int(orig_series.isna().sum()),
                "cleaned_missing": int(clean_series.isna().sum()),
                "original_missing_rate": round(float(orig_series.isna().sum()) / orig_len * 100, 2),
                "cleaned_missing_rate": round(float(clean_series.isna().sum()) / clean_len * 100, 2),
                "original_outliers": count_outliers(orig_series),
                "cleaned_outliers": count_outliers(clean_series),
                "original_duplicate": orig_duplicate,
                "cleaned_duplicate": clean_duplicate,
                "data_type": get_contract_dtype(clean_col)
            }

        # ============ 质量评分：计算清洗前后的质量评分对比 ============
        def calc_quality_scores(data_df: pd.DataFrame) -> Dict[str, float]:
            """计算数据的4维度质量评分"""
            total_cells = len(data_df) * len(data_df.columns) if len(data_df.columns) > 0 else 0
            
            # 完整性 = (1 - 缺失值率) * 100
            total_missing = int(data_df.isna().sum().sum())
            completeness = (1 - total_missing / total_cells) * 100 if total_cells > 0 else 100.0
            
            # 唯一性 = (1 - 重复行率) * 100
            duplicate_rows_count = int(data_df.duplicated().sum())
            total_rows = len(data_df)
            uniqueness = (1 - duplicate_rows_count / total_rows) * 100 if total_rows > 0 else 100.0
            
            # 一致性：基于类型错误数估算（需要 contract 提供列的 expected_type）
            type_error_count = 0
            for col in data_df.columns:
                if col in contract_for_scoring:
                    expected_type = contract_for_scoring[col].get('expected_type') if isinstance(contract_for_scoring[col], dict) else None
                    if expected_type in ('integer', 'number'):
                        numeric_series = pd.to_numeric(data_df[col], errors='coerce')
                        type_error_count += int(
                            (numeric_series.isna() & data_df[col].notna()).sum()
                        )
            consistency = max(0.0, 100.0 - (type_error_count / max(total_cells, 1)) * 100)
            
            # 有效性：基于异常值数估算（IQR，需要 contract 提供列的 expected_type）
            total_outliers = 0
            for col in data_df.columns:
                if col in contract_for_scoring:
                    expected_type = contract_for_scoring[col].get('expected_type') if isinstance(contract_for_scoring[col], dict) else None
                    if expected_type in ('integer', 'number'):
                        numeric_series = pd.to_numeric(data_df[col], errors='coerce').dropna()
                        if len(numeric_series) >= 4:
                            numeric_series = numeric_series.astype(float)
                            Q1 = float(numeric_series.quantile(0.25))
                            Q3 = float(numeric_series.quantile(0.75))
                            IQR = Q3 - Q1
                            lower = Q1 - 1.5 * IQR
                            upper = Q3 + 1.5 * IQR
                            total_outliers += int(
                                ((numeric_series < lower) | (numeric_series > upper)).sum()
                            )
            validity = (1 - total_outliers / total_cells) * 100 if total_cells > 0 else 100.0
            
            return {
                "completeness": round(float(completeness), 2),
                "uniqueness": round(float(uniqueness), 2),
                "consistency": round(float(consistency), 2),
                "validity": round(float(validity), 2)
            }
        
        # 计算清洗前的质量评分
        quality_before = calc_quality_scores(original_df)
        # 计算清洗后的质量评分
        quality_after = calc_quality_scores(cleaned_df)

        # ============ 标记列统计 ============
        # 收集所有标记列（列名含"_标记_"），统计标记行数
        marked_columns = []
        for col in cleaned_df.columns:
            if '_标记_' in col:
                if col in original_df.columns:
                    continue
                mark_count = int(cleaned_df[col].sum()) if cleaned_df[col].dtype == bool else int((cleaned_df[col] == True).sum())
                parts = col.split('_标记_')
                source_col = parts[0]
                mark_type = parts[1] if len(parts) > 1 else '标记'
                marked_columns.append({
                    "column": col,
                    "source_column": source_col,
                    "mark_type": mark_type,
                    "marked_count": mark_count
                })

        summary = {
            "original_rows": int(len(original_df)),
            "cleaned_rows": int(len(cleaned_df)),
            "original_cols": int(len(original_df.columns)),
            "cleaned_cols": int(len(cleaned_df.columns)),
            "operations_count": len(operations_log),
            "marked_columns_count": len(marked_columns)
        }

        return {
            "row_level_diff": row_level_diff,
            "column_level_stats": column_level_stats,
            "quality_scores": {
                "before": quality_before,
                "after": quality_after
            },
            "summary": summary,
            "marked_columns": marked_columns
        }

    def _infer_error_type(self, col: str, operations_log: List[Dict]) -> str:
        """根据操作日志推断指定列的值变更属于哪种错误类型

        Args:
            col: 列名
            operations_log: 操作日志

        Returns:
            错误类型字符串（缺失值/异常值/类型错误/范围错误/去重/列操作/行过滤/其他）
        """
        type_mapping = {
            'missing_values': '缺失值',
            'outlier': '异常值',
            'type_error': '类型错误',
            'range_error': '范围错误',
            'deduplication': '去重',
            'column_op': '列操作',
            'row_filter': '行过滤'
        }
        # 行级操作不会导致单元格值变更，排除在未指定列匹配之外
        row_level_ops = {'row_filter', 'deduplication'}

        # 优先匹配指定了列的操作
        for log in reversed(operations_log):
            op_type = log.get('type', '')
            op_cols = log.get('columns', []) or []
            if op_type in type_mapping and op_cols and col in op_cols:
                return type_mapping[op_type]

        # 再匹配未指定列的列级操作（排除行级操作，行级操作只删除行不修改值）
        for log in reversed(operations_log):
            op_type = log.get('type', '')
            op_cols = log.get('columns', []) or []
            if op_type in type_mapping and op_type not in row_level_ops and not op_cols:
                return type_mapping[op_type]
        return '其他'

    def _infer_method(self, col: str, operations_log: List[Dict]) -> str:
        """根据操作日志推断指定列的处理方法

        Args:
            col: 列名
            operations_log: 操作日志

        Returns:
            处理方法字符串（如"均值填充"/"中位数填充"/"删除行"/"截断"/"标记缺失"等）
        """
        # 行级操作不会导致单元格值变更，排除在未指定列匹配之外
        row_level_ops = {'row_filter', 'deduplication'}

        # 统一的方法映射表
        method_mapping = {
            'mean': '均值填充',
            'median': '中位数填充',
            'mode': '众数填充',
            'drop': '删除行',
            'clip': '截断',
            'mark_missing': '标记缺失',
            'fill': '自定义值填充',
            'remove': '删除行',
            'delete': '删除行',
            'keep': '保留原值',
            'coerce': '强制转换',
            'auto': '自动处理',
            'row_filter': '行过滤',
            'drop_duplicates': '去重',
            'condition': '条件过滤'
        }

        # 优先匹配指定了列的操作
        for log in reversed(operations_log):
            op_cols = log.get('columns', []) or []
            method = log.get('method', '') or ''
            if op_cols and col in op_cols and method:
                return method_mapping.get(method, method)

        # 再匹配未指定列的列级操作（排除行级操作）
        for log in reversed(operations_log):
            op_type = log.get('type', '')
            op_cols = log.get('columns', []) or []
            method = log.get('method', '') or ''
            if op_type not in row_level_ops and not op_cols and method:
                return method_mapping.get(method, method)
        return '未知'

    def _infer_change_type(self, col: str, orig_val, clean_val, orig_is_nan, clean_is_nan, operations_log: List[Dict]) -> tuple:
        """根据实际值变更内容智能推断错误类型和处理方法

        Args:
            col: 列名
            orig_val: 原始值
            clean_val: 清洗后值
            orig_is_nan: 原始值是否为NaN
            clean_is_nan: 清洗后值是否为NaN
            operations_log: 操作日志

        Returns:
            (error_type, method) 元组
        """
        # 错误类型：显示大类（简洁名称），兼容单复数形式
        type_mapping = {
            'missing_values': '缺失值',
            'outlier': '异常值',
            'outliers': '异常值',
            'type_error': '类型错误',
            'type_errors': '类型错误',
            'range_error': '范围错误',
            'range_errors': '范围错误',
            'deduplication': '去重',
            'column_op': '列操作',
            'column_ops': '列操作',
            'row_filter': '行过滤'
        }

        # 处理方法：显示具体方法名
        method_mapping = {
            'mean': '均值填充',
            'median': '中位数填充',
            'mode': '众数填充',
            'drop': '删除行',
            'clip': '截断',
            'clip_upper': '截断上限',
            'clip_lower': '截断下限',
            'clip_nearest': '就近截断',
            'mark_missing': '标记缺失',
            'mark': '标记缺失',
            'fill': '自定义值填充',
            'custom': '自定义值填充',
            'remove': '删除行',
            'delete': '删除行',
            'delete_row': '删除行',
            'coerce': '强制转换',
            'coerce_or_mark': '强制转换',
            'auto': '自动处理',
            'row_filter': '行过滤',
            'drop_duplicates': '去重',
            'keep_first': '保留首条',
            'keep_last': '保留末条',
            'delete_all': '删除全部',
            'condition': '条件过滤'
        }

        # 辅助函数：从操作日志中匹配指定列的操作
        def find_matching_op(check_types):
            for log in reversed(operations_log):
                op_type = log.get('type', '')
                op_cols = log.get('columns', []) or []
                method = log.get('method', '') or ''
                # 兼容单复数形式
                normalized_type = op_type.rstrip('s') if op_type.endswith('s') else op_type
                normalized_check = {t.rstrip('s') if t.endswith('s') else t for t in check_types}
                if normalized_type in normalized_check and (not op_cols or col in op_cols):
                    return op_type, method
            return None, None

        def format_method(method):
            """格式化方法名：先在 mapping 中查找，否则根据常见关键词推断"""
            if not method:
                return '未知'
            if method in method_mapping:
                return method_mapping[method]
            # 兜底：根据关键词推断
            if 'mean' in method:
                return '均值填充'
            if 'median' in method:
                return '中位数填充'
            if 'mode' in method:
                return '众数填充'
            if 'clip' in method or 'nearest' in method:
                return '截断'
            if 'mark' in method:
                return '标记缺失'
            if 'delete' in method or 'drop' in method or 'remove' in method:
                return '删除行'
            if 'fill' in method or 'custom' in method:
                return '自定义值填充'
            if 'coerce' in method or 'convert' in method:
                return '强制转换'
            return method

        # 根据值变更特征进行智能判断
        # 1. 原始值是NaN，清洗后不是NaN → 缺失值填充
        if orig_is_nan and not clean_is_nan:
            op_type, method = find_matching_op({'missing_values'})
            if op_type:
                return (type_mapping[op_type], format_method(method))

        # 2. 原始值不是NaN，清洗后是NaN → 异常值标记/范围标记
        elif not orig_is_nan and clean_is_nan:
            op_type, method = find_matching_op({'outlier', 'range_error'})
            if op_type:
                return (type_mapping[op_type], format_method(method))

        # 3. 原始值和清洗后都不是NaN，但值发生了变化 → 异常值截断/类型转换/范围修正
        elif not orig_is_nan and not clean_is_nan and str(orig_val) != str(clean_val):
            # 判断是否是数值变化
            try:
                float(orig_val)
                float(clean_val)
                # 数值变化通常是异常值处理或范围修正
                op_type, method = find_matching_op({'outlier', 'range_error'})
                if op_type:
                    return (type_mapping[op_type], format_method(method))
            except (ValueError, TypeError):
                # 非数值变化可能是类型转换或其他操作
                op_type, method = find_matching_op({'type_error', 'column_op'})
                if op_type:
                    return (type_mapping[op_type], format_method(method))

        # 4. 兜底：按原始逻辑匹配
        return (self._infer_error_type(col, operations_log), self._infer_method(col, operations_log))
