import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings:

    PROJECT_NAME = "Data Insight Platform"
    PROJECT_VERSION = "2.0.0"

    DATABASE_URL = os.getenv("DATABASE_URL", "")

    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))

    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 120

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

    # 联系管理员申请频率限制（秒）：同 IP/用户名窗口内限 1 条；0 表示不限制（开发测试用）
    SUPPORT_RATE_LIMIT_SECONDS = int(os.getenv("SUPPORT_RATE_LIMIT_SECONDS", "600"))

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")

    REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_TTL = int(os.getenv("REDIS_TTL", "3600"))

    CLICKHOUSE_ENABLED = os.getenv("CLICKHOUSE_ENABLED", "false").lower() == "true"
    CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
    CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
    CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
    CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "analysis")

    # ===== ClickHouse 分析加速（一期，2026-08-15）=====
    # 数据同步开关：上传/导入的 raw_data 本地数据集自动同步到 ClickHouse，用于聚合分析加速
    CLICKHOUSE_SYNC_ENABLED = os.getenv("CLICKHOUSE_SYNC_ENABLED", "true").lower() == "true"
    # 启用 ClickHouse 加速的最小行数：低于此阈值直接走 pandas（小表 pandas 更快，避免无谓同步）
    CLICKHOUSE_MIN_ROWS = int(os.getenv("CLICKHOUSE_MIN_ROWS", "10000"))
    # 查询超时（秒）：超时视为 ClickHouse 不可用，自动降级 pandas，绝不阻塞请求
    CLICKHOUSE_QUERY_TIMEOUT = int(os.getenv("CLICKHOUSE_QUERY_TIMEOUT", "5"))
    # 同步分块行数：每批写入的行数，控制大表同步的内存峰值
    CLICKHOUSE_SYNC_BATCH = int(os.getenv("CLICKHOUSE_SYNC_BATCH", "50000"))

    # 本次 Celery 演进后必须启用 Celery，基础设施级降级保留但业务代码不降级
    # 已接入 ML 训练/清洗/特征工程异步化
    CELERY_ENABLED = os.getenv("CELERY_ENABLED", "true").lower() == "true"
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

    # ===== 异步任务配置收口（v3 新增）=====
    # 所有 Celery 相关参数统一从环境变量读取，避免在 task_manager.py / docker-compose.yml 中硬编码
    # 修改上限只需改 .env，无需改代码，方便开发/生产环境差异化配置

    # 异步触发阈值：数据集行数 >= 此值时走异步（Celery），否则同步执行
    # 开发阶段可用较小值测试异步链路，生产环境建议保持 10000
    ASYNC_THRESHOLD = int(os.getenv("ASYNC_THRESHOLD", "10000"))

    # 任务硬超时（秒）：超时后 Worker 强制终止任务进程，防止慢算法卡死队列
    CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800"))

    # 任务软超时（秒）：超时后向任务抛 SoftTimeLimitExceeded，任务可捕获后做清理
    CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "1500"))

    # Worker 预取倍数：每次只预取 1 个任务，避免长任务占用预取槽位导致后续任务排队
    CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))

    # 单用户并发上限：同一用户 running+pending 状态的异步任务数不得超过此值
    # 超限返回 HTTP 429，防止单用户提交过多任务占满 Worker 队列
    # 不同用户之间不隔离（共享 Worker 队列），但通过此上限防止单用户垄断资源
    # 总上限 = MAX_RUNNING_PER_USER(2) + MAX_PENDING_PER_USER(10) = 12
    # ===== 任务排队机制（v4 新增）=====
    # 将原来的单一并发上限拆分为两层：running（正在执行）+ pending（排队等待）
    # 用户可批量提交任务，超出 running 的进入 pending 队列等待调度器激活
    # 总上限 = MAX_RUNNING_PER_USER + MAX_PENDING_PER_USER

    # 每用户同时执行的任务数（提交给 Celery 的并发数）
    MAX_RUNNING_PER_USER = int(os.getenv("MAX_RUNNING_PER_USER", "2"))

    # 每用户等待中的任务数（排队队列长度）
    # 提升到 10 让用户可批量提交更多任务等待执行，无需等待前序任务完成
    # 总上限 = MAX_RUNNING_PER_USER(2) + MAX_PENDING_PER_USER(10) = 12
    MAX_PENDING_PER_USER = int(os.getenv("MAX_PENDING_PER_USER", "10"))

    # ===== AI 会话：单话题追问上限与会话有效期 =====
    # 追问次数上限：控制一个话题内允许连续追问的次数（软上限，避免无限 token 累积）
    # 会话有效期（分钟）：会话超过该时长无活动后自动过期，需开始新话题
    # 均可通过 .env 覆盖，方便开发/生产差异化
    AI_CONVERSATION_FOLLOWUP_MAX = int(os.getenv("AI_CONVERSATION_FOLLOWUP_MAX", "999"))
    AI_CONVERSATION_TTL_MINUTES = int(os.getenv("AI_CONVERSATION_TTL_MINUTES", "360"))

    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "data-insight")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

    def __init__(self):
        if not self.DATABASE_URL or self.DATABASE_URL.startswith("sqlite://"):
            raise ValueError("必须使用 PostgreSQL，SQLite 已废弃")


settings = Settings()


# ===== 数据集颜色色板（方案 A：按 dataset_id 派生，零存储）=====
# 命名方案：名称保持用户所起（不再追加时间戳/序号），区分靠颜色 + 创建时间 + #id
# 12 色高区分度、色盲友好（避免红绿邻近色对），同 id 恒同色
DATASET_PALETTE = [
    "#5B4CE0",  # 紫
    "#14B8A6",  # 青
    "#F25F4A",  # 珊瑚
    "#2E9DF0",  # 蓝
    "#8B5CF6",  # 紫罗兰
    "#F59E0B",  # 琥珀
    "#EC4899",  # 粉
    "#22C55E",  # 绿
    "#6366F1",  # 靛
    "#EAB308",  # 黄
    "#06B6D4",  # 青蓝
    "#F97316",  # 橙
]


def dataset_color(dataset_id: int) -> str:
    """按数据集 id 派生固定颜色（方案 A，无需数据库字段/迁移）"""
    if not dataset_id:
        return DATASET_PALETTE[0]
    return DATASET_PALETTE[dataset_id % len(DATASET_PALETTE)]
