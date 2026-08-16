from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone, timedelta

Base = declarative_base()

SHANGHAI_TZ = timezone(timedelta(hours=8))


def shanghai_now():
    """返回上海时区当前时间"""
    return datetime.now(SHANGHAI_TZ)


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")
    is_active = Column(Boolean, default=True)  # 账号是否启用（管理员禁用后登录/操作受限）
    failed_login_count = Column(Integer, default=0)  # 连续登录失败次数（用于暴力破解锁定）
    locked_until = Column(DateTime, nullable=True)  # 登录锁定截止时间（None 表示未锁定）
    last_login_at = Column(DateTime, nullable=True)  # 最后登录时间
    last_login_ip = Column(String, nullable=True)  # 最后登录IP
    created_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<User {self.username}>"


class Dataset(Base):
    """数据集模型"""
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)  # 索引：按用户查询数据集
    name = Column(String, nullable=False, index=True)  # 索引：名称唯一性校验
    connection_id = Column(Integer)  # 关联的数据源连接
    table_name = Column(String)  # 表名（数据库）或文件名（文件）
    schema = Column(JSON)  # 数据结构信息
    file_path = Column(String)  # 文件路径
    data_preview = Column(Text)  # 数据预览（JSON格式）
    row_count = Column(Integer)  # 数据行数
    file_size = Column(Integer)  # 文件大小（字节）
    module_source = Column(String, default="upload", index=True)  # 索引：按模块筛选数据
    module_label = Column(String)  # 模块标签，如 "清洗产物"/"ML产物"/"AI产物"
    algorithm = Column(String)  # 使用的算法/方式，如 "缺失值填充+去重"/"K-Means(k=3)"
    parent_id = Column(Integer)  # 父数据ID，标识产物来自哪个直接父数据
    root_dataset_id = Column(Integer)  # 根数据ID，追溯回最原始的raw_data，用于按原始数据筛选产物
    root_connection_id = Column(Integer)  # 根来源连接ID，追溯远程数据库来源（血缘用）
    source_type = Column(String, default="upload")  # 数据来源类型: upload/remote_db/derived
    tags = Column(String)  # 标签，JSON数组字符串
    remarks = Column(String)  # 备注描述
    artifact_type = Column(String, default="raw_data", index=True)  # 索引：按产物类型筛选
    report_content = Column(Text)  # JSON格式的报告内容（仅ml_report/ai_report使用）
    status = Column(String, default="active", index=True)  # 索引：按状态筛选（active/deleted/corrupted）
    deleted_at = Column(DateTime)  # 删除时间（回收站用）
    created_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<Dataset {self.name}>"


class AIConversation(Base):
    """AI会话模型"""
    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1)
    dataset_id = Column(Integer)
    module_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    conversation = Column(JSON)
    follow_up_remaining = Column(Integer, default=10)
    expires_at = Column(DateTime)
    # 会话历史压缩摘要：超出滑动窗口的旧消息会被压缩为摘要文本存储于此
    summary = Column(Text)
    # 最近一次注入的上下文项快照（JSON），便于会话恢复时重建上下文
    last_context_items = Column(JSON)
    created_at = Column(DateTime, default=shanghai_now)
    updated_at = Column(DateTime, default=shanghai_now, onupdate=shanghai_now)

    def __repr__(self):
        return f"<AIConversation {self.title}>"


class AIUsageLog(Base):
    """AI使用日志模型"""
    __tablename__ = "ai_usage_log"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer)
    module_type = Column(String(50))
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<AIUsageLog {self.module_type}/{self.total_tokens}>"


class AIConfig(Base):
    """AI配置模型"""
    __tablename__ = "ai_config"

    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String(500), nullable=False)
    base_url = Column(String(500))
    model = Column(String(100))
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<AIConfig {self.model}>"


class TaskRecord(Base):
    """任务记录模型 - 记录所有用户操作历史（同步/异步）"""
    __tablename__ = "task_records"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), nullable=False)  # upload/cleaning/ml/feature_engineering/data_analysis/data_mining/ai
    user_id = Column(Integer, nullable=False)
    dataset_id = Column(Integer)
    params = Column(JSON)
    status = Column(String(20), default="pending")  # pending/running/success/failed/cancelled
    result_summary = Column(JSON)
    error_message = Column(Text)
    execution_time = Column(Integer)  # 执行时间（毫秒）
    # v3 新增：Celery 任务ID（异步任务取消时反查）和失败原因分类
    celery_task_id = Column(String(255), nullable=True)
    failure_category = Column(String(30), nullable=True)  # param_error/data_error/system_error/timeout/network_error/unknown
    created_at = Column(DateTime, default=shanghai_now)
    completed_at = Column(DateTime)

    def __repr__(self):
        return f"<TaskRecord {self.task_type}/{self.status}>"


class AIMessage(Base):
    """AI对话消息模型 - 单条消息存储（替代 conversation JSON 数组）"""
    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, index=True)  # 关联 ai_conversations.id
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    context_items = Column(JSON)  # 本轮注入的上下文项 ID 列表
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<AIMessage {self.role}/{self.conversation_id}>"


class AIConversationContext(Base):
    """AI会话上下文关联模型 - 持久化用户选过的上下文项"""
    __tablename__ = "ai_conversation_contexts"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, index=True)  # 关联 ai_conversations.id
    item_type = Column(String(20), nullable=False)  # dataset / operation
    ref_id = Column(Integer, nullable=False)  # dataset_id 或 task_record_id
    artifact_type = Column(String(50))  # 产物类型
    added_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<AIConversationContext {self.item_type}/{self.ref_id}>"


class DataSourceConnection(Base):
    """远程数据库连接模型"""
    __tablename__ = "datasource_connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    db_type = Column(String(20), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    database = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    extra_params = Column(String(500))
    created_at = Column(DateTime, default=shanghai_now)
    updated_at = Column(DateTime, default=shanghai_now)


class AppConfig(Base):
    """应用配置键值对表（全服务共用）

    存储加密密钥等全局配置项，通过 key 唯一标识。
    不依赖环境变量，服务重启不丢失。
    """
    __tablename__ = "app_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=shanghai_now)


class SupportMessage(Base):
    """用户联系管理员申请（无需登录，登录页/联系管理员页提交）

    category:
        - restore_dataset: 恢复永久删除数据集
        - unlock: 解锁账户
        - error_report: 系统错误上报
    """
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(30), nullable=False)  # restore_dataset/unlock/error_report
    username = Column(String(100))  # 申请人用户名（可选）
    contact = Column(String(200))  # 联系方式（邮箱/手机，解锁必填）
    content = Column(JSON)  # 表单内容：dataset_name/description/steps 等
    attachment_path = Column(String)  # 截图 MinIO 路径（错误上报可选）
    attachment_name = Column(String)  # 截图原始文件名
    client_ip = Column(String(50))  # 提交 IP（频率限制与溯源）
    status = Column(String(20), default="pending", index=True)  # pending/done
    admin_note = Column(String(500))  # 管理员处理备注
    admin_id = Column(Integer)  # 处理管理员ID
    processed_at = Column(DateTime)  # 处理完成时间
    created_at = Column(DateTime, default=shanghai_now)

    def __repr__(self):
        return f"<SupportMessage {self.category}/{self.status}>"


class CacheStatsHourly(Base):
    """缓存命中统计小时归档（2026-08-15 新增）

    由后台线程每分钟将 cache_manager 的进程内小时采样 upsert 到本表，
    实现命中历史持久化（服务重启不丢失），供管理端缓存命中率历史趋势展示。
    hour 格式：本地时间 "YYYYMMDDHH"，唯一键。
    """
    __tablename__ = "cache_stats_hourly"

    id = Column(Integer, primary_key=True, index=True)
    hour = Column(String(10), unique=True, index=True, nullable=False)  # "YYYYMMDDHH"（本地时间）
    hits = Column(Integer, default=0)  # 该小时命中次数
    misses = Column(Integer, default=0)  # 该小时未命中次数
    hit_rate = Column(Integer, default=0)  # 命中率（0-100 整数，避免浮点）
    total_keys = Column(Integer, default=0)  # 该小时应用缓存键总数（快照）
    memory_bytes = Column(Integer, default=0)  # 该小时内存占用字节（快照）
    updated_at = Column(DateTime, default=shanghai_now, onupdate=shanghai_now)

    def __repr__(self):
        return f"<CacheStatsHourly {self.hour} hits={self.hits} misses={self.misses}>"


class LogRecord(Base):
    """日志入库记录（2026-08-15 新增）

    仅持久化 ERROR/WARNING 级别的关键日志（由 logger.py 异步批量写入），
    供管理端"运行日志-统计概览"做错误趋势/级别分布/Top 错误分析；
    大量 INFO 级 API 日志仍保留在文件系统轮转，避免数据库膨胀。
    """
    __tablename__ = "log_records"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False, index=True)  # ERROR / WARNING
    module = Column(String(20), default="system", index=True)  # api/error/system
    message = Column(Text, nullable=False)  # 日志消息内容
    traceback = Column(Text, nullable=True)  # 异常堆栈（仅 ERROR 带堆栈时有）
    created_at = Column(DateTime, default=shanghai_now, index=True)

    def __repr__(self):
        return f"<LogRecord {self.level}/{self.module} @{self.created_at}>"
