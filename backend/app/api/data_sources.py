"""数据源（远程数据库连接）管理 API

提供连接 CRUD、测试连通、浏览表结构/行数功能。
密码通过 Fernet 加密存储，API 返回时脱敏显示。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text, inspect as sa_inspect
from pydantic import BaseModel
from typing import Optional, List
from urllib.parse import quote
from app.models import DataSourceConnection
from app.utils.db import get_db
from app.utils.security import get_current_user
from app.utils.crypto import encrypt_password, decrypt_password, InvalidTokenError
from app.services.data_service import DataService

router = APIRouter(prefix="/api/data-sources", tags=["数据源管理"])

# ====== Pydantic Schemas ======

class DataSourceCreate(BaseModel):
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    extra_params: Optional[str] = None


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    extra_params: Optional[str] = None


class TestConnectionRequest(BaseModel):
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    extra_params: Optional[str] = None


# ====== 工具函数 ======

def _build_db_url(
    db_type: str, user: str, password: str, host: str, port: int,
    database: str, extra_params: Optional[str] = None
) -> str:
    """构建远程数据库连接 URL。

    用户名/密码需 URL 编码，否则含 @ : / ? # 等特殊字符时 URL 解析错乱或认证失败（修复）。
    """
    # 用户名/密码经 URL 编码后再拼入连接串，避免特殊字符破坏 URL 结构
    safe_user = quote(user, safe="")
    safe_password = quote(password, safe="")
    safe_database = quote(database, safe="/")
    if db_type == "mysql":
        url = f"mysql+pymysql://{safe_user}:{safe_password}@{host}:{port}/{safe_database}"
    elif db_type == "postgresql":
        url = f"postgresql+psycopg2://{safe_user}:{safe_password}@{host}:{port}/{safe_database}"
    else:
        raise HTTPException(400, f"不支持的数据库类型: {db_type}，仅支持 mysql / postgresql")
    if extra_params:
        url += f"?{extra_params.lstrip('?')}"
    return url


def _to_response(conn: DataSourceConnection) -> dict:
    return {
        "id": conn.id, "name": conn.name, "db_type": conn.db_type,
        "host": conn.host, "port": conn.port, "database": conn.database,
        "username": conn.username, "extra_params": conn.extra_params,
        "password_display": "******"
    }


def _safe_decrypt(conn: DataSourceConnection) -> str:
    """安全解密：密钥不匹配时抛出明确 HTTP 异常，引导用户重建数据源"""
    try:
        return decrypt_password(conn.password_encrypted)
    except InvalidTokenError as e:
        raise HTTPException(
            400,
            f"数据源「{conn.name}」的密码无法解密（加密密钥已变更）。请删除该数据源后重新创建。"
        )


def _get_own_connection(conn_id: int, user_id: int, db: Session) -> DataSourceConnection:
    conn = db.query(DataSourceConnection).filter(
        DataSourceConnection.id == conn_id,
        DataSourceConnection.user_id == user_id
    ).first()
    if not conn:
        raise HTTPException(404, "数据源不存在")
    return conn


# 远程连接统一超时配置：避免数据库不可达时请求长时间挂起
REMOTE_CONNECT_TIMEOUT = 5  # 建立连接超时（秒）


def _create_remote_engine(url: str):
    """创建带超时配置的远程数据库引擎"""
    return create_engine(url, connect_args={"connect_timeout": REMOTE_CONNECT_TIMEOUT})


# ====== Routes ======

@router.get("/")
def list_connections(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """获取当前用户的所有数据源连接"""
    conns = db.query(DataSourceConnection).filter(
        DataSourceConnection.user_id == current_user.id
    ).order_by(DataSourceConnection.created_at.desc()).all()
    return [_to_response(c) for c in conns]


@router.post("/")
def create_connection(
    body: DataSourceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """新建数据源连接"""
    # 重名检测：同一用户下连接名称唯一，避免在数据源选择器中混淆
    existing = db.query(DataSourceConnection).filter(
        DataSourceConnection.user_id == current_user.id,
        DataSourceConnection.name == body.name
    ).first()
    if existing:
        raise HTTPException(400, f"已存在名为「{body.name}」的连接，请更换名称")
    conn = DataSourceConnection(
        user_id=current_user.id,
        name=body.name,
        db_type=body.db_type,
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        password_encrypted=encrypt_password(body.password),
        extra_params=body.extra_params
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return _to_response(conn)


@router.put("/{conn_id}")
def update_connection(
    conn_id: int, body: DataSourceUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """更新数据源连接（未传的字段保持原值）"""
    conn = _get_own_connection(conn_id, current_user.id, db)
    # 修改名称时进行重名检测（排除自身）
    if body.name is not None and body.name != conn.name:
        dup = db.query(DataSourceConnection).filter(
            DataSourceConnection.user_id == current_user.id,
            DataSourceConnection.name == body.name,
            DataSourceConnection.id != conn_id
        ).first()
        if dup:
            raise HTTPException(400, f"已存在名为「{body.name}」的连接，请更换名称")
    for field in ("name", "host", "port", "database", "username", "extra_params"):
        val = getattr(body, field)
        if val is not None:
            setattr(conn, field, val)
    if body.password is not None:
        conn.password_encrypted = encrypt_password(body.password)
    db.commit()
    return _to_response(conn)


@router.delete("/{conn_id}")
def delete_connection(
    conn_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """删除数据源连接（有引用时拒绝，并返回引用的数据集列表）"""
    conn = _get_own_connection(conn_id, current_user.id, db)
    # 检查所有数据集引用（包括 active 和 deleted 状态）
    from app.models import Dataset, shanghai_now
    ref_datasets = db.query(Dataset).filter(
        Dataset.connection_id == conn_id
    ).all()
    # 工作副本是可再生的中间产物，删除连接时一并软删，不阻止连接删除
    for d in ref_datasets:
        if d.artifact_type == "feature_workcopy":
            d.status = "deleted"
            d.deleted_at = shanghai_now()
    normal_refs = [d for d in ref_datasets if d.artifact_type != "feature_workcopy"]
    active_refs = [d for d in normal_refs if d.status == "active"]
    deleted_refs = [d for d in normal_refs if d.status != "active"]
    
    if active_refs:
        ref_names = [d.name for d in active_refs[:5]]
        suffix = "..." if len(active_refs) > 5 else ""
        raise HTTPException(
            400,
            f"该连接被 {len(active_refs)} 个活跃数据集引用（{', '.join(ref_names)}{suffix}），"
            f"请先从各模块中删除这些数据集后再删除连接"
        )
    
    # 清理已删除/回收站的数据集的连接引用
    for ds in deleted_refs:
        ds.connection_id = None
    
    db.delete(conn)
    db.commit()
    return {"success": True}


@router.post("/verify")
def verify_connection(
    body: TestConnectionRequest,
    current_user=Depends(get_current_user)
):
    """验证连接（不保存到数据库，需登录）"""
    return _test_connection_internal(body)


@router.post("/test")
def test_connection(
    body: TestConnectionRequest,
    current_user=Depends(get_current_user)
):
    """测试连接（不保存到数据库，需登录）—— /test 别名，兼容前端调用"""
    return _test_connection_internal(body)


def _format_db_error(e: Exception) -> str:
    """将数据库连接异常转为中文友好提示，区分超时/拒绝连接/认证失败等场景"""
    msg = str(e).lower()
    if "timed out" in msg or "timeout" in msg:
        return "连接超时，请检查主机地址和端口是否正确"
    if "can't connect" in msg or "connection refused" in msg or "no route to host" in msg:
        return "无法连接到数据库服务器，请检查地址和端口"
    if "access denied" in msg or "authentication" in msg or "password" in msg:
        return "认证失败，请检查用户名和密码"
    if "unknown database" in msg:
        return f"数据库不存在: {body_database_hint(e)}"
    return f"连接失败: {str(e)}"


def body_database_hint(e: Exception):
    """从异常信息中提取数据库名（用于 unknown database 提示）"""
    import re
    m = re.search(r"Unknown database '([^']+)'", str(e))
    return m.group(1) if m else ""


def _test_connection_internal(body: TestConnectionRequest) -> dict:
    """内部：执行连接测试逻辑"""
    url = _build_db_url(body.db_type, body.username, body.password,
                         body.host, body.port, body.database, body.extra_params)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"success": True, "message": "连接成功"}
    except Exception as e:
        return {"success": False, "message": _format_db_error(e)}


@router.get("/{conn_id}/tables")
def list_tables(
    conn_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """列出远程数据库中的表"""
    conn = _get_own_connection(conn_id, current_user.id, db)
    url = _build_db_url(conn.db_type, conn.username,
                         _safe_decrypt(conn),
                         conn.host, conn.port, conn.database, conn.extra_params)
    engine = _create_remote_engine(url)
    try:
        with engine.connect() as c:
            inspector = sa_inspect(engine)
            return inspector.get_table_names()
    except Exception as e:
        raise HTTPException(502, _format_db_error(e))
    finally:
        engine.dispose()


@router.get("/{conn_id}/tables/{table_name}/schema")
def get_table_schema(
    conn_id: int, table_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """获取表的列信息"""
    conn = _get_own_connection(conn_id, current_user.id, db)
    url = _build_db_url(conn.db_type, conn.username,
                         _safe_decrypt(conn),
                         conn.host, conn.port, conn.database, conn.extra_params)
    engine = _create_remote_engine(url)
    try:
        with engine.connect() as c:
            inspector = sa_inspect(engine)
            columns = inspector.get_columns(table_name)
            return [{"name": col["name"], "type": str(col["type"]), "nullable": col.get("nullable", True)}
                    for col in columns]
    except Exception as e:
        raise HTTPException(502, _format_db_error(e))
    finally:
        engine.dispose()


@router.get("/{conn_id}/tables/{table_name}/count")
def get_table_count(
    conn_id: int, table_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """获取表的行数"""
    conn = _get_own_connection(conn_id, current_user.id, db)
    # 表名标识符校验，防止 SQL 注入（与 aggregate 接口一致）
    DataService(db)._validate_identifier(table_name, "表名")
    url = _build_db_url(conn.db_type, conn.username,
                         _safe_decrypt(conn),
                         conn.host, conn.port, conn.database, conn.extra_params)
    engine = _create_remote_engine(url)
    try:
        with engine.connect() as c:
            result = c.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            return {"row_count": result.scalar()}
    except Exception as e:
        raise HTTPException(502, _format_db_error(e))
    finally:
        engine.dispose()


class AggregateMetric(BaseModel):
    type: str
    columns: Optional[List[str]] = None
    top_n: Optional[int] = 10


class AggregateRequest(BaseModel):
    metrics: List[AggregateMetric]


@router.post("/{conn_id}/tables/{table_name}/aggregate")
def aggregate_remote_table(
    conn_id: int, table_name: str,
    body: AggregateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """SQL 下推聚合查询：在远程数据库侧执行聚合，不拉明细数据

    用于统计/质量/图表推荐等场景，避免大表全量加载导致 OOM。
    支持的 metric 类型：
      - count: 全表行数
      - numeric_stats: 数值列统计（count/unique/mean/std/min/max/sum）
      - categorical_stats: 分类列 top N
      - null_count: 各列缺失值数
      - unique_count: 各列唯一值数
      - duplicate_count: 重复行数（基于指定列）
    """
    # 复用 DataService 的 SQL 下推能力：连接解析、标识符校验、SQL 构建都在那里
    data_service = DataService(db)
    try:
        return data_service.query_remote_aggregate(
            connection_id=conn_id,
            table_name=table_name,
            user_id=current_user.id,
            metrics=[m.model_dump(exclude_none=True) for m in body.metrics]
        )
    except ValueError as e:
        # 非法标识符（表名/列名不通过白名单）
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, _format_db_error(e))
