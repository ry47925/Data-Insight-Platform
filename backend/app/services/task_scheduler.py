"""任务调度器（后台线程）

定时扫描 pending 状态的任务，当用户有空闲执行额度时激活任务（提交到 Celery）。

设计要点：
1. 独立后台线程运行，不阻塞 FastAPI 主进程
2. 每 5 秒扫描一次 pending 任务，按创建时间 FIFO 激活
3. 激活前检查用户 running 任务数是否小于 MAX_RUNNING_PER_USER
4. 复用 task_manager.run_task 提交 Celery，更新 task_record 状态和 celery_task_id
5. 激活失败时标记任务为 failed，避免反复重试卡死队列
"""
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskScheduler:
    """任务调度器单例

    通过后台线程定时扫描 pending 任务并激活，实现任务排队等待机制。
    线程设为 daemon，随主进程退出自动终止。
    """

    def __init__(self):
        self._thread = None
        self._running = False
        self._interval = 5  # 调度间隔（秒），平衡响应速度和数据库负载
        self._last_persist = 0.0  # 上次缓存统计落库时间戳（每 60 秒一次）

    def start(self):
        """启动调度器线程"""
        if self._running:
            logger.warning("任务调度器已在运行，无需重复启动")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,  # daemon 线程，主进程退出时自动终止
            name="TaskScheduler"
        )
        self._thread.start()
        logger.info("✅ 任务调度器已启动（间隔 %ds）", self._interval)

    def stop(self):
        """停止调度器线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("任务调度器已停止")

    def _run(self):
        """调度器主循环"""
        # 延迟启动 3 秒，等待应用初始化完成（数据库连接、Celery 等）
        time.sleep(3)
        while self._running:
            try:
                self._schedule_once()
            except Exception as e:
                # 捕获异常避免循环退出，记录日志后继续
                logger.error(f"⚠️ 任务调度器异常: {e}", exc_info=True)
            # 缓存命中历史持久化：每 60 秒落库一次（独立于 Celery 状态）
            try:
                self._persist_cache_stats()
            except Exception as e:
                logger.error(f"⚠️ 缓存统计落库异常: {e}", exc_info=True)
            time.sleep(self._interval)

    def _persist_cache_stats(self):
        """将缓存进程内小时归档持久化到数据库（2026-08-15 新增，每 60 秒一次）"""
        now = time.time()
        if now - self._last_persist < 60:
            return
        self._last_persist = now
        from app.utils.db import SessionLocal
        from app.services.cache_manager import cache_manager

        db = SessionLocal()
        try:
            written = cache_manager.persist_hourly(db)
            if written > 0:
                logger.debug(f"🗄️ 缓存命中历史已落库（{written} 小时）")
        finally:
            db.close()

    def _schedule_once(self):
        """执行一次调度：扫描 pending 任务并尝试激活"""
        # 延迟导入避免循环依赖
        from app.utils.db import SessionLocal
        from app.utils.task_records import get_pending_tasks, count_user_tasks_by_status
        from app.config import settings
        from app.services.task_manager import task_manager

        # Celery 未启用时不调度，避免无效的数据库查询
        if not settings.CELERY_ENABLED:
            return

        db = SessionLocal()
        try:
            # 查询所有 pending 任务，按创建时间升序（FIFO）
            pending_tasks = get_pending_tasks(db, limit=20)

            if not pending_tasks:
                return

            activated_count = 0
            for record in pending_tasks:
                # 检查该用户当前 running 任务数是否已达上限
                running_count = count_user_tasks_by_status(
                    db, record.user_id, ["running"]
                )
                if running_count >= settings.MAX_RUNNING_PER_USER:
                    # 该用户执行额度已满，跳过（后续任务也可能属于同一用户，但需逐个检查）
                    continue

                # 尝试激活任务
                success = self._activate_task(db, record)
                if success:
                    activated_count += 1
                    # 激活成功后该用户的 running 数 +1，下一个同用户任务需重新检查
                    # 不同用户的任务可并行激活，不互相阻塞

            if activated_count > 0:
                logger.info(f"📋 调度器激活了 {activated_count} 个等待中的任务")

        finally:
            # 确保数据库连接归还连接池
            db.close()

    def _activate_task(self, db, record) -> bool:
        """激活单个 pending 任务：提交到 Celery 并更新状态

        Args:
            db: 数据库会话
            record: TaskRecord 对象（status=pending）

        Returns:
            True 表示激活成功，False 表示失败（已标记为 failed）
        """
        from app.services.task_manager import task_manager
        from app.utils.task_records import mark_task_running, update_task_record
        from app.models import TaskRecord

        try:
            # 复用 task_manager 的任务注册表，根据 task_type 查找处理函数
            handler = task_manager._task_registry.get(record.task_type)
            if not handler:
                # 未注册的任务类型无法激活，标记为 failed 避免反复重试
                update_task_record(
                    db=db,
                    record_id=record.id,
                    status="failed",
                    error_message=f"未注册任务类型: {record.task_type}，无法激活",
                    failure_category="system_error"
                )
                logger.error(f"❌ 任务 {record.id} 激活失败：未注册任务类型 {record.task_type}")
                return False

            # 使用原 params 重新提交到 Celery
            # retry_task 内部会调用 run_task(handler, **params)
            result = task_manager.retry_task(str(record.id), db)

            if result.get("status") == "error":
                # 提交失败，标记为 failed 并记录错误信息
                error_msg = result.get("message", "Celery 提交失败")
                update_task_record(
                    db=db,
                    record_id=record.id,
                    status="failed",
                    error_message=f"任务激活失败: {error_msg}",
                    failure_category="system_error"
                )
                logger.error(f"❌ 任务 {record.id} 激活失败: {error_msg}")
                return False

            # 提交成功，更新 celery_task_id（状态已由 retry_task 流程处理为 pending）
            # 这里需要确保状态更新为 running
            new_celery_id = result.get("task_id", "")
            if new_celery_id:
                # 重新查询记录，确保拿到最新状态
                db.refresh(record)
                record.status = "running"
                record.celery_task_id = new_celery_id
                record.error_message = None
                record.completed_at = None
                db.commit()
                logger.info(f"✅ 任务 {record.id} 已激活（celery_id={new_celery_id}）")
                return True

            return False

        except Exception as e:
            # 激活过程异常，标记为 failed 避免卡死队列
            update_task_record(
                db=db,
                record_id=record.id,
                status="failed",
                error_message=f"任务激活异常: {str(e)}",
                failure_category="system_error"
            )
            logger.error(f"❌ 任务 {record.id} 激活异常: {e}", exc_info=True)
            return False


# 全局单例
task_scheduler = TaskScheduler()
