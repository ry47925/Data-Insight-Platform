from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.models import Dataset, User
from app.schemas.dataset import DatasetCreate, DatasetUpdate, DatasetResponse, DatasetDataResponse, DataStatisticsResponse, _format_shanghai
from app.services.data_service import DataService, DataCleaningService
from app.services.storage_manager import storage_manager
from app.services.cache_manager import cache_manager
from app.utils.db import get_db
from app.utils.security import get_current_user
from app.utils.common import clean_dataset_name, build_product_name, clear_user_dataset_cache, get_dataset_or_404, MODULE_LABEL_MAP, validate_upload_file
from app.utils.task_records import create_task_record, update_task_record
from urllib.parse import quote
from app.config import settings
import os
import io
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# 中文字体配置：动态检测系统中可用的中文字体，避免 Docker 容器（仅装 fonts-wqy-zenhei）中文字体缺失导致 PDF 报告乱码
# 与 data_analysis.py 中 _get_chinese_font 保持一致逻辑，确保本地 Windows 与 Docker 容器均能正确渲染中文
def _get_chinese_font():
    """检测系统中可用的中文字体，返回字体名称列表。
    本地 Windows 通常有 SimHei/Microsoft YaHei；Docker 容器安装 fonts-wqy-zenhei 后有 WenQuanYi Zen Hei。
    若没有可用中文字体，则返回 ['DejaVu Sans'] 作为后备（中文会显示为方框）。"""
    preferred_fonts = [
        'SimHei', 'Microsoft YaHei', 'WenQuanYi Zen Hei',
        'Noto Sans CJK SC', 'Noto Sans SC', 'Source Han Sans SC',
        'PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS'
    ]
    available_fonts = set()
    for font in fm.fontManager.ttflist:
        available_fonts.add(font.name)
    result = [f for f in preferred_fonts if f in available_fonts]
    if not result:
        result = ['DejaVu Sans']
    return result


_CHINESE_FONTS = _get_chinese_font()
plt.rcParams['font.sans-serif'] = _CHINESE_FONTS
plt.rcParams['axes.unicode_minus'] = False
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# 上海时区（UTC+8），用于生成时间戳
SHANGHAI_TZ = timezone(timedelta(hours=8))

router = APIRouter()

def _get_cache_key(user_id: int) -> str:
    """生成数据集列表缓存键前缀"""
    return f"datasets:user:{user_id}:list"





@router.get("/")
async def list_datasets(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(100, ge=1, le=500, description="每页数量，最大500"),
    paginated: bool = Query(False, description="是否返回分页结构（true=分页字典，false=列表，兼容旧前端）"),
    skip: int = Query(None, description="已废弃，请使用 page/page_size"),
    limit: int = Query(None, description="已废弃，请使用 page/page_size"),
    module_source: str = Query(None, description="按模块来源筛选: cleaning/ml/ai/pipeline/upload"),
    artifact_type: str = Query(None, description="按产物类型筛选: raw_data/cleaning_result/ml_report/ai_report/pipeline_result"),
    root_dataset_id: int = Query(None, description="按根数据ID筛选，用于筛选同一原始数据的所有产物"),
    status: str = Query("active", description="按状态筛选: active/deleted/corrupted"),
    include_remote: bool = Query(False, description="是否包含远程数据库代理记录（管理端使用）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据集列表，支持按模块来源和产物类型筛选

    - paginated=false（默认）：返回列表（兼容旧前端）
    - paginated=true：返回 {datasets, total, page, page_size, total_pages}
    - 兼容旧参数 skip/limit（已废弃，内部转换为 page/page_size）
    """
    from sqlalchemy import or_

    # 兼容旧参数 skip/limit：如果传了旧参数，转换为 page/page_size
    if skip is not None or limit is not None:
        skip_val = skip or 0
        limit_val = limit or 100
        page = (skip_val // limit_val) + 1 if limit_val > 0 else 1
        page_size = limit_val

    cache_key = _get_cache_key(current_user.id)
    cache_key += f":{status}:{module_source or ''}:{artifact_type or ''}:{root_dataset_id or ''}:{page}:{page_size}:{paginated}"

    cached_data = cache_manager.get(cache_key)
    if cached_data:
        return cached_data

    query = db.query(Dataset)
    query = query.filter(Dataset.user_id == current_user.id)
    if status == "active":
        query = query.filter(or_(Dataset.status == "active", Dataset.status == None, Dataset.status == "corrupted"))
    else:
        query = query.filter(Dataset.status == status)
    # 默认排除远程数据库代理记录（file_path=NULL），管理端传 include_remote=true 则可查看
    if not include_remote:
        query = query.filter(
            (Dataset.source_type != "remote_db") | (Dataset.file_path.isnot(None))
        )
    # 默认隐藏特征工程"工作副本"（远程表动态新增列的内部存储，由后端自动维护）
    if not artifact_type:
        query = query.filter(Dataset.artifact_type != "feature_workcopy")
    if module_source:
        query = query.filter(Dataset.module_source == module_source)
    if artifact_type:
        query = query.filter(Dataset.artifact_type == artifact_type)
    if root_dataset_id is not None:
        query = query.filter(Dataset.root_dataset_id == root_dataset_id)

    # 先查总数，再分页查询
    total = query.count()
    start = (page - 1) * page_size
    datasets = query.order_by(Dataset.created_at.desc()).offset(start).limit(page_size).all()

    for ds in datasets:
        current_status = ds.status or "active"
        if current_status == "active" and ds.file_path and not storage_manager.exists(ds.file_path):
            ds.status = "corrupted"
    db.commit()

    result = [DatasetResponse.from_orm(ds).dict() for ds in datasets]

    if paginated:
        response = {
            "datasets": result,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size)
        }
    else:
        # 兼容旧前端：返回列表
        response = result

    cache_manager.set(cache_key, response, ttl=300)
    return response


def _trigger_ch_sync(dataset_id: int) -> None:
    """触发数据集同步到 ClickHouse 副本（失败不影响主流程，分析走 pandas 保底）"""
    try:
        from app.services.clickhouse_service import trigger_sync
        trigger_sync(dataset_id)
    except Exception as e:
        print(f"⚠️ ClickHouse 同步触发失败 dataset={dataset_id}: {e}")


def _cleanup_clickhouse_copy(dataset_id: int) -> None:
    """清理数据集在 ClickHouse 中的副本（删除/清空时调用，失败仅告警）"""
    try:
        from app.services.clickhouse_service import clickhouse_service
        clickhouse_service.drop_dataset(dataset_id)
    except Exception as e:
        print(f"⚠️ ClickHouse 副本清理失败 dataset={dataset_id}: {e}")


@router.post("/", response_model=DatasetResponse)
async def create_dataset(
    file: UploadFile = File(...),
    module_source: str = Query("upload", description="来源模块: upload/cleaning/ml/ai/feature_engineering/pipeline/batch_predict"),
    artifact_type: str = Query("raw_data", description="产物类型: raw_data/predict_data"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传文件，artifact_type和module_source由参数指定"""
    import time
    start_time = time.time()

    # 校验上传文件扩展名，前后端限制保持一致
    validate_upload_file(file)

    name = clean_dataset_name(file.filename)
    
    task_record = create_task_record(
        db=db,
        task_type="upload",
        user_id=current_user.id,
        params={"filename": name, "module_source": module_source, "artifact_type": artifact_type}
    )

    content = await file.read()

    object_name = f"uploads/user_{current_user.id}/{name}"
    file_path = storage_manager.save_bytes(object_name, content)

    data_service = DataService(db)
    try:
        df = data_service._load_from_file(file_path)
        schema = data_service.get_schema(df)
        row_count = len(df)
        data_preview = data_service.get_sample_data(df, 10)
    except Exception as e:
        storage_manager.delete(file_path)
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="failed",
            error_message=str(e),
            execution_time=execution_time,
            failure_category="data_error"
        )
        raise HTTPException(status_code=400, detail=f"无法解析文件: {str(e)}")

    file_size = len(content)
    new_dataset = Dataset(
        name=name,
        user_id=current_user.id,
        file_path=file_path,
        schema=schema,
        row_count=row_count,
        file_size=file_size,
        data_preview=str(data_preview[:5]),
        module_source=module_source,
        module_label=MODULE_LABEL_MAP.get(module_source, "原始数据"),
        artifact_type=artifact_type
    )
    db.add(new_dataset)
    db.commit()
    db.refresh(new_dataset)

    execution_time = int((time.time() - start_time) * 1000)
    update_task_record(
        db=db,
        record_id=task_record.id,
        status="success",
        dataset_id=new_dataset.id,
        result_summary={
            "dataset_id": new_dataset.id,
            "dataset_name": new_dataset.name,
            "row_count": new_dataset.row_count,
            "column_count": len(df.columns),
            "file_size": new_dataset.file_size
        },
        execution_time=execution_time
    )

    clear_user_dataset_cache(current_user.id)

    # 触发 ClickHouse 副本同步（仅 raw_data 且行数达阈值的数据集在任务内同步；失败不影响上传）
    _trigger_ch_sync(new_dataset.id)

    return new_dataset


# 别名路由：兼容前端 /datasets/upload 调用
@router.post("/upload", response_model=DatasetResponse)
async def upload_dataset_alias(
    file: UploadFile = File(...),
    module_source: str = Query("upload", description="来源模块"),
    artifact_type: str = Query("raw_data", description="产物类型"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传文件别名接口（兼容 /datasets/upload 路径）"""
    return await create_dataset(file=file, module_source=module_source, artifact_type=artifact_type, db=db, current_user=current_user)


@router.post("/record", response_model=DatasetResponse)
async def create_dataset_record(
    dataset: DatasetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建数据集记录（供各模块调用，JSON body）"""
    name = clean_dataset_name(dataset.name)

    file_size = None
    if dataset.file_path and storage_manager.exists(dataset.file_path):
        file_bytes = storage_manager.get_file_bytes(dataset.file_path)
        file_size = len(file_bytes)
    new_dataset = Dataset(
        name=name,
        user_id=current_user.id,  # 数据隔离：关联当前用户
        connection_id=dataset.connection_id,
        table_name=dataset.table_name,
        file_path=dataset.file_path,
        file_size=file_size,
        module_source=dataset.module_source,
        module_label=dataset.module_label,
        algorithm=dataset.algorithm,
        parent_id=dataset.parent_id,
        tags=dataset.tags,
        artifact_type=dataset.artifact_type,
        report_content=dataset.report_content
    )
    db.add(new_dataset)
    db.commit()
    db.refresh(new_dataset)
    return new_dataset


@router.put("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset(
    dataset_id: int,
    dataset_update: DatasetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """编辑数据集元数据（name, tags, remarks）"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 记录编辑前的值，用于操作历史详情展示变动信息
    old_name = dataset.name
    old_tags = dataset.tags
    old_remarks = dataset.remarks
    name_changed = False
    tags_changed = False
    remarks_changed = False

    if dataset_update.name is not None:
        # 命名方案（2026-08-13 起）：名称允许重复，不再做同类产物唯一性校验。
        # 同名数据集靠 dataset_id + 颜色 + 创建时间区分；用户编辑删除拼接内容（时间戳等）不再被拦截。
        dataset.name = dataset_update.name.strip()
        name_changed = True
    if dataset_update.tags is not None:
        dataset.tags = dataset_update.tags
        tags_changed = True
    if dataset_update.remarks is not None:
        dataset.remarks = dataset_update.remarks
        remarks_changed = True

    db.commit()
    db.refresh(dataset)

    # 记录编辑操作到操作历史（含标签和备注的变动详情）
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id, dataset_id=dataset_id,
        params={
            "operation": "edit_meta",
            "dataset_name": dataset.name,
            "dataset_id": dataset_id,
            "old_name": old_name if name_changed else None,
            "new_name": dataset.name if name_changed else None,
            "tags_updated": tags_changed,
            "remarks_updated": remarks_changed,
        }
    )
    # 构造变动详情，让用户在详情抽屉中能看到具体的旧值→新值
    changes_detail = {}
    if name_changed:
        changes_detail["名称"] = f"{old_name} → {dataset.name}"
    if tags_changed:
        changes_detail["标签"] = f"{old_tags or '空'} → {dataset.tags or '空'}"
    if remarks_changed:
        changes_detail["备注"] = f"{old_remarks or '空'} → {dataset.remarks or '空'}"

    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": 1,
                           "changed_fields": [field for field in ["名称", "标签", "备注"] if field in changes_detail],
                           "changes_detail": changes_detail,
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    return dataset


def _resolve_record_object(db: Session, record, params: dict):
    """解析操作历史记录的操作对象信息

    本地：优先 dataset_id 反查 Dataset.name，缺失时回退 params.dataset_name
    远程：params.dataset_name 即表名；按 params.remote_config.connection_id 反查连接名
    （连接可能已删除，查不到时返回 None，前端降级只显示表名）

    Returns:
        (dataset_name, remote_connection_name)
    """
    from app.models import DataSourceConnection
    params = params if isinstance(params, dict) else {}
    dataset_name = None
    if getattr(record, "dataset_id", None):
        ds = db.query(Dataset).filter(Dataset.id == record.dataset_id).first()
        if ds:
            dataset_name = ds.name
    if not dataset_name:
        dataset_name = params.get("dataset_name")
    remote_connection_name = None
    remote_config = params.get("remote_config")
    if isinstance(remote_config, dict) and remote_config.get("connection_id"):
        conn = db.query(DataSourceConnection).filter(
            DataSourceConnection.id == remote_config.get("connection_id")
        ).first()
        if conn:
            remote_connection_name = conn.name
    return dataset_name, remote_connection_name


@router.get("/task-records")
async def get_task_records(
    task_type: str = Query(None, description="任务类型过滤（精确匹配单个 task_type）"),
    task_type_prefix: str = Query(None, description="任务类型前缀匹配（如 feature_engineering 匹配 5 个子类型）"),
    task_type_in: list = Query(None, description="任务类型多值匹配（如 ml+ml_training），优先级低于 task_type 高于 prefix"),
    operation: str = Query(None, description="具体操作筛选（params.operation，如 soft_delete / batch_predict）"),
    exclude_operation: str = Query(None, description="排除指定具体操作（params.operation），用于特征工程主操作筛选中剔除导出操作"),
    operation_in: list = Query(None, description="具体操作多值匹配（params.operation OR 组合，如 cluster+save_cluster）"),
    status: str = Query(None, description="状态过滤"),
    dataset_id: int = Query(None, description="按数据集筛选，用于从数据管理跳转"),
    module_source: str = Query(None, description="按上传来源模块筛选（params.module_source，如 cleaning/ml/ai）"),
    artifact_type: str = Query(None, description="按产物类型筛选（params.artifact_type，如 raw_data/predict_data）"),
    is_remote: bool = Query(None, description="按数据来源筛选：true=仅远程数据库操作，false=仅本地操作"),
    connection_id: int = Query(None, description="远程记录按连接ID匹配（params.remote_config->>'connection_id'）"),
    table_name: str = Query(None, description="远程记录按表名匹配（params.remote_config->>'table_name'）"),
    date_from: str = Query(None, description="开始时间（含），ISO 8601 格式，如 2026-08-01T00:00:00"),
    date_to: str = Query(None, description="结束时间（含），ISO 8601 格式"),
    keyword: str = Query(None, description="关键字搜索（匹配数据集名称或文件名）"),
    page: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(None, description="每页数量（推荐使用，与全局分页参数统一）"),
    per_page: int = Query(20, description="已废弃，请使用 page_size"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前用户的操作历史记录

    支持两级筛选：
    - 一级（操作大类）：通过 task_type（单类型）/ task_type_in（多值）/ task_type_prefix（前缀匹配）
    - 二级（具体操作）：通过 operation（params.operation 字段）
    其他筛选：status / dataset_id / module_source / artifact_type / date_from / date_to / keyword
    """
    from app.utils.task_records import get_task_records as query_task_records
    from app.utils.task_labels import (
        get_task_type_label, get_operation_label, get_status_label,
        get_task_type_tag_type, label_result_summary, label_params, extract_operation,
        build_action_description,
        get_failure_category_label, get_failure_category_tag_type, is_retryable_failure,
    )
    from app.services.task_manager import task_manager
    from datetime import datetime as dt

    # 解析时间参数
    parsed_date_from = None
    parsed_date_to = None
    if date_from:
        try:
            parsed_date_from = dt.fromisoformat(date_from.replace('Z', '+00:00'))
        except ValueError:
            pass
    if date_to:
        try:
            parsed_date_to = dt.fromisoformat(date_to.replace('Z', '+00:00'))
        except ValueError:
            pass

    # 兼容 page_size 参数：优先使用 page_size，未传则回退到 per_page
    effective_page_size = page_size if page_size is not None else per_page

    result = query_task_records(
        db=db,
        user_id=current_user.id,
        task_type=task_type,
        task_type_prefix=task_type_prefix,
        task_type_in=task_type_in,
        operation=operation,
        exclude_operation=exclude_operation,
        operation_in=operation_in,
        status=status,
        page=page,
        per_page=effective_page_size,
        dataset_id=dataset_id,
        module_source=module_source,
        artifact_type=artifact_type,
        connection_id=connection_id,
        table_name=table_name,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        keyword=keyword,
        is_remote=is_remote,
    )
    
    records = []
    for record in result["records"]:
        record_params = record.params if isinstance(record.params, dict) else {}
        # 操作对象：本地反查数据集名；远程取表名 + 连接名
        dataset_name, remote_connection_name = _resolve_record_object(db, record, record_params)

        execution_time = record.execution_time
        # 提取 operation（二级分类，用于"具体操作"筛选与展示）
        record_operation = extract_operation(record.params)
        # 提取远程标识：params.is_remote 为 true 表示基于远程数据库执行
        record_is_remote = bool(record_params.get("is_remote"))
        records.append({
            "id": record.id,
            "task_type": record.task_type,
            "task_type_label": get_task_type_label(record.task_type),
            "task_type_tag_type": get_task_type_tag_type(record.task_type),
            "operation": record_operation,
            "operation_label": get_operation_label(record_operation) if record_operation else None,
            "is_remote": record_is_remote,
            "dataset_id": record.dataset_id,
            "dataset_name": dataset_name,
            "remote_connection_name": remote_connection_name,
            "action_description": build_action_description(
                task_type=record.task_type,
                operation=record_operation,
                params=record.params or {},
                result_summary=record.result_summary or {},
                status=record.status,
                dataset_name=dataset_name,
            ),
            "status": record.status,
            "status_label": get_status_label(record.status),
            # celery_task_id：用于列表页取消按钮直接调用取消接口，无需先查详情
            "celery_task_id": record.celery_task_id,
            # failure_category：失败原因分类，前端据此决定是否显示重试按钮
            "failure_category": record.failure_category,
            "failure_category_label": get_failure_category_label(record.failure_category),
            "failure_category_tag_type": get_failure_category_tag_type(record.failure_category),
            "is_retryable": is_retryable_failure(record.failure_category),
            # can_retry：综合判断是否可重试（status=failed + task_type 已注册 handler + failure_category 可重试）
            # 前端两处（GlobalTaskPanel / TaskHistory）统一使用此字段，避免硬编码 RETRYABLE_TASK_TYPES
            "can_retry": (
                record.status == "failed"
                and task_manager.is_task_type_retryable(record.task_type)
                and is_retryable_failure(record.failure_category)
            ),
            "execution_time": execution_time,
            "result_summary": record.result_summary,
            "result_summary_labeled": label_result_summary(record.result_summary),
            "params": record.params,
            "params_labeled": label_params(record.params),
            "error_message": record.error_message[:200] if record.error_message else None,
            "created_at": _format_shanghai(record.created_at) if record.created_at else None,
            "completed_at": _format_shanghai(record.completed_at) if record.completed_at else None
        })
    
    return {
        "records": records,
        "total": result["total"],
        "page": result["page"],
        "page_size": effective_page_size,
        "per_page": result["per_page"],  # 兼容旧前端
        "total_pages": max(1, (result["total"] + effective_page_size - 1) // effective_page_size)
    }


@router.get("/task-records/{record_id}")
async def get_single_task_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询单条任务记录（按 ID 精确查询，用于进度轮询）

    替代列表接口前端筛选方式，避免任务记录超过 50 条时找不到目标任务导致进度卡住。
    """
    from app.models import TaskRecord
    from app.utils.task_labels import (
        get_task_type_label, get_operation_label, get_status_label,
        label_result_summary, label_params, extract_operation,
        build_action_description,
        get_failure_category_label, get_failure_category_tag_type, is_retryable_failure,
    )
    from app.services.task_manager import task_manager

    record = db.query(TaskRecord).filter(
        TaskRecord.id == record_id,
        TaskRecord.user_id == current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="任务记录不存在")

    record_params = record.params if isinstance(record.params, dict) else {}
    dataset_name, remote_connection_name = _resolve_record_object(db, record, record_params)

    record_operation = extract_operation(record.params)

    return {
        "id": record.id,
        "task_type": record.task_type,
        "task_type_label": get_task_type_label(record.task_type),
        "operation": record_operation,
        "operation_label": get_operation_label(record_operation) if record_operation else None,
        "dataset_id": record.dataset_id,
        "dataset_name": dataset_name,
        "remote_connection_name": remote_connection_name,
        "action_description": build_action_description(
            task_type=record.task_type,
            operation=record_operation,
            params=record.params or {},
            result_summary=record.result_summary or {},
            status=record.status,
            dataset_name=dataset_name,
        ),
        "status": record.status,
        "status_label": get_status_label(record.status),
        # celery_task_id 和 failure_category 新增字段
        "celery_task_id": record.celery_task_id,
        "failure_category": record.failure_category,
        "failure_category_label": get_failure_category_label(record.failure_category),
        "failure_category_tag_type": get_failure_category_tag_type(record.failure_category),
        "is_retryable": is_retryable_failure(record.failure_category),
        # can_retry：综合判断是否可重试（与列表接口保持一致）
        "can_retry": (
            record.status == "failed"
            and task_manager.is_task_type_retryable(record.task_type)
            and is_retryable_failure(record.failure_category)
        ),
        "result_summary": record.result_summary,
        "result_summary_labeled": label_result_summary(record.result_summary),
        "params": record.params,
        "params_labeled": label_params(record.params),
        "error_message": record.error_message,
        "execution_time": record.execution_time,
        "created_at": _format_shanghai(record.created_at) if record.created_at else None,
        "completed_at": _format_shanghai(record.completed_at) if record.completed_at else None
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_async_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """取消异步任务

    参数 task_id 为 task_records 表主键 ID（即前端 taskRecordId）。
    流程：
    1. 查询 TaskRecord 验证归属当前用户且状态为 pending/running
    2. 通过 celery_task_id 调用 task_manager.cancel_task 终止 Celery 任务
    3. 更新 TaskRecord.status = 'cancelled'
    已取消的任务不可恢复，需重新提交。
    """
    from app.models import TaskRecord
    from app.services.task_manager import task_manager
    from datetime import datetime

    try:
        # 验证任务记录属于当前用户
        record = db.query(TaskRecord).filter(
            TaskRecord.id == task_id,
            TaskRecord.user_id == current_user.id
        ).first()
        if not record:
            return {"status": "error", "message": "任务记录不存在或无权操作"}

        # 仅 pending/running 状态可取消
        if record.status not in ("pending", "running"):
            return {"status": "error", "message": f"仅等待中/执行中的任务可取消，当前状态: {record.status}"}

        # 通过 celery_task_id 取消 Celery 任务
        if record.celery_task_id:
            result = task_manager.cancel_task(record.celery_task_id)
            if result.get("status") == "error":
                return {"status": "error", "message": result.get("message", "取消失败")}

        # 更新 TaskRecord 状态为 cancelled
        record.status = "cancelled"
        record.completed_at = datetime.utcnow()
        db.commit()

        return {"status": "success", "message": "任务已取消"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.post("/tasks/{task_id}/retry")
async def retry_async_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """重试失败的异步任务

    参数 task_id 为 task_records 表主键 ID（即前端 taskRecordId）。
    流程：
    1. 查询 TaskRecord 验证归属当前用户且 status='failed'
    2. 检查 failure_category 是否可重试（param_error/data_error 不可重试）
    3. 检查并发上限：若 running+pending 总数已达上限，返回 429 拒绝
    4. 若 running 未满：重置为 pending → 提交 Celery → 更新为 running
    5. 若 running 已满：仅重置为 pending，由调度器自动激活（排队等待）
    原失败记录保留不删除，便于追溯历史。
    """
    from app.models import TaskRecord
    from app.services.task_manager import task_manager
    from app.utils.task_labels import is_retryable_failure, get_failure_category_label
    from app.utils.task_records import check_task_queue_capacity

    try:
        # 验证任务记录属于当前用户
        record = db.query(TaskRecord).filter(
            TaskRecord.id == task_id,
            TaskRecord.user_id == current_user.id
        ).first()
        if not record:
            return {"status": "error", "message": "任务记录不存在或无权操作"}

        # 仅失败任务允许重试
        if record.status != "failed":
            return {"status": "error", "message": f"仅失败任务可重试，当前状态: {record.status}"}

        # 检查失败分类是否可重试
        if record.failure_category and not is_retryable_failure(record.failure_category):
            return {
                "status": "error",
                "message": f"失败原因「{get_failure_category_label(record.failure_category)}」不可重试，请修改参数或处理数据后重新执行"
            }

        # 检查并发上限：failed 状态不会被计入 running/pending 统计，无需 exclude_task_id
        # check_task_queue_capacity 在总上限超限时抛 HTTPException(429)
        can_run_now, queue_msg = check_task_queue_capacity(
            db, user_id=current_user.id, exclude_task_id=None
        )

        # 重置原记录状态为 pending，Celery 任务执行时通过原 params 中的
        # task_record_id 上报进度到同一条记录，前端刷新后可见状态变化
        record.status = "pending"
        record.error_message = None
        record.failure_category = None
        record.completed_at = None
        record.celery_task_id = None  # 清除旧 ID，pending 状态未提交 Celery，避免取消时误调 revoke
        # 重置进度信息，保留 retry 历史
        existing_summary = record.result_summary if isinstance(record.result_summary, dict) else {}
        retry_history = existing_summary.get("retry_history", [])
        retry_history.append({
            "previous_status": "failed",
            "previous_error": existing_summary.get("error", ""),
            "retry_time": datetime.utcnow().isoformat()
        })
        record.result_summary = {"retry_history": retry_history}
        db.commit()

        # 根据 running 额度决定立即提交 Celery 还是进入 pending 队列等待调度器激活
        if not can_run_now:
            # running 已满，任务保持 pending 状态，由调度器（每5秒扫描）自动激活
            return {
                "status": "pending",
                "task_record_id": task_id,
                "message": f"任务已加入等待队列，{queue_msg}"
            }

        # running 未满，立即提交 Celery 执行
        result = task_manager.retry_task(str(task_id), db)
        if result.get("status") == "error":
            # 重试提交失败时回滚状态为 failed
            record.status = "failed"
            db.commit()
            return {"status": "error", "message": result.get("message", "重试失败")}

        # 提交成功，更新 celery_task_id 并标记为 running
        new_celery_id = result.get("task_id", "")
        if new_celery_id:
            record.celery_task_id = new_celery_id
            record.status = "running"
            db.commit()

        return {
            "status": "queued",
            "task_id": new_celery_id,
            "task_record_id": task_id,
            "message": "任务已重新提交并开始执行"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取数据集详情"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return dataset


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """删除数据集

    处理逻辑分两种情况：
    1. 文件已损坏（status=corrupted 或文件在 MinIO 中不存在）：直接物理删除数据库记录和残留文件
    2. 文件正常：软删除，将 status 改为 deleted 并记录删除时间，数据进入回收站
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 删除保护：检查是否有依赖该数据集的运行中或等待中任务
    from app.models import TaskRecord
    from app.utils.task_labels import get_task_type_label
    running_tasks = db.query(TaskRecord).filter(
        TaskRecord.dataset_id == dataset_id,
        TaskRecord.user_id == current_user.id,
        TaskRecord.status.in_(["running", "pending"])
    ).all()
    if running_tasks:
        # operation_label 不是 TaskRecord 模型属性，使用 get_task_type_label 获取中文标签
        task_desc = "、".join([get_task_type_label(t.task_type) or t.task_type for t in running_tasks[:3]])
        raise HTTPException(
            status_code=409,
            detail=f"该数据集有 {len(running_tasks)} 个正在执行或等待中的任务（{task_desc}），"
                   f"请等待任务完成或先在任务面板取消任务后再删除"
        )

    # 判断文件是否已损坏：优先使用 status 字段，若 status 为 None/active 则直接检测文件
    is_corrupted = dataset.status == "corrupted"
    if not is_corrupted and dataset.file_path:
        if not storage_manager.exists(dataset.file_path):
            is_corrupted = True
            dataset.status = "corrupted"
            db.commit()
    
    if is_corrupted:
        # 损坏记录物理删除，记录到操作历史
        corrupted_name = dataset.name
        corrupted_artifact_type = dataset.artifact_type
        corrupted_file_size = dataset.file_size
        if dataset.file_path:
            try:
                storage_manager.delete(dataset.file_path)
            except Exception:
                pass
        db.delete(dataset)
        db.commit()
        # 记录损坏物理删除操作
        task_record = create_task_record(
            db=db, task_type="dataset", user_id=current_user.id, dataset_id=dataset_id,
            params={
                "operation": "permanent_delete",
                "dataset_name": corrupted_name,
                "dataset_id": dataset_id,
                "artifact_type": corrupted_artifact_type,
                "file_size": corrupted_file_size,
            }
        )
        update_task_record(db=db, record_id=task_record.id, status="success",
                           result_summary={"affected_count": 1}, execution_time=0)
        clear_user_dataset_cache(current_user.id)
        # 清理 ClickHouse 副本（损坏数据集已物理删除）
        _cleanup_clickhouse_copy(dataset_id)
        return {"message": "已删除损坏的记录"}
    
    if dataset.status != "active":
        raise HTTPException(status_code=400, detail="数据集不在活跃状态")
    
    file_moved = False
    if dataset.file_path:
        if storage_manager.exists(dataset.file_path):
            trash_filename = f"trash/{dataset_id}_{os.path.basename(dataset.file_path)}"
            try:
                content = storage_manager.read(dataset.file_path)
                trash_path = storage_manager.save(trash_filename, content)
                storage_manager.delete(dataset.file_path)
                dataset.file_path = trash_path
                file_moved = True
                print(f"✅ 文件已移到回收站: {trash_path}")
            except Exception as e:
                print(f"❌ 移动文件到回收站失败: {e}")
                raise HTTPException(status_code=500, detail=f"移动文件到回收站失败: {e}")
        else:
            print(f"⚠️ 文件不存在，跳过移动: {dataset.file_path}")
    
    dataset.status = "deleted"
    dataset.deleted_at = datetime.now(SHANGHAI_TZ)
    db.commit()

    # 记录软删除操作到操作历史
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id, dataset_id=dataset_id,
        params={
            "operation": "soft_delete",
            "dataset_name": dataset.name,
            "dataset_id": dataset_id,
            "artifact_type": dataset.artifact_type,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": 1,
                           "dataset_name": dataset.name,
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 清理 ClickHouse 副本（软删除进入回收站，不再参与分析）
    _cleanup_clickhouse_copy(dataset_id)

    return {"message": "已移到回收站", "file_moved": file_moved}


@router.post("/batch-delete")
async def batch_delete_datasets(
    ids: list = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """批量删除数据集（移到回收站）"""
    # 删除保护：检查是否有依赖待删除数据集的运行中或等待中任务
    from app.models import TaskRecord
    from app.utils.task_labels import get_task_type_label
    running_tasks = db.query(TaskRecord).filter(
        TaskRecord.dataset_id.in_(ids),
        TaskRecord.user_id == current_user.id,
        TaskRecord.status.in_(["running", "pending"])
    ).all()
    if running_tasks:
        # 按数据集分组统计
        blocked_ids = list(set(t.dataset_id for t in running_tasks))
        # operation_label 不是 TaskRecord 模型属性，使用 get_task_type_label 获取中文标签
        task_desc = "、".join([get_task_type_label(t.task_type) or t.task_type for t in running_tasks[:3]])
        raise HTTPException(
            status_code=409,
            detail=f"有 {len(blocked_ids)} 个数据集存在正在执行或等待中的任务（{task_desc}），"
                   f"请等待任务完成或先在任务面板取消任务后再删除"
        )

    datasets = db.query(Dataset).filter(Dataset.id.in_(ids), Dataset.user_id == current_user.id, Dataset.status == "active").all()
    
    moved_count = 0
    for dataset in datasets:
        if dataset.file_path and storage_manager.exists(dataset.file_path):
            trash_filename = f"trash/{dataset.id}_{os.path.basename(dataset.file_path)}"
            try:
                content = storage_manager.read(dataset.file_path)
                trash_path = storage_manager.save(trash_filename, content)
                storage_manager.delete(dataset.file_path)
                dataset.file_path = trash_path
                moved_count += 1
                print(f"✅ 批量删除: 文件已移到回收站 ID={dataset.id}, Path={trash_path}")
            except Exception as e:
                print(f"❌ 批量删除: 移动文件失败 ID={dataset.id}, Error={e}")
        dataset.status = "deleted"
        dataset.deleted_at = datetime.now(SHANGHAI_TZ)
    
    db.commit()

    # 记录批量删除操作到操作历史
    # 保存操作对象名称列表（截断前 50 个），供操作历史"操作对象"列展示
    dataset_names = [d.name for d in datasets][:50]
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id,
        params={
            "operation": "batch_delete",
            "target_ids": ids,
            "target_count": len(ids),
            "actual_deleted": len(datasets),
            "dataset_names": dataset_names,
            "names_truncated": len(datasets) > 50,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": len(datasets),
                           "target_count": len(ids),
                           "actual_deleted": len(datasets),
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 清理批量删除数据集的 ClickHouse 副本
    for dataset in datasets:
        _cleanup_clickhouse_copy(dataset.id)

    return {"message": f"已将 {len(datasets)} 项移到回收站，其中 {moved_count} 个文件已移动"}


# ==================== 回收站相关接口 ====================

@router.get("/trash/list")
async def list_trash(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(100, ge=1, le=500, description="每页数量，最大500"),
    paginated: bool = Query(False, description="是否返回分页结构（true=分页字典，false=列表，兼容旧前端）"),
    skip: int = Query(None, description="已废弃，请使用 page/page_size"),
    limit: int = Query(None, description="已废弃，请使用 page/page_size"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取回收站列表

    - paginated=false（默认）：返回列表（兼容旧前端）
    - paginated=true：返回 {datasets, total, page, page_size, total_pages}
    - 兼容旧参数 skip/limit（已废弃，内部转换为 page/page_size）
    """
    # 兼容旧参数 skip/limit
    if skip is not None or limit is not None:
        skip_val = skip or 0
        limit_val = limit or 100
        page = (skip_val // limit_val) + 1 if limit_val > 0 else 1
        page_size = limit_val

    base_query = db.query(Dataset).filter(Dataset.status == "deleted", Dataset.user_id == current_user.id)
    total = base_query.count()
    start = (page - 1) * page_size
    datasets = base_query.order_by(Dataset.deleted_at.desc()).offset(start).limit(page_size).all()

    result = [DatasetResponse.from_orm(ds).dict() for ds in datasets]

    if paginated:
        return {
            "datasets": result,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size)
        }
    else:
        # 兼容旧前端：返回列表
        return result


@router.post("/trash/restore/{dataset_id}")
async def restore_dataset(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """从回收站恢复数据集"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.status != "deleted":
        raise HTTPException(status_code=400, detail="数据集不在回收站中")

    # 远程数据库代理记录不可恢复（无本地文件，只是远程引用）
    if not dataset.file_path:
        raise HTTPException(
            status_code=400,
            detail="远程数据库导入的数据集无本地文件，无法从回收站恢复。请在模块中通过数据源连接重新使用该表。"
        )
    
    if dataset.file_path and storage_manager.exists(dataset.file_path) and "trash/" in dataset.file_path:
        # 从 trash 文件名还原原始文件名（trash/{id}_{basename}）
        original_filename = os.path.basename(dataset.file_path).split("_", 1)[-1] if "_" in os.path.basename(dataset.file_path) else os.path.basename(dataset.file_path)
        # 恢复到用户原属目录：uploads/user_{id}/{uuid}/{filename}
        # 使用 uploads 作为默认目录，因为 trash 中已丢失原始模块前缀，
        # 而 storage_manager.save 会在路径中自动注入 UUID 保证唯一
        restore_path = f"uploads/user_{current_user.id}/{original_filename}"

        try:
            content = storage_manager.read(dataset.file_path)
            new_path = storage_manager.save(restore_path, content)
            storage_manager.delete(dataset.file_path)
            dataset.file_path = new_path
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"恢复文件失败: {e}")
    
    dataset.status = "active"
    dataset.deleted_at = None
    db.commit()

    # 记录恢复操作到操作历史
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id, dataset_id=dataset_id,
        params={
            "operation": "restore",
            "dataset_name": dataset.name,
            "dataset_id": dataset_id,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": 1,
                           "dataset_name": dataset.name,
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 恢复后重新触发 ClickHouse 副本同步（数据集重新参与分析）
    _trigger_ch_sync(dataset_id)

    return {"message": "已恢复"}


@router.delete("/trash/{dataset_id}")
async def permanent_delete_dataset(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """从回收站删除数据集（状态改为 purged，用户端不再显示，管理端可恢复）"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.status != "deleted":
        raise HTTPException(status_code=400, detail="数据集不在回收站中")
    
    dataset.status = "purged"
    dataset.deleted_at = datetime.now(SHANGHAI_TZ)

    # 记录永久删除操作到操作历史（在 commit 前捕获名称等信息）
    purged_name = dataset.name
    purged_artifact_type = dataset.artifact_type
    purged_file_size = dataset.file_size

    db.commit()

    # 记录永久删除操作到操作历史
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id, dataset_id=dataset_id,
        params={
            "operation": "permanent_delete",
            "dataset_name": purged_name,
            "dataset_id": dataset_id,
            "artifact_type": purged_artifact_type,
            "file_size": purged_file_size,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": 1,
                           "dataset_name": purged_name,
                           "artifact_type": purged_artifact_type,
                           "actual_deleted": 1,
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 清理 ClickHouse 副本（永久删除不再参与分析）
    _cleanup_clickhouse_copy(dataset_id)

    return {"message": "已移入业务回收站"}


@router.delete("/clear/all")
async def clear_all_datasets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """清空所有活跃数据集（永久删除所有数据集）

    对 ML 模型记录会级联删除保存在 pkl 内部的测试集 CSV 文件。
    """
    datasets = db.query(Dataset).filter(
        (Dataset.status == "active") | (Dataset.status == None) | (Dataset.status == "corrupted"),
        Dataset.user_id == current_user.id
    ).all()

    # ML 模型级联清理测试集文件(在删除主文件前执行)
    from app.api.ml import cascade_delete_ml_testset
    for dataset in datasets:
        if dataset.artifact_type == "ml_model":
            cascade_delete_ml_testset(dataset)
        if dataset.file_path and storage_manager.exists(dataset.file_path):
            try:
                storage_manager.delete(dataset.file_path)
            except Exception as e:
                print(f"删除文件失败: {e}")
        db.delete(dataset)

    db.commit()

    # 记录清空所有数据集操作到操作历史
    dataset_names = [d.name for d in datasets][:50]
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id,
        params={
            "operation": "clear_all",
            "deleted_count": len(datasets),
            "dataset_names": dataset_names,
            "names_truncated": len(datasets) > 50,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": len(datasets),
                           "cleared_count": len(datasets),
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 清理清空数据集的 ClickHouse 副本
    for dataset in datasets:
        _cleanup_clickhouse_copy(dataset.id)

    return {"message": f"已清空所有数据集，共删除 {len(datasets)} 项"}


@router.delete("/trash/clear/all")
async def clear_trash(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """清空回收站（将状态改为 purged，用户端不再显示，管理端可恢复）"""
    datasets = db.query(Dataset).filter(Dataset.status == "deleted", Dataset.user_id == current_user.id).all()
    
    now = datetime.now(SHANGHAI_TZ)
    for dataset in datasets:
        dataset.status = "purged"
        dataset.deleted_at = now
    
    db.commit()

    # 记录清空回收站操作到操作历史
    dataset_names = [d.name for d in datasets][:50]
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id,
        params={
            "operation": "clear_trash",
            "purged_count": len(datasets),
            "dataset_names": dataset_names,
            "names_truncated": len(datasets) > 50,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "affected_count": len(datasets),
                           "cleared_count": len(datasets),
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 清理清空回收站数据集的 ClickHouse 副本
    for dataset in datasets:
        _cleanup_clickhouse_copy(dataset.id)

    return {"message": f"已清空回收站，共处理 {len(datasets)} 项"}


@router.get("/{dataset_id}/data", response_model=DatasetDataResponse)
async def get_dataset_data(
    dataset_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据集数据（分页）

    Args:
        dataset_id: 数据集ID
        page: 页码，从1开始，默认1
        page_size: 每页行数，默认100，最大1000
        db: 数据库会话
        current_user: 当前用户

    Returns:
        DatasetDataResponse: 包含列名、数据、总行数、页码、页大小
    """
    # 校验数据集归属，防止越权访问他人数据（IDOR 修复）
    get_dataset_or_404(db, dataset_id, current_user.id)
    data_service = DataService(db)
    try:
        # 使用分页加载，避免全量构建 DataFrame 导致大数据集 OOM
        page_df, total = data_service.load_dataset_page(dataset_id, page, page_size)

        return {
            "columns": page_df.columns.tolist(),
            "data": data_service.get_sample_data(page_df, page_size),
            "total_rows": total,
            "page": page,
            "page_size": page_size
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{dataset_id}/statistics", response_model=DataStatisticsResponse)
async def get_dataset_statistics(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取数据集统计信息

    Args:
        dataset_id: 数据集ID
        db: 数据库会话
        current_user: 当前用户

    Returns:
        DataStatisticsResponse: 包含行数、列数、缺失值统计、重复行数、各列统计详情
    """
    # 校验数据集归属，防止越权访问他人数据（IDOR 修复）
    get_dataset_or_404(db, dataset_id, current_user.id)
    data_service = DataService(db)
    try:
        df = data_service.load_dataset(dataset_id)
        quality_report = data_service.get_data_quality_report(df)
        stats = data_service.get_statistics(df)

        return {
            "row_count": quality_report['total_rows'],
            "column_count": quality_report['total_columns'],
            "missing_values": {col: info['count'] for col, info in quality_report['missing_values'].items()},
            "duplicate_rows": quality_report['duplicate_rows'],
            "statistics": stats
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{dataset_id}/quality")
async def get_data_quality(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取数据质量报告

    Args:
        dataset_id: 数据集ID
        db: 数据库会话
        current_user: 当前用户

    Returns:
        dict: 包含总行数、总列数、缺失值统计、重复行数、各列质量评分等
    """
    # 校验数据集归属，防止越权访问他人数据（IDOR 修复）
    get_dataset_or_404(db, dataset_id, current_user.id)
    data_service = DataService(db)
    try:
        df = data_service.load_dataset(dataset_id)
        report = data_service.get_data_quality_report(df)
        return report
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{dataset_id}/import", response_model=DatasetResponse)
async def import_dataset(
    dataset_id: int,
    target_module: str = Query(..., description="目标模块: cleaning/ml/ai/feature_engineering/pipeline"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """将数据集导入到指定模块（复制一份到目标模块的原始数据中）"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    new_file_path = None
    new_filename = None
    import_file_size = None
    
    if dataset.file_path and storage_manager.exists(dataset.file_path):
        # 命名方案（2026-08-13 起）：导入保持源名（剥离历史拼接），不再追加 `_import_时间戳` 后缀。
        # 区分靠 parent_id（血缘）+ module_source（目标模块）+ 颜色 + 创建时间。
        src_base, src_ext = os.path.splitext(dataset.name)
        if not src_ext:
            src_ext = '.csv'
        new_filename = f"{clean_dataset_name(src_base)}{src_ext}"

        content = storage_manager.get_file_bytes(dataset.file_path)
        object_name = f"uploads/user_{current_user.id}/{new_filename}"
        new_file_path = storage_manager.save_bytes(object_name, content)
        import_file_size = len(content)

    original_columns = []
    if new_file_path and storage_manager.exists(new_file_path):
        try:
            df = data_service._load_from_file(new_file_path)
            original_columns = list(df.columns)
        except Exception:
            pass

    imported_name = new_filename if new_filename else clean_dataset_name(dataset.name)
    imported = Dataset(
        name=imported_name,
        user_id=current_user.id,
        file_path=new_file_path,
        file_size=import_file_size,
        schema=dataset.schema,
        row_count=dataset.row_count,
        data_preview=dataset.data_preview,
        module_source=target_module,
        module_label=MODULE_LABEL_MAP.get(target_module, "原始数据"),
        parent_id=dataset_id,
        artifact_type="raw_data",
        tags=json.dumps({"original_columns": original_columns}) if original_columns else None
    )
    db.add(imported)
    db.commit()
    db.refresh(imported)

    # 记录跨模块导入操作到操作历史
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=current_user.id, dataset_id=dataset_id,
        params={
            "operation": "import_to_module",
            "source_dataset_id": dataset_id,
            "source_dataset_name": dataset.name,
            "source_module": dataset.module_source,
            "target_module": target_module,
            "new_dataset_id": imported.id,
            "new_dataset_name": imported.name,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={
                           "new_dataset_id": imported.id,
                           "new_dataset_name": imported.name,
                           "source_dataset_name": dataset.name,
                           "source_module": dataset.module_source,
                           "target_module": target_module,
                       }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    # 导入创建的 raw_data 副本同样纳入 ClickHouse 同步（行数达阈值时在任务内同步）
    _trigger_ch_sync(imported.id)

    return imported


@router.get("/{dataset_id}/lineage")
async def get_dataset_lineage(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据集的数据血缘关系（向上追溯父级，向下查找子级）"""

    def build_dataset_node(ds: Dataset) -> dict:
        return {
            "id": ds.id,
            "name": ds.name,
            "module_source": ds.module_source,
            "module_label": ds.module_label,
            "artifact_type": ds.artifact_type,
            "status": ds.status,
            "row_count": ds.row_count,
            "file_size": ds.file_size,
            "created_at": _format_shanghai(ds.created_at) if ds.created_at else None,
            "is_ai_plan": False
        }

    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    ancestors = []
    current = dataset
    while current.parent_id:
        parent = db.query(Dataset).filter(Dataset.id == current.parent_id).first()
        if parent:
            node = build_dataset_node(parent)
            node["relation_type"] = "parent"
            is_import = parent.module_source != current.module_source
            node["is_import"] = is_import
            ancestors.append(node)
            current = parent
        else:
            break

    # 血缘虚拟根节点：向上追溯到最顶层后，若该数据集来源于远程数据库，
    # 补充一个虚拟节点表示远程数据源连接，让用户直观看到数据的远程来源
    root_source = None
    root_dataset = current  # 最顶层祖先（或 dataset 本身）
    if root_dataset.connection_id:
        from app.models import DataSourceConnection
        conn = db.query(DataSourceConnection).filter(
            DataSourceConnection.id == root_dataset.connection_id
        ).first()
        if conn:
            root_source = {
                "id": f"remote_{conn.id}",  # 虚拟 ID，避免与真实数据集 ID 冲突
                "name": f"{conn.name} ({conn.db_type})",
                "module_source": "remote_db",
                "module_label": "远程数据库",
                "artifact_type": "remote_table",
                "status": "active",
                "row_count": None,
                "file_size": None,
                "created_at": None,
                "is_ai_plan": False,
                "relation_type": "remote_root",
                "is_import": True,
                "connection_id": conn.id,
                "host": conn.host,
                "port": conn.port,
                "database": conn.database,
                "table_name": root_dataset.table_name,
                "is_virtual": True  # 标记为虚拟节点
            }

    all_dataset_ids = {dataset_id}
    for a in ancestors:
        all_dataset_ids.add(a["id"])

    descendants = []
    def find_descendants(parent_id: int, level: int = 0):
        # 查询 Dataset 表中的直接子节点
        children = db.query(Dataset).filter(Dataset.parent_id == parent_id).all()
        for child in children:
            node = build_dataset_node(child)
            node["relation_type"] = "child"
            is_import = child.module_source != dataset.module_source
            node["is_import"] = is_import
            node["level"] = level
            descendants.append(node)
            all_dataset_ids.add(child.id)
            find_descendants(child.id, level + 1)

    find_descendants(dataset_id)

    descendants.sort(key=lambda x: x.get("level", 0))

    return {
        "self": build_dataset_node(dataset),
        "ancestors": ancestors[::-1],
        "descendants": descendants,
        "root_source": root_source
    }


def _download_name(dataset: Dataset, ext: str) -> str:
    """构造下载文件名：与前端展示名一致（源名去扩展名 + 真实内容后缀），中文经 URL 编码"""
    return quote(build_product_name(dataset.name, ext))


@router.get("/{dataset_id}/export")
async def export_dataset(
    dataset_id: int,
    format: str = Query("csv", description="导出格式: csv/excel/json/pdf/markdown"),
    report_type: str = Query("static", description="报告类型: static/dynamic (仅analysis_report有效)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """导出数据集
    - data 类型（raw_data, cleaning_result）: 支持 CSV/Excel/JSON/PDF
    - report 类型（ml_report, ai_report）: 支持 PDF/Markdown（从 report_content 生成）
    - analysis_report: 支持 HTML（static/dynamic）
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    data_service = DataService(db)

    # 报告类型：从 report_content 生成导出内容
    if dataset.artifact_type in ("ml_report", "ai_report", "ml_model", "analysis_report"):
        return _export_report(dataset, format, report_type)

    # 数据类型：从文件导出
    try:
        df = data_service.load_dataset(dataset_id)

        if format == "csv":
            output = io.StringIO()
            df.to_csv(output, index=False, encoding='utf-8-sig')
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'csv')}"}
            )
        elif format == "json":
            output = io.StringIO()
            df.to_json(output, orient="records", force_ascii=False, indent=2)
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'json')}"}
            )
        elif format == "excel":
            output = io.BytesIO()
            df.to_excel(output, index=False, engine='openpyxl')
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'xlsx')}"}
            )
        elif format == "pdf":
            # 使用 matplotlib 生成 PDF 报告（含统计摘要 + 数据预览表）
            quality_report = data_service.get_data_quality_report(df)
            stats = data_service.get_statistics(df)

            pdf_buffer = io.BytesIO()

            # 创建 PDF 报告
            fig, axes = plt.subplots(2, 1, figsize=(11, 8.5))
            fig.suptitle(f"数据集报告 - ID: {dataset_id}", fontsize=16, fontweight='bold')

            # 上半部分：统计摘要
            ax1 = axes[0]
            ax1.axis('off')
            summary_text = (
                f"数据概览\n"
                f"{'='*50}\n"
                f"总行数: {quality_report['total_rows']}\n"
                f"总列数: {quality_report['total_columns']}\n"
                f"重复行数: {quality_report['duplicate_rows']}\n"
                f"缺失值列数: {len(quality_report['missing_values'])}\n\n"
                f"缺失值详情:\n"
            )
            for col, info in quality_report['missing_values'].items():
                summary_text += f"  - {col}: {info['count']} ({info['percentage']}%)\n"

            if 'numeric' in stats:
                summary_text += f"\n数值列统计:\n"
                # 全空列的统计值为 None，先判空再格式化，避免 .2f 抛 TypeError 导致导出 500
                def _fmt_stat(v):
                    return 'N/A' if v is None else f"{float(v):.2f}"
                for col_name, col_stats in stats['numeric'].items():
                    summary_text += f"  - {col_name}: "
                    summary_text += f"mean={_fmt_stat(col_stats.get('mean'))}, "
                    summary_text += f"std={_fmt_stat(col_stats.get('std'))}, "
                    summary_text += f"min={_fmt_stat(col_stats.get('min'))}, "
                    summary_text += f"max={_fmt_stat(col_stats.get('max'))}\n"

            ax1.text(0.05, 0.95, summary_text, transform=ax1.transAxes,
                     fontsize=9, verticalalignment='top',
                     bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.5))

            # 下半部分：数据预览表
            ax2 = axes[1]
            ax2.axis('off')
            preview_df = df.head(10)

            table = ax2.table(
                cellText=preview_df.values.astype(str),
                colLabels=preview_df.columns,
                cellLoc='center',
                loc='center'
            )
            table.auto_set_font_size(False)
            table.set_fontsize(7)
            table.scale(1.0, 1.2)
            ax2.set_title("数据预览 (前10行)", fontsize=12, fontweight='bold')

            plt.tight_layout(rect=[0, 0, 1, 0.95])
            fig.savefig(pdf_buffer, format='pdf', bbox_inches='tight')
            plt.close(fig)
            pdf_buffer.seek(0)

            return StreamingResponse(
                iter([pdf_buffer.getvalue()]),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'pdf')}"}
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _export_report(dataset: Dataset, format: str, report_type: str = "static"):
    """从 report_content 导出报告"""
    report_label = dataset.artifact_type or "report"

    if not dataset.report_content:
        raise HTTPException(status_code=400, detail="该报告没有内容可导出")

    # analysis_report 类型：HTML 格式直接下载，其他格式提示仅支持 HTML
    if dataset.artifact_type == "analysis_report":
        if format == "html":
            output = io.StringIO()
            try:
                parsed_content = json.loads(dataset.report_content)
                report_html = parsed_content.get("html", dataset.report_content)
                dynamic_data = parsed_content.get("dynamic_data", {})
            except json.JSONDecodeError:
                report_html = dataset.report_content
                dynamic_data = {}
            
            if report_type == "dynamic":
                dynamic_html = _build_dynamic_report_html(report_html, dynamic_data)
                output.write(dynamic_html)
            else:
                output.write(report_html)
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/html",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'html')}"}
            )
        else:
            raise HTTPException(status_code=400, detail="仅支持 HTML 格式导出")

    try:
        report_data = json.loads(dataset.report_content)
    except json.JSONDecodeError:
        report_data = {"raw": dataset.report_content}

    if format == "markdown":
        # 生成 Markdown 格式报告
        md_lines = [f"# {dataset.name}", ""]
        md_lines.append(f"**产物类型**: {report_label}")
        md_lines.append(f"**算法**: {dataset.algorithm or 'N/A'}")
        md_lines.append(f"**创建时间**: {dataset.created_at}")
        md_lines.append("")
        md_lines.append("## 报告内容")
        md_lines.append("")
        md_lines.append("```json")
        md_lines.append(json.dumps(report_data, indent=2, ensure_ascii=False))
        md_lines.append("```")

        md_content = "\n".join(md_lines)
        output = io.StringIO()
        output.write(md_content)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'md')}"}
        )

    elif format == "pdf":
        # 生成 PDF 格式报告（使用中文字体，与前端查看报告内容一致）
        pdf_buffer = io.BytesIO()

        # 构建报告文本（与前端 renderModelReport 内容一致）
        lines = []
        lines.append(f"📊 模型报告")
        lines.append("")

        # === 模型信息 ===
        mi = report_data.get("model_info", {})
        lines.append("📌 模型信息")
        lines.append("-" * 50)
        algo_map = {
            'logistic_regression': '逻辑回归',
            'random_forest': '随机森林',
            'svm': '支持向量机',
            'linear_regression': '线性回归',
            'ridge_regression': '岭回归'
        }
        task_map = {'classification': '分类任务', 'regression': '回归任务'}
        lines.append(f"模型名称: {mi.get('model_name', '-')}")
        lines.append(f"算法: {algo_map.get(mi.get('algorithm'), mi.get('algorithm', '-'))}")
        lines.append(f"任务类型: {task_map.get(mi.get('task_type'), mi.get('task_type', '-'))}")
        lines.append(f"目标列: {mi.get('target_column', '-')}")
        lines.append(f"特征数量: {mi.get('feature_count', 0)}")
        lines.append(f"特征列: {', '.join(mi.get('feature_columns', [])) or '-'}")
        lines.append(f"创建时间: {mi.get('created_at', '-')}")
        lines.append("")

        # === 训练参数 ===
        tp = report_data.get("training_params", {})
        lines.append("⚙️ 训练参数")
        lines.append("-" * 50)
        lines.append(f"测试集比例: {tp.get('test_size', '-')}")
        lines.append(f"交叉验证折数: {tp.get('cv_folds', '-')} 折")
        lines.append(f"是否自动调优: {'是' if tp.get('auto_tune') else '否'}")
        tune_map = {'grid': '网格搜索(穷尽)', 'random': '随机搜索(快速)'}
        lines.append(f"调优方法: {tune_map.get(tp.get('tune_method'), tp.get('tune_method', '-'))}")
        lines.append("")

        # === 最优超参数 ===
        bp = report_data.get("best_params", {})
        if bp:
            lines.append("🎯 最优超参数")
            lines.append("-" * 50)
            param_names = {
                'C': '正则化强度C', 'solver': '求解器', 'n_estimators': '树的数量',
                'max_depth': '最大深度', 'min_samples_split': '最小分割样本数',
                'kernel': '核函数', 'gamma': '核系数', 'alpha': '正则化系数'
            }
            solver_names = {'lbfgs': 'L-BFGS优化器', 'liblinear': 'LIBLINEAR优化器', 'saga': 'SAGA优化器'}
            kernel_names = {'linear': '线性核', 'rbf': '高斯核(RBF)', 'poly': '多项式核', 'sigmoid': 'Sigmoid核'}
            for k, v in bp.items():
                cn = param_names.get(k, k)
                val = solver_names.get(v, v) if k == 'solver' else kernel_names.get(v, v) if k == 'kernel' else v
                lines.append(f"{cn}: {val}")
            lines.append("")

        # === 性能指标 ===
        pm = report_data.get("performance_metrics", {})
        if pm:
            lines.append("📈 性能评估指标")
            lines.append("-" * 50)
            metric_names = {
                'accuracy': '准确率(Accuracy)', 'precision': '精确率(Precision)',
                'recall': '召回率(Recall)', 'f1': 'F1分数', 'roc_auc': 'ROC AUC',
                'r2': 'R² 决定系数', 'mse': 'MSE 均方误差', 'rmse': 'RMSE 均方根误差',
                'mae': 'MAE 平均绝对误差', 'cv_mean': '交叉验证均值', 'cv_std': '交叉验证标准差'
            }
            for k, v in pm.items():
                lines.append(f"{metric_names.get(k, k)}: {v}")
            lines.append("")

        # === 数据集划分 ===
        ds = report_data.get("dataset_split", {})
        if ds:
            lines.append("📂 数据集划分")
            lines.append("-" * 50)
            lines.append(f"总样本数: {ds.get('total', '-')}")
            lines.append(f"训练+验证集: {ds.get('trainval', '-')} ({ds.get('trainval_ratio', 0) * 100:.1f}%)")
            lines.append(f"测试集: {ds.get('test', '-')} ({ds.get('test_ratio', 0) * 100:.1f}%)")
            lines.append(f"说明: {ds.get('description', '-')}")
            lines.append("")

        # === 特征重要性 ===
        fi = report_data.get("feature_importance", {})
        if fi:
            lines.append("🔍 特征重要性")
            lines.append("-" * 50)
            sorted_fi = sorted(fi.items(), key=lambda x: x[1], reverse=True)
            for feat, imp in sorted_fi[:10]:
                bar = '█' * int(imp * 20)
                lines.append(f"{feat}: {imp:.4f} {bar}")
            lines.append("")

        # === 调优结果 ===
        tr = report_data.get("tune_results", {})
        if tr:
            lines.append("🔧 调优结果")
            lines.append("-" * 50)
            lines.append(f"最佳分数: {tr.get('best_score', '-')}")
            lines.append(f"方法: {'网格搜索' if tr.get('method') == 'grid' else '随机搜索'}")
            lines.append(f"候选参数组合数: {tr.get('n_candidates', '-')}")
            lines.append("")

        report_text = "\n".join(lines)

        # 生成 PDF：使用 rcParams 中配置的中文字体（_CHINESE_FONTS 动态检测）
        # 不再硬编码 family='Microsoft YaHei'，避免 Docker 容器中无该字体时中文乱码
        fig, ax = plt.subplots(figsize=(11, 14))
        ax.axis('off')
        ax.text(0.02, 0.99, report_text, transform=ax.transAxes,
                fontsize=10, verticalalignment='top', horizontalalignment='left',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

        fig.savefig(pdf_buffer, format='pdf', bbox_inches='tight')
        plt.close(fig)
        pdf_buffer.seek(0)

        return StreamingResponse(
            iter([pdf_buffer.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_download_name(dataset, 'pdf')}"}
        )

    else:
        raise HTTPException(status_code=400, detail=f"报告类型不支持格式: {format}，支持: pdf/markdown")


def _build_dynamic_report_html(static_html: str, dynamic_data: dict = None) -> str:
    """构建动态报告HTML，包含Vue.js和ECharts，支持交互"""
    generated_at = datetime.now(SHANGHAI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    dynamic_data = dynamic_data or {}
    
    dynamic_html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>数据分析报告（动态版）</title>
    <script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <script src="https://unpkg.com/element-plus/dist/index.full.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css">
    <style>
        :root {
            --primary: #4361ee;
            --primary-light: #eef1fd;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --info: #3b82f6;
            --text-primary: #1f2937;
            --text-secondary: #6b7280;
            --text-muted: #9ca3af;
            --content-bg: #f4f6f9;
            --card-bg: #ffffff;
            --card-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
            --radius: 10px;
            --radius-sm: 6px;
        }
        body { margin: 0; background: var(--content-bg); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; }
        .dynamic-report { min-height: 100%; padding: 28px; }
        .report-header { margin-bottom: 28px; }
        .report-header h1 { font-size: 22px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px 0; }
        .report-time { font-size: 13px; color: var(--text-secondary); margin: 0; }
        .report-body { line-height: 1.6; }
        .report-section { margin-bottom: 28px; }
        .section-title { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 16px 0; padding-left: 12px; border-left: 4px solid var(--primary); display: flex; align-items: center; gap: 8px; }
        .weight-note { background: #fffbeb; border: 1px solid #fde68a; border-radius: var(--radius-sm); padding: 10px 14px; margin: 0 0 12px 0; font-size: 13px; color: #92400e; }
        .table-wrapper { overflow-x: auto; border-radius: var(--radius-sm); border: 1px solid #e5e7eb; background: var(--card-bg); }
        .report-table { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--text-primary); }
        .report-table th { background: #f5f7fa; color: #606266; font-weight: 600; text-align: center; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; border-right: 1px solid #e5e7eb; white-space: nowrap; }
        .report-table td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; border-right: 1px solid #e5e7eb; text-align: center; }
        .report-table th:last-child, .report-table td:last-child { border-right: none; }
        .report-table tbody tr:nth-child(even) { background: #fafafa; }
        .report-table tbody tr:hover { background: #f5f7fa; }
        .report-table td:first-child, .report-table th:first-child { text-align: left; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 16px 0; }
        .stat-card { background: var(--card-bg); border-radius: var(--radius); padding: 20px; text-align: center; box-shadow: var(--card-shadow); }
        .stat-value { font-size: 32px; font-weight: 700; color: var(--primary); margin-bottom: 6px; }
        .stat-label { font-size: 13px; color: var(--text-secondary); }
        .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; line-height: 1.4; }
        .tag-success { background: #e6f7e6; color: #2f9a2f; }
        .tag-info { background: #f4f6f9; color: #606266; }
        .tag-warning { background: #fff4e6; color: #e6a23c; }
        .charts-container { display: flex; flex-direction: column; gap: 20px; }
        .chart-item { background: var(--card-bg); padding: 20px; border-radius: var(--radius); border: none; box-shadow: var(--card-shadow); }
        .chart-title { font-size: 15px; font-weight: 600; color: var(--text-primary); margin: 0 0 12px 0; }
        .chart-controls { margin-bottom: 12px; }
        .chart-wrapper { display: block; }
        .chart-canvas { width: 100%; height: 420px; }
        .pivot-container { display: flex; flex-direction: column; gap: 20px; }
        .pivot-item { background: var(--card-bg); padding: 20px; border-radius: var(--radius); border: none; box-shadow: var(--card-shadow); }
        .pivot-title { font-size: 15px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0; }
        .pivot-info { font-size: 13px; color: var(--text-secondary); margin: 0 0 12px 0; }
        @media (max-width: 768px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 480px) { .stats-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div id="app" class="dynamic-report">
        <div class="report-header">
            <h1>{{ reportTitle }}</h1>
            <p class="report-time">生成时间：{{ reportTime }}</p>
        </div>
        <div class="report-body">
            <div v-if="reportData.data_preview" class="report-section">
                <h2 class="section-title">数据预览</h2>
                <div class="table-wrapper">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th v-for="col in reportData.data_preview.columns" :key="col">{{ col }}</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="(row, idx) in reportData.data_preview.rows" :key="idx">
                                <td v-for="col in reportData.data_preview.columns" :key="col">{{ row[col] ?? '-' }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <p style="font-size:13px;color:#666;margin-top:8px;">显示前 {{ reportData.data_preview.rows.length }} 行数据</p>
            </div>

            <div v-if="reportData.quality" class="report-section">
                <h2 class="section-title">数据质量概览</h2>
                <div class="stats-grid">
                    <div v-for="metric in reportData.quality.metrics" :key="metric.label" class="stat-card">
                        <div class="stat-value">{{ metric.value }}</div>
                        <div class="stat-label">{{ metric.label }}</div>
                    </div>
                </div>
            </div>

            <div v-if="reportData.column_info" class="report-section">
                <h2 class="section-title">列信息</h2>
                <div class="weight-note">质量评分权重：完整性60% + 唯一性20% + 类型20%</div>
                <div class="table-wrapper">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>列名</th>
                                <th>类型</th>
                                <th>缺失数</th>
                                <th>缺失率(%)</th>
                                <th>完整性</th>
                                <th>唯一性</th>
                                <th>质量评分</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in reportData.column_info" :key="row.name">
                                <td>{{ row.name }}</td>
                                <td><span class="tag" :class="row.type==='数值'?'tag-success':'tag-info'">{{ row.type }}</span></td>
                                <td>{{ row.missing_count }}</td>
                                <td>{{ row.missing_rate }}</td>
                                <td><span class="tag" :class="row.completeness==='高'?'tag-success':(row.completeness==='低'?'tag-warning':'tag-info')">{{ row.completeness }}</span></td>
                                <td><span class="tag" :class="row.uniqueness==='高'?'tag-success':(row.uniqueness==='低'?'tag-warning':'tag-info')">{{ row.uniqueness }}</span></td>
                                <td :style="{color:getScoreColor(row.quality_score)}">{{ row.quality_score }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div v-if="reportData.numeric_stats" class="report-section">
                <h2 class="section-title">数值列统计</h2>
                <div class="table-wrapper">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th v-for="col in numericColumns" :key="col.key">{{ col.label }}</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in reportData.numeric_stats" :key="row.column">
                                <td v-for="col in numericColumns" :key="col.key">{{ row[col.key] ?? '-' }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div v-if="reportData.categorical_stats && reportData.categorical_stats.length" class="report-section">
                <h2 class="section-title">分类列统计</h2>
                <div class="table-wrapper">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>列名</th>
                                <th>唯一值数</th>
                                <th>缺失数</th>
                                <th>缺失率(%)</th>
                                <th style="text-align:left;">TOP 值</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in reportData.categorical_stats" :key="row.column">
                                <td>{{ row.column }}</td>
                                <td>{{ row.unique_count }}</td>
                                <td>{{ row.missing_count }}</td>
                                <td>{{ row.missing_rate }}</td>
                                <td style="text-align:left;">
                                    <span v-if="row.top_values && row.top_values.length">
                                        <span v-for="(item, idx) in row.top_values" :key="idx" style="margin-right:8px;">
                                            <span style="color:#606266;">{{ item.value }}</span>
                                            <span style="color:#909399;">({{ item.count }})</span>
                                        </span>
                                    </span>
                                    <span v-else style="color:#909399;">-</span>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div v-if="reportData.charts && reportData.charts.length" class="report-section">
                <h2 class="section-title">自定义图表</h2>
                <div class="charts-container">
                    <div v-for="(chart, idx) in reportData.charts" :key="idx" class="chart-item">
                        <h3 class="chart-title">{{ getChartTitle(chart) }}</h3>
                        <div class="chart-controls">
                            <el-checkbox v-model="chartShowDataLabels[idx]" @change="toggleDataLabels(idx)">显示数据标签</el-checkbox>
                        </div>
                        <div class="chart-wrapper">
                            <div :id="'chart-' + idx" class="chart-canvas"></div>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="reportData.pivot && reportData.pivot.length" class="report-section">
                <h2 class="section-title">透视表</h2>
                <div class="pivot-container">
                    <div v-for="(pivot, idx) in reportData.pivot" :key="idx" class="pivot-item">
                        <h3 class="pivot-title">{{ pivot.title || '透视表' + (idx+1) }}</h3>
                        <p class="pivot-info">行维度: {{ pivot.row_dim || '-' }} | 列维度: {{ pivot.col_dim || '-' }} | 值字段: {{ pivot.value_field }} | 聚合方式: {{ pivot.agg_func }}</p>
                        <div class="table-wrapper">
                            <table class="report-table">
                                <thead>
                                    <tr>
                                        <th v-for="col in pivot.columns" :key="col">{{ col }}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="(row, ridx) in getPivotData(pivot)" :key="ridx">
                                        <td v-for="col in pivot.columns" :key="col">{{ row[col] ?? '-' }}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        window.reportData = __REPORT_DATA__;
    </script>
    <script>
        const { createApp, ref, computed, onMounted, nextTick } = Vue;
        createApp({
            setup() {
                const reportData = ref({});
                const reportTitle = computed(() => reportData.value.config?.title || '数据分析报告');
                const reportTime = computed(() => reportData.value.config?.generated_at || '');
                const chartShowDataLabels = ref({});
                const chartInstances = ref({});

                const numericColumns = computed(() => [
                    {key:'column', label:'列名', width:110},
                    {key:'mean', label:'均值', width:80},
                    {key:'median', label:'中位数', width:80},
                    {key:'std', label:'标准差', width:80},
                    {key:'min', label:'最小值', width:80},
                    {key:'max', label:'最大值', width:80},
                    {key:'q25', label:'Q25', width:70},
                    {key:'q50', label:'Q50', width:70},
                    {key:'q75', label:'Q75', width:70},
                    {key:'p90', label:'P90', width:70},
                    {key:'p95', label:'P95', width:70},
                    {key:'p99', label:'P99', width:70},
                    {key:'skewness', label:'偏度', width:70},
                    {key:'kurtosis', label:'峰度', width:70},
                    {key:'cv', label:'变异系数(CV)', width:110},
                    {key:'mode', label:'众数', width:70},
                    {key:'zero_count', label:'零值数', width:75},
                    {key:'zero_rate', label:'零值率(%)', width:85},
                    {key:'missing_count', label:'缺失数', width:75},
                    {key:'missing_rate', label:'缺失率(%)', width:85}
                ]);

                function getScoreColor(score) {
                    if (score >= 90) return '#67c23a';
                    if (score >= 70) return '#e6a23c';
                    return '#f56c6c';
                }

                function getPivotData(pivot) {
                    if (!pivot.data || !pivot.columns) return [];
                    return pivot.data.map(row => {
                        const obj = {};
                        pivot.columns.forEach((col, idx) => {
                            obj[col] = row[idx] !== undefined ? row[idx] : '';
                        });
                        return obj;
                    });
                }

                const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607'];

                function buildChartOption(chartData, chartType) {
                    const option = {
                        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                        legend: { show: true, top: 10, type: 'scroll' },
                        grid: { left: '3%', right: '4%', bottom: '3%', top: 60, containLabel: true }
                    };

                    const labels = chartData.labels || [];
                    const values = chartData.values || [];
                    const series = chartData.series || [];
                    const xData = chartData.x || [];
                    const yData = chartData.y || [];

                    // 通用数据缩放配置
                    function getDataZoom() {
                        return [
                            { type: 'inside', xAxisIndex: [0], start: 0, end: 100 },
                            { type: 'slider', xAxisIndex: [0], start: 0, end: 100, bottom: 10, height: 24 }
                        ];
                    }

                    // 直方图/柱状图/折线图/面积图：优先使用 series，否则回退到 values
                    if (['histogram', 'bar', 'line', 'area', 'multi_line', 'stacked_bar'].includes(chartType)) {
                        option.grid.bottom = 80;
                        option.dataZoom = getDataZoom();
                        // 兼容多种 X 轴字段：multi_line/area 输出 x，stacked_bar 输出 categories，其他输出 labels
                        var xLabels = chartData.x || chartData.categories || labels;
                        option.xAxis = { type: 'category', data: xLabels, axisLabel: { rotate: 45 } };
                        option.yAxis = { type: 'value' };
                        if (series.length > 0) {
                            option.series = series.map((s, i) => ({
                                name: s.name || '',
                                type: chartType === 'stacked_bar' ? 'bar' : (chartType === 'histogram' ? 'bar' : 'line'),
                                // 兼容 s.data 和 s.values 两种字段格式
                                data: s.data || s.values || [],
                                stack: chartType === 'stacked_bar' ? 'total' : undefined,
                                areaStyle: chartType === 'area' ? { color: seriesColors[i % seriesColors.length] + '30' } : undefined,
                                smooth: ['line', 'area', 'multi_line'].includes(chartType),
                                itemStyle: { color: seriesColors[i % seriesColors.length] },
                                label: { show: chartShowDataLabels.value[chartType + '_' + i] || false, position: 'top' }
                            }));
                        } else {
                            option.series = [{
                                type: chartType === 'histogram' || chartType === 'bar' || chartType === 'stacked_bar' ? 'bar' : 'line',
                                data: chartData.y || values,
                                areaStyle: chartType === 'area' ? { color: seriesColors[0] + '30' } : undefined,
                                smooth: ['line', 'area'].includes(chartType),
                                itemStyle: { color: seriesColors[0] },
                                label: { show: chartShowDataLabels.value[chartType + '_0'] || false, position: 'top' }
                            }];
                        }
                    } else if (chartType === 'pie') {
                        option.tooltip = { trigger: 'item' };
                        option.series = [{
                            type: 'pie',
                            radius: ['40%', '70%'],
                            center: ['50%', '50%'],
                            avoidLabelOverlap: false,
                            itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
                            label: { show: chartShowDataLabels.value[chartType + '_0'] || false, formatter: '{b}: {c} ({d}%)' },
                            emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
                            labelLine: { show: !chartShowDataLabels.value[chartType + '_0'] },
                            data: labels.map((name, i) => ({ value: values[i], name }))
                        }];
                    } else if (chartType === 'scatter' || chartType === 'bubble') {
                        option.grid.bottom = 80;
                        option.dataZoom = getDataZoom();
                        option.xAxis = { type: 'value' };
                        option.yAxis = { type: 'value' };
                        if (chartType === 'bubble' && chartData.size) {
                            option.series = [{
                                type: 'scatter',
                                data: xData.map((xi, i) => [xi, yData[i], chartData.size[i]]),
                                symbolSize: val => Math.max(5, val[2] || 10),
                                itemStyle: { color: seriesColors[0], opacity: 0.7 }
                            }];
                        } else {
                            option.series = [{
                                type: 'scatter',
                                data: (chartData.x || labels).map((xi, i) => [xi, (chartData.y || values)[i]]),
                                symbolSize: 8,
                                itemStyle: { color: seriesColors[0] }
                            }];
                        }
                    } else if (chartType === 'boxplot') {
                        option.grid.bottom = 80;
                        option.dataZoom = getDataZoom();
                        option.xAxis = { type: 'category', data: series.map(s => s.name) };
                        option.yAxis = { type: 'value' };
                        const boxData = series.map(s => s.data.slice(0, 5));
                        const outlierData = [];
                        series.forEach((s, idx) => {
                            const outliers = s.data[5] || [];
                            outliers.forEach(val => outlierData.push([idx, val]));
                        });
                        option.series = [
                            { type: 'boxplot', data: boxData, itemStyle: { color: seriesColors[0] } },
                            { type: 'scatter', data: outlierData, symbolSize: 6, itemStyle: { color: seriesColors[1] } }
                        ];
                    } else if (chartType === 'heatmap') {
                        const matrix = chartData.data || [];
                        const heatData = [];
                        let maxVal = 1;
                        for (let i = 0; i < matrix.length; i++) {
                            for (let j = 0; j < (matrix[i]?.length || 0); j++) {
                                heatData.push([j, i, matrix[i][j]]);
                                maxVal = Math.max(maxVal, Math.abs(matrix[i][j]));
                            }
                        }
                        option.grid = { top: 30, left: 80, right: 120, bottom: 80 };
                        option.dataZoom = getDataZoom();
                        option.xAxis = { type: 'category', data: labels, axisLabel: { rotate: 45 } };
                        option.yAxis = { type: 'category', data: labels };
                        option.visualMap = { min: -maxVal, max: maxVal, calculable: true, orient: 'vertical', right: 10, top: 'center' };
                        option.series = [{ type: 'heatmap', data: heatData, label: { show: true, formatter: p => p.value[2].toFixed(2) } }];
                    } else if (chartType === 'kde') {
                        option.grid.bottom = 80;
                        option.dataZoom = getDataZoom();
                        option.xAxis = { type: 'value' };
                        option.yAxis = { type: 'value', name: '密度' };
                        if (series.length > 0) {
                            option.series = series.map((s, i) => ({
                                name: s.name,
                                type: 'line',
                                // 兼容 s.data 和 s.values 两种字段格式
                                data: (chartData.x || []).map((xi, idx) => [xi, (s.data || s.values || [])[idx]]),
                                smooth: true,
                                areaStyle: { color: seriesColors[i % seriesColors.length] + '30' },
                                itemStyle: { color: seriesColors[i % seriesColors.length] }
                            }));
                        } else {
                            option.series = [{
                                type: 'line',
                                data: (chartData.x || []).map((xi, i) => [xi, yData[i]]),
                                smooth: true,
                                areaStyle: { color: seriesColors[0] + '30' },
                                itemStyle: { color: seriesColors[0] }
                            }];
                        }
                    } else if (chartType === 'qq') {
                        // 标准化QQ图：理论分位数 vs 样本分位数的散点 + 参考线
                        option.grid.bottom = 80;
                        option.dataZoom = getDataZoom();
                        var allVals = [];
                        if (series.length > 0) {
                            series.forEach(function(s) { allVals = allVals.concat(s.theoretical || [], s.sample || []); });
                        } else {
                            allVals = (chartData.theoretical || []).concat(chartData.sample || []);
                        }
                        var minVal = allVals.length > 0 ? Math.min.apply(Math, allVals) : 0;
                        var maxVal = allVals.length > 0 ? Math.max.apply(Math, allVals) : 1;
                        var qqSeries = [];
                        if (series.length > 0) {
                            series.forEach(function(s, i) {
                                qqSeries.push({
                                    name: s.name, type: 'scatter',
                                    data: (s.theoretical || []).map(function(t, idx) { return [t, (s.sample || [])[idx]]; }),
                                    symbolSize: 6,
                                    itemStyle: { color: seriesColors[i % seriesColors.length] }
                                });
                            });
                        } else {
                            qqSeries.push({
                                type: 'scatter',
                                data: (chartData.theoretical || []).map(function(t, i) { return [t, (chartData.sample || [])[i]]; }),
                                symbolSize: 6,
                                itemStyle: { color: seriesColors[0] }
                            });
                        }
                        // 添加 y=x 参考线
                        qqSeries.push({ type: 'line', data: [[minVal, minVal], [maxVal, maxVal]], symbol: 'none', lineStyle: { type: 'dashed', color: '#999' } });
                        option.xAxis = { type: 'value', name: '理论分位数', min: minVal, max: maxVal };
                        option.yAxis = { type: 'value', name: '样本分位数', min: minVal, max: maxVal };
                        option.series = qqSeries;
                    } else if (chartType === 'dual_axis') {
                        // 双Y轴图：柱状图(左轴) + 折线图(右轴)
                        option.grid.bottom = 80;
                        option.dataZoom = getDataZoom();
                        option.xAxis = { type: 'category', data: chartData.x || [], axisLabel: { rotate: 30 } };
                        option.yAxis = [
                            { type: 'value', name: chartData.y1_name || 'Y1', position: 'left' },
                            { type: 'value', name: chartData.y2_name || 'Y2', position: 'right' }
                        ];
                        option.series = [
                            { name: chartData.y1_name || 'Y1', type: 'bar', data: chartData.y1 || [], itemStyle: { color: seriesColors[0] } },
                            { name: chartData.y2_name || 'Y2', type: 'line', data: chartData.y2 || [], yAxisIndex: 1, smooth: true, itemStyle: { color: seriesColors[1] } }
                        ];
                    } else if (chartType === 'radar') {
                        // 雷达图：多维度数据对比
                        var indicators = (chartData.indicators || []).map(function(name) { return { name: name, max: 100 }; });
                        option.radar = { indicator: indicators };
                        option.series = [{
                            type: 'radar',
                            data: (chartData.series || []).map(function(s) {
                                return { name: s.name, value: s.value || s.data || [] };
                            })
                        }];
                    } else if (chartType === 'table_heatmap') {
                        // 表格热力图：行列交叉表格按值着色
                        var rowLabels = chartData.rows || [];
                        var colLabels = chartData.columns || [];
                        var matrix = chartData.data || [];
                        var heatData = [];
                        var maxVal = 0;
                        for (var i = 0; i < matrix.length; i++) {
                            for (var j = 0; j < (matrix[i] ? matrix[i].length : 0); j++) {
                                var val = matrix[i][j];
                                if (val !== null && val !== undefined) {
                                    heatData.push([j, i, val]);
                                    maxVal = Math.max(maxVal, Math.abs(val));
                                }
                            }
                        }
                        option.grid = { top: 30, left: 100, right: 30, bottom: 100 };
                        option.xAxis = { type: 'category', data: colLabels, axisLabel: { rotate: 45 } };
                        option.yAxis = { type: 'category', data: rowLabels };
                        option.visualMap = { min: 0, max: maxVal || 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 10 };
                        option.series = [{ type: 'heatmap', data: heatData, label: { show: true } }];
                    }
                    return option;
                }

                function getChartTitle(chart) {
                    const typeMap = {
                        'histogram': '频数直方图', 'bar': '柱状图', 'line': '折线图', 'area': '面积图',
                        'multi_line': '多折线图', 'stacked_bar': '堆叠柱状图', 'pie': '饼图',
                        'scatter': '散点图', 'bubble': '气泡图', 'boxplot': '箱线图',
                        'kde': '单变量KDE密度图', 'qq': '标准化QQ图', 'heatmap': '热力图',
                        'dual_axis': '双Y轴图', 'radar': '雷达图', 'table_heatmap': '表格热力图'
                    };
                    const title = (chart.title || '').trim();
                    const typeName = typeMap[chart.chart_type] || chart.chart_type;
                    if (!title || title === chart.chart_type + ':' || title === chart.chart_type) {
                        return typeName;
                    }
                    return title;
                }

                function initCharts() {
                    if (!reportData.value.charts) return;
                    reportData.value.charts.forEach((chart, idx) => {
                        nextTick(() => {
                            const dom = document.getElementById('chart-' + idx);
                            if (!dom) return;
                            const ec = echarts.init(dom);
                            chartInstances.value[idx] = ec;

                            const option = buildChartOption(chart.data || {}, chart.chart_type || 'bar');
                            ec.setOption(option);

                            window.addEventListener('resize', () => ec.resize());
                        });
                    });
                }

                function toggleDataLabels(idx) {
                    const ec = chartInstances.value[idx];
                    if (!ec) return;
                    const show = chartShowDataLabels.value[idx] || false;
                    ec.setOption({
                        series: ec.getOption().series.map(s => ({ ...s, label: { ...s.label, show } }))
                    });
                }

                onMounted(() => {
                    reportData.value = window.reportData || {};
                    console.log('[动态报告] reportData:', reportData.value);
                    initCharts();
                });

                return { reportData, reportTitle, reportTime, numericColumns, getScoreColor, getPivotData, getChartTitle, chartShowDataLabels, toggleDataLabels };
            }
        }).use(ElementPlus).mount('#app');
    </script>
</body>
</html>'''
    
    report_data_json = json.dumps(dynamic_data, ensure_ascii=False)
    return dynamic_html.replace('__REPORT_DATA__', report_data_json)