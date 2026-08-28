from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.models import TaskRecord
from datetime import datetime
import json


def create_task_record(db: Session, task_type: str, user_id: int, dataset_id: int = None,
                       params: dict = None, initial_status: str = "running") -> TaskRecord:
    """创建任务记录

    Args:
        initial_status: 初始状态
            - "running"（默认）：同步任务，创建后立即执行
            - "pending"：异步任务，已提交 Celery 但未开始执行，等待 Worker 拉取
    """
    # 规范化无效/占位数据集 ID（不该再写入 0 这类脏引用，统一归为 NULL）
    if dataset_id is not None:
        try:
            if int(dataset_id) <= 0:
                dataset_id = None
        except (TypeError, ValueError):
            dataset_id = None
    record = TaskRecord(
        task_type=task_type,
        user_id=user_id,
        dataset_id=dataset_id,
        params=params,
        status=initial_status,
        created_at=datetime.utcnow()
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def mark_task_running(db: Session, record_id: int, celery_task_id: str = None) -> TaskRecord:
    """将任务状态从 pending 更新为 running

    由路由层在 Celery 提交成功后调用，写入 celery_task_id 并切换状态。
    用于异步任务提交后立即返回 task_id 给前端，前端通过轮询查询进度。

    Args:
        record_id: 任务记录ID
        celery_task_id: Celery 返回的任务ID，用于后续取消任务时反查
    """
    record = db.query(TaskRecord).filter(TaskRecord.id == record_id).first()
    if record:
        record.status = "running"
        if celery_task_id:
            record.celery_task_id = celery_task_id
        db.commit()
        db.refresh(record)
    return record


def _merge_result_summary(existing: dict, new: dict) -> dict:
    """深度合并两个 result_summary 字典

    用于增量更新进度信息，避免覆盖历史进度。
    合并规则：新字段覆盖同名旧字段，但保留旧字典中独有的内容；
    对于 progress_history 列表做追加合并以保留完整进度历史。
    """
    merged = dict(existing)  # 浅拷贝旧数据，保留独有字段
    for key, new_value in new.items():
        # progress_history 列表做追加合并，避免丢失历史进度记录
        if key == "progress_history" and isinstance(new_value, list) and isinstance(merged.get("progress_history"), list):
            merged["progress_history"] = merged["progress_history"] + new_value
        elif isinstance(new_value, dict) and isinstance(merged.get(key), dict):
            # 嵌套字典递归合并，保留旧字典中独有字段
            merged[key] = _merge_result_summary(merged[key], new_value)
        else:
            # 其他类型由新值覆盖
            merged[key] = new_value
    return merged


def update_task_record(db: Session, record_id: int, status: str, result_summary: dict = None,
                       error_message: str = None, execution_time: int = None, dataset_id: int = None,
                       failure_category: str = None) -> TaskRecord:
    """更新任务记录状态

    当传入的 result_summary 与数据库中已有 result_summary 均为字典时，
    采用深度合并以保留历史进度信息；其他情况保持原有覆盖行为。
    status/error_message/execution_time 等字段的更新逻辑保持不变。

    Args:
        failure_category: 失败原因分类（仅 status=failed 时有意义）
            - param_error: 参数错误（不可重试）
            - data_error: 数据问题（不可重试）
            - system_error: 系统临时故障（可重试）
            - timeout: 超时（可重试）
            - network_error: 网络问题（可重试）
            - unknown: 未知错误（可重试）
    """
    # 清理可能存在的脏事务状态：调用方（如 _execute_* 函数的 except 块）
    # 可能因前一个数据库操作失败导致 session 处于未回滚状态，直接查询会抛
    # SQLAlchemyError。rollback 在无未提交事务时是 no-op，不会影响正常流程。
    try:
        db.rollback()
    except Exception:
        pass
    record = db.query(TaskRecord).filter(TaskRecord.id == record_id).first()
    if record:
        record.status = status
        # 清理 result_summary 中不可 JSON 序列化的类型（如 Timestamp、numpy int64 等）
        # 远程模式下数据预览包含 datetime/Timestamp 对象，直接存入 JSON 列会抛 TypeError
        if result_summary is not None:
            result_summary = json.loads(json.dumps(result_summary, default=str, ensure_ascii=False))
        # 增量合并 result_summary，避免覆盖历史进度信息
        if result_summary is not None and isinstance(result_summary, dict) and isinstance(record.result_summary, dict):
            record.result_summary = _merge_result_summary(record.result_summary, result_summary)
        else:
            record.result_summary = result_summary
        # 最终保护：合并后的 record.result_summary 可能因旧值残留 Timestamp 等不可序列化对象
        # 在 commit 前统一清理，确保 psycopg2 的 JSON 编码不会失败
        if record.result_summary is not None:
            record.result_summary = json.loads(json.dumps(record.result_summary, default=str, ensure_ascii=False))
        record.error_message = error_message
        record.execution_time = execution_time
        record.completed_at = datetime.utcnow()
        if dataset_id:
            record.dataset_id = dataset_id
        # 失败分类仅在传入时写入，避免覆盖已有分类
        if failure_category:
            record.failure_category = failure_category
        # 事务保护：commit 失败时 rollback 恢复会话，避免后续操作全部失败
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    return record


def get_task_records(db: Session, user_id: int = None, task_type: str = None,
                     status: str = None, page: int = 1, per_page: int = 20,
                     dataset_id: int = None, task_type_prefix: str = None,
                     operation: str = None, date_from: datetime = None,
                     date_to: datetime = None, keyword: str = None,
                     task_type_in: list = None, module_source: str = None,
                     artifact_type: str = None, is_remote: bool = None,
                     exclude_operation: str = None, operation_in: list = None,
                     connection_id: int = None, table_name: str = None):
    """查询任务记录

    Args:
        dataset_id: 按数据集筛选，用于从数据管理跳转至操作历史时定位特定数据集的操作记录
        task_type_prefix: task_type 前缀匹配（如 'feature_engineering' 匹配 5 个子类型），
                         用于前端"操作大类"筛选特征工程时一次查出所有子类型
        operation: 按 params.operation 过滤（PostgreSQL JSON 查询），用于"具体操作"二级筛选
        date_from: 开始时间（含），按 created_at 过滤
        date_to: 结束时间（含），按 created_at 过滤
        keyword: 关键字搜索，匹配 params->>'dataset_name' 或 params->>'filename'
        task_type_in: task_type 多值匹配（如 ['ml','ml_training']），优先级低于 task_type，
                     高于 task_type_prefix，用于"机器学习"大类未选具体操作时一次查出多个子类型
        module_source: 按 params.module_source 过滤（PostgreSQL JSON 查询），
                      用于"文件上传"二级分类按模块筛选上传记录
        artifact_type: 按 params.artifact_type 过滤（PostgreSQL JSON 查询），
                      用于区分"上传数据集"和"预测数据集"等产物类型
        is_remote: 按数据来源筛选（PostgreSQL JSON 查询 params->>'is_remote'），
                  True=仅远程数据库操作，False=仅本地操作，None=不过滤
        exclude_operation: 排除指定 params.operation 的记录（PostgreSQL JSON 查询）。
                           用于特征工程主操作筛选时排除导出操作（export_selected/export_pool），
                           因为导出记录与主操作共用 task_type，仅靠 task_type 会混入。
        operation_in: 具体操作多值匹配（PostgreSQL JSON 查询 params->>'operation' OR 组合）。
                      用于数据挖掘结果恢复等场景一次匹配 cluster + save_cluster。
        connection_id: 远程记录按 params.remote_config->>'connection_id' 匹配（与 table_name 配合定位远程表）。
        table_name: 远程记录按 params.remote_config->>'table_name' 匹配。

    所有新增参数默认 None，保证现有调用无需改动。
    """
    query = db.query(TaskRecord).order_by(TaskRecord.created_at.desc())

    if user_id:
        query = query.filter(TaskRecord.user_id == user_id)
    # task_type 精确匹配（优先级最高）
    if task_type:
        query = query.filter(TaskRecord.task_type == task_type)
    elif task_type_in:
        # task_type 多值匹配：用于机器学习大类查 ml + ml_training
        from sqlalchemy import or_
        query = query.filter(TaskRecord.task_type.in_(task_type_in))
    elif task_type_prefix:
        # 前缀匹配：feature_engineering 匹配 feature_engineering_select 等 5 个子类型
        query = query.filter(TaskRecord.task_type.like(f'{task_type_prefix}_%'))
    if status:
        query = query.filter(TaskRecord.status == status)
    if dataset_id:
        query = query.filter(TaskRecord.dataset_id == dataset_id)
    if operation:
        # PostgreSQL JSON 查询 params->>'operation'，用 text() 兼容 SQLAlchemy 版本
        from sqlalchemy import text
        query = query.filter(text("params->>'operation' = :op_val").bindparams(op_val=operation))
    if operation_in:
        # 具体操作多值匹配（如 ['cluster', 'save_cluster']），用 OR 组合多个 params->>'operation' 条件
        from sqlalchemy import text
        op_conds = " OR ".join([f"params->>'operation' = :op_in_{i}" for i in range(len(operation_in))])
        op_binds = {f"op_in_{i}": v for i, v in enumerate(operation_in)}
        query = query.filter(text(op_conds).bindparams(**op_binds))
    if connection_id is not None:
        # 远程记录匹配：params.remote_config->>'connection_id'（JSON 数字以文本比较）
        from sqlalchemy import text
        query = query.filter(text(
            "params->'remote_config'->>'connection_id' = :cid"
        ).bindparams(cid=str(connection_id)))
    if table_name:
        # 远程记录匹配：params.remote_config->>'table_name'
        from sqlalchemy import text
        query = query.filter(text(
            "params->'remote_config'->>'table_name' = :tn"
        ).bindparams(tn=table_name))
    if exclude_operation:
        # 排除指定 operation 的记录（用于特征工程主操作筛选中剔除同 task_type 的导出操作）
        from sqlalchemy import text
        query = query.filter(text("params->>'operation' != :ex_op_val").bindparams(ex_op_val=exclude_operation))
    if module_source:
        # 按 params.module_source 过滤，用于文件上传二级分类按模块筛选
        from sqlalchemy import text
        query = query.filter(text("params->>'module_source' = :ms_val").bindparams(ms_val=module_source))
    if artifact_type:
        # 按 params.artifact_type 过滤，用于区分上传数据集/预测数据集等
        from sqlalchemy import text
        query = query.filter(text("params->>'artifact_type' = :at_val").bindparams(at_val=artifact_type))
    if is_remote is not None:
        # 按数据来源筛选：远程数据库操作 vs 本地操作
        # params->>'is_remote' 返回字符串 'true'/'false'
        # 注意：上传/数据治理/AI对话等本地操作的 params 中没有 is_remote 字段（返回 NULL），
        # 且所有远程执行路径均已写入 is_remote=true（已全量核对），因此"无字段=本地"成立。
        from sqlalchemy import text
        if is_remote:
            # 远程：仅匹配显式 is_remote=true 的记录
            query = query.filter(text("params->>'is_remote' = 'true'"))
        else:
            # 本地：匹配 is_remote=false 或没有该字段（NULL）的记录，兼容全部历史记录
            # 注意：整个 OR 条件必须用括号包裹，否则与前面其他筛选（operation/status 等）
            # 通过 AND 连接时，SQL 优先级导致 OR 短路所有本地记录，使其他筛选全部失效
            query = query.filter(text(
                "((params->>'is_remote') IS NULL OR params->>'is_remote' = 'false')"
            ))
    if date_from:
        query = query.filter(TaskRecord.created_at >= date_from)
    if date_to:
        query = query.filter(TaskRecord.created_at <= date_to)
    if keyword:
        # 关键字匹配 dataset_name 或 filename（二者均存在 params JSON 中）
        # 用 text() 写 PostgreSQL JSON 查询，避免 .astext 版本兼容问题
        from sqlalchemy import text, or_
        keyword_pattern = f'%{keyword}%'
        query = query.filter(text(
            "params->>'dataset_name' ILIKE :kw OR params->>'filename' ILIKE :kw"
        ).bindparams(kw=keyword_pattern))

    total = query.count()
    records = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "records": records,
        "total": total,
        "page": page,
        "per_page": per_page
    }


def update_task_progress(db: Session, task_id: int, stage: str, progress: int, message: str = "") -> None:
    """更新任务进度到 result_summary

    用于异步任务的阶段进度上报，result_summary 增量更新避免覆盖历史进度。

    注意：SQLAlchemy 的 JSON 字段不会自动检测"原地修改"（in-place mutation）。
    当 existing_summary 是 record.result_summary 的同一引用时，修改字典内容后
    重新赋值 record.result_summary = existing_summary 不会触发变更检测，
    导致 db.commit() 不生成 UPDATE 语句，进度丢失。
    必须调用 flag_modified 显式标记字段已修改。
    """
    # 查询失败时自动 rollback 重试：_execute_* 函数的 except 块中可能
    # session 处于脏状态，直接查询会抛 SQLAlchemyError
    try:
        record = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    except Exception:
        db.rollback()
        record = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    # 找不到记录时直接返回，避免影响主流程
    if not record:
        return

    # 读取现有 result_summary，为 None 或非字典时初始化为空字典
    existing_summary = record.result_summary if isinstance(record.result_summary, dict) else {}

    # 更新当前进度字段，便于前端实时展示任务状态
    existing_summary["current_stage"] = stage
    existing_summary["current_progress"] = progress
    existing_summary["current_message"] = message

    # 追加到 progress_history 列表，保留完整进度历史用于回溯排查
    progress_history = existing_summary.get("progress_history", [])
    if not isinstance(progress_history, list):
        progress_history = []
    progress_history.append({
        "stage": stage,
        "progress": progress,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })
    existing_summary["progress_history"] = progress_history

    record.result_summary = existing_summary
    # 显式标记 result_summary 已修改，否则 SQLAlchemy 不检测 JSON 字段的原地修改
    flag_modified(record, "result_summary")
    # 清理可能残留的不可序列化对象（Timestamp/NaT 等），防止 psycopg2 JSON 编码失败
    if record.result_summary is not None:
        record.result_summary = json.loads(json.dumps(record.result_summary, default=str, ensure_ascii=False))
    db.commit()


def classify_failure(error: Exception) -> str:
    """根据异常类型分类失败原因（兜底分类，优先在抛异常处主动传入 failure_category）

    分类优先级：pandas 异常类型 > data_error 消息关键字 > 异常类型精确匹配 > Celery 异常 > 消息关键字兜底

    注意：data_error 的消息关键字检查必须在 param_error 的类型检查之前，
    因为 ValueError 既可能是参数错误也可能是数据问题（如 ValueError("空数据")）。

    Returns:
        失败分类字符串，取值：
        - param_error: 参数错误（ValueError/TypeError/KeyError 等），不可重试
        - data_error: 数据问题（EmptyDataError/空数据 等），不可重试
        - system_error: 系统故障（数据库/内存/权限等），可重试
        - timeout: 超时（SoftTimeLimitExceeded/TimeoutError），可重试
        - network_error: 网络问题（连接拒绝/Redis/MinIO 不可达），可重试
        - unknown: 未知错误，允许重试
    """
    if error is None:
        return "unknown"

    # 1. 优先按 pandas 异常类型精确匹配
    try:
        import pandas.errors
        if isinstance(error, pandas.errors.EmptyDataError):
            return "data_error"
    except Exception:
        pass

    # 2. data_error 消息关键字优先于 param_error 类型检查
    # 原因：ValueError("空数据") 应归为 data_error 而非 param_error
    msg = str(error).lower()
    if any(kw in msg for kw in ["空数据", "无有效列", "缺失值过多", "no valid column", "empty"]):
        return "data_error"

    # 3. 按异常类型精确匹配
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError)):
        # 这些异常通常是参数或数据格式问题，重试也是同样参数，必须修改后重新执行
        return "param_error"

    if isinstance(error, TimeoutError):
        return "timeout"

    # 4. 按 Celery 异常类型匹配
    try:
        from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded
        if isinstance(error, (SoftTimeLimitExceeded, TimeLimitExceeded)):
            return "timeout"
    except ImportError:
        pass

    # 5. 兜底：按异常消息关键字匹配（粗粒度，可能误判，仅作最后兜底）
    if any(kw in msg for kw in ["timeout", "timed out"]):
        return "timeout"
    if any(kw in msg for kw in ["connection", "network", "minio", "redis", "refused", "unreachable"]):
        return "network_error"
    if any(kw in msg for kw in ["不支持", "无效", "不存在", "非法", "not supported", "invalid"]):
        return "param_error"
    if any(kw in msg for kw in ["celery", "database", "psycopg2", "sqlalchemy", "permission", "memory"]):
        return "system_error"
    return "unknown"


def count_user_tasks_by_status(db: Session, user_id: int, statuses: list,
                                exclude_task_id: int = None) -> int:
    """统计用户指定状态集合的任务数

    用于任务排队机制，分别统计 running 和 pending 状态的任务数，
    以判断是否可以立即执行或需要进入等待队列。

    Args:
        user_id: 用户ID
        statuses: 状态列表，如 ["running"] 或 ["running", "pending"]
        exclude_task_id: 需要排除的任务记录ID。并发检查通常在 create_task_record 之后调用，
                        此时刚创建的 task_record 已是 running/pending 状态会被统计进去，
                        导致实际可用并发数比配置值少 1。传入当前 task_record.id 可避免此问题。
    """
    query = db.query(TaskRecord).filter(
        TaskRecord.user_id == user_id,
        TaskRecord.status.in_(statuses)
    )
    if exclude_task_id is not None:
        query = query.filter(TaskRecord.id != exclude_task_id)
    return query.count()


def check_task_queue_capacity(db: Session, user_id: int, exclude_task_id: int = None) -> tuple:
    """检查用户任务队列容量，决定新任务是可以立即执行还是需要进入等待队列

    任务排队机制核心判断函数：
    1. 先检查 running+pending 总数是否超过总上限，超限直接拒绝（429）
    2. 再检查 running 数量是否达到上限，未达上限可立即执行，否则进入 pending 队列

    Args:
        user_id: 用户ID
        exclude_task_id: 排除的任务ID（通常是刚创建的 task_record），
                        避免当前任务自身被计入统计导致计数偏大

    Returns:
        (can_run_now, message)
        - can_run_now: True 表示可以立即提交 Celery 执行；False 表示需要进入 pending 队列等待
        - message: 状态说明，用于日志和返回给前端

    Raises:
        HTTPException(429): 当 running+pending 总数超过 MAX_RUNNING+MAX_PENDING 时
    """
    from fastapi import HTTPException
    from app.config import settings

    running_count = count_user_tasks_by_status(db, user_id, ["running"], exclude_task_id)
    pending_count = count_user_tasks_by_status(db, user_id, ["pending"], exclude_task_id)
    total_count = running_count + pending_count

    max_total = settings.MAX_RUNNING_PER_USER + settings.MAX_PENDING_PER_USER
    if total_count >= max_total:
        raise HTTPException(
            status_code=429,
            detail=f"任务总数超限（当前 {total_count} 个，上限 {max_total} 个："
                   f"{settings.MAX_RUNNING_PER_USER} 个执行中 + "
                   f"{settings.MAX_PENDING_PER_USER} 个等待中），"
                   f"请等待现有任务完成或取消部分任务后再试"
        )

    if running_count < settings.MAX_RUNNING_PER_USER:
        return True, f"立即执行（当前 running={running_count}，pending={pending_count}）"
    else:
        return False, f"进入等待队列（当前 running={running_count}，pending={pending_count}）"


def get_pending_tasks(db: Session, limit: int = 10) -> list:
    """查询所有 pending 状态的任务，按创建时间升序排列

    用于任务调度器定时扫描等待队列，先提交的任务先被激活执行（FIFO）。

    Args:
        limit: 单次查询上限，避免任务堆积时单次扫描过多记录
    """
    return db.query(TaskRecord).filter(
        TaskRecord.status == "pending"
    ).order_by(TaskRecord.created_at.asc()).limit(limit).all()
