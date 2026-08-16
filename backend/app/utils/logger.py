"""
日志系统配置模块

提供三类日志记录能力（task 日志已移除：任务执行信息由 TaskRecord 数据库表记录，避免冗余）：
- api: API访问日志（文件轮转）
- error: 错误日志（文件轮转 + ERROR 入库）
- system: 系统日志（文件轮转 + WARNING/ERROR 入库）

持久化策略（2026-08-15 重构）：
- 大量 INFO 级日志保留在文件系统（按天轮转 + 单文件 50MB 上限 + 保留 30 份）
- ERROR/WARNING 级别的关键日志由 DbLogHandler 异步入队，后台线程批量写入 log_records 表，
  供管理端"运行日志-统计概览"做错误趋势/级别分布/Top 错误分析，不阻塞主流程
"""

import os
import logging
import queue
import threading
import traceback as _traceback
from logging.handlers import TimedRotatingFileHandler

# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")

# 确保日志目录存在
os.makedirs(LOG_DIR, exist_ok=True)

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 单文件大小上限：超过后立即轮转（防止某天异常大量日志撑爆单个文件）
MAX_LOG_FILE_BYTES = 50 * 1024 * 1024

# 各日志记录器的配置（task 已移除）
_LOG_CONFIGS = {
    "api": {
        "filename": "api.log",
        "level": logging.INFO,
    },
    "error": {
        "filename": "error.log",
        "level": logging.ERROR,
    },
    "system": {
        "filename": "system.log",
        "level": logging.INFO,
    },
}

# 缓存已创建的日志记录器
_loggers = {}

# ===== 数据库异步写库（ERROR/WARNING 入库） =====
_db_queue = queue.Queue(maxsize=1000)  # 队列满时丢弃新记录，保护主流程内存
_db_thread = None
_db_lock = threading.Lock()


class SizedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """按天轮转 + 单文件大小上限（超过 maxBytes 立即轮转）"""

    def __init__(self, filename, when="midnight", interval=1,
                 backupCount=30, maxBytes=MAX_LOG_FILE_BYTES, encoding="utf-8"):
        self.maxBytes = maxBytes
        super().__init__(filename, when=when, interval=interval,
                         backupCount=backupCount, encoding=encoding)

    def shouldRollover(self, record):
        roll = super().shouldRollover(record)
        if not roll and self.maxBytes > 0 and self.stream:
            try:
                self.stream.seek(0, 2)
                size = self.stream.tell()
            except (AttributeError, OSError):
                return 0
            if size + len(record.getMessage()) > self.maxBytes:
                roll = 1
        return roll


class DbLogHandler(logging.Handler):
    """将 ERROR/WARNING 级别日志异步入队，由后台线程批量写入 log_records 表

    仅处理 WARNING 及以上级别；API 等大量 INFO 日志不入库。
    入队失败或队列满时静默丢弃，绝不阻塞主流程。
    """

    def emit(self, record):
        try:
            if record.levelno < logging.WARNING:
                return
            if _db_queue.full():
                return
            module = record.name[3:] if record.name.startswith("di_") else record.name
            traceback_text = None
            if record.exc_info:
                try:
                    # 不依赖 logging.Handler.formatException（不同 Python 版本存在性不一致）
                    traceback_text = "".join(_traceback.format_exception(*record.exc_info))
                except Exception:
                    traceback_text = None
            _db_queue.put({
                "level": record.levelname,
                "module": module,
                "message": record.getMessage(),
                "traceback": traceback_text,
            }, block=False)
        except Exception:
            pass


class _DbLogWriterThread(threading.Thread):
    """后台批量写库线程：从队列取 ERROR/WARNING 记录批量插入 log_records"""

    def run(self):
        while True:
            items = []
            try:
                item = _db_queue.get(timeout=1)
                items.append(item)
                while len(items) < 100:
                    try:
                        items.append(_db_queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                continue
            except Exception:
                continue
            if items:
                self._flush(items)

    @staticmethod
    def _flush(items):
        try:
            from app.utils.db import SessionLocal
            from app.models import LogRecord
            db = SessionLocal()
            try:
                db.bulk_save_objects([LogRecord(**item) for item in items])
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception:
            # 写库失败不影响主流程（日志功能降级为仅文件）
            pass


def _ensure_db_writer():
    """确保后台写库线程已启动（线程安全）"""
    global _db_thread
    with _db_lock:
        if _db_thread is None or not _db_thread.is_alive():
            _db_thread = _DbLogWriterThread(daemon=True)
            _db_thread.start()


def _create_logger(name, filename, level):
    """创建按天轮转 + 大小上限的文件日志记录器，并附加数据库写库 handler"""
    logger = logging.getLogger(f"di_{name}")
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    file_path = os.path.join(LOG_DIR, filename)
    handler = SizedTimedRotatingFileHandler(file_path)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(handler)

    # 附加数据库写库 handler（仅 ERROR/WARNING 入库）
    db_handler = DbLogHandler()
    db_handler.setLevel(logging.WARNING)
    logger.addHandler(db_handler)

    # 错误日志同时输出到控制台
    if name == "error":
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(console_handler)

    _ensure_db_writer()
    return logger


def get_logger(name="system"):
    """
    获取指定类型的日志记录器

    Args:
        name: 日志类型 (api/error/system)

    Returns:
        logging.Logger 实例
    """
    if name not in _LOG_CONFIGS:
        name = "system"

    if name not in _loggers:
        config = _LOG_CONFIGS[name]
        _loggers[name] = _create_logger(name, config["filename"], config["level"])

    return _loggers[name]


def log_api_request(method, path, status_code, duration_ms, client_ip="unknown"):
    """记录 API 请求（仅文件，不入库）"""
    logger = get_logger("api")
    logger.info(f"{method} {path} -> {status_code} | {duration_ms}ms | IP: {client_ip}")


def log_error(message, exc_info=None):
    """记录错误（文件 + ERROR 入库）"""
    logger = get_logger("error")
    logger.error(message, exc_info=exc_info)


def log_system(message, level="info"):
    """记录系统事件（文件 + WARNING/ERROR 入库）"""
    logger = get_logger("system")
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(message)


# 初始化时记录启动信息
log_system("日志系统初始化完成", level="info")
