"""
异步任务管理器
支持 Celery 异步执行，Celery 不可用时使用同步执行

架构说明：
- 模块级 celery 实例（下方 `celery` 变量）是 Worker 启动时使用的入口
  Worker 通过 `celery -A app.services.task_manager worker` 启动
- TaskManager._celery 引用同一个模块级实例，确保业务代码注册的任务
  与 Worker 监听的任务在同一个 Celery 注册表中
- include 参数指定 Worker 启动时需要导入的 api 模块，
  触发 @task_manager.register_task 装饰器执行，完成任务注册
"""
import time
import traceback
from typing import Optional, Callable, Any, Dict
from app.config import settings


# 业务模块列表：Worker 启动时需导入这些模块以触发 @task_manager.register_task 装饰器
# 新增异步业务模块时，在此列表追加模块路径即可，无需修改其他代码
_CELERY_INCLUDE_MODULES = [
    'app.api.cleaning',
    'app.api.data_analysis',
    'app.api.data_mining',
    'app.api.feature_engineering',
    'app.api.ml',
    'app.services.clickhouse_service',
]


class TaskManager:
    """
    任务管理器
    优先使用 Celery 异步执行，不可用时使用同步执行
    """

    def __init__(self):
        self._celery = None
        self._celery_available = False
        # 任务类型与处理函数的映射表，供 retry_task 在重试时查找原任务对应的业务函数。
        # 业务模块在启动时通过 register_task_handler 注册，避免重试逻辑硬编码各业务函数。
        self._task_registry: Dict[str, Callable] = {}

        if settings.CELERY_ENABLED:
            self._init_celery()

    def _init_celery(self):
        """初始化 Celery

        引用模块级 celery 实例（而非创建新实例），确保 TaskManager 注册的任务
        与 Worker 监听的任务在同一个 Celery 注册表中。否则会导致 Worker
        收到任务消息后报 NotRegistered 错误。

        所有配置从 settings 读取（config.py 收口），避免硬编码。
        修改超时/并发只需改 .env，无需改代码。
        """
        try:
            # 引用模块级 celery 实例，确保 Worker 和 TaskManager 使用同一注册表
            # 模块级 celery 在本函数调用前已创建（见文件末尾）
            self._celery = celery
            self._celery.conf.result_backend = settings.CELERY_RESULT_BACKEND
            # 任务时间限制(防止 MLP 等慢算法卡死 worker 导致全队列堵塞)
            # task_time_limit:硬限制,超时后 worker 强制终止任务进程(秒)
            # task_soft_time_limit:软限制,超时后向任务抛 SoftTimeLimitExceeded(秒)
            # worker_prefetch_multiplier=1:每次只预取 1 个任务,避免长任务占用预取槽位导致后续任务排队
            # 所有值从 config.py 读取，支持环境变量调整
            self._celery.conf.task_time_limit = settings.CELERY_TASK_TIME_LIMIT
            self._celery.conf.task_soft_time_limit = settings.CELERY_TASK_SOFT_TIME_LIMIT
            self._celery.conf.worker_prefetch_multiplier = settings.CELERY_WORKER_PREFETCH_MULTIPLIER
            self._celery_available = True
            print("✅ Celery 异步任务已启用")
        except Exception as e:
            print(f"⚠️ Celery 初始化失败，使用同步执行: {e}")
            self._celery_available = False

    def is_async_available(self) -> bool:
        """检查异步任务是否可用（Celery 已初始化且有活跃 Worker）

        仅检查 Celery 实例是否初始化成功是不够的：Redis broker 仍在运行时，
        _celery_available 会保持 True，即使 Worker 已停止。此时路由层的 503 检查
        会被跳过，run_task 内部检测到无活跃 Worker 后抛出 RuntimeError，
        导致返回 500 而非预期的 503。因此这里同时通过 ping 探测 Worker 是否在线。

        性能影响：ping 超时 1 秒，仅在提交异步任务（≥1万行）时调用，
        不影响常规请求。
        """
        if not self._celery_available:
            return False
        return self._check_worker_alive()

    def _check_worker_alive(self) -> bool:
        """
        检测是否有活跃的 Celery Worker
        通过 inspect.ping 探测，超时 1 秒内无响应则认为 Worker 不可用
        """
        if not self._celery_available or self._celery is None:
            return False
        try:
            inspect = self._celery.control.inspect(timeout=1)
            result = inspect.ping()
            # result 为 {worker_name: {'ok': 'pong'}} 字典，空则无活跃 Worker
            return bool(result)
        except Exception:
            return False

    def run_task(self, task_func: Callable, *args, no_degrade: bool = False, **kwargs) -> Dict[str, Any]:
        """
        运行任务（自动选择同步或异步）

        优先通过 Celery 异步执行，若 Worker 不可达则使用同步执行。
        当 no_degrade=True 时，Worker 不可达不会降级到同步执行，而是抛出异常，
        确保大数据集（≥1万行）任务必须异步执行，防止同步执行卡死 API 进程。

        Args:
            task_func: 任务函数
            *args: 任务位置参数
            no_degrade: 是否禁止降级到同步执行（默认 False，允许降级）
            **kwargs: 任务关键字参数（不会传给 task_func 的 no_degrade 已被显式提取）

        Returns:
            任务结果或任务ID

        Raises:
            RuntimeError: 当 no_degrade=True 且 Celery 不可用或 Worker 不可达时
        """
        if self._celery_available:
            if not self._check_worker_alive():
                if no_degrade:
                    # 禁止降级：Worker 不可达时直接报错，不 fallback 到同步
                    # 防止大数据集同步执行卡死 API 进程
                    raise RuntimeError("无活跃 Celery Worker，且任务配置为不允许降级到同步执行（no_degrade=True）")
                print("⚠️ 无活跃 Celery Worker，使用同步执行")
                return self._run_sync(task_func, *args, **kwargs)
            try:
                # 获取任务名：优先使用 Celery Task 对象的 name 属性
                # register_task 装饰器显式指定了 name=完整路径，所以 task.name 就是完整路径
                # 对于非 Celery 场景（同步执行），fallback 到 __module__.__name__
                if hasattr(task_func, 'name'):
                    full_task_name = task_func.name
                else:
                    full_task_name = f"{task_func.__module__}.{task_func.__name__}"
                task = self._celery.send_task(full_task_name, args=args, kwargs=kwargs)
                return {
                    "status": "queued",
                    "task_id": task.id,
                    "message": "任务已提交到队列"
                }
            except Exception as e:
                if no_degrade:
                    raise RuntimeError(f"Celery 提交失败，且任务配置为不允许降级: {e}")
                print(f"⚠️ Celery 提交失败，使用同步执行: {e}")
                return self._run_sync(task_func, *args, **kwargs)
        else:
            if no_degrade:
                raise RuntimeError("Celery 未启用，且任务配置为不允许降级到同步执行（no_degrade=True）")
            return self._run_sync(task_func, *args, **kwargs)

    def _run_sync(self, task_func: Callable, *args, **kwargs) -> Dict[str, Any]:
        """同步执行任务"""
        start_time = time.time()
        try:
            result = task_func(*args, **kwargs)
            return {
                "status": "completed",
                "result": result,
                "execution_time": round(time.time() - start_time, 2),
                "mode": "sync"
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "execution_time": round(time.time() - start_time, 2),
                "mode": "sync"
            }

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        取消异步任务

        对于 pending 状态的任务，revoke 会将其从队列中移除；
        对于 running 状态的任务，revoke(terminate=True) 会向 Worker 发送终止信号以中断执行。
        """
        if not self._celery_available:
            return {"status": "error", "message": "Celery 未启用，无法取消任务"}

        try:
            # terminate=True 确保正在执行的任务也会被强制终止，而非仅阻止未开始的任务
            self._celery.control.revoke(task_id, terminate=True)
            return {
                "status": "success",
                "message": "任务已取消",
                "task_id": task_id
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _adapt_retry_params(self, task_type: str, original_record, params: dict) -> Optional[Dict[str, Any]]:
        """将 TaskRecord.params（任务元数据）适配为处理函数所需的业务参数

        params 存储的是用于前端展示的元数据（operation/dataset_name/algorithm 等），
        而处理函数需要的是业务参数（task_record_id/user_id/dataset_id/config/pipeline 等）。
        重试时必须从 params 中提取/重建业务参数，否则直接 **params 解包会导致 TypeError。

        Returns:
            适配后的参数字典（不含 task_record_id，由 retry_task 注入）；
            返回 None 表示该 operation 不支持重试（如 export/test_evaluate 等同步操作）。
        """
        operation = params.get("operation", "")
        user_id = original_record.user_id
        dataset_id = original_record.dataset_id

        if task_type == "cleaning":
            # 仅 execute_clean / save_clean_result 可重试，contract_config/problem_strategy 不可
            if operation not in ("execute_clean", "save_clean_result"):
                return None
            config = params.get("config", {}) or {}
            # config 在问题清单模式下是 {pipeline, problem_strategies}，管道模式下是 pipeline 列表
            if isinstance(config, dict):
                pipeline = config.get("pipeline") or []
                problem_strategies = config.get("problem_strategies")
            else:
                pipeline = config or []
                problem_strategies = None
            return {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "pipeline": pipeline,
                "contract": params.get("contract", {}) or {},
                "force": params.get("force", False),
                "problem_strategies": problem_strategies,
                "save_result": params.get("save_confirmed", False),
            }

        if task_type == "ml_training":
            if operation != "train":
                return None
            inner = params.get("params", {}) or {}
            return {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "config": {
                    "dataset_id": dataset_id,
                    "target_column": inner.get("target_column"),
                    "feature_columns": inner.get("feature_columns", []),
                    "task_type": inner.get("task_type", "classification"),
                    "algorithm": params.get("algorithm", "random_forest"),
                    "test_size": inner.get("test_size", 0.2),
                    "cv_folds": inner.get("cv_folds", 5),
                    "auto_tune": inner.get("auto_tune", False),
                    "tune_method": inner.get("tune_method", "random"),
                    # 重试时恢复随机种子与自定义超参，保证结果可复现、调参空间不丢失（修复）
                    "random_seed": inner.get("random_seed", 42),
                    "hyperparams": inner.get("hyperparams", {}),
                },
                # 远程模式重试必须携带 remote_config，否则 _execute_training 无法加载数据（修复）
                "remote_config": params.get("remote_config"),
            }

        if task_type == "ml":
            # 仅 batch_predict 可重试，test_evaluate/export_report 不可
            if operation != "batch_predict":
                return None
            return {
                "user_id": user_id,
                "model_id": params.get("model_id"),
                "predict_dataset_id": params.get("predict_dataset_id"),
                # 远程模式重试必须携带 remote_config，否则 _execute_batch_predict 无法加载数据（修复）
                "remote_config": params.get("remote_config"),
            }

        if task_type == "data_mining":
            # 聚类/关联规则/序列模式均可重试（operation 以 save_ 前缀区分保存，同样可重试）
            if operation not in ("cluster", "save_cluster", "association", "save_association",
                                 "sequence", "save_sequence"):
                return None
            return {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "config": params.get("config", {}) or {},
                "is_remote": bool(params.get("is_remote", False)),
                "remote_config": params.get("remote_config"),
            }

        if task_type == "data_analysis":
            # 仅 generate_report 可重试，save_report 为同步保存不可重试
            if operation != "generate_report":
                return None
            return {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "config": params.get("config", {}) or {},
                "remote_config": params.get("remote_config"),
            }

        if task_type == "feature_engineering_construct":
            if operation != "construct_features":
                return None
            return {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "operations": params.get("operations", {}) or {},
                # 远程模式重试必须携带 remote_config，否则 _execute_*_features 无法加载数据（修复）
                "remote_config": params.get("remote_config"),
            }

        # feature_engineering_select/encode/scale/reduce 统一使用 config 参数
        if task_type in ("feature_engineering_select", "feature_engineering_encode",
                         "feature_engineering_scale", "feature_engineering_reduce"):
            expected_ops = {
                "feature_engineering_select": "select_features",
                "feature_engineering_encode": "encode_features",
                "feature_engineering_scale": "scale_features",
                "feature_engineering_reduce": "reduce_features",
            }
            if operation != expected_ops.get(task_type, ""):
                return None
            return {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "config": params.get("config", {}) or {},
                # 远程模式重试必须携带 remote_config，否则 _execute_*_features 无法加载数据（修复）
                "remote_config": params.get("remote_config"),
            }

        return None

    def retry_task(self, task_id: str, db_session) -> Dict[str, Any]:
        """
        手动重试失败任务

        复用原 TaskRecord（调用方 datasets.py 已将状态重置为 pending），
        从 params 中适配出处理函数所需的业务参数，重新提交到 Celery。
        原失败记录的 retry_history 保留以便追溯历史。

        重试始终使用 no_degrade=True（不降级到同步执行），原因：
        - datasets.py 在 retry_task 返回后会设置 running 状态并写入 celery_task_id，
          若降级为同步执行，处理函数已将状态更新为 completed/failed，
          随后的 running 覆盖会导致状态错乱。
        - 用户重试前应确保 Celery 可用，否则返回错误由调用方回滚为 failed。
        """
        if not self._celery_available:
            return {"status": "error", "message": "Celery 未启用，无法重试任务"}

        try:
            from app.models import TaskRecord
            # 从数据库查询原任务记录，用于复用原任务参数
            original_record = db_session.query(TaskRecord).filter(TaskRecord.id == task_id).first()
            if not original_record:
                return {"status": "error", "message": "原任务记录不存在"}

            task_type = original_record.task_type
            # params 是 JSON 字段，存储原任务元数据（operation/dataset_name 等）
            params = original_record.params or {}

            # 根据 task_type 查找业务模块注册的处理函数，避免重试逻辑硬编码各业务函数
            handler = self._task_registry.get(task_type)
            if not handler:
                return {"status": "error", "message": f"未注册任务类型: {task_type}，无法重试"}

            # 适配参数：从 params（元数据）提取 handler 所需的业务参数
            adapted = self._adapt_retry_params(task_type, original_record, params)
            if adapted is None:
                operation = params.get("operation", "未知")
                return {"status": "error", "message": f"任务操作「{operation}」不支持重试"}

            # 注入 task_record_id（复用原记录，处理函数通过它上报进度）
            adapted["task_record_id"] = int(task_id)

            # 重试不降级：Celery 不可用时返回错误，避免同步执行导致状态覆盖
            result = self.run_task(handler, no_degrade=True, **adapted)
            new_task_id = result.get("task_id", "")

            return {
                "status": "queued",
                "task_id": new_task_id,
                "message": "任务已重新提交",
                "original_task_id": task_id
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def register_task(self, func: Callable) -> Callable:
        """
        装饰器：注册任务函数

        显式指定任务名为完整路径（module.function_name），
        确保 send_task 提交的任务名与 Worker 注册的任务名一致。
        如果不指定 name，Celery 会自动使用完整路径，但 @task 装饰器
        返回的 Promise 对象的 __module__ 会变成 celery.local，
        导致 run_task 中构造的任务名不匹配。

        使用示例:
            @task_manager.register_task
            def train_model(dataset_id: int):
                # 训练模型逻辑
                pass
        """
        if self._celery_available:
            # 显式指定任务名为完整路径，确保与 send_task 使用的名称一致
            full_name = f"{func.__module__}.{func.__name__}"
            return self._celery.task(name=full_name)(func)
        else:
            # 直接返回原函数
            return func

    def register_task_handler(self, task_type: str, handler: Callable) -> None:
        """
        注册任务处理函数

        业务模块在启动时调用此方法，将 task_type 与对应的处理函数关联，
        供 retry_task 在重试时根据原任务的 task_type 找到对应的业务函数。
        """
        self._task_registry[task_type] = handler

    def is_task_type_retryable(self, task_type: str) -> bool:
        """判断 task_type 是否已注册处理函数，从而是否可重试

        retry_task 重试时通过 _task_registry 查找处理函数，
        未注册的 task_type（如 upload/dataset/data_mining 等同步任务）
        无法重试，前端不应显示重试按钮。

        与 is_retryable_failure 配合使用，综合判断 can_retry：
            can_retry = (status == 'failed'
                        and is_task_type_retryable(task_type)
                        and (not failure_category or is_retryable_failure(failure_category)))
        """
        return task_type in self._task_registry

    def get_stats(self) -> Dict[str, Any]:
        """获取任务统计信息

        pending/active 来自 Celery inspect 实时队列：
        - pending：已投递到 broker 但尚未被 worker 取走的任务数（reserved 之外、队列中等待）
        - active：worker 正在执行的任务数
        - completed/failed：Celery 不维护历史累计计数，统一返回 0，
          已完成/失败的任务数请从任务管理接口（数据库 TaskRecord）统计，避免误导。
        """
        if self._celery_available:
            try:
                inspect = self._celery.control.inspect()
                active_workers = inspect.active() or {}
                reserved_tasks = inspect.reserved() or {}
                # reserved 返回的是 worker 已领取但尚未开始执行的任务；pending 口径为队列中等待数
                active_count = sum(len(v) for v in active_workers.values() if v)
                reserved_count = sum(len(v) for v in reserved_tasks.values() if v)

                return {
                    "workers": len(active_workers),
                    "pending": reserved_count,
                    "active": active_count,
                    "completed": 0,
                    "failed": 0,
                    "mode": "async"
                }
            except Exception:
                return {
                    "workers": 0,
                    "pending": 0,
                    "active": 0,
                    "completed": 0,
                    "failed": 0,
                    "mode": "async"
                }
        else:
            return {
                "workers": 0,
                "pending": 0,
                "active": 0,
                "completed": 0,
                "failed": 0,
                "mode": "sync"
            }


# 模块级 Celery 实例（供 celery worker 使用）
# 所有配置从 settings 读取，与 TaskManager._init_celery 保持一致
# include 参数指定 Worker 启动时需导入的 api 模块，触发 @task_manager.register_task
# 装饰器执行，将任务函数注册到 Celery 注册表，否则 Worker 收到任务消息会报 NotRegistered
try:
    from celery import Celery
    celery = Celery(
        'data_insight',
        broker=settings.CELERY_BROKER_URL,
        include=_CELERY_INCLUDE_MODULES,
    )
    celery.conf.result_backend = settings.CELERY_RESULT_BACKEND
    # worker 进程同样配置时间限制,与 TaskManager._init_celery 保持一致
    celery.conf.task_time_limit = settings.CELERY_TASK_TIME_LIMIT
    celery.conf.task_soft_time_limit = settings.CELERY_TASK_SOFT_TIME_LIMIT
    celery.conf.worker_prefetch_multiplier = settings.CELERY_WORKER_PREFETCH_MULTIPLIER
except Exception:
    celery = None

# 全局任务管理器实例
task_manager = TaskManager()
