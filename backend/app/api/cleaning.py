from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import re
import io
import time
from app.models import Dataset, User
from app.schemas.dataset import DatasetResponse
from app.services.data_service import DataService, DataCleaningService
from app.services.storage_manager import storage_manager
from app.utils.db import get_db, SessionLocal
from app.utils.security import get_current_user
from app.utils.common import clean_dataset_name, clear_user_dataset_cache, MODULE_LABEL_MAP, validate_upload_file
from app.utils.task_records import (
    create_task_record, update_task_record, update_task_progress,
    mark_task_running, classify_failure, check_task_queue_capacity
)
from app.services.task_manager import task_manager
from app.config import settings
import pandas as pd
import numpy as np
import json
from datetime import datetime, timezone, timedelta
from celery.exceptions import SoftTimeLimitExceeded

# 上海时区（UTC+8），用于生成清洗结果时间戳
SHANGHAI_TZ = timezone(timedelta(hours=8))

router = APIRouter()


# 清洗请求模型
# 问题清单与管道为依赖关系：
# - problem_strategies：问题清单策略，定义各类问题的处理方式
# - pipeline：根据问题清单自动生成，决定执行顺序，并支持追加列操作/行过滤
# - contract：数据契约，提供类型/范围约束
class CleaningRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    # 远程数据源配置（与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None  # {"use_remote": True, "connection_id": N, "table_name": "..."}
    # 四步向导产物：用户定义的清洗管道（保留用户顺序，不再强制重排）
    pipeline: Optional[List[Dict[str, Any]]] = None
    # 四步向导产物：数据契约 {列名: {契约规则}}，结构详见 DataCleaningService.validate_contract 文档
    # 支持字段：expected_type/ranges/decimal_places/min_date/max_date/enum_values/
    #          min_length/max_length/bool_representation/allow_missing/allow_duplicate
    # 旧字段 min_value/max_value（或 min/max/bool_repr）仍兼容，会被 normalize_contract 自动规范化
    contract: Optional[Dict[str, Any]] = None
    # 问题清单模式（Task 7）：按问题清单策略执行清洗
    # 结构：{ "missing_values": [...], "type_errors": [...], "range_errors": [...],
    #         "outliers": [...], "row_duplicates": [...], "column_duplicates": [...] }
    # 每项为该问题的处理策略列表，pipeline 中的 operation 字段决定执行顺序
    problem_strategies: Optional[Dict[str, Any]] = None
    # 是否强制执行（忽略 dry-run 警告），前端确认警告后设为 True
    force: bool = False
    # 是否保存清洗结果（默认不保存，用户在审计页面点击保存时才保存）
    save_result: bool = False


def _build_cleaning_result_summary(
    original_df: pd.DataFrame,
    cleaned_df: pd.DataFrame,
    audit_report: Optional[Dict[str, Any]],
    operations_log: Optional[List[Dict[str, Any]]],
    operations_audit: Optional[List[Dict[str, Any]]],
    warnings: Optional[List] = None,
    save_result: bool = False,
    pipeline: Optional[List[Dict[str, Any]]] = None,
    problem_strategies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造清洗任务 result_summary，统一字段格式便于操作历史展示。

    根据 save_result 区分两种 operation：
    - save_result=False（执行清洗 execute_clean）：记录管道步骤数/列重命名/行过滤/原始行数/审计行数/质量评分/问题数量
    - save_result=True（保存清洗结果 save_clean_result）：记录新数据集信息/原始行数/清洗后行数/移除行数/质量评分/问题数量
    问题数量来源优先级：operations_audit（问题清单模式）> operations_log（管道模式）。
    """
    # 质量评分：从 audit_report.quality_scores 提取 before/after
    quality_scores = (audit_report or {}).get("quality_scores", {}) or {}
    quality_before = quality_scores.get("before", {}) or {}
    quality_after = quality_scores.get("after", {}) or {}

    # 问题数量统计（按 5 类问题归一化）
    problem_counts = {
        "missing_values": 0,
        "duplicates": 0,
        "type_errors": 0,
        "outliers": 0,
        "range_errors": 0,
    }

    # 问题清单模式：operations_audit[].operation + affected_rows
    if operations_audit:
        # operation 字段 -> problem_counts 的 key 映射
        op_field_map = {
            "missing_values": "missing_values",
            "row_duplicates": "duplicates",
            "column_duplicates": "duplicates",
            "type_errors": "type_errors",
            "range_errors": "range_errors",
            "outliers": "outliers",
        }
        for op in operations_audit:
            op_name = op.get("operation", "")
            pc_key = op_field_map.get(op_name)
            if not pc_key:
                continue
            affected = op.get("affected_rows", [])
            if isinstance(affected, list):
                problem_counts[pc_key] += len(affected)
            elif isinstance(affected, (int, float)):
                problem_counts[pc_key] += int(affected)
    elif operations_log:
        # 管道模式：operations_log[].type + affected_rows
        op_type_map = {
            "missing_values": "missing_values",
            "deduplication": "duplicates",
            "type_error": "type_errors",
            "range_error": "range_errors",
            "outlier": "outliers",
        }
        for log in operations_log:
            log_type = log.get("type", "")
            pc_key = op_type_map.get(log_type)
            if not pc_key:
                continue
            affected = log.get("affected_rows", 0)
            if isinstance(affected, (int, float)):
                problem_counts[pc_key] += int(affected)
            elif isinstance(affected, list):
                problem_counts[pc_key] += len(affected)

    # 管道步骤数：优先用 operations_audit 长度，其次 operations_log
    pipeline_steps = len(operations_audit) if operations_audit else (
        len(operations_log) if operations_log else 0
    )

    # 根据 save_result 区分 operation 和返回字段
    if save_result:
        # 保存清洗结果：记录新数据集信息 + 行数变化 + 质量评分 + 问题统计
        return {
            "operation": "save_clean_result",
            "original_rows": int(len(original_df)),
            "cleaned_rows": int(len(cleaned_df)),
            "removed_rows": int(len(original_df) - len(cleaned_df)),
            "quality_before": quality_before,
            "quality_after": quality_after,
            "problem_counts": problem_counts,
            "pipeline_steps": pipeline_steps,
            "warnings_ignored": len(warnings) if warnings else 0,
        }
    else:
        # 执行清洗：记录管道步骤数/列重命名/行过滤/审计行数/质量评分/问题数量（不保存数据集）
        # 从 pipeline 或 problem_strategies 推断是否有列重命名和行过滤
        has_rename = False
        has_row_filter = False
        pipeline_order = []
        # 管道顺序：优先取实际执行的 pipeline（含 column_ops/row_filter，且顺序与执行一致）
        # problem_strategies 仅 6 类问题策略（不含列操作/行过滤），顺序也非用户管道顺序，仅作回退
        if pipeline:
            pipeline_order = [op.get("operation", "") for op in pipeline if isinstance(op, dict)]
            for op in pipeline:
                if isinstance(op, dict):
                    op_name = op.get("operation", "")
                    if "rename" in op_name.lower() or "column" in op_name.lower():
                        has_rename = True
                    if "row" in op_name.lower() or "filter" in op_name.lower():
                        has_row_filter = True
        elif problem_strategies:
            # 回退：从 strategies 的 key 推断（历史/无 pipeline 参数场景）
            pipeline_order = list(problem_strategies.keys()) if isinstance(problem_strategies, dict) else []
            for k in pipeline_order:
                if "rename" in k.lower() or "column" in k.lower():
                    has_rename = True
                if "row" in k.lower() or "filter" in k.lower():
                    has_row_filter = True

        return {
            "operation": "execute_clean",
            "original_rows": int(len(original_df)),
            "audit_rows": int(len(cleaned_df)),
            "quality_before": quality_before,
            "quality_after": quality_after,
            "problem_counts": problem_counts,
            "pipeline_steps": pipeline_steps,
            "pipeline_order": pipeline_order,
            "has_rename": has_rename,
            "has_row_filter": has_row_filter,
            "warnings_ignored": len(warnings) if warnings else 0,
        }



@router.get("/raw-data", response_model=list[DatasetResponse])
async def get_cleaning_raw_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取清洗模块专用的原始数据列表（仅返回 module_source=cleaning 且 artifact_type=raw_data 的数据）"""
    datasets = db.query(Dataset).filter(
        Dataset.module_source == "cleaning",
        Dataset.artifact_type == "raw_data",
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).all()
    return datasets


@router.get("/columns/{dataset_id}")
async def get_dataset_columns(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据集的列名列表"""
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.module_source != "cleaning" or dataset.artifact_type != "raw_data":
        raise HTTPException(status_code=403, detail="只能使用清洗模块的原始数据")

    data_service = DataService(db)
    df = data_service.load_dataset(dataset_id)
    return {"columns": list(df.columns)}


@router.get("/data/{dataset_id}")
async def get_dataset_data(
    dataset_id: int,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(100, ge=1, le=1000, description="每页行数，最大1000"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据集数据（分页，用于前端数据质量检测）

    统一分页返回结构：{columns, rows, total, page, page_size, total_pages}
    """
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.module_source != "cleaning" or dataset.artifact_type != "raw_data":
        raise HTTPException(status_code=403, detail="只能使用清洗模块的原始数据")

    data_service = DataService(db)
    # 使用分页加载，避免全量构建 DataFrame 导致大数据集 OOM
    page_df, total = data_service.load_dataset_page(dataset_id, page, page_size)
    columns = list(page_df.columns)
    # 保持原有的字符串序列化方式（前端依赖此格式）
    rows = page_df.fillna('').astype(str).values.tolist()
    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size)
    }


@router.get("/precheck/{dataset_id}")
async def get_precheck(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """清洗前数据预检：自动检测缺失值、重复行、类型识别、异常值和类型错误，返回数据问题清单"""
    return await _do_precheck(db, current_user, dataset_id=dataset_id)


class PrecheckRequest(BaseModel):
    """预检请求：支持本地数据集和远程数据库"""
    dataset_id: Optional[int] = None
    remote: Optional[Dict[str, Any]] = None


@router.post("/precheck")
async def post_precheck(
    body: PrecheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """清洗前数据预检（POST版）：支持远程数据库"""
    return await _do_precheck(
        db, current_user,
        dataset_id=body.dataset_id,
        remote_config=body.remote
    )


async def _do_precheck(db, current_user, dataset_id=None, remote_config=None):
    """预检核心逻辑（本地/远程统一入口）"""
    data_service = DataService(db)

    # 统一加载数据
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 本地模式验证：只能预检清洗模块上传的原始数据
    if not is_remote and dataset:
        if dataset.module_source != "cleaning" or dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能预检清洗模块上传的原始数据")

    try:
        cleaning_service = DataCleaningService(df)
        precheck_result = cleaning_service.precheck(df)
        return precheck_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-problems/{dataset_id}")
async def analyze_problems(
    dataset_id: int,
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据契约计算数据问题清单

    根据规范化后的契约对原始数据进行六类问题检测：
    缺失值、类型错误、范围错误、异常值、行重复、列重复。
    范围错误优先于异常值（一个值不会同时出现在两个问题组中）。

    Args:
        dataset_id: 数据集ID（远程模式传 0 占位）
        body: { contract: {契约字典}, remote: {远程配置, 可选} }

    Returns:
        {
            "summary": {各问题类型的真实总数},
            "problems": {各问题类型的清单列表}
        }

    说明：
    - problems 列表最多返回前100条/组（行重复5组、列重复10组）以保证响应大小可控
    - 支持远程数据库模式：body 中传入 remote 字段即可
    """
    # 从 body 提取 contract 和 remote 配置
    contract = body.get("contract", {})
    remote_config = body.get("remote")
    is_remote = remote_config and remote_config.get("use_remote")

    data_service = DataService(db)
    try:
        if is_remote:
            # 远程模式：统一加载入口
            df, dataset = data_service.load_module_data(
                dataset_id=None,
                remote_config=remote_config,
                user_id=current_user.id
            )
        else:
            # 1. 验证数据集属于当前用户
            dataset = db.query(Dataset).filter(
                Dataset.id == dataset_id,
                Dataset.user_id == current_user.id,
                Dataset.status == "active"
            ).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="数据集不存在")
            # 限制：只能分析清洗模块上传的原始数据
            if dataset.module_source != "cleaning" or dataset.artifact_type != "raw_data":
                raise HTTPException(status_code=403, detail="只能分析清洗模块上传的原始数据")
            # 2. 加载数据集
            df = data_service.load_dataset(dataset_id)

        cleaning_service = DataCleaningService(df)
        # 3. 规范化契约：兼容旧字段、补充默认值、清理无关字段
        normalized_contract = cleaning_service.normalize_contract(contract or {})
        # 4. 契约校验：拦截不合理的类型配置（如数值列配 date/email/url），
        #    避免用户契约静默失效导致空的问题清单
        contract_validation = cleaning_service.validate_contract(df, contract or {})
        if not contract_validation.get("valid", False):
            # 拼接错误列表为字符串，便于前端直接展示
            errors = contract_validation.get("errors", [])
            error_msg = "; ".join(errors) if errors else "数据契约校验失败"
            raise HTTPException(status_code=400, detail=error_msg)
        # 5. 调用 analyze_problems 计算问题清单
        result = cleaning_service.analyze_problems(df, normalized_contract)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dry-run/{dataset_id}")
async def dry_run(
    dataset_id: int,
    request: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """检查管道配置的合理性

    Task 8：对用户配置的清洗管道进行 dry-run 预检，不实际执行清洗，
    仅返回警告、错误和建议顺序，供前端在执行清洗前确认配置是否合理。

    请求体结构：
    {
        "contract": {列名: {契约规则}},
        "problem_strategies": {问题类型: 策略列表},
        "pipeline": [{"operation": 类型, "params": {...}}],
        "remote": {远程配置, 可选}
    }

    返回结构：
    {
        "valid": 是否可以执行（errors 为空即 True）,
        "warnings": [警告列表],
        "errors": [错误列表],
        "suggested_order": [推荐的操作顺序]
    }
    """
    # 提取远程配置
    remote_config = request.get('remote')
    is_remote = remote_config and remote_config.get("use_remote")

    # 1. 解析请求参数（contract/problem_strategies/pipeline 均可选）
    contract = request.get('contract') or {}
    problem_strategies = request.get('problem_strategies') or {}
    pipeline = request.get('pipeline') or []

    data_service = DataService(db)
    try:
        if is_remote:
            # 远程模式：统一加载入口
            df, dataset = data_service.load_module_data(
                dataset_id=None,
                remote_config=remote_config,
                user_id=current_user.id
            )
        else:
            # 本地模式：验证数据集属于当前用户
            dataset = db.query(Dataset).filter(
                Dataset.id == dataset_id,
                Dataset.user_id == current_user.id,
                Dataset.status == "active"
            ).first()
            if not dataset:
                raise HTTPException(status_code=404, detail="数据集不存在")
            # 限制：只能对清洗模块上传的原始数据进行 dry-run 预检
            if dataset.module_source != "cleaning" or dataset.artifact_type != "raw_data":
                raise HTTPException(status_code=403, detail="只能对清洗模块上传的原始数据进行 dry-run 预检")
            # 加载数据集
            df = data_service.load_dataset(dataset_id)

        cleaning_service = DataCleaningService(df)
        # 2. 契约校验：规范化契约，避免契约本身矛盾影响 dry-run 检查
        contract_validation = cleaning_service.validate_contract(df, contract)
        normalized_contract = contract_validation.get("normalized_contract", contract)
        # 3. 调用 dry_run_pipeline 进行预检，返回警告/错误/建议顺序
        result = cleaning_service.dry_run_pipeline(
            df, normalized_contract, problem_strategies, pipeline
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=DatasetResponse)
async def cleaning_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传文件到清洗模块，artifact_type=raw_data, module_source=cleaning"""
    import time as _time
    start_time = _time.time()

    validate_upload_file(file)

    name = clean_dataset_name(file.filename)

    # 创建任务记录，与数据管理上传接口保持一致
    task_record = create_task_record(
        db=db,
        task_type="upload",
        user_id=current_user.id,
        params={"filename": name, "module_source": "cleaning", "artifact_type": "raw_data"}
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
        execution_time = int((_time.time() - start_time) * 1000)
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
        file_path=file_path,
        file_size=file_size,
        schema=schema,
        row_count=row_count,
        data_preview=str(data_preview[:5]),
        module_source="cleaning",
        module_label=MODULE_LABEL_MAP.get("cleaning", "数据清洗"),
        artifact_type="raw_data",
        user_id=current_user.id
    )
    db.add(new_dataset)
    db.commit()
    db.refresh(new_dataset)

    # 更新任务记录为成功
    execution_time = int((_time.time() - start_time) * 1000)
    update_task_record(
        db=db,
        record_id=task_record.id,
        status="success",
        dataset_id=new_dataset.id,
        result_summary={
            "dataset_name": new_dataset.name,
            "row_count": new_dataset.row_count,
            "column_count": len(df.columns),
            "file_size": new_dataset.file_size
        },
        execution_time=execution_time
    )

    clear_user_dataset_cache(current_user.id)

    # 触发 ClickHouse 副本同步（raw_data 且行数达阈值时在任务内同步；失败不影响上传）
    from app.services.clickhouse_service import trigger_sync
    trigger_sync(new_dataset.id)

    return new_dataset


class CleaningStepRecordRequest(BaseModel):
    """清洗向导步骤记录请求"""
    dataset_id: int
    step: str  # contract_config / problem_strategy
    contract: Optional[Dict[str, Any]] = None
    problem_strategies: Optional[Dict[str, Any]] = None


@router.post("/record-step")
async def record_cleaning_step(
    body: CleaningStepRecordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """记录清洗向导的步骤配置（阶段1契约/阶段2问题清单）

    前端在点击"下一步：问题清单"时记录契约配置，
    点击"下一步：管道配置"时记录问题清单策略。
    阶段3/4由 /comprehensive 接口根据 save_result 自动区分。
    """
    # 校验数据集存在且属于当前用户（修复：原查询未带 user_id 过滤，可对他人数据集写入操作记录）
    dataset = db.query(Dataset).filter(
        Dataset.id == body.dataset_id,
        Dataset.user_id == current_user.id
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    start_time = time.time()

    if body.step == "contract_config":
        # 阶段1：契约配置
        contract_fields = len(body.contract) if body.contract else 0
        task_record = create_task_record(
            db=db,
            task_type="cleaning",
            user_id=current_user.id,
            dataset_id=body.dataset_id,
            params={
                "dataset_name": dataset.name,
                "operation": "contract_config",
                "contract": body.contract,
            }
        )
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="success",
            result_summary={
                "operation": "contract_config",
                "column_count": contract_fields,
                "contract_fields": contract_fields,
            },
            execution_time=execution_time
        )
        return {"status": "success", "message": "契约配置已记录"}

    elif body.step == "problem_strategy":
        # 阶段2：问题清单配置
        # 统计各类问题数量
        problem_counts = {}
        affected_columns = set()
        if body.problem_strategies:
            for problem_type, strategies in body.problem_strategies.items():
                if isinstance(strategies, list):
                    problem_counts[problem_type] = len(strategies)
                    for s in strategies:
                        if isinstance(s, dict) and "column" in s:
                            affected_columns.add(s["column"])
                        elif isinstance(s, dict) and "columns" in s:
                            affected_columns.update(s["columns"] if isinstance(s["columns"], list) else [s["columns"]])

        task_record = create_task_record(
            db=db,
            task_type="cleaning",
            user_id=current_user.id,
            dataset_id=body.dataset_id,
            params={
                "dataset_name": dataset.name,
                "operation": "problem_strategy",
                "problem_strategies": body.problem_strategies,
            }
        )
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="success",
            result_summary={
                "operation": "problem_strategy",
                "problem_counts": problem_counts,
                "affected_columns": len(affected_columns),
            },
            execution_time=execution_time
        )
        return {"status": "success", "message": "问题清单配置已记录"}

    else:
        raise HTTPException(status_code=400, detail=f"未知的 step: {body.step}")


def _reject_sampled_save(df, task_record_id: int, start_time: float, db: Session):
    """大表采样数据禁止保存为清洗结果

    远程表超过 5 万行时按采样数据执行清洗预览，采样结果只是全量的子集，
    直接保存为"清洗后数据集"会误导用户认为已清洗全量数据。
    应提示用户先导入为本地数据集再对全量执行清洗。
    """
    if df.attrs.get('is_sampled'):
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="failed",
            error_message="当前远程表超过 5 万行，清洗是在采样数据上执行的预览，"
                          "请先将该表导入为本地数据集，再对全量数据执行清洗并保存",
            execution_time=execution_time,
            failure_category="param_error"
        )
        raise HTTPException(
            status_code=400,
            detail="当前远程表超过 5 万行，清洗是在采样数据上执行的预览。"
                   "请先将该表导入为本地数据集，再对全量数据执行清洗并保存"
        )


@router.post("/comprehensive")
async def comprehensive_clean(
    body: Optional[CleaningRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """综合清洗：执行多种清洗并保存结果为 cleaning_result 产物

    问题清单与管道为依赖关系：
    - problem_strategies：问题清单策略，定义缺失值/类型错误/范围错误/异常值/重复值等的处理方式
    - pipeline：根据问题清单自动生成，决定执行顺序，并允许追加列操作（重命名/删除/类型转换）和行过滤
    - contract：数据契约，提供类型/范围约束，供类型错误处理和缺失值智能填充使用
    - force：dry-run 检测到警告时是否强制执行

    实际执行时，若传入 problem_strategies 则优先走问题清单分支；
    纯 pipeline 分支需保证前端结构与 execute_pipeline() 内部格式一致（当前不一致，见 code_issues.md 3.2）。
    """
    # 合并参数：优先使用 JSON body 中的值
    dataset_id = body.dataset_id if body else None
    remote_config = body.remote if body else None
    # 四步向导产物
    pipeline = body.pipeline if body else None
    contract = body.contract if body else None
    force = body.force if body else False
    # 问题清单模式（Task 7）
    problem_strategies = body.problem_strategies if body else None
    # 是否保存清洗结果
    save_result = body.save_result if body else False

    # 至少需要一个数据源
    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="缺少 dataset_id 或 remote 参数")

    # 统一数据加载（本地数据集或远程数据库）
    data_service = DataService(db)
    try:
        df, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 调试日志
    if is_remote:
        print(f"[CleaningAPI] 接收请求 remote={remote_config}, "
              f"problem_strategies={problem_strategies is not None}, "
              f"pipeline={pipeline is not None}")
    else:
        print(f"[CleaningAPI] 接收请求 dataset_id={dataset_id}, "
              f"problem_strategies={problem_strategies is not None}, "
              f"pipeline={pipeline is not None}")

    # 本地数据集模式：验证来源必须是 cleaning 模块的原始数据
    if not is_remote and original_dataset:
        if original_dataset.module_source != "cleaning" or original_dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能使用清洗模块上传的原始数据进行清洗操作")

    # 埋点：创建任务记录（status=running）
    start_time = time.time()
    operation_name = "save_clean_result" if save_result else "execute_clean"
    task_record = create_task_record(
        db=db,
        task_type="cleaning",
        user_id=current_user.id,
        dataset_id=dataset_id,  # 远程模式下为 None
        params={
            "dataset_name": original_dataset.name if original_dataset else remote_config.get("table_name", "远程表"),
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": operation_name,
            "mode": "problem_strategies" if problem_strategies else (
                "pipeline" if pipeline else "unknown"
            ),
            "config": {
                "pipeline": pipeline,
                "problem_strategies": problem_strategies
            } if problem_strategies else (
                pipeline if pipeline else {}
            ),
            "contract": contract or {},
            "force": force,
            "save_confirmed": save_result
        }
    )

    data_service = DataService(db)

    # 行数判断：远程模式使用已加载 df 的长度，本地模式使用 dataset.row_count
    if is_remote:
        row_count = len(df)
    else:
        row_count = original_dataset.row_count or 0
    ASYNC_THRESHOLD = settings.ASYNC_THRESHOLD

    # 远程模式暂不支持异步（Celery 任务路径改动较大），强制走同步
    original_df_for_comparison = None

    # ============================================================
    # 问题清单模式分支（Task 7）：problem_strategies + pipeline + contract
    # 智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
    # 远程模式：强制走同步
    # ============================================================
    try:
        if problem_strategies is not None:
            # 远程模式强制同步
            if not is_remote and row_count >= ASYNC_THRESHOLD:
                # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
                if not task_manager.is_async_available():
                    execution_time = int((time.time() - start_time) * 1000)
                    update_task_record(
                        db=db,
                        record_id=task_record.id,
                        status="failed",
                        error_message="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集",
                        execution_time=execution_time,
                        failure_category="system_error"
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集"
                    )

                # 任务排队机制：检查用户队列容量，决定立即执行还是进入等待队列
                try:
                    can_run_now, queue_msg = check_task_queue_capacity(
                        db, current_user.id, exclude_task_id=task_record.id
                    )
                except HTTPException as queue_err:
                    execution_time = int((time.time() - start_time) * 1000)
                    update_task_record(
                        db=db,
                        record_id=task_record.id,
                        status="failed",
                        error_message=str(queue_err.detail),
                        execution_time=execution_time,
                        failure_category="param_error"
                    )
                    raise queue_err

                if can_run_now:
                    # 立即执行：提交到 Celery 队列
                    task_result = task_manager.run_task(
                        _execute_cleaning_pipeline,
                        task_record_id=task_record.id,
                        user_id=current_user.id,
                        dataset_id=dataset_id,
                        pipeline=pipeline or [],
                        contract=contract or {},
                        force=force,
                        problem_strategies=problem_strategies,
                        save_result=save_result,
                        no_degrade=True
                    )
                    celery_task_id = task_result.get("task_id")
                    if celery_task_id:
                        mark_task_running(db, task_record.id, celery_task_id=celery_task_id)
                    return {
                        "task_record_id": task_record.id,
                        "task_id": celery_task_id,
                        "status": "running",
                        "message": "数据清洗任务已提交，请在右上角任务面板查看进度",
                        "row_count": row_count
                    }
                else:
                    # 进入等待队列：不提交 Celery，由调度器自动激活
                    task_record.status = "pending"
                    db.commit()
                    return {
                        "task_record_id": task_record.id,
                        "task_id": None,
                        "status": "pending",
                        "message": f"清洗任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                        "row_count": row_count
                    }

            # 小数据集：同步执行，此时才加载完整数据（远程模式已加载）
            if is_remote:
                # 远程模式：df 已在 load_module_data 中加载，只设置对比副本
                original_df_for_comparison = df.copy()
            else:
                df = data_service.load_dataset(dataset_id)
                original_df_for_comparison = df.copy()
            print(f"[清洗调试] 原始数据行数: {len(df)}, 列数: {len(df.columns)}")
            cleaning_service = DataCleaningService(df)

            # 1. 契约校验：避免契约本身矛盾（如 min > max）导致后续清洗失败
            contract_validation = cleaning_service.validate_contract(df, contract or {})
            if not contract_validation.get("valid", False):
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="failed",
                    error_message="契约校验失败: " + "; ".join(contract_validation.get("errors", [])),
                    execution_time=execution_time,
                    failure_category="param_error"
                )
                raise HTTPException(
                    status_code=400,
                    detail={
                        "status": "contract_invalid",
                        "errors": contract_validation.get("errors", []),
                        "message": "数据契约校验失败，请检查契约配置"
                    }
                )

            # 使用规范化后的契约进行后续清洗
            normalized_contract = contract_validation.get("normalized_contract", contract or {})

            # 2. dry-run 预检：检测列依赖冲突、缺失值填充位置等
            # 若同时传入 pipeline（决定执行顺序），用其作为 dry-run 检测依据
            warnings = []
            dry_run_errors = []
            if pipeline:
                # Task 8：调用新的 dry_run_pipeline 接口（返回 dict 结构）
                dry_run_result = cleaning_service.dry_run_pipeline(
                    df, normalized_contract, problem_strategies, pipeline
                )
                warnings = dry_run_result.get('warnings', [])
                dry_run_errors = dry_run_result.get('errors', [])

            # 2.5 错误阻断：若存在 errors，直接返回 error，不允许强制执行
            if dry_run_errors:
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="error",
                    result_summary={
                        "errors_count": len(dry_run_errors),
                        "errors": dry_run_errors
                    },
                    execution_time=execution_time
                )
                return {
                    "status": "error",
                    "errors": dry_run_errors,
                    "message": "检测到配置错误，请修正后重新执行"
                }

            # 3. 警告拦截：若存在警告且未强制执行，返回 warning 让前端确认后重试
            if warnings and not force:
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="warning",
                    result_summary={
                        "warnings_count": len(warnings),
                        "warnings": warnings
                    },
                    execution_time=execution_time
                )
                return {
                    "status": "warning",
                    "warnings": warnings,
                    "message": "检测到潜在问题，请确认后重新请求"
                }

            # 4. 执行清洗：按问题清单策略执行，返回清洗后 df 和审计信息
            try:
                cleaning_result = cleaning_service.execute_cleaning_with_strategies(
                    df, normalized_contract, problem_strategies, pipeline or []
                )
            except ValueError as e:
                # 自定义值校验失败等业务异常，记录后返回 400
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="failed",
                    error_message=str(e),
                    execution_time=execution_time,
                    failure_category=classify_failure(e)
                )
                raise HTTPException(status_code=400, detail=str(e))

            cleaned_df = cleaning_result["cleaned_df"]
            audit_info = cleaning_result["audit"]
            operations_audit = audit_info.get("operations", [])

            # 5. 生成对比审计报告（基于清洗前后差异 + 问题清单审计信息）
            # 复用 generate_audit_report 计算行列级差异，再合并 execute_cleaning_with_strategies 的审计
            # 构建更丰富的 operations_log：包含每个 strategy 项的 method 和 column，便于推断错误类型
            operations_log_for_audit = []
            for op in operations_audit:
                op_type = op.get("operation", "")
                op_changes = op.get("changes", [])
                # 将每个变更项展开为一条操作日志，包含 method 和 column
                if op_changes:
                    for ch in op_changes:
                        operations_log_for_audit.append({
                            "type": op_type,
                            "method": ch.get("strategy", ""),
                            "columns": [ch.get("column", "")] if ch.get("column") else [],
                            "affected_rows": 1,
                            # 保留原始变更信息（含 row_index/column/strategy/status），
                            # 供 generate_audit_report 按 (row_index, column) 精确匹配处理方式
                            "changes": [ch]
                        })
                else:
                    # 没有变更的操作（仅删除行等），按行聚合
                    operations_log_for_audit.append({
                        "type": op_type,
                        "method": "",
                        "columns": [],
                        "affected_rows": len(op.get("affected_rows", []))
                    })
            audit_report = cleaning_service.generate_audit_report(
                original_df_for_comparison, cleaned_df,
                operations_log_for_audit,
                # 传入契约用于质量评分计算（一致性和有效性需要列的 expected_type）
                contract=normalized_contract
            )
            # 合并 execute_cleaning_with_strategies 返回的审计信息
            audit_report["problem_strategies_audit"] = audit_info
            # 保留 generate_audit_report 生成的完整 quality_scores（包含 before 和 after），不被覆盖
            if "quality_scores" not in audit_report:
                audit_report["quality_scores"] = audit_info.get("quality_scores", {})

            # 6. 保存清洗结果到 MinIO（仅在 save_result=True 时保存）
            clean_dataset = None
            if save_result:
                # 大表采样数据禁止保存为清洗结果（采样是子集，保存会误导用户）
                _reject_sampled_save(df, task_record.id, start_time, db)
                if is_remote:
                    original_name = remote_config.get("table_name", "remote_table")
                    parent_id = None  # 远程表无父数据集
                else:
                    original_name = original_dataset.name.rsplit(".", 1)[0]
                    parent_id = dataset_id
                original_name = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', original_name)
                timestamp = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H-%M-%S")
                clean_filename = f"{original_name}_clean_{timestamp}.csv"

                csv_buffer = io.StringIO()
                cleaned_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                csv_content = csv_buffer.getvalue().encode('utf-8')

                object_name = f"cleaning/user_{current_user.id}/{clean_filename}"
                clean_file_path = storage_manager.save_bytes(object_name, csv_content)

                # 算法描述：基于问题清单审计构建可读字符串
                algorithm_parts_new = []
                op_type_desc_map = {
                    'row_duplicates': '行重复处理', 'column_duplicates': '列重复处理',
                    'type_errors': '类型错误处理', 'range_errors': '范围错误处理',
                    'outliers': '异常值处理', 'missing_values': '缺失值处理',
                    'column_ops': '列操作', 'row_filter': '行过滤'
                }
                for op in operations_audit:
                    op_name = op.get("operation", "")
                    op_desc = op_type_desc_map.get(op_name, op_name)
                    details = op.get("details", "")
                    algorithm_parts_new.append(f"{op_desc}({details})" if details else op_desc)
                algorithm_desc = "+".join(algorithm_parts_new) if algorithm_parts_new else "问题清单清洗"

                # 命名方案：产物保留源名（剥离历史拼接），不追加时间戳/清洗等后缀，靠 #id/颜色区分
                clean_name = f"{clean_dataset_name(original_name)}.csv"
                clean_file_size = len(csv_content)
                clean_dataset = Dataset(
                    name=clean_name,
                    file_path=clean_file_path,
                    file_size=clean_file_size,
                    schema=data_service.get_schema(cleaned_df),
                    row_count=len(cleaned_df),
                    data_preview=str(data_service.get_sample_data(cleaned_df, 5)),
                    module_source="cleaning",
                    module_label=MODULE_LABEL_MAP.get("cleaning", "数据清洗"),
                    algorithm=algorithm_desc,
                    parent_id=parent_id,
                    artifact_type="cleaning_result",
                    user_id=current_user.id,
                    # 远程来源血缘字段
                    connection_id=remote_config.get("connection_id") if is_remote else None,
                    table_name=remote_config.get("table_name") if is_remote else None,
                    root_connection_id=remote_config.get("connection_id") if is_remote else None,
                    source_type="derived"
                )
                db.add(clean_dataset)
                db.commit()
                db.refresh(clean_dataset)

                clear_user_dataset_cache(current_user.id)

            # 埋点：更新任务记录为成功
            execution_time = int((time.time() - start_time) * 1000)
            # 构造结构化 result_summary（补全质量评分/问题数量/管道步骤等字段）
            cleaning_summary = _build_cleaning_result_summary(
                original_df=original_df_for_comparison,
                cleaned_df=cleaned_df,
                audit_report=audit_report,
                operations_log=None,  # 问题清单模式无 operations_log
                operations_audit=operations_audit,
                warnings=warnings,
                save_result=save_result,
                problem_strategies=problem_strategies,
            )
            # 保留产物字段（new_dataset_id/new_dataset_name）便于操作历史跳转
            cleaning_summary["new_dataset_id"] = clean_dataset.id if clean_dataset else None
            cleaning_summary["new_dataset_name"] = clean_dataset.name if clean_dataset else None
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="success",
                dataset_id=clean_dataset.id if clean_dataset else None,
                result_summary=cleaning_summary,
                execution_time=execution_time
            )

            result = {
                "status": "success",
                "audit_report": audit_report
            }
            if clean_dataset:
                result["cleaned_dataset_id"] = clean_dataset.id
                result["cleaning_result"] = {
                    "id": clean_dataset.id,
                    "name": clean_dataset.name,
                    "artifact_type": clean_dataset.artifact_type,
                    "algorithm": clean_dataset.algorithm
                }
            return result

        # ============================================================
        # 新模式分支：四步向导产物（pipeline + contract + force）
        # 智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
        # 流程：契约校验 -> dry-run 预检 -> 警告拦截 -> 执行管道 -> 审计报告
        # ============================================================
        if pipeline is not None:
            # 智能异步分发：≥1万行异步提交到 Celery，<1万行同步执行
            # 远程模式：强制同步执行（_execute_cleaning_pipeline 不支持 remote_config）
            # 阈值与 ml.train_supervised_model 保持一致（ASYNC_THRESHOLD=settings.ASYNC_THRESHOLD）
            # 使用 dataset.row_count 判断行数，避免大数据集无谓加载
            if not is_remote and row_count >= ASYNC_THRESHOLD:
                # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
                if not task_manager.is_async_available():
                    execution_time = int((time.time() - start_time) * 1000)
                    update_task_record(
                        db=db,
                        record_id=task_record.id,
                        status="failed",
                        error_message="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集",
                        execution_time=execution_time,
                        failure_category="system_error"
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集"
                    )

                # 任务排队机制：检查用户队列容量，决定立即执行还是进入等待队列
                try:
                    can_run_now, queue_msg = check_task_queue_capacity(
                        db, current_user.id, exclude_task_id=task_record.id
                    )
                except HTTPException as queue_err:
                    execution_time = int((time.time() - start_time) * 1000)
                    update_task_record(
                        db=db,
                        record_id=task_record.id,
                        status="failed",
                        error_message=str(queue_err.detail),
                        execution_time=execution_time,
                        failure_category="param_error"
                    )
                    raise queue_err

                if can_run_now:
                    # 立即执行：提交到 Celery 队列
                    task_result = task_manager.run_task(
                        _execute_cleaning_pipeline,
                        task_record_id=task_record.id,
                        user_id=current_user.id,
                        dataset_id=dataset_id,
                        pipeline=pipeline,
                        contract=contract or {},
                        force=force,
                        save_result=save_result,
                        no_degrade=True
                    )
                    celery_task_id = task_result.get("task_id")
                    if celery_task_id:
                        mark_task_running(db, task_record.id, celery_task_id=celery_task_id)
                    return {
                        "task_record_id": task_record.id,
                        "task_id": celery_task_id,
                        "status": "running",
                        "message": "数据清洗任务已提交，请在右上角任务面板查看进度",
                        "row_count": row_count
                    }
                else:
                    # 进入等待队列：不提交 Celery，由调度器自动激活
                    task_record.status = "pending"
                    db.commit()
                    return {
                        "task_record_id": task_record.id,
                        "task_id": None,
                        "status": "pending",
                        "message": f"清洗任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                        "row_count": row_count
                    }

            # 小数据集或远程模式：同步执行
            # 远程模式：df 已在 load_module_data 中加载，只需设置对比副本
            # 本地模式：此时才加载完整数据
            if is_remote:
                original_df_for_comparison = df.copy()
            else:
                if df is None:
                    df = data_service.load_dataset(dataset_id)
                original_df_for_comparison = df.copy()
            cleaning_service = DataCleaningService(df)

            # 1. 契约校验：避免契约本身矛盾（如 min > max）导致后续清洗失败
            contract_validation = cleaning_service.validate_contract(df, contract or {})
            if not contract_validation.get("valid", False):
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="failed",
                    error_message="契约校验失败: " + "; ".join(contract_validation.get("errors", [])),
                    execution_time=execution_time,
                    failure_category="param_error"
                )
                raise HTTPException(
                    status_code=400,
                    detail={
                        "status": "contract_invalid",
                        "errors": contract_validation.get("errors", []),
                        "message": "数据契约校验失败，请检查契约配置"
                    }
                )

            # 2. dry-run 预检：检测列依赖冲突、缺失值填充位置、类型转换冲突等
            # Task 8：pipeline 模式无 problem_strategies，传入空字典
            dry_run_result = cleaning_service.dry_run_pipeline(
                df, contract or {}, {}, pipeline or []
            )
            warnings = dry_run_result.get('warnings', [])
            dry_run_errors = dry_run_result.get('errors', [])

            # 2.5 错误阻断：若存在 errors，直接返回 error
            if dry_run_errors:
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="error",
                    result_summary={
                        "errors_count": len(dry_run_errors),
                        "errors": dry_run_errors
                    },
                    execution_time=execution_time
                )
                return {
                    "status": "error",
                    "errors": dry_run_errors,
                    "message": "检测到配置错误，请修正后重新执行"
                }

            # 3. 警告拦截：若存在警告且未强制执行，返回 warning 让前端确认后重试
            if warnings and not force:
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db,
                    record_id=task_record.id,
                    status="warning",
                    result_summary={
                        "warnings_count": len(warnings),
                        "warnings": warnings
                    },
                    execution_time=execution_time
                )
                return {
                    "status": "warning",
                    "warnings": warnings,
                    "message": "检测到潜在问题，请确认后重新请求"
                }

            # 4. 执行清洗管道：按用户定义顺序执行，返回清洗后 df 和操作日志
            cleaned_df, operations_log = cleaning_service.execute_pipeline(
                df, pipeline, contract or {}
            )

            # 5. 生成审计报告：对比清洗前后差异并计算质量评分
            audit_report = cleaning_service.generate_audit_report(
                original_df_for_comparison, cleaned_df, operations_log,
                contract=contract or {}
            )

            # 6. 保存清洗结果到 MinIO（时间戳命名，artifact_type=cleaning_result，仅在 save_result=True 时保存）
            clean_dataset = None
            if save_result:
                # 大表采样数据禁止保存为清洗结果（采样是子集，保存会误导用户）
                _reject_sampled_save(df, task_record.id, start_time, db)
                if is_remote:
                    original_name = remote_config.get("table_name", "remote_table")
                    parent_id = None
                else:
                    original_name = original_dataset.name.rsplit(".", 1)[0]
                    parent_id = dataset_id
                original_name = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', original_name)
                timestamp = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H-%M-%S")
                clean_filename = f"{original_name}_clean_{timestamp}.csv"

                csv_buffer = io.StringIO()
                cleaned_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                csv_content = csv_buffer.getvalue().encode('utf-8')

                object_name = f"cleaning/user_{current_user.id}/{clean_filename}"
                clean_file_path = storage_manager.save_bytes(object_name, csv_content)

                # 算法描述：基于操作日志构建可读字符串，便于审计追溯
                algorithm_parts_new = []
                for log_item in operations_log:
                    op_type_desc = {
                        'deduplication': '去重', 'missing_values': '缺失值填充',
                        'outlier': '异常值处理', 'type_error': '类型错误处理',
                        'range_error': '范围错误处理', 'column_op': '列操作',
                        'row_filter': '行过滤'
                    }.get(log_item.get('type'), log_item.get('type', '未知'))
                    method_desc = log_item.get('method', '')
                    algorithm_parts_new.append(
                        f"{op_type_desc}({method_desc})" if method_desc else op_type_desc
                    )
                algorithm_desc = "+".join(algorithm_parts_new) if algorithm_parts_new else "管道清洗"

                # 命名方案：产物保留源名（剥离历史拼接），不追加时间戳/清洗等后缀，靠 #id/颜色区分
                clean_name = f"{clean_dataset_name(original_name)}.csv"
                clean_file_size = len(csv_content)
                clean_dataset = Dataset(
                    name=clean_name,
                    file_path=clean_file_path,
                    file_size=clean_file_size,
                    schema=data_service.get_schema(cleaned_df),
                    row_count=len(cleaned_df),
                    data_preview=str(data_service.get_sample_data(cleaned_df, 5)),
                    module_source="cleaning",
                    module_label=MODULE_LABEL_MAP.get("cleaning", "数据清洗"),
                    algorithm=algorithm_desc,
                    parent_id=parent_id,
                    artifact_type="cleaning_result",
                    user_id=current_user.id,
                    # 远程来源血缘字段
                    connection_id=remote_config.get("connection_id") if is_remote else None,
                    table_name=remote_config.get("table_name") if is_remote else None,
                    root_connection_id=remote_config.get("connection_id") if is_remote else None,
                    source_type="derived"
                )
                db.add(clean_dataset)
                db.commit()
                db.refresh(clean_dataset)

                clear_user_dataset_cache(current_user.id)

            # 埋点：更新任务记录为成功
            execution_time = int((time.time() - start_time) * 1000)
            # 构造结构化 result_summary（pipeline 模式：从 operations_log 统计问题数量）
            cleaning_summary = _build_cleaning_result_summary(
                original_df=original_df_for_comparison,
                cleaned_df=cleaned_df,
                audit_report=audit_report,
                operations_log=operations_log,
                operations_audit=None,  # pipeline 模式无 operations_audit
                warnings=warnings,
                save_result=save_result,
                pipeline=pipeline,
            )
            # 保留产物字段便于操作历史跳转
            cleaning_summary["new_dataset_id"] = clean_dataset.id if clean_dataset else None
            cleaning_summary["new_dataset_name"] = clean_dataset.name if clean_dataset else None
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="success",
                dataset_id=clean_dataset.id if clean_dataset else None,
                result_summary=cleaning_summary,
                execution_time=execution_time
            )

            result = {
                "status": "success",
                "audit_report": audit_report
            }
            if clean_dataset:
                result["cleaned_dataset_id"] = clean_dataset.id
                result["cleaning_result"] = {
                    "id": clean_dataset.id,
                    "name": clean_dataset.name,
                    "artifact_type": clean_dataset.artifact_type,
                    "algorithm": clean_dataset.algorithm
                }
            return result

        # 旧模式（operations 字典）已删除，前端统一使用 pipeline + problem_strategies 模式
        # 若执行到此说明既没有走异步分支，也没有走同步的 pipeline/problem_strategies 分支
        # 这种情况理论上不会发生（前面同步分支已覆盖 pipeline 和 problem_strategies 两种情况）
        # 保留兜底错误以防逻辑漏洞
        raise HTTPException(
            status_code=400,
            detail="未匹配到有效的清洗模式，请传入 pipeline + contract 或 problem_strategies"
        )
    except ValueError as e:
        import traceback
        print(f"[清洗错误] ValueError: {e}")
        print(f"[清洗错误] Traceback:\n{traceback.format_exc()}")
        # 埋点：更新任务记录为失败（含失败分类，便于前端展示和重试控制）
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="failed",
            error_message=str(e),
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise HTTPException(status_code=400, detail=str(e))


@task_manager.register_task
def _execute_cleaning_pipeline(task_record_id: int, user_id: int, dataset_id: int,
                                pipeline: list, contract: dict, force: bool,
                                problem_strategies: dict = None,
                                save_result: bool = False):
    """清洗核心执行函数（同步/异步共用入口）

    支持两种清洗模式（由 problem_strategies 是否传入决定）：
    1. 问题清单模式（Task 7）：调用 execute_cleaning_with_strategies 按问题清单策略执行
    2. 管道模式：调用 execute_pipeline 按 operation 顺序执行

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 预检(10%)：加载数据集
    - 契约校验(20%)：校验数据契约 + dry-run 预检
    - 管道执行(30%/50%/80%)：执行清洗管道
    - 审计对比(100%)：生成审计报告并保存结果

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID
        pipeline: 用户定义的清洗管道（保留用户顺序），决定 operation 执行顺序
        contract: 数据契约
        force: 是否强制执行（忽略 dry-run 警告）
        problem_strategies: 问题清单策略（Task 7），传入时启用问题清单模式

    Returns:
        清洗结果字典（与原同步接口返回结构保持一致）
    """
    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()
    # 问题清单模式标志：传入 problem_strategies 即启用该模式
    use_problem_strategies = problem_strategies is not None

    try:
        # ===== 阶段1：预检（10%） =====
        update_task_progress(db, task_record_id, "预检", 10, "正在预检数据")

        original_dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.status == "active").first()
        if not original_dataset:
            raise ValueError(f"数据集 {dataset_id} 不存在或已被删除")

        data_service = DataService(db)
        df = data_service.load_dataset(dataset_id)
        # 保存原始数据副本，用于后续审计对比和质量评分计算
        original_df_for_comparison = df.copy()

        # ===== 阶段2：契约校验（20%） =====
        update_task_progress(db, task_record_id, "契约校验", 20, "正在校验数据契约")

        cleaning_service = DataCleaningService(df)
        # 契约校验：避免契约本身矛盾（如 min > max）导致后续清洗失败
        contract_validation = cleaning_service.validate_contract(df, contract or {})
        if not contract_validation.get("valid", False):
            raise ValueError("契约校验失败: " + "; ".join(contract_validation.get("errors", [])))
        # 使用规范化后的契约进行后续清洗（包含默认值与类型清理）
        normalized_contract = contract_validation.get("normalized_contract", contract or {})

        # dry-run 预检：检测列依赖冲突、缺失值填充位置、类型转换冲突等
        # Task 8：根据模式传入对应参数调用新的 dry_run_pipeline 接口（返回 dict）
        if use_problem_strategies:
            dry_run_result = cleaning_service.dry_run_pipeline(
                df, normalized_contract, problem_strategies or {}, pipeline or []
            )
        else:
            dry_run_result = cleaning_service.dry_run_pipeline(
                df, normalized_contract, {}, pipeline or []
            )
        warnings = dry_run_result.get('warnings', [])
        dry_run_errors = dry_run_result.get('errors', [])

        # 错误阻断：若存在 errors，直接报错
        if dry_run_errors:
            raise ValueError("配置错误: " + "; ".join([e.get('message', str(e)) for e in dry_run_errors]))

        # 警告拦截：异步模式下若存在警告且未强制执行，更新 task_record 为 warning 状态
        # 用户通过轮询 task_record 看到 warning 后，可携带 force=True 重新请求
        if warnings and not force:
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="warning",
                result_summary={
                    "warnings_count": len(warnings),
                    "warnings": warnings
                },
                execution_time=execution_time
            )
            return {
                "status": "warning",
                "warnings": warnings,
                "message": "检测到潜在问题，请确认后重新请求"
            }

        # ===== 阶段3：管道执行（30%/50%/80%） =====
        update_task_progress(db, task_record_id, "管道执行", 30, "正在执行清洗管道")

        # 根据模式选择执行方法
        # 问题清单模式：调用 execute_cleaning_with_strategies
        # 管道模式：调用 execute_pipeline
        if use_problem_strategies:
            cleaning_result = cleaning_service.execute_cleaning_with_strategies(
                df, normalized_contract, problem_strategies, pipeline or []
            )
            cleaned_df = cleaning_result["cleaned_df"]
            audit_info = cleaning_result["audit"]
            operations_audit = audit_info.get("operations", [])
            # 转换为 generate_audit_report 兼容的 operations_log 格式
            operations_log = [
                {
                    "type": op.get("operation", ""),
                    "method": "",
                    "columns": [],
                    "affected_rows": len(op.get("affected_rows", []))
                }
                for op in operations_audit
            ]
        else:
            # 执行清洗管道：按用户定义顺序执行，返回清洗后 df 和操作日志
            cleaned_df, operations_log = cleaning_service.execute_pipeline(
                df, pipeline, normalized_contract
            )
            operations_audit = []
            audit_info = None

        update_task_progress(db, task_record_id, "管道执行", 50, "正在执行清洗管道")

        update_task_progress(db, task_record_id, "管道执行", 80, "正在执行清洗管道")

        # ===== 阶段4：审计对比（100%） =====
        update_task_progress(db, task_record_id, "审计对比", 100, "清洗完成，生成审计报告")

        # 生成审计报告：对比清洗前后差异并计算质量评分
        audit_report = cleaning_service.generate_audit_report(
            original_df_for_comparison, cleaned_df, operations_log,
            contract=contract or {}
        )
        # 问题清单模式：合并 execute_cleaning_with_strategies 返回的审计信息
        if use_problem_strategies and audit_info:
            audit_report["problem_strategies_audit"] = audit_info
            # 保留 generate_audit_report 生成的完整 quality_scores（包含 before 和 after），不被覆盖
            if "quality_scores" not in audit_report:
                audit_report["quality_scores"] = audit_info.get("quality_scores", {})

        # 保存清洗结果到 MinIO（仅在 save_result=True 时保存）
        clean_dataset = None
        if save_result:
            original_name = original_dataset.name.rsplit(".", 1)[0]
            original_name = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', original_name)
            timestamp = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H-%M-%S")
            clean_filename = f"{original_name}_clean_{timestamp}.csv"

            csv_buffer = io.StringIO()
            cleaned_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            csv_content = csv_buffer.getvalue().encode('utf-8')

            object_name = f"cleaning/user_{user_id}/{clean_filename}"
            clean_file_path = storage_manager.save_bytes(object_name, csv_content)

            # 算法描述：基于操作日志构建可读字符串，便于审计追溯
            # 问题清单模式与管道模式分别使用不同的描述映射
            if use_problem_strategies:
                op_type_desc_map = {
                    'row_duplicates': '行重复处理', 'column_duplicates': '列重复处理',
                    'type_errors': '类型错误处理', 'range_errors': '范围错误处理',
                    'outliers': '异常值处理', 'missing_values': '缺失值处理',
                    'column_ops': '列操作', 'row_filter': '行过滤'
                }
                algorithm_parts_new = []
                for op in operations_audit:
                    op_name = op.get("operation", "")
                    op_desc = op_type_desc_map.get(op_name, op_name)
                    details = op.get("details", "")
                    algorithm_parts_new.append(f"{op_desc}({details})" if details else op_desc)
                algorithm_desc = "+".join(algorithm_parts_new) if algorithm_parts_new else "问题清单清洗"
            else:
                algorithm_parts_new = []
                for log_item in operations_log:
                    op_type_desc = {
                        'deduplication': '去重', 'missing_values': '缺失值填充',
                        'outlier': '异常值处理', 'type_error': '类型错误处理',
                        'range_error': '范围错误处理', 'column_op': '列操作',
                        'row_filter': '行过滤'
                    }.get(log_item.get('type'), log_item.get('type', '未知'))
                    method_desc = log_item.get('method', '')
                    algorithm_parts_new.append(
                        f"{op_type_desc}({method_desc})" if method_desc else op_type_desc
                    )
                algorithm_desc = "+".join(algorithm_parts_new) if algorithm_parts_new else "管道清洗"

            # 命名方案：产物保留源名（剥离历史拼接），不追加时间戳/清洗等后缀，靠 #id/颜色区分
            clean_name = f"{clean_dataset_name(original_name)}.csv"
            clean_file_size = len(csv_content)
            clean_dataset = Dataset(
                name=clean_name,
                file_path=clean_file_path,
                file_size=clean_file_size,
                schema=data_service.get_schema(cleaned_df),
                row_count=len(cleaned_df),
                data_preview=str(data_service.get_sample_data(cleaned_df, 5)),
                module_source="cleaning",
                module_label=MODULE_LABEL_MAP.get("cleaning", "数据清洗"),
                algorithm=algorithm_desc,
                parent_id=dataset_id,
                artifact_type="cleaning_result",
                user_id=user_id
            )
            db.add(clean_dataset)
            db.commit()
            db.refresh(clean_dataset)

        # 埋点：更新任务记录为成功（必须在 clear_user_dataset_cache 之前执行，
        # 确保任务状态正确更新；缓存清理是副作用操作，失败不应影响任务状态）
        execution_time = int((time.time() - start_time) * 1000)
        # 构造结构化 result_summary（异步分支：根据 use_problem_strategies 选择数据源）
        cleaning_summary = _build_cleaning_result_summary(
            original_df=original_df_for_comparison,
            cleaned_df=cleaned_df,
            audit_report=audit_report,
            operations_log=None if use_problem_strategies else operations_log,
            operations_audit=operations_audit if use_problem_strategies else None,
            warnings=warnings,
            save_result=save_result,
            pipeline=pipeline,
            problem_strategies=problem_strategies if use_problem_strategies else None,
        )
        # 保留产物字段便于操作历史跳转
        cleaning_summary["new_dataset_id"] = clean_dataset.id if clean_dataset else None
        cleaning_summary["new_dataset_name"] = clean_dataset.name if clean_dataset else None
        # 补充完整审计报告和成功标记，使异步回调能直接获取审计数据
        cleaning_summary["audit_report"] = audit_report
        cleaning_summary["success"] = True
        cleaning_summary["cleaned_dataset_id"] = clean_dataset.id if clean_dataset else None
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=clean_dataset.id if clean_dataset else None,
            result_summary=cleaning_summary,
            execution_time=execution_time
        )

        # 缓存清理放在任务状态更新之后，失败只记日志不抛异常，避免影响已成功的任务状态
        try:
            clear_user_dataset_cache(user_id)
        except Exception as cache_err:
            import logging
            logging.error(f"清洗任务 {task_record_id} 缓存清理失败（不影响任务结果）: {cache_err}")

        result = {
            "status": "success",
            "audit_report": audit_report
        }
        if clean_dataset:
            result["cleaned_dataset_id"] = clean_dataset.id
            result["cleaning_result"] = {
                "id": clean_dataset.id,
                "name": clean_dataset.name,
                "artifact_type": clean_dataset.artifact_type,
                "algorithm": clean_dataset.algorithm
            }
        return result
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"清洗执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception as inner_e:
            # 会话可能已失效，先 rollback 恢复会话，再用新会话重试一次状态更新
            import logging
            logging.error(f"清洗任务 {task_record_id} 超时状态更新失败: {inner_e}", exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            try:
                with SessionLocal() as retry_db:
                    update_task_record(
                        db=retry_db,
                        record_id=task_record_id,
                        status="failed",
                        error_message=f"清洗执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                        execution_time=execution_time,
                        failure_category="timeout"
                    )
            except Exception as retry_err:
                logging.error(f"清洗任务 {task_record_id} 超时状态重试更新仍失败: {retry_err}", exc_info=True)
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed（含失败分类，便于前端展示和重试控制）
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=str(e),
                execution_time=execution_time,
                failure_category=classify_failure(e)
            )
        except Exception as inner_e:
            # 会话可能已失效，先 rollback 恢复会话，再用新会话重试一次状态更新
            import logging
            logging.error(f"清洗任务 {task_record_id} 失败状态更新失败: {inner_e}", exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            try:
                with SessionLocal() as retry_db:
                    update_task_record(
                        db=retry_db,
                        record_id=task_record_id,
                        status="failed",
                        error_message=str(e),
                        execution_time=execution_time,
                        failure_category=classify_failure(e)
                    )
            except Exception as retry_err:
                logging.error(f"清洗任务 {task_record_id} 失败状态重试更新仍失败: {retry_err}", exc_info=True)
        raise
    finally:
        # 无论同步还是异步，都关闭独立创建的 db 会话
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("cleaning", _execute_cleaning_pipeline)