from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.config import settings
from app.models import Base

def create_db_engine():
    return create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


engine = create_db_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        # 显式 rollback 未提交的事务,避免连接归还连接池后残留 idle in transaction 状态
        # 只读查询也会开启事务,不 rollback 会导致连接泄漏(表现为系统逐渐变卡)
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


def _ensure_user_columns(engine):
    """确保 users 表有新字段（开发阶段用，避免已存在的表无法自动添加新列）"""
    inspector = inspect(engine)
    if 'users' not in inspector.get_table_names():
        return
    existing_columns = [col['name'] for col in inspector.get_columns('users')]
    with engine.connect() as conn:
        if 'last_login_at' not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP"))
            conn.commit()
        if 'last_login_ip' not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_login_ip VARCHAR"))
            conn.commit()


def _ensure_ai_conversation_columns(engine):
    """确保 ai_conversations 表有新字段（summary 和 last_context_items）

    这两个字段用于会话压缩和上下文恢复，对已存在的表通过 ALTER TABLE 补列。
    """
    inspector = inspect(engine)
    if 'ai_conversations' not in inspector.get_table_names():
        return
    existing_columns = [col['name'] for col in inspector.get_columns('ai_conversations')]
    with engine.connect() as conn:
        if 'summary' not in existing_columns:
            conn.execute(text("ALTER TABLE ai_conversations ADD COLUMN summary TEXT"))
            conn.commit()
        if 'last_context_items' not in existing_columns:
            conn.execute(text("ALTER TABLE ai_conversations ADD COLUMN last_context_items JSON"))
            conn.commit()


def _ensure_task_record_columns(engine):
    """确保 task_records 表有 celery_task_id 和 failure_category 字段

    这两个字段用于：
    - celery_task_id：异步任务取消时通过 Celery 任务 ID 反查并 revoke
    - failure_category：失败原因分类（param_error/data_error/system_error/timeout/network_error/unknown），
      前端根据分类决定是否提供重试按钮

    遵循项目现有的 _ensure_user_columns / _ensure_ai_conversation_columns 模式：
    通过 inspector 反射已有表结构，仅当列缺失时执行 ALTER TABLE ADD COLUMN，
    避免开发阶段已存在表无法自动添加新列的问题。
    """
    inspector = inspect(engine)
    if 'task_records' not in inspector.get_table_names():
        return
    existing_columns = [col['name'] for col in inspector.get_columns('task_records')]
    with engine.connect() as conn:
        if 'celery_task_id' not in existing_columns:
            conn.execute(text("ALTER TABLE task_records ADD COLUMN celery_task_id VARCHAR(255)"))
            conn.commit()
        if 'failure_category' not in existing_columns:
            conn.execute(text("ALTER TABLE task_records ADD COLUMN failure_category VARCHAR(30)"))
            conn.commit()


def _ensure_datasource_table(engine):
    """确保 datasource_connections 表存在（开发阶段用）

    遵循项目现有模式：通过 inspector 反射，表缺失时 ALTER TABLE 创建。
    """
    inspector = inspect(engine)
    if 'datasource_connections' in inspector.get_table_names():
        return
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE datasource_connections (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                db_type VARCHAR(20) NOT NULL,
                host VARCHAR(255) NOT NULL,
                port INTEGER NOT NULL,
                database VARCHAR(100) NOT NULL,
                username VARCHAR(100) NOT NULL,
                password_encrypted TEXT NOT NULL,
                extra_params VARCHAR(500),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_datasource_user_id ON datasource_connections(user_id)"
        ))
        conn.commit()


def _ensure_app_config_table(engine):
    """确保 app_config 表存在（开发阶段用）

    用于存储全局配置项（如加密密钥），不依赖环境变量，重启不丢失。
    """
    inspector = inspect(engine)
    if 'app_config' in inspector.get_table_names():
        return
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE app_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.commit()


def _ensure_dataset_source_columns(engine):
    """迁移：为 datasets 表添加 root_connection_id 和 source_type 列（v2.1 远程数据库重构）"""
    inspector = inspect(engine)
    if 'datasets' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('datasets')}
    with engine.connect() as conn:
        if 'root_connection_id' not in cols:
            conn.execute(text("ALTER TABLE datasets ADD COLUMN root_connection_id INTEGER"))
            conn.commit()
        if 'source_type' not in cols:
            conn.execute(text("ALTER TABLE datasets ADD COLUMN source_type VARCHAR(20) DEFAULT 'upload'"))
            conn.commit()
            # 回填已有数据：file_path=NULL 且有 connection_id 的标记为 remote_db
            conn.execute(text(
                "UPDATE datasets SET source_type = 'remote_db' "
                "WHERE file_path IS NULL AND connection_id IS NOT NULL AND source_type = 'upload'"
            ))
            conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_user_columns(engine)
    _ensure_ai_conversation_columns(engine)
    _ensure_task_record_columns(engine)
    _ensure_datasource_table(engine)
    _ensure_app_config_table(engine)
    _ensure_dataset_source_columns(engine)
