"""
特征工程 API — 5 个独立模块（构造/编码/缩放/降维/选择）+ 动态列池 + 只增不删

执行接口采用智能异步：
- 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id 供前端轮询进度
- 数据集 < 1万行：同步执行，直接返回结果
- Celery 不可用且 ≥1万行：返回 HTTP 503，不降级到同步执行
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models import Dataset, User
from app.schemas.dataset import DatasetResponse
from app.utils.db import get_db, SessionLocal
from app.utils.security import get_current_user
from app.utils.common import clean_dataset_name, build_product_name, get_root_dataset_id, check_data_quality, clear_user_dataset_cache, MODULE_LABEL_MAP, validate_upload_file
from app.config import settings
from app.services.data_service import DataService
from app.services.storage_manager import storage_manager
from app.services.task_manager import task_manager
from app.services.cache_manager import cache_manager
from app.utils.task_records import (
    create_task_record, update_task_record, update_task_progress,
    mark_task_running, classify_failure, check_task_queue_capacity
)
from celery.exceptions import SoftTimeLimitExceeded
import os
import io
import re
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

SHANGHAI_TZ = timezone(timedelta(hours=8))

router = APIRouter()

# 智能异步阈值：从 config.py 读取，支持环境变量调整
ASYNC_THRESHOLD = settings.ASYNC_THRESHOLD


# ============================================================
# 工具函数
# ============================================================


def _update_dataset_file(dataset: Dataset, df: pd.DataFrame, db: Session):
    """原地更新数据集文件，不创建新文件"""
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_content = csv_buffer.getvalue().encode('utf-8')
    # inplace=True 直接覆盖原文件，避免生成新 UUID 路径导致读取旧文件
    storage_manager.save_bytes(dataset.file_path, csv_content, inplace=True)
    dataset.file_size = len(csv_content)
    dataset.row_count = len(df)
    data_service = DataService(db)
    dataset.schema = data_service.get_schema(df)
    dataset.data_preview = str(data_service.get_sample_data(df, 5))
    db.commit()
    db.refresh(dataset)


def _read_csv_from_minio(file_path: str) -> pd.DataFrame:
    """从 MinIO 读取数据文件（按扩展名分派 CSV/Excel/JSON）

    函数名沿用历史命名，但实际支持后端允许上传的全部格式（.csv/.xlsx/.xls/.json），
    确保上传 Excel/JSON 后列池、预览等后续读取也能正常解析。
    """
    file_bytes = storage_manager.get_file_bytes(file_path)
    lower_path = file_path.lower()
    if lower_path.endswith('.xlsx') or lower_path.endswith('.xls'):
        return pd.read_excel(io.BytesIO(file_bytes))
    if lower_path.endswith('.json'):
        return pd.read_json(io.BytesIO(file_bytes))
    try:
        return pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig')
    except Exception:
        return pd.read_csv(io.BytesIO(file_bytes))


def _get_column_type(series):
    """推断列类型

    改进：对 object 类型的列尝试 pd.to_numeric 转换，
    若大部分值可转为数值则视为 numeric（与 scale/reduce 内部的转换逻辑一致），
    避免"含个别字符串的数值列"被误判为 string 而被 _validate_operation 拒绝。
    """
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    # object 类型：先尝试数值转换，再尝试日期转换
    if series.dtype == 'object' or series.dtype.name == 'category':
        numeric_series = pd.to_numeric(series, errors='coerce')
        # 超过50%的值可转为数值，视为数值列
        if numeric_series.notna().sum() > len(series) * 0.5:
            return "numeric"
    try:
        s = pd.to_datetime(series, errors='coerce')
        if s.notna().sum() > len(series) * 0.5:
            return "datetime"
    except Exception:
        pass
    return "string"


def _coerce_numeric_columns(df):
    """将 object 类型列中超过 50% 可转为数值的列转换为数值类型

    远程模式下 SQLAlchemy 返回的数据未做类型转换，数值列可能被加载为 object 类型，
    导致 select_dtypes(include=[np.number]) 漏掉数值列。
    本函数对 object 列尝试 pd.to_numeric 转换，与 _get_column_type 的判断逻辑一致。
    """
    for col in df.columns:
        if df[col].dtype == 'object':
            converted = pd.to_numeric(df[col], errors='coerce')
            if converted.notna().sum() > len(df[col]) * 0.5:
                df[col] = converted
    return df


def _update_tags(dataset: Dataset, new_columns: dict, db: Session):
    """更新 tags 中的 generated_columns，记录每列由哪个模块生成"""
    tags_data = {}
    if dataset.tags:
        try:
            tags_data = json.loads(dataset.tags)
        except (json.JSONDecodeError, TypeError):
            pass
    if 'generated_columns' not in tags_data:
        tags_data['generated_columns'] = {}
    tags_data['generated_columns'].update(new_columns)
    dataset.tags = json.dumps(tags_data)
    db.commit()


def _update_workcopy_sampling(dataset: Dataset, is_sampled: bool, sample_size, db: Session):
    """更新工作副本 tags 中的采样状态

    大表采样得到的构造列不应被下游当作全量数据（清洗禁止保存、统计提示采样），
    因此每次保存工作副本时都要同步记录当前数据的采样状态。
    """
    tags_data = {}
    if dataset.tags:
        try:
            tags_data = json.loads(dataset.tags)
        except (json.JSONDecodeError, TypeError):
            pass
    tags_data['is_sampled'] = is_sampled
    if sample_size is not None:
        tags_data['sample_size'] = sample_size
    dataset.tags = json.dumps(tags_data, ensure_ascii=False)
    db.commit()


def _find_remote_workcopy(db: Session, user_id: int, remote_config: dict) -> Optional[Dataset]:
    """查找远程表的特征工程工作副本（每个远程表最多一个 active）"""
    if not remote_config:
        return None
    return db.query(Dataset).filter(
        Dataset.user_id == user_id,
        Dataset.connection_id == remote_config.get("connection_id"),
        Dataset.table_name == remote_config.get("table_name"),
        Dataset.source_type == "derived",
        Dataset.module_source == "feature_engineering",
        Dataset.artifact_type == "feature_workcopy",
        Dataset.status == "active"
    ).order_by(Dataset.id.desc()).first()


def _save_remote_workcopy(db: Session, user_id: int, remote_config: dict,
                          df: pd.DataFrame, algorithm_parts: list,
                          new_columns: list, module: str) -> tuple:
    """将远程表处理后的 df 保存/更新到该远程表的"工作副本"数据集

    工作副本模拟本地数据集"原地更新"的行为：
    - 构造/编码/缩放/降维产生的新列累积保存在同一个工作副本中
    - 其他模块加载该远程表时（load_module_data）优先读取工作副本，从而使用动态新增的列
    - 工作副本使用 artifact_type='feature_workcopy'，与正式导出产物（feature_result）区分，
      并在普通数据集列表中隐藏

    Args:
        module: 生成模块标识（construct/encode/scale/reduce），用于记录列来源

    Returns:
        (workcopy_id, workcopy_name)
    """
    conn_id = (remote_config or {}).get("connection_id")
    tbl_name = (remote_config or {}).get("table_name")
    data_service = DataService(db)
    module_label = MODULE_LABEL_MAP.get("feature_engineering", "特征工程")
    workcopy = _find_remote_workcopy(db, user_id, remote_config)
    # 从 df.attrs 读取本次处理的采样状态（大表采样时 load_module_data 会设置）
    is_sampled = bool(df.attrs.get('is_sampled', False))
    sample_size = df.attrs.get('sample_size')

    if workcopy:
        # 已有工作副本：覆盖更新文件（模拟本地原地更新），新列累积
        _update_dataset_file(workcopy, df, db)
        _update_tags(workcopy, {nc: {"module": module, "label": module_label} for nc in new_columns}, db)
        _update_workcopy_sampling(workcopy, is_sampled, sample_size, db)
        workcopy.algorithm = f"特征工程·远程处理(累积{len(df.columns)}列)"
        db.commit()
        return workcopy.id, workcopy.name

    # 首次创建工作副本
    # 命名方案：工作副本保留远程表名（剥离历史拼接），不追加 _特征处理 后缀，靠 #id/颜色区分
    new_dataset_name = f"{clean_dataset_name(tbl_name)}.csv"
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_content = csv_buffer.getvalue().encode('utf-8')
    object_name = f"feature_engineering/user_{user_id}/{new_dataset_name}"
    result_path = storage_manager.save_bytes(object_name, csv_content)
    # 记录数据库真实列名作为原始列集合，防止删除构造列时误删原始列
    try:
        schema_cols = data_service.get_remote_table_schema(conn_id, tbl_name, user_id)
        original_columns = [c["name"] for c in schema_cols]
    except Exception:
        # 连接不可用（如已删除）时，回退为当前 df 中减去本次新增列
        original_columns = [c for c in df.columns if c not in new_columns]
    tags_payload = {
        "is_workcopy": True,
        "original_columns": original_columns,
        "generated_columns": {nc: {"module": module, "label": module_label} for nc in new_columns}
    }
    if is_sampled:
        tags_payload["is_sampled"] = True
        if sample_size is not None:
            tags_payload["sample_size"] = sample_size
    workcopy = Dataset(
        name=new_dataset_name,
        file_path=result_path,
        file_size=len(csv_content),
        schema=data_service.get_schema(df),
        row_count=len(df),
        data_preview=str(data_service.get_sample_data(df, 5)),
        module_source="feature_engineering",
        module_label=module_label,
        algorithm=f"特征工程·远程处理({'+'.join(algorithm_parts) if algorithm_parts else '无'})",
        parent_id=None,
        root_dataset_id=None,
        artifact_type="feature_workcopy",
        user_id=user_id,
        connection_id=conn_id,
        table_name=tbl_name,
        root_connection_id=conn_id,
        source_type="derived",
        tags=json.dumps(tags_payload, ensure_ascii=False)
    )
    db.add(workcopy)
    db.commit()
    db.refresh(workcopy)
    return workcopy.id, workcopy.name


def _clear_precheck_cache(user_id: int, dataset_id: int, remote_config: dict = None):
    """清理指定数据集的预检缓存

    在 construct/encode/scale/reduce/delete_column 执行后调用，
    因为这些操作会修改数据集内容（原地更新文件），预检结果已失效。
    远程模式下按 connection_id/table_name 构造缓存键，与 precheck 的远程键保持一致。
    """
    if remote_config and remote_config.get("use_remote"):
        cache_key = (f"feature_engineering:precheck:user:{user_id}:"
                     f"remote:{remote_config.get('connection_id')}:{remote_config.get('table_name')}")
    else:
        cache_key = f"feature_engineering:precheck:user:{user_id}:dataset:{dataset_id}"
    cache_manager.delete(cache_key)


def _build_fe_result_summary(
    operation: str,
    pool_before: list,
    pool_after: list,
    new_columns: list,
    df_after: pd.DataFrame = None,
    extra: dict = None,
) -> dict:
    """构造特征工程操作 result_summary，统一字段便于操作历史展示。

    补全字段：operation / column_pool_before / column_pool_after / added_columns。
    added_columns 包含 name + type，便于操作历史中查看新增列详情。
    """
    # 新增列含类型（df_after 提供时推断类型，否则仅 name）
    if new_columns and df_after is not None:
        added_columns = [
            {
                "name": col,
                "type": _get_column_type(df_after[col]) if col in df_after.columns else "未知"
            }
            for col in new_columns
        ]
    else:
        added_columns = [{"name": col} for col in (new_columns or [])]

    summary = {
        "operation": operation,
        "column_pool_before": pool_before,
        "column_pool_after": pool_after,
        "added_columns": added_columns,
    }
    if extra:
        summary.update(extra)
    return summary



# ============================================================
# 基础 API
# ============================================================

@router.get("/raw-data", response_model=list[DatasetResponse])
async def get_fe_raw_data(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取特征工程模块专用的原始数据列表（仅返回 module_source=feature_engineering 且 artifact_type=raw_data 的数据）"""
    datasets = db.query(Dataset).filter(
        Dataset.module_source == "feature_engineering",
        Dataset.artifact_type == "raw_data",
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).all()
    return datasets


@router.get("/datasets")
async def get_feature_datasets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取特征工程模块的原始数据（/datasets 别名，保持向后兼容）"""
    datasets = db.query(Dataset).filter(
        Dataset.module_source == "feature_engineering",
        Dataset.artifact_type == "raw_data",
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).all()
    return datasets


@router.get("/data/{dataset_id}")
async def get_feature_data(
    dataset_id: int,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(100, ge=1, le=1000, description="每页行数，最大1000"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据集预览（分页）

    统一分页返回结构：{columns, rows, total, page, page_size, total_pages}
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    # 使用分页加载，避免全量构建 DataFrame 导致大数据集 OOM
    data_service = DataService(db)
    page_df, total = data_service.load_dataset_page(dataset_id, page, page_size)
    columns = list(page_df.columns)
    # 先替换无穷大再填充空值：JSON 不支持 Infinity，直接序列化会导致前端解析失败
    page_df = page_df.replace([float('inf'), float('-inf')], pd.NA)
    rows = page_df.fillna("").to_dict(orient="records")
    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size)
    }


@router.get("/column-pool/{dataset_id}")
async def get_column_pool(dataset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取数据集的列池（所有列名 + 类型 + 是否原始列）"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    df = _read_csv_from_minio(dataset.file_path)
    col_types = {col: _get_column_type(df[col]) for col in df.columns}

    # 从 tags 中读取原始列名和生成列信息
    original_columns = set()
    generated_columns = {}
    if dataset.tags:
        try:
            tags_data = json.loads(dataset.tags)
            original_columns = set(tags_data.get("original_columns", []))
            generated_columns = tags_data.get("generated_columns", {})
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "columns": [{
            "name": col,
            "type": col_types[col],
            "is_original": col in original_columns,
            "module": generated_columns.get(col, {}).get("module", ""),
            "source_label": generated_columns.get(col, {}).get("label", "")
        } for col in df.columns],
        "total": len(df.columns)
    }


@router.get("/remote-column-pool")
async def get_remote_column_pool(connection_id: int = Query(...), table_name: str = Query(...),
                                 db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取远程表当前生效的列池（含动态新增的构造列）

    优先读取该远程表的工作副本（远程构造/编码/缩放/降维产生的新列已累积其中），
    无工作副本时回退为数据库表原始列。
    """
    data_service = DataService(db)
    remote_config = {"use_remote": True, "connection_id": connection_id, "table_name": table_name}
    df, _ = data_service.load_module_data(remote_config=remote_config, user_id=current_user.id)
    col_types = {col: _get_column_type(df[col]) for col in df.columns}

    # 原始列标记：有工作副本时，不在 generated_columns 中的列视为原始列
    workcopy = _find_remote_workcopy(db, current_user.id, remote_config)
    generated_columns = {}
    if workcopy and workcopy.tags:
        try:
            tags_data = json.loads(workcopy.tags)
            generated_columns = tags_data.get("generated_columns", {})
        except (json.JSONDecodeError, TypeError):
            pass
    original_columns = {c for c in df.columns if c not in generated_columns} if workcopy else set(df.columns)

    return {
        "columns": [{
            "name": col,
            "type": col_types[col],
            "is_original": col in original_columns,
            "module": generated_columns.get(col, {}).get("module", ""),
            "source_label": generated_columns.get(col, {}).get("label", ""),
            "source": "generated" if col in generated_columns else "original",
            "sourceLabel": generated_columns.get(col, {}).get("label", "远程表")
        } for col in df.columns],
        "total": len(df.columns),
        "workcopy_dataset_id": workcopy.id if workcopy else None
    }


@router.delete("/column-pool/{dataset_id}")
async def delete_column(dataset_id: int, column_name: str = Query(..., description="要删除的列名"),
                        remote: Optional[str] = Query(None, description="远程配置JSON字符串，格式: {use_remote, connection_id, table_name}"),
                        db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """删除数据集中的构造列（非原始列）

    远程模式下删除该远程表工作副本中的构造列（原始数据库表不受影响）
    """
    import urllib.parse

    remote_config = json.loads(remote) if remote else None
    is_remote = remote_config and remote_config.get("use_remote")

    if is_remote:
        # 远程模式：定位该远程表的工作副本，从中删除构造列
        dataset = _find_remote_workcopy(db, current_user.id, remote_config)
        if not dataset:
            raise HTTPException(status_code=404, detail="远程表尚无特征工程工作副本，无法删除列")
    else:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id, Dataset.status == "active").first()
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
    
    # 读取当前数据
    df = _read_csv_from_minio(dataset.file_path)
    
    # URL解码列名，处理中文和特殊字符
    decoded_column_name = urllib.parse.unquote(column_name)
    
    # 检查列是否存在（同时检查原始列名和解码后的列名）
    if decoded_column_name not in df.columns and column_name not in df.columns:
        available_cols = list(df.columns)
        raise HTTPException(status_code=404, detail=f"列 '{decoded_column_name}' 不存在。当前可用的列: {', '.join(available_cols)}")
    
    # 使用正确的列名
    actual_column_name = decoded_column_name if decoded_column_name in df.columns else column_name
    
    # 检查是否为原始列
    original_columns = set()
    generated_columns = {}
    if dataset.tags:
        try:
            tags_data = json.loads(dataset.tags)
            original_columns = set(tags_data.get("original_columns", []))
            generated_columns = tags_data.get("generated_columns", {})
        except (json.JSONDecodeError, TypeError):
            pass
    
    if actual_column_name in original_columns:
        raise HTTPException(status_code=400, detail="原始列不能删除")
    
    # 删除列
    df = df.drop(columns=[actual_column_name])
    
    # 更新 tags 中的 generated_columns
    if actual_column_name in generated_columns:
        del generated_columns[actual_column_name]
    elif column_name in generated_columns:
        del generated_columns[column_name]
    
    # 保存更新后的数据文件
    _update_dataset_file(dataset, df, db)
    
    # 更新 tags
    if dataset.tags:
        try:
            tags_data = json.loads(dataset.tags)
        except (json.JSONDecodeError, TypeError):
            tags_data = {}
    else:
        tags_data = {}
    tags_data["generated_columns"] = generated_columns
    dataset.tags = json.dumps(tags_data, ensure_ascii=False)
    db.commit()

    # 数据集已修改，失效预检缓存（本地/远程按各自 cache_key 清理）
    _clear_precheck_cache(current_user.id, dataset_id, remote_config if is_remote else None)

    return {"message": f"已删除列: {actual_column_name}", "remaining_columns": len(df.columns)}


@router.post("/rename-column")
async def rename_column(body: dict, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """重命名数据集中的列（原始列与构造列均可）

    本地模式更新数据集文件与 tags（original_columns / generated_columns）；
    远程模式更新该远程表特征工程工作副本，原始数据库表不受影响。
    修复此前"双击重命名仅改前端状态、不持久化"导致后续操作列不存在的问题。
    """
    dataset_id = body.get("dataset_id")
    column = body.get("column")
    new_name = body.get("new_name")
    remote = body.get("remote")

    remote_config = remote if remote and remote.get("use_remote") else None
    is_remote = bool(remote_config)

    if not column or not new_name:
        raise HTTPException(status_code=400, detail="列名与新列名不能为空")
    if column == new_name:
        raise HTTPException(status_code=400, detail="新列名与原列名相同")

    if is_remote:
        dataset = _find_remote_workcopy(db, current_user.id, remote_config)
        if not dataset:
            raise HTTPException(status_code=404, detail="远程表尚无特征工程工作副本，无法重命名列")
    else:
        dataset = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.user_id == current_user.id,
            Dataset.status == "active"
        ).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

    # 读取当前数据并校验列名
    df = _read_csv_from_minio(dataset.file_path)
    if column not in df.columns:
        raise HTTPException(status_code=404,
                            detail=f"列 '{column}' 不存在。当前可用的列: {', '.join(list(df.columns)[:20])}")
    if new_name in df.columns and new_name != column:
        raise HTTPException(status_code=400, detail=f"新列名 '{new_name}' 已存在")

    # 重命名列
    df = df.rename(columns={column: new_name})

    # 同步更新 tags 中的 original_columns / generated_columns，保持列池来源标记一致
    tags_data = {}
    if dataset.tags:
        try:
            tags_data = json.loads(dataset.tags)
        except (json.JSONDecodeError, TypeError):
            tags_data = {}
    original_columns = tags_data.get("original_columns", [])
    generated_columns = tags_data.get("generated_columns", {})

    if column in original_columns:
        tags_data["original_columns"] = [new_name if c == column else c for c in original_columns]
    if column in generated_columns:
        # 构造列的键随列名同步重命名，避免后续删除/溯源失效
        tags_data["generated_columns"][new_name] = generated_columns.pop(column)

    # 保存更新后的数据文件与 tags
    _update_dataset_file(dataset, df, db)
    dataset.tags = json.dumps(tags_data, ensure_ascii=False)
    db.commit()

    # 数据集已修改，失效预检缓存
    _clear_precheck_cache(current_user.id, dataset_id, remote_config if is_remote else None)

    return {"message": f"已将列 '{column}' 重命名为 '{new_name}'", "columns": df.columns.tolist()}


@router.post("/select-features")
async def select_features(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串，格式: {use_remote, connection_id, table_name}"),
    config: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """特征选择：从已构建的特征中筛选与目标列相关性最高的Top-K个特征

    智能异步执行（≥1万行异步，<1万行同步，Celery 不可用且≥1万行报503不降级）：
    - 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id
    - 数据集 < 1万行：同步执行，直接返回结果
    - Celery 不可用且 ≥ 1万行：返回 HTTP 503，不降级到同步
    - 远程模式：强制同步执行

    Args:
        dataset_id: 数据集ID（与 remote 互斥），通过 query 传递
        remote: 远程配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
        config: {
            "target_column": 目标列名,
            "method": "chi2"|"mutual_info"|"pearson"|"tree",
            "task_type": "classification"|"regression",
            "top_k": 保留特征数
        }
    """
    target_column = config.get("target_column")
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None

    # 至少需要一个数据源
    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")
    if not target_column:
        raise HTTPException(status_code=400, detail="请指定 target_column")

    is_remote = remote_config and remote_config.get("use_remote")

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

    # 远程模式：跳过本地数据集验证（本地来源校验已在前置参数校验中完成）

    # 埋点：创建任务记录（status=running）
    # task_type="feature_engineering_select" 与 retry_task 注册表键匹配，便于失败后手动重试时查找处理函数
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="feature_engineering_select",
        user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "dataset_name": original_dataset.name if original_dataset else remote_config.get("table_name", "远程表"),
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "select_features",
            "target_column": target_column,
            "config": config
        }
    )

    # 远程模式强制同步执行
    if is_remote:
        row_count = len(df)
        return _execute_select_features(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            preloaded_df=df,
            remote_config=remote_config
        )

    # 本地数据集模式
    dataset = original_dataset
    # 优先使用 dataset.row_count（数据库存储）决定同步/异步，避免加载大数据集
    row_count = dataset.row_count or 0

    # 智能异步分发：≥1万行必须异步提交，<1万行同步执行
    if row_count >= ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集"
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
            # 立即执行：异步提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            task_result = task_manager.run_task(
                _execute_select_features,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                config=config,
                no_degrade=True
            )

            # 写入 celery_task_id，供后续取消任务时反查
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)

            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "特征选择任务已提交，请在右上角任务面板查看进度",
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
                "message": f"特征选择任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 小数据集：同步执行，直接返回结果
    return _execute_select_features(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        config=config
    )


@task_manager.register_task
def _execute_select_features(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                              preloaded_df: pd.DataFrame = None, remote_config: dict = None):
    """特征选择核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载(20%)：加载数据集、目标列校验、特征/目标分离
    - 特征转换(50%)：目标列编码、数据质量检测
    - 特征选择(80%)：计算特征得分（chi2/互信息/皮尔逊/树模型）
    - 保存结果(100%)：排序、生成新数据集、保存到数据库

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下为 None）
        config: 特征选择配置（与 select_features 接口入参一致）
        preloaded_df: 远程模式下预加载的 DataFrame（跳过 MinIO 加载）
        remote_config: 远程数据源配置

    Returns:
        特征选择结果字典（与原同步接口返回结构保持一致）
    """
    from sklearn.feature_selection import (
        chi2, mutual_info_classif, mutual_info_regression
    )
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.preprocessing import LabelEncoder

    is_remote = remote_config and remote_config.get("use_remote")

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载（20%） =====
        update_task_progress(db, task_record_id, "数据加载", 20, "正在加载数据集和目标列")

        target_column = config.get("target_column")
        method = config.get("method", "mutual_info")
        task_type = config.get("task_type", "classification")
        top_k = config.get("top_k", 10)

        # 远程模式：使用预加载的 df，跳过本地数据集查询
        if is_remote and preloaded_df is not None:
            df = preloaded_df.copy()
        else:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")
            df = _read_csv_from_minio(dataset.file_path)

        if target_column not in df.columns:
            all_cols = list(df.columns)
            raise ValueError(f"目标列 '{target_column}' 不存在。当前可用的列: {', '.join(all_cols)}")

        # 分离特征和目标
        # 远程模式下数值列可能被加载为object类型，先做类型转换
        df = _coerce_numeric_columns(df)
        y_raw = df[target_column]
        X = df.drop(columns=[target_column])

        # 仅保留数值列（特征选择需要数值）
        X_numeric = X.select_dtypes(include=[np.number])
        # 强制转换为数值类型，便于后续 sklearn 处理
        X_numeric = X_numeric.apply(pd.to_numeric, errors='coerce')
        X_numeric = X_numeric.dropna(axis=1, how='all')
        # 注意：此处不再提前用均值填充。下方会先检测数据质量，排除含 NaN/inf/常量 的列，
        # 再对剩余可用列做均值填充（仅兜底，理论上已无 NaN）。避免"先填充又排除"的逻辑矛盾，
        # 也避免 inf 污染均值（含 inf 列的 mean() 会返回 inf）。
        all_numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        if X_numeric.shape[1] == 0:
            error_msg = "没有可用的数值特征列（特征选择需要数值类型的特征列）。"
            error_msg += f"当前可用的数值列: {', '.join(all_numeric_cols) if all_numeric_cols else '无'}。"
            if target_column in all_numeric_cols:
                error_msg += f"目标列 '{target_column}' 是数值列，请确保还有其他数值列作为特征。"
            raise ValueError(error_msg)

        # ===== 阶段2：特征转换（50%） =====
        update_task_progress(db, task_record_id, "特征转换", 50, "正在进行目标列编码和数据质量检测")

        # 数据质量检测：特征选择自动排除包含无穷大值、缺失值或常量列的特征列
        # - inf/NaN：sklearn 的 chi2/mutual_info/tree 无法处理
        # - 常量列：方差为0，pearson 相关性计算返回 NaN，会导致后续排序抛 TypeError
        quality_issues = check_data_quality(df, X_numeric.columns.tolist())
        excluded_columns = set()
        excluded_details = []
        if quality_issues['infinite_columns']:
            for col in quality_issues['infinite_columns']:
                excluded_columns.add(col)
                excluded_details.append(f"{col}(含无穷大值)")
        if quality_issues['nan_columns']:
            for col in quality_issues['nan_columns']:
                excluded_columns.add(col)
                nan_count = int(df[col].isna().sum())
                excluded_details.append(f"{col}({nan_count}个缺失值)")
        # 常量列在所有方法中都会带来问题：pearson 返回 NaN 排序异常；
        # chi2 方差为0；mutual_info 得分为0无意义；tree 重要性为0。
        # 统一排除，避免 pearson 排序时 NaN 比较抛 TypeError。
        constant_in_x = [c for c in quality_issues['constant_columns'] if c in X_numeric.columns]
        if constant_in_x:
            for col in constant_in_x:
                excluded_columns.add(col)
                excluded_details.append(f"{col}(常量列)")

        if excluded_columns:
            X_numeric = X_numeric.drop(columns=list(excluded_columns), errors='ignore')

        # 排除问题列后，对剩余列做均值填充作为兜底（理论上已无 NaN/inf，防止极端情况）
        # 此时均值计算不会受 inf 污染，因为含 inf 的列已被排除
        if X_numeric.shape[1] > 0:
            X_numeric = X_numeric.fillna(X_numeric.mean())

        if X_numeric.shape[1] == 0:
            error_msg = "特征选择执行失败：所有数值特征列均包含缺失值或无穷大值，没有可用特征。"
            error_msg += f"存在问题的列: {', '.join(excluded_details)}。"
            error_msg += "请先在数据清洗模块处理数据后重试。"
            raise ValueError(error_msg)

        # 处理目标列缺失值和无穷大：自动填充，避免 sklearn 报错
        y_fill_warnings = []
        if pd.api.types.is_numeric_dtype(y_raw):
            # 处理无穷大值：替换为NaN后统一填充
            if np.isinf(y_raw).any():
                y_raw = y_raw.replace([np.inf, -np.inf], np.nan)
                y_fill_warnings.append(f"目标列 '{target_column}' 含无穷大值，已替换为缺失值并填充")
            # 处理缺失值：分类任务用众数，回归任务用均值
            if y_raw.isna().any():
                nan_count = int(y_raw.isna().sum())
                if task_type == "classification":
                    fill_val = y_raw.mode().iloc[0] if not y_raw.mode().empty else 0
                    y_raw = y_raw.fillna(fill_val)
                    y_fill_warnings.append(f"目标列 '{target_column}' 含{nan_count}个缺失值，已用众数({fill_val})填充")
                else:
                    fill_val = y_raw.mean()
                    y_raw = y_raw.fillna(fill_val)
                    y_fill_warnings.append(f"目标列 '{target_column}' 含{nan_count}个缺失值，已用均值({round(fill_val, 4)})填充")
        else:
            # 非数值目标列：统一识别各种形式的缺失值（空字符串、'NA'、'null'、'nan' 等）
            # 仅靠 isna() 无法检测到空字符串等非标准缺失值，会导致 pd.to_numeric 后产生 NaN
            missing_mask = y_raw.isna() | (y_raw.astype(str).str.strip().isin(['', 'NA', 'N/A', 'null', 'NULL', 'nan', 'NaN', 'None']))
            if missing_mask.any():
                # 先将非标准缺失值替换为真正的 NaN，便于统一填充
                y_raw = y_raw.astype(object).where(~missing_mask, np.nan)
                nan_count = int(missing_mask.sum())
                if task_type == "classification":
                    mode_series = y_raw.dropna()
                    mode_val = mode_series.mode().iloc[0] if not mode_series.mode().empty else (mode_series.iloc[0] if len(mode_series) > 0 else 0)
                    y_raw = y_raw.fillna(mode_val)
                    y_fill_warnings.append(f"目标列 '{target_column}' 含{nan_count}个缺失值，已用众数({mode_val})填充")
                else:
                    y_numeric_temp = pd.to_numeric(y_raw, errors='coerce')
                    fill_val = y_numeric_temp.mean()
                    if pd.isna(fill_val):
                        fill_val = 0
                    y_raw = y_numeric_temp.fillna(fill_val)
                    y_fill_warnings.append(f"目标列 '{target_column}' 含{nan_count}个缺失值，已用均值({round(fill_val, 4)})填充")

        # 处理目标列编码
        # 注意：pandas 2.x 读取 CSV 时字符串列 dtype 为 'str'（非 'object'），
        # 必须用 is_string_dtype 兼容检测，否则字符串目标列会误走数值分支全部转为 NaN
        if task_type == "classification":
            if pd.api.types.is_string_dtype(y_raw) or y_raw.dtype == 'object' or y_raw.dtype.name == 'category':
                le = LabelEncoder()
                y = le.fit_transform(y_raw.astype(str))
            else:
                # 连续数值型：用于卡方检验时需分箱离散化（卡方要求y为非负整数）
                y = pd.to_numeric(y_raw, errors='coerce').values
                if method == "chi2":
                    # 用分位数分箱（最多5类），转为非负整数
                    valid_y = y[~np.isnan(y)]
                    unique_count = len(np.unique(valid_y)) if len(valid_y) > 0 else 0
                    q = min(5, unique_count)
                    if q < 2:
                        q = 2
                    y = pd.qcut(y, q=q, labels=False, duplicates='drop')
                    y = pd.Series(y).fillna(0).values  # qcut 可能保留 NaN，填充为0
                    y = y - y.min()  # 归一化到非负整数
        else:
            y = pd.to_numeric(y_raw, errors='coerce')
            if y.isna().any():
                raise ValueError("目标列包含非数值内容，请使用分类任务")
            # 卡方检验仅适用分类任务，回归场景使用互信息回归
            if method == "chi2":
                method = "mutual_info"

        # 统一防御：确保编码后的 y 不含 NaN（sklearn 的 chi2/mutual_info/tree 均要求 y 无 NaN）
        # 覆盖边缘情况：object 列中非标准缺失值经 pd.to_numeric 转换后可能残留 NaN
        y_array = np.asarray(y)
        if y_array.dtype.kind in 'fc' and np.isnan(y_array).any():
            remaining_nan = int(np.isnan(y_array).sum())
            valid_y = y_array[~np.isnan(y_array)]
            if task_type == "classification":
                fill_val = pd.Series(valid_y).mode().iloc[0] if len(valid_y) > 0 and not pd.Series(valid_y).mode().empty else 0
            else:
                fill_val = float(np.mean(valid_y)) if len(valid_y) > 0 else 0.0
            y = np.where(np.isnan(y_array), fill_val, y_array)
            y_fill_warnings.append(f"目标列 '{target_column}' 编码后仍残留{remaining_nan}个缺失值，已用{fill_val}填充")

        # 检查 y 是否为常量（所有值相同）：常量目标无法计算特征相关性，得分会全部为0
        y_unique_count = len(np.unique(np.asarray(y)))
        if y_unique_count < 2:
            raise ValueError(
                f"目标列 '{target_column}' 编码后只有 {y_unique_count} 个唯一值，"
                f"无法计算特征相关性（得分将全部为0）。"
                f"请检查目标列是否全为相同值或全为缺失值，更换目标列后重试。"
            )

        # ===== 阶段3：特征选择（80%） =====
        update_task_progress(db, task_record_id, "特征选择", 80, f"正在使用 {method} 计算特征得分")

        # 计算特征得分
        scores = {}
        if method == "chi2":
            # 卡方检验：仅适用于分类任务，且特征必须非负
            X_pos = X_numeric - X_numeric.min() + 1e-6
            score_values, _ = chi2(X_pos, y)
            # chi2值与特征数值大小相关，数值大的特征会产生超大chi2值
            # 归一化到0-100范围，便于用户理解和比较
            raw_scores = {col: float(score_values[i]) for i, col in enumerate(X_numeric.columns)}
            total = sum(raw_scores.values())
            if total > 0:
                # 归一化：每个特征占总chi2值的百分比，放大到0-100范围
                scores = {col: round((s / total) * 100, 4) for col, s in raw_scores.items()}
            else:
                scores = {col: 0.0 for col in X_numeric.columns}
        elif method == "mutual_info":
            # 智能判断：若 task_type=classification 但目标列是连续数值型，自动切换为 regression
            if task_type == "classification" and pd.api.types.is_numeric_dtype(y_raw):
                score_values = mutual_info_regression(X_numeric, y, random_state=42)
            elif task_type == "classification":
                score_values = mutual_info_classif(X_numeric, y, random_state=42)
            else:
                score_values = mutual_info_regression(X_numeric, y, random_state=42)
            scores = {col: float(score_values[i]) for i, col in enumerate(X_numeric.columns)}
        elif method == "pearson":
            # 皮尔逊相关系数（-1到1），使用绝对值便于排序
            correlations = {}
            for col in X_numeric.columns:
                corr = np.corrcoef(X_numeric[col], y)[0, 1]
                correlations[col] = abs(float(corr))  # 使用绝对值便于排序
            scores = correlations
        elif method == "tree":
            # 基于树模型的重要性
            if task_type == "classification":
                model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
            else:
                model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
            model.fit(X_numeric, y)
            score_values = model.feature_importances_
            scores = {col: float(score_values[i]) for i, col in enumerate(X_numeric.columns)}
        else:
            raise ValueError(f"不支持的方法: {method}")

        # ===== 阶段4：完成（100%） =====
        update_task_progress(db, task_record_id, "保存结果", 100, "特征选择完成，正在保存结果")

        # 排序并选择Top-K
        sorted_features = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_k = min(top_k, len(sorted_features))
        selected_features = [f[0] for f in sorted_features[:top_k]]
        feature_scores = {f[0]: float(f[1]) for f in sorted_features[:top_k]}

        # 特征选择只返回得分排名结果，不生成中间数据集
        # 用户确认得分后通过"导出特征选择产物"按钮才生成最终产物，避免冗余数据集
        method_labels = {
            "chi2": "卡方检验",
            "mutual_info": "互信息",
            "pearson": "皮尔逊相关",
            "tree": "树模型重要性"
        }

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            result_summary={
                "operation": "select_features",
                "n_selected": len(selected_features),
                "n_features": X_numeric.shape[1],
                "selected_features": selected_features,
                "feature_scores": feature_scores,
                "all_scores": {k: float(v) for k, v in scores.items()},
                "method": method,
                "method_label": method_labels.get(method, method),
                "task_type": task_type,
                "top_k": top_k,
                "total_features": X_numeric.shape[1],
                "excluded_columns": list(excluded_columns),
                "excluded_details": excluded_details,
                "target_fill_warnings": y_fill_warnings,
                "message": "特征选择完成" + (f"（已自动排除以下问题列：{', '.join(excluded_details)}，建议清洗数据后重新选择以获得更完整结果）" if excluded_columns else "") + (f"；目标列自动填充提示：{'；'.join(y_fill_warnings)}" if y_fill_warnings else "")
            },
            execution_time=execution_time
        )

        return {
            "selected_features": selected_features,
            "feature_scores": feature_scores,
            "all_scores": {k: float(v) for k, v in scores.items()},
            "method": method,
            "method_label": method_labels.get(method, method),
            "task_type": task_type,
            "top_k": top_k,
            "total_features": X_numeric.shape[1],
            "excluded_columns": list(excluded_columns),
            "excluded_details": excluded_details,
            "target_fill_warnings": y_fill_warnings,
            "message": "特征选择完成" + (f"（已自动排除以下问题列：{', '.join(excluded_details)}，建议清洗数据后重新选择以获得更完整结果）" if excluded_columns else "") + (f"；目标列自动填充提示：{'；'.join(y_fill_warnings)}" if y_fill_warnings else "")
        }
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"特征选择任务执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed，便于前端展示失败原因和重试
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
        except Exception:
            # 更新任务记录失败时不掩盖原异常
            pass
        raise
    finally:
        # 无论同步还是异步，都关闭独立创建的 db 会话
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("feature_engineering_select", _execute_select_features)


@router.post("/upload", response_model=DatasetResponse)
async def feature_upload(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """上传文件到特征工程模块"""
    import time as _time
    start_time = _time.time()
    validate_upload_file(file)

    filename = clean_dataset_name(file.filename)

    # 埋点：创建上传任务记录
    task_record = create_task_record(
        db=db,
        task_type="upload",
        user_id=current_user.id,
        params={"filename": filename, "module_source": "feature_engineering", "artifact_type": "raw_data"}
    )

    content = await file.read()

    object_name = f"uploads/user_{current_user.id}/{filename}"
    file_path = storage_manager.save_bytes(object_name, content)

    data_service = DataService(db)
    try:
        df = _read_csv_from_minio(file_path)
    except Exception as e:
        storage_manager.delete(file_path)
        execution_time = int((_time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record.id, status="failed",
            error_message=str(e), execution_time=execution_time,
            failure_category="data_error"
        )
        raise HTTPException(status_code=400, detail=f"无法解析文件: {str(e)}")

    file_size = len(content)
    original_columns = list(df.columns)
    dataset = Dataset(
        name=filename,
        file_path=file_path,
        file_size=file_size,
        schema=data_service.get_schema(df),
        row_count=len(df),
        data_preview=str(data_service.get_sample_data(df, 5)),
        module_source="feature_engineering",
        module_label=MODULE_LABEL_MAP.get("feature_engineering", "特征工程"),
        artifact_type="raw_data",
        tags=json.dumps({"original_columns": original_columns}),
        user_id=current_user.id
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    execution_time = int((_time.time() - start_time) * 1000)
    update_task_record(
        db=db, record_id=task_record.id, status="success",
        dataset_id=dataset.id,
        result_summary={
            "dataset_name": dataset.name,
            "row_count": dataset.row_count,
            "column_count": len(df.columns),
            "file_size": dataset.file_size
        },
        execution_time=execution_time
    )

    clear_user_dataset_cache(current_user.id)

    # 触发 ClickHouse 副本同步（raw_data 且行数达阈值时在任务内同步；失败不影响上传）
    from app.services.clickhouse_service import trigger_sync
    trigger_sync(dataset.id)

    return dataset


# ============================================================
# 1.4 导出特征选择产物
# ============================================================

@router.post("/export-selected")
async def export_selected_features(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串，格式: {use_remote, connection_id, table_name}"),
    config: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    导出特征选择产物：基于 select_features 的结果，导出选中的特征到CSV

    dataset_id: 原始数据ID（与 remote 互斥），通过 query 传递
    remote: 远程配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
    config: {
        "selected_features": ["col1", "col2", ...],
        "target_column": "目标列名"
    }
    """
    selected_features = config.get("selected_features", [])
    target_column = config.get("target_column", "")
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None

    if not selected_features:
        raise HTTPException(status_code=400, detail="请指定 selected_features")

    is_remote = remote_config and remote_config.get("use_remote")

    # 统一数据加载
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not is_remote and not dataset:
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")

    # 验证所选特征列是否存在
    missing = [c for c in selected_features if c not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"以下列不存在: {', '.join(missing)}")

    # 包含选中的特征和目标列
    export_columns = selected_features.copy()
    if target_column and target_column in df.columns and target_column not in export_columns:
        export_columns.append(target_column)

    df_export = df[export_columns]

    # 远程模式下的源名称
    if is_remote:
        base = remote_config.get("table_name", "remote_table")
        base = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', base)
    else:
        base = os.path.splitext(dataset.name)[0]
        base = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', base)
    # 命名方案：产物保留源名（去扩展名 + 真实内容后缀 .csv），不拼"特征选择导出"/时间戳，靠 #id/颜色区分
    filename = build_product_name(base, "csv")

    csv_buffer = io.StringIO()
    df_export.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_content = csv_buffer.getvalue().encode('utf-8')

    object_name = f"feature_engineering/user_{current_user.id}/{filename}"
    file_path = storage_manager.save_bytes(object_name, csv_content)
    file_size = len(csv_content)

    # 远程模式：root_id 为 None，parent_id 为 None（按规则）
    if is_remote:
        root_id = None
        parent_id = None
    else:
        root_id = get_root_dataset_id(db, dataset)
        parent_id = dataset_id

    # algorithm 显示前5个列名+省略，便于用户快速识别产物内容
    display_cols = selected_features[:5]
    if len(selected_features) > 5:
        algorithm_desc = f"特征选择导出({', '.join(display_cols)}...等{len(selected_features)}列)"
    else:
        algorithm_desc = f"特征选择导出({', '.join(display_cols)})"

    result = Dataset(
        name=filename,
        file_path=file_path,
        file_size=file_size,
        schema=data_service.get_schema(df_export),
        row_count=len(df_export),
        data_preview=str(data_service.get_sample_data(df_export, 5)),
        module_source="feature_engineering",
        module_label=MODULE_LABEL_MAP.get("feature_engineering", "特征工程"),
        algorithm=algorithm_desc,
        parent_id=parent_id,
        root_dataset_id=root_id,
        artifact_type="feature_result",
        user_id=current_user.id,
        # 远程来源血缘字段
        connection_id=remote_config.get("connection_id") if is_remote else None,
        table_name=remote_config.get("table_name") if is_remote else None,
        root_connection_id=remote_config.get("connection_id") if is_remote else None,
        source_type="derived" if is_remote else "upload"
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    # 记录导出操作到操作历史
    dataset_name = remote_config.get("table_name", "远程表") if is_remote else dataset.name
    task_record = create_task_record(
        db=db, task_type="feature_engineering_select", user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "operation": "export_selected",
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "selected_features": selected_features,
            "target_column": target_column,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
        dataset_id=result.id,
        result_summary={
            "operation": "export_selected",
            "new_dataset_id": result.id,
            "new_dataset_name": result.name,
            "selected_features": selected_features,
            "row_count": len(df_export),
            "file_size": file_size,
        }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    return {
        "success": True,
        "message": f"已导出 {len(export_columns)} 列到特征选择产物",
        "result": {"id": result.id, "name": result.name, "column_count": len(export_columns)}
    }


# ============================================================
# 1.5 导出列池产物
# ============================================================

@router.post("/export-pool")
async def export_column_pool(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串，格式: {use_remote, connection_id, table_name}"),
    config: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    导出列池产物：导出当前列池的所有列到CSV

    dataset_id: 原始数据ID（与 remote 互斥），通过 query 传递
    remote: 远程配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
    config: {
        "column_names": ["col1", "col2", ...]  // 空数组则导出全部列
    }
    """
    column_names = config.get("column_names", [])
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None

    is_remote = remote_config and remote_config.get("use_remote")

    # 统一数据加载
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not is_remote and not dataset:
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")

    # 如果没有指定列名，则导出全部列
    if not column_names:
        column_names = list(df.columns)
    else:
        # 验证所选列是否存在
        missing = [c for c in column_names if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"以下列不存在: {', '.join(missing)}")

    df_export = df[column_names]

    # 远程模式下的源名称
    if is_remote:
        base = remote_config.get("table_name", "remote_table")
        base = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', base)
    else:
        base = os.path.splitext(dataset.name)[0]
        base = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$', '', base)
    # 命名方案：产物保留源名（去扩展名 + 真实内容后缀 .csv），不拼"列池导出"/时间戳，靠 #id/颜色区分
    filename = build_product_name(base, "csv")

    csv_buffer = io.StringIO()
    df_export.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_content = csv_buffer.getvalue().encode('utf-8')

    object_name = f"feature_engineering/user_{current_user.id}/{filename}"
    file_path = storage_manager.save_bytes(object_name, csv_content)
    file_size = len(csv_content)

    # 远程模式：root_id 为 None，parent_id 为 None（按规则）
    if is_remote:
        root_id = None
        parent_id = None
    else:
        root_id = get_root_dataset_id(db, dataset)
        parent_id = dataset_id

    # algorithm 显示前5个列名+省略，便于用户快速识别产物内容
    display_cols = column_names[:5]
    if len(column_names) > 5:
        algorithm_desc = f"列池导出({', '.join(display_cols)}...等{len(column_names)}列)"
    else:
        algorithm_desc = f"列池导出({', '.join(display_cols)})"

    result = Dataset(
        name=filename,
        file_path=file_path,
        file_size=file_size,
        schema=data_service.get_schema(df_export),
        row_count=len(df_export),
        data_preview=str(data_service.get_sample_data(df_export, 5)),
        module_source="feature_engineering",
        module_label=MODULE_LABEL_MAP.get("feature_engineering", "特征工程"),
        algorithm=algorithm_desc,
        parent_id=parent_id,
        root_dataset_id=root_id,
        artifact_type="feature_result",
        user_id=current_user.id,
        # 远程来源血缘字段
        connection_id=remote_config.get("connection_id") if is_remote else None,
        table_name=remote_config.get("table_name") if is_remote else None,
        root_connection_id=remote_config.get("connection_id") if is_remote else None,
        source_type="derived" if is_remote else "upload"
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    # 记录导出操作到操作历史
    dataset_name = remote_config.get("table_name", "远程表") if is_remote else dataset.name
    task_record = create_task_record(
        db=db, task_type="feature_engineering_construct", user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "operation": "export_pool",
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "columns": column_names,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
        dataset_id=result.id,
        result_summary={
            "operation": "export_pool",
            "new_dataset_id": result.id,
            "new_dataset_name": result.name,
            "column_count": len(column_names),
            "row_count": len(df_export),
            "file_size": file_size,
        }, execution_time=0)

    clear_user_dataset_cache(current_user.id)

    return {
        "success": True,
        "message": f"已导出 {len(column_names)} 列到列池产物",
        "result": {"id": result.id, "name": result.name, "column_count": len(column_names)}
    }


# ============================================================
# 模块1: 特征构造（只增不删）
# ============================================================

def _validate_operation(op_type: str, op: dict, col_types: dict, df: pd.DataFrame) -> list:
    """验证单个操作，返回错误列表"""
    errors = []
    if op_type == "arithmetic":
        col1 = op.get("col1", "")
        col2 = op.get("col2", "")
        name = op.get("name", "")
        if not name:
            errors.append("特征名称不能为空")
        if not col1:
            errors.append("col1不能为空")
        if not col2:
            errors.append("col2不能为空")
        if col1 and col1 not in df.columns:
            errors.append(f"列 '{col1}' 不存在")
        elif col1 and col_types.get(col1) == "string":
            errors.append(f"列 '{col1}' 是文本类型，不能参与算术运算")
        # col2 可能是常量（数字），只在是列名时检查
        if col2 and col2 in df.columns and col_types.get(col2) == "string":
            errors.append(f"列 '{col2}' 是文本类型，不能参与算术运算")

    elif op_type == "polynomial":
        col = op.get("column", "")
        if col not in df.columns:
            errors.append(f"列 '{col}' 不存在")
        elif col_types.get(col) != "numeric":
            errors.append(f"多项式特征只能对数值列操作")

    elif op_type == "log_transform":
        col = op.get("column", "")
        if col not in df.columns:
            errors.append(f"列 '{col}' 不存在")
        elif col_types.get(col) != "numeric":
            errors.append(f"对数变换只能对数值列操作")

    elif op_type == "binning":
        col = op.get("column", "")
        if col not in df.columns:
            errors.append(f"列 '{col}' 不存在")
        elif col_types.get(col) != "numeric":
            errors.append(f"分箱只能对数值列操作")

    elif op_type == "time_split":
        col = op.get("column", "")
        if col not in df.columns:
            errors.append(f"列 '{col}' 不存在")

    elif op_type == "category_cross":
        cols = op.get("columns", [])
        for col in cols:
            if col not in df.columns:
                errors.append(f"列 '{col}' 不存在")

    elif op_type == "target_encoding":
        col = op.get("column", "")
        target_col = op.get("target_column", "")
        if col not in df.columns:
            errors.append(f"列 '{col}' 不存在")
        if target_col not in df.columns:
            errors.append(f"目标列 '{target_col}' 不存在")
        elif col_types.get(target_col) != "numeric":
            errors.append(f"Target编码的目标列必须是数值类型")

    return errors


@router.post("/construct")
async def construct_features(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串，格式: {use_remote, connection_id, table_name}"),
    operations: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """特征构造：只新增列，不修改原列

    智能异步执行（≥1万行异步，<1万行同步，Celery 不可用且≥1万行报503不降级）：
    - 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id
    - 数据集 < 1万行：同步执行，直接返回结果
    - Celery 不可用且 ≥ 1万行：返回 HTTP 503，不降级到同步
    - 远程模式：强制同步执行

    operations: {
        "arithmetic": [{"name": "fe_xxx", "col1": "colA", "op": "+", "col2": "10"}],
        "polynomial": [{"column": "age", "degree": 2, "name": "fe_age^2"}],
        "log_transform": [{"column": "income", "name": "fe_log_income"}],
        "binning": [{"column": "age", "bins": 5, "method": "equal_width", "name": "fe_age_bin"}],
        "time_split": [{"column": "date", "extract": ["year","month","day"]}],
        "category_cross": [{"columns": ["city","job"], "separator": "_", "name": "fe_cross"}],
        "target_encoding": [{"column": "city", "target_column": "price", "name": "fe_te"}]
    }
    remote: 远程数据源配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
    """
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None
    is_remote = remote_config and remote_config.get("use_remote")

    # 至少需要一个数据源
    if not dataset_id and not is_remote:
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")

    # 统一数据加载
    data_service = DataService(db)
    try:
        df, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 远程模式：跳过本地数据集验证（本地来源校验已在前置参数校验中完成）

    # 埋点：创建任务记录（status=running）
    # task_type="feature_engineering_construct" 与 retry_task 注册表键匹配，便于失败后手动重试时查找处理函数
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="feature_engineering_construct",
        user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "dataset_name": original_dataset.name if original_dataset else remote_config.get("table_name", "远程表"),
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "construct_features",
            "operations": operations
        }
    )

    # 远程模式强制同步执行
    if is_remote:
        row_count = len(df)
        return _execute_construct_features(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            operations=operations,
            preloaded_df=df,
            remote_config=remote_config
        )

    # 本地数据集模式
    dataset = original_dataset
    # 优先使用 dataset.row_count（数据库存储）决定同步/异步，避免加载大数据集
    row_count = dataset.row_count or 0

    # 智能异步分发：≥1万行必须异步提交，<1万行同步执行
    if row_count >= ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集"
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
            # 立即执行：异步提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            task_result = task_manager.run_task(
                _execute_construct_features,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                operations=operations,
                no_degrade=True
            )

            # 写入 celery_task_id，供后续取消任务时反查
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)

            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "特征构造任务已提交，请在右上角任务面板查看进度",
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
                "message": f"特征构造任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 小数据集：同步执行，直接返回结果
    return _execute_construct_features(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        operations=operations
    )


@task_manager.register_task
def _execute_construct_features(task_record_id: int, user_id: int, dataset_id: int, operations: dict,
                                 preloaded_df: pd.DataFrame = None, remote_config: dict = None):
    """特征构造核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载(20%)：加载数据集、列类型推断
    - 操作校验(50%)：预验证所有构造操作
    - 特征构造(80%)：执行7类构造（四则运算/多项式/对数/分箱/时间/交叉/Target编码）
    - 保存结果(100%)：原地更新数据集文件、记录生成列来源

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下为 None）
        operations: 构造操作配置（与 construct_features 接口入参一致）
        preloaded_df: 远程模式下预加载的 DataFrame（跳过 MinIO 加载）
        remote_config: 远程数据源配置

    Returns:
        构造结果字典（与原同步接口返回结构保持一致）
    """
    is_remote = remote_config and remote_config.get("use_remote")

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载 =====
        update_task_progress(db, task_record_id, "数据加载", 20, "正在加载数据集和推断列类型")

        # 远程模式：使用预加载的 df，跳过本地数据集查询
        if is_remote and preloaded_df is not None:
            df = preloaded_df.copy()
        else:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")
            df = _read_csv_from_minio(dataset.file_path)

        # 远程模式下数值列可能被加载为 object 类型，先做类型转换
        # 与 select_features/scale/reduce 保持一致，避免 _validate_operation 误判
        df = _coerce_numeric_columns(df)
        col_types = {col: _get_column_type(df[col]) for col in df.columns}
        # 记录操作前列池，用于操作历史展示列池变化
        pool_before = list(df.columns)

        # ===== 阶段2：操作校验 =====
        update_task_progress(db, task_record_id, "操作校验", 50, "正在预验证所有构造操作")

        # 预验证
        all_errors = []
        op_type_map = {
            "arithmetic": "四则运算", "polynomial": "多项式", "log_transform": "对数变换",
            "binning": "分箱", "time_split": "时间拆解", "category_cross": "类别交叉",
            "target_encoding": "Target编码"
        }
        # 收集所有操作将要生成的新列名，统一检测重名（与原列重名或操作间互相重名）
        # 避免 df[name]=... 静默覆盖原列数据
        pending_new_names = []
        for op_type, op_list in operations.items():
            if not op_list: continue
            for i, op in enumerate(op_list):
                errs = _validate_operation(op_type, op, col_types, df)
                # 收集该操作将生成的新列名
                if op_type == "arithmetic":
                    n = op.get("name")
                    if n: pending_new_names.append(("四则运算", n))
                elif op_type == "polynomial":
                    base_name = op.get("name", f"fe_{op.get('column','')}")
                    degree = op.get("degree", 2)
                    # 幂次列名统一为 {base}^{d}（d=2,3,...），避免 d==2 复用基础名导致列名与内容错位
                    for d in range(2, degree + 1):
                        n = f"{base_name}^{d}"
                        pending_new_names.append(("多项式", n))
                elif op_type == "log_transform":
                    n = op.get("name", f"fe_log_{op.get('column','')}")
                    pending_new_names.append(("对数变换", n))
                elif op_type == "binning":
                    bcol = op.get("column", "")
                    bmethod = op.get("method", "equal_width")
                    suffix = "ew" if bmethod == "equal_width" else "ef"
                    n = op.get("name", f"fe_{bcol}_{suffix}_bin")
                    pending_new_names.append(("分箱", n))
                elif op_type == "time_split":
                    col = op.get("column", "")
                    for ext in op.get("extract", ["year","month","day"]):
                        pending_new_names.append(("时间拆解", f"fe_{col}_{ext}"))
                elif op_type == "category_cross":
                    n = op.get("name", f"fe_{'_'.join(op.get('columns',[]))}_cross")
                    pending_new_names.append(("类别交叉", n))
                elif op_type == "target_encoding":
                    n = op.get("name", f"fe_{op.get('column','')}_target_enc")
                    pending_new_names.append(("Target编码", n))
                if errs:
                    op_name = op.get("name") or op.get("column") or f"#{i+1}"
                    for e in errs:
                        all_errors.append(f"[{op_type_map.get(op_type, op_type)}] {op_name}: {e}")

        # 检测新列名是否与现有列重名
        existing_cols_set = set(df.columns)
        for op_label, new_name in pending_new_names:
            if new_name in existing_cols_set:
                all_errors.append(f"[{op_label}] {new_name}: 列名已存在，请更换名称避免覆盖原列")

        # 检测操作之间互相重名
        name_count = {}
        for _, n in pending_new_names:
            name_count[n] = name_count.get(n, 0) + 1
        for n, c in name_count.items():
            if c > 1:
                all_errors.append(f"列名 '{n}' 在多个操作中重复出现 {c} 次，请确保列名唯一")

        if all_errors:
            # 验证失败：任务标记为 failed（此前误标 success 导致前端任务面板显示"成功"但列池无变化）（修复）
            execution_time = int((time.time() - start_time) * 1000)
            error_preview = "；".join(all_errors[:5])
            if len(all_errors) > 5:
                error_preview += f"；等共 {len(all_errors)} 个问题"
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                dataset_id=dataset_id,
                error_message=f"特征构造验证失败：{error_preview}",
                failure_category="param_error",
                result_summary={
                    "validation_failed": True,
                    "errors_count": len(all_errors),
                    "errors": all_errors
                },
                execution_time=execution_time
            )
            return {"success": False, "message": "验证失败", "errors": all_errors}

        # ===== 阶段3：特征构造 =====
        update_task_progress(db, task_record_id, "特征构造", 80, "正在执行特征构造操作")

        # 执行构造
        new_columns = []
        algorithm_parts = []
        exec_errors = []
        exec_warnings = []

        # 四则运算
        if "arithmetic" in operations:
            for op in operations["arithmetic"]:
                try:
                    col1 = op.get("col1", "")
                    op_char = op.get("op", "+")
                    col2 = op.get("col2", "")
                    name = op.get("name", f"fe_{col1}_{op_char}_{col2}")

                    if not col1 or not col2:
                        exec_errors.append(f"四则运算: col1和col2不能为空")
                        continue

                    # 除法操作：检测分母是否含0，含0则拒绝构造
                    if op_char == "/":
                        # 判断 col2 是列名还是常数
                        try:
                            const_value = float(col2)
                            is_col2_constant = True
                        except (ValueError, TypeError):
                            is_col2_constant = False
                            const_value = None

                        if is_col2_constant:
                            # col2 是常数
                            if const_value == 0:
                                # 常数为0，直接拒绝构造
                                exec_errors.append(f"四则运算 [{name}]: 除数常数为0，不允许构造除法特征")
                                continue
                            else:
                                # 常数不为0，正常除法
                                df[name] = df[col1] / const_value
                        else:
                            # col2 是列名，检测该列是否包含0值
                            zero_count = int((df[col2] == 0).sum())
                            if zero_count > 0:
                                # 分母含0，直接拒绝构造
                                exec_errors.append(f"四则运算 [{name}]: 分母列 '{col2}' 包含 {zero_count} 个0值，不允许构造除法特征。请先在数据清洗模块处理0值，或选择其他列")
                                continue
                            else:
                                # 没有除零，正常除法
                                df[name] = df[col1] / df[col2]
                    else:
                        # 加减乘法：直接用 pandas 原生运算，避免 df.eval 对中文/特殊字符列名解析失败
                        # 与除法分支一样先判断 col2 是常数还是列名
                        try:
                            const_value = float(col2)
                            is_col2_constant = True
                        except (ValueError, TypeError):
                            is_col2_constant = False
                            const_value = None

                        if is_col2_constant:
                            if op_char == "+":
                                df[name] = df[col1] + const_value
                            elif op_char == "-":
                                df[name] = df[col1] - const_value
                            elif op_char == "*":
                                df[name] = df[col1] * const_value
                        else:
                            if op_char == "+":
                                df[name] = df[col1] + df[col2]
                            elif op_char == "-":
                                df[name] = df[col1] - df[col2]
                            elif op_char == "*":
                                df[name] = df[col1] * df[col2]
                    new_columns.append(name)
                except Exception as e:
                    exec_errors.append(f"四则运算: {str(e)}")

        # 多项式
        if "polynomial" in operations:
            for op in operations["polynomial"]:
                try:
                    col = op["column"]
                    degree = op.get("degree", 2)
                    # 限制 degree 范围：最小2，最大5，避免生成过多列导致内存爆炸
                    if not isinstance(degree, int) or degree < 2:
                        exec_errors.append(f"多项式 [{op.get('name', col)}]: degree 必须≥2，当前为 {degree}")
                        continue
                    if degree > 5:
                        exec_errors.append(f"多项式 [{op.get('name', col)}]: degree 过大（{degree}），最大支持5，已自动调整为5")
                        degree = 5
                    for d in range(2, degree + 1):
                        # 幂次列名统一为 {base}^{d}，与校验/前端预览保持一致，避免列名与内容错位
                        base_name = op.get("name") or f"fe_{col}"
                        nc = f"{base_name}^{d}"
                        df[nc] = df[col] ** d
                        new_columns.append(nc)
                    algorithm_parts.append(f"多项式({col})")
                except Exception as e:
                    exec_errors.append(f"多项式: {str(e)}")

        # 对数变换
        if "log_transform" in operations:
            for op in operations["log_transform"]:
                try:
                    col = op["column"]
                    nc = op.get("name", f"fe_log_{col}")
                    # 对数变换仅对正值有意义：负值会被 clip 为 0，给出警告而非静默处理
                    neg_count = int((df[col] < 0).sum())
                    if neg_count > 0:
                        exec_warnings.append(
                            f"对数变换 [{col}]: {neg_count}个负值已被裁剪为0（log仅对非负值定义），"
                            f"生成的特征列可能失真，建议清洗后重新构造"
                        )
                    df[nc] = np.log1p(df[col].clip(lower=0))
                    new_columns.append(nc)
                    algorithm_parts.append(f"对数变换({col})")
                except Exception as e:
                    exec_errors.append(f"对数变换: {str(e)}")

        # 分箱
        if "binning" in operations:
            for op in operations["binning"]:
                try:
                    col = op["column"]
                    bins = op.get("bins", 5)
                    method = op.get("method", "equal_width")
                    # 区分等宽/等频后缀，避免同列两种分箱方法列名冲突
                    if method == "equal_width":
                        nc = op.get("name", f"fe_{col}_ew_bin")
                    else:
                        nc = op.get("name", f"fe_{col}_ef_bin")
                    # 校验 bins 范围：pd.cut/qcut 要求 bins≥2
                    if not isinstance(bins, int) or bins < 2:
                        exec_errors.append(f"分箱 [{nc}]: bins 必须≥2，当前为 {bins}")
                        continue
                    if method == "equal_width":
                        df[nc] = pd.cut(df[col], bins=bins, labels=False)
                    else:
                        df[nc] = pd.qcut(df[col], q=bins, labels=False, duplicates='drop')
                    new_columns.append(nc)
                    algorithm_parts.append(f"分箱({col})")
                except Exception as e:
                    exec_errors.append(f"分箱: {str(e)}")

        # 时间拆解
        if "time_split" in operations:
            for op in operations["time_split"]:
                try:
                    col = op["column"]
                    extracts = op.get("extract", ["year", "month", "day"])
                    ts = pd.to_datetime(df[col], errors='coerce')
                    # 检查解析成功率：如果大部分值解析失败（NaT），说明列不是有效的日期格式
                    valid_count = ts.notna().sum()
                    total_count = len(ts)
                    if total_count > 0 and valid_count / total_count < 0.5:
                        exec_errors.append(
                            f"时间拆解: 列 '{col}' 的日期解析成功率仅 {valid_count}/{total_count} "
                            f"({valid_count/total_count*100:.1f}%)，请确认该列为有效的日期格式"
                        )
                        continue
                    for ext in extracts:
                        nc = f"fe_{col}_{ext}"
                        if ext == "year": df[nc] = ts.dt.year
                        elif ext == "month": df[nc] = ts.dt.month
                        elif ext == "day": df[nc] = ts.dt.day
                        elif ext == "weekday": df[nc] = ts.dt.weekday
                        elif ext == "quarter": df[nc] = ts.dt.quarter
                        elif ext == "is_weekend": df[nc] = (ts.dt.weekday >= 5).astype(int)
                        new_columns.append(nc)
                    algorithm_parts.append(f"时间拆解({col})")
                    # 部分解析失败时添加警告
                    if valid_count < total_count:
                        exec_errors.append(f"时间拆解: 列 '{col}' 有 {total_count - valid_count} 个值无法解析为日期，已忽略")
                except Exception as e:
                    exec_errors.append(f"时间拆解: {str(e)}")

        # 类别交叉
        if "category_cross" in operations:
            for op in operations["category_cross"]:
                try:
                    cols = op["columns"]
                    sep = op.get("separator", "_")
                    nc = op.get("name", f"fe_{sep.join(cols)}_cross")
                    df[nc] = df[cols].astype(str).agg(sep.join, axis=1)
                    new_columns.append(nc)
                    algorithm_parts.append(f"类别交叉")
                except Exception as e:
                    exec_errors.append(f"类别交叉: {str(e)}")

        # Target 编码
        if "target_encoding" in operations:
            for op in operations["target_encoding"]:
                try:
                    col = op["column"]
                    target_col = op["target_column"]
                    nc = op.get("name", f"fe_{col}_target_enc")
                    mean_map = df.groupby(col)[target_col].mean()
                    df[nc] = df[col].map(mean_map)
                    new_columns.append(nc)
                    algorithm_parts.append(f"Target编码({col})")
                except Exception as e:
                    exec_errors.append(f"Target编码: {str(e)}")

        # ===== 阶段4：保存结果 =====
        update_task_progress(db, task_record_id, "保存结果", 100, "特征构造完成，正在保存结果")

        # 远程模式：将含新列的 df 保存为本地派生数据集，后续操作可使用此数据集
        # 远程模式每次从原表加载，新列只在内存中无法持久化，因此必须保存为本地数据集
        new_dataset_id = None
        new_dataset_name = None
        if is_remote:
            # 远程模式：将含新列的 df 保存/更新到该远程表的"工作副本"数据集
            # 工作副本模拟本地数据集"原地更新"：新列累积，其他模块加载该远程表时自动读取
            if new_columns:
                new_dataset_id, new_dataset_name = _save_remote_workcopy(
                    db, user_id, remote_config, df, algorithm_parts, new_columns, "construct"
                )
                clear_user_dataset_cache(user_id)
                _clear_precheck_cache(user_id, dataset_id, remote_config)
        else:
            # 本地模式：保存结果（原地更新）
            _update_dataset_file(dataset, df, db)
            # 记录生成列来源
            _update_tags(dataset, {nc: {"module": "construct", "label": "特征构造"} for nc in new_columns}, db)
            # 数据集已修改，失效预检缓存
            _clear_precheck_cache(user_id, dataset_id)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        # 构造结构化 result_summary（含列池变化和新增列详情）
        fe_summary = _build_fe_result_summary(
            operation="construct_features",
            pool_before=pool_before,
            pool_after=list(df.columns),
            new_columns=new_columns,
            df_after=df,
            extra={
                "new_columns_count": len(new_columns),
                "total_columns": len(df.columns),
                "exec_errors_count": len(exec_errors),
                "success": True,
                "new_columns": new_columns,
                "exec_errors": exec_errors,
                "exec_warnings": exec_warnings
            }
        )
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=dataset_id,
            result_summary=fe_summary,
            execution_time=execution_time
        )

        return {
            "success": True,
            "message": "特征构造完成",
            "new_columns": new_columns,
            "total_columns": len(df.columns),
            "algorithm": "+".join(algorithm_parts),
            "exec_errors": exec_errors,
            "exec_warnings": exec_warnings,
            # 远程模式下返回派生数据集ID，前端应切换到本地模式使用此数据集
            "new_dataset_id": new_dataset_id,
            "new_dataset_name": new_dataset_name,
        }
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"特征构造任务执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed，便于前端展示失败原因和重试
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
        except Exception:
            pass
        raise
    finally:
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("feature_engineering_construct", _execute_construct_features)


# ============================================================
# 模块2: 特征编码（只增不删，保留原列）
# ============================================================

@router.post("/encode")
async def encode_features(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串"),
    config: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """特征编码：只新增列，保留原列

    智能异步执行（≥1万行异步，<1万行同步，Celery 不可用且≥1万行报503不降级）：
    - 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id
    - 数据集 < 1万行：同步执行，直接返回结果
    - Celery 不可用且 ≥ 1万行：返回 HTTP 503，不降级到同步
    - 远程模式：强制同步执行

    config: {
        "encoding_map": {"city": "onehot", "gender": "label"},
        "names": {"city": "ohe_city", "gender": "le_gender"}  // 可选，自定义列名
    }
    remote: 远程数据源配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
    """
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None
    is_remote = remote_config and remote_config.get("use_remote")

    # 至少需要一个数据源
    if not dataset_id and not is_remote:
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")

    # 统一数据加载
    data_service = DataService(db)
    try:
        df, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 远程模式：跳过本地数据集验证（本地来源校验已在前置参数校验中完成）

    # 埋点：创建任务记录（status=running）
    # task_type="feature_engineering_encode" 与 retry_task 注册表键匹配，便于失败后手动重试时查找处理函数
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="feature_engineering_encode",
        user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "dataset_name": original_dataset.name if original_dataset else remote_config.get("table_name", "远程表"),
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "encode_features",
            "config": config
        }
    )

    # 远程模式强制同步执行
    if is_remote:
        row_count = len(df)
        return _execute_encode_features(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            preloaded_df=df,
            remote_config=remote_config
        )

    # 本地数据集模式
    dataset = original_dataset
    # 优先使用 dataset.row_count（数据库存储）决定同步/异步，避免加载大数据集
    row_count = dataset.row_count or 0

    # 智能异步分发：≥1万行必须异步提交，<1万行同步执行
    if row_count >= ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集"
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
            # 立即执行：异步提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            task_result = task_manager.run_task(
                _execute_encode_features,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                config=config,
                no_degrade=True
            )

            # 写入 celery_task_id，供后续取消任务时反查
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)

            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "特征编码任务已提交，请在右上角任务面板查看进度",
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
                "message": f"特征编码任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 小数据集：同步执行，直接返回结果
    return _execute_encode_features(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        config=config
    )


@task_manager.register_task
def _execute_encode_features(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                              preloaded_df: pd.DataFrame = None, remote_config: dict = None):
    """特征编码核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载(20%)：加载数据集、校验编码配置
    - 编码准备(50%)：解析 encoding_map 和自定义列名
    - 执行编码(80%)：对每列执行 OneHot 或 Label 编码
    - 保存结果(100%)：原地更新数据集文件、记录生成列来源

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下为 None）
        config: 编码配置（与 encode_features 接口入参一致）
        preloaded_df: 远程模式下预加载的 DataFrame（跳过 MinIO 加载）
        remote_config: 远程数据源配置

    Returns:
        编码结果字典（与原同步接口返回结构保持一致）
    """
    is_remote = remote_config and remote_config.get("use_remote")

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载 =====
        update_task_progress(db, task_record_id, "数据加载", 20, "正在加载数据集和编码配置")

        # 远程模式：使用预加载的 df，跳过本地数据集查询
        if is_remote and preloaded_df is not None:
            df = preloaded_df.copy()
        else:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")
            df = _read_csv_from_minio(dataset.file_path)
        # 远程模式下数值列可能被加载为 object 类型，先做类型转换保持一致
        df = _coerce_numeric_columns(df)
        # 记录操作前列池，用于操作历史展示列池变化
        pool_before = list(df.columns)
        encoding_map = config.get("encoding_map", {})
        custom_names = config.get("names", {})
        # 优先使用 encoding_list（支持同列多编码），兼容旧接口 encoding_map
        encoding_list = config.get("encoding_list")
        if encoding_list:
            encode_items = [(item["column"], item["method"], item.get("name", "")) for item in encoding_list]
        else:
            encode_items = [(col, method, custom_names.get(col, "")) for col, method in encoding_map.items()]

        if not encode_items:
            raise ValueError("请指定需要编码的列")

        # ===== 阶段2：编码准备 =====
        update_task_progress(db, task_record_id, "编码准备", 50, "正在解析编码配置和校验列名冲突")

        # 校验 label 编码的自定义列名是否与现有列重名（OneHot 编码会自动加前缀，不检测）
        existing_cols_set = set(df.columns)
        name_conflicts = []
        for col, method, custom_name in encode_items:
            if method == "label":
                nc = custom_name or f"le_{col}"
                if nc in existing_cols_set:
                    name_conflicts.append(f"{nc}(由列 '{col}' 的 Label 编码生成)")
        if name_conflicts:
            raise ValueError(f"以下编码列名已存在，请更换名称避免覆盖原列: {', '.join(name_conflicts)}")

        # ===== 阶段3：执行编码 =====
        update_task_progress(db, task_record_id, "执行编码", 80, "正在对每列执行 OneHot 或 Label 编码")

        encoded_cols = []
        exec_errors = []
        # OneHot 编码的高基数列上限：超过此值会生成过多列，可能导致内存爆炸
        ONEHOT_CARDINALITY_LIMIT = 100
        for col, method, custom_name in encode_items:
            if col not in df.columns:
                continue
            if method == "onehot":
                # 高基数列检测：唯一值过多时 OneHot 会生成与行数相当的列
                unique_count = df[col].nunique()
                if unique_count > ONEHOT_CARDINALITY_LIMIT:
                    exec_errors.append(f"OneHot编码 [{col}]: 唯一值数 {unique_count} 超过上限 {ONEHOT_CARDINALITY_LIMIT}，会生成过多列导致内存爆炸，请使用 Label 编码或先分箱")
                    continue
                prefix = custom_name or f"ohe_{col}"
                dummies = pd.get_dummies(df[col], prefix=prefix, drop_first=True)
                df = pd.concat([df, dummies], axis=1)
                encoded_cols.extend(list(dummies.columns))
            elif method == "label":
                nc = custom_name or f"le_{col}"
                df[nc] = pd.factorize(df[col])[0]
                encoded_cols.append(nc)

        # ===== 阶段4：保存结果 =====
        update_task_progress(db, task_record_id, "保存结果", 100, "特征编码完成，正在保存结果")

        # 远程模式：保存/更新工作副本，使新列可被其他模块动态使用（模拟本地原地更新）
        if not is_remote:
            # 本地模式：原地更新
            _update_dataset_file(dataset, df, db)
            _update_tags(dataset, {nc: {"module": "encode", "label": "特征编码"} for nc in encoded_cols}, db)
            # 数据集已修改，失效预检缓存
            _clear_precheck_cache(user_id, dataset_id)
        else:
            if encoded_cols:
                _save_remote_workcopy(db, user_id, remote_config, df, [], encoded_cols, "encode")
                clear_user_dataset_cache(user_id)
                _clear_precheck_cache(user_id, dataset_id, remote_config)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        # 构造结构化 result_summary（含列池变化和新增列详情）
        # encoding_method：去重后的编码方式列表，task_labels 会将 onehot/label 转为"独热编码"/"标签编码"
        encoding_methods = sorted(set(method for _, method, _ in encode_items))
        fe_summary = _build_fe_result_summary(
            operation="encode_features",
            pool_before=pool_before,
            pool_after=list(df.columns),
            new_columns=encoded_cols,
            df_after=df,
            extra={
                "encoded_columns_count": len(encoded_cols),
                "total_columns": len(df.columns),
                "exec_errors_count": len(exec_errors),
                "encoding_method": encoding_methods,
                "success": True,
                "new_columns": encoded_cols,
                "encoded_columns": encoded_cols,
                "exec_errors": exec_errors
            }
        )
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=dataset_id,
            result_summary=fe_summary,
            execution_time=execution_time
        )

        return {
            "success": True, "message": "特征编码完成",
            "encoded_columns": encoded_cols,
            "exec_errors": exec_errors,
        }
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"特征编码任务执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed，便于前端展示失败原因和重试
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
        except Exception:
            pass
        raise
    finally:
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("feature_engineering_encode", _execute_encode_features)


# ============================================================
# 模块3: 特征缩放（只增不删，保留原列）
# ============================================================

@router.post("/scale")
async def scale_features(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串"),
    config: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """特征缩放：新增 std_/norm_ 列，保留原列

    智能异步执行（≥1万行异步，<1万行同步，Celery 不可用且≥1万行报503不降级）：
    - 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id
    - 数据集 < 1万行：同步执行，直接返回结果
    - Celery 不可用且 ≥ 1万行：返回 HTTP 503，不降级到同步
    - 远程模式：强制同步执行

    config: {
        "method": "standard" | "minmax",
        "columns": ["age", "income"],
        "names": {"age": "std_age", "income": "std_income"}  // 可选
    }
    remote: 远程数据源配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
    """
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None
    is_remote = remote_config and remote_config.get("use_remote")

    # 至少需要一个数据源
    if not dataset_id and not is_remote:
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")

    # 统一数据加载
    data_service = DataService(db)
    try:
        df, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 远程模式：跳过本地数据集验证（本地来源校验已在前置参数校验中完成）

    # 埋点：创建任务记录（status=running）
    # task_type="feature_engineering_scale" 与 retry_task 注册表键匹配，便于失败后手动重试时查找处理函数
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="feature_engineering_scale",
        user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "dataset_name": original_dataset.name if original_dataset else remote_config.get("table_name", "远程表"),
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "scale_features",
            "config": config
        }
    )

    # 远程模式强制同步执行
    if is_remote:
        row_count = len(df)
        return _execute_scale_features(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            preloaded_df=df,
            remote_config=remote_config
        )

    # 本地数据集模式
    dataset = original_dataset
    # 优先使用 dataset.row_count（数据库存储）决定同步/异步，避免加载大数据集
    row_count = dataset.row_count or 0

    # 智能异步分发：≥1万行必须异步提交，<1万行同步执行
    if row_count >= ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集"
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
            # 立即执行：异步提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            task_result = task_manager.run_task(
                _execute_scale_features,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                config=config,
                no_degrade=True
            )

            # 写入 celery_task_id，供后续取消任务时反查
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)

            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "特征缩放任务已提交，请在右上角任务面板查看进度",
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
                "message": f"特征缩放任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 小数据集：同步执行，直接返回结果
    return _execute_scale_features(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        config=config
    )


@task_manager.register_task
def _execute_scale_features(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                             preloaded_df: pd.DataFrame = None, remote_config: dict = None):
    """特征缩放核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载(20%)：加载数据集、解析缩放配置
    - 列类型转换(50%)：字符串列转数值、校验可缩放列
    - 执行缩放(80%)：StandardScaler 或 MinMaxScaler 训练与变换
    - 保存结果(100%)：原地更新数据集文件、记录生成列来源

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下为 None）
        config: 缩放配置（与 scale_features 接口入参一致）
        preloaded_df: 远程模式下预加载的 DataFrame（跳过 MinIO 加载）
        remote_config: 远程数据源配置

    Returns:
        缩放结果字典（与原同步接口返回结构保持一致）
    """
    from sklearn.preprocessing import StandardScaler, MinMaxScaler

    is_remote = remote_config and remote_config.get("use_remote")

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载 =====
        update_task_progress(db, task_record_id, "数据加载", 20, "正在加载数据集和缩放配置")

        # 远程模式：使用预加载的 df，跳过本地数据集查询
        if is_remote and preloaded_df is not None:
            df = preloaded_df.copy()
        else:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")
            df = _read_csv_from_minio(dataset.file_path)
        # 记录操作前列池，用于操作历史展示列池变化
        pool_before = list(df.columns)
        method = config.get("method", "standard")
        user_columns = config.get("columns", [])
        custom_names = config.get("names", {})

        # 远程模式下数值列可能被加载为object类型，先做类型转换
        df = _coerce_numeric_columns(df)
        all_numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        # 记录用户是否主动选择了列：空列表表示全部数值列
        is_all_numeric_mode = not user_columns
        columns = user_columns if user_columns else all_numeric_cols

        missing_cols = [c for c in columns if c not in df.columns]

        # ===== 阶段2：列类型转换 =====
        update_task_progress(db, task_record_id, "列类型转换", 50, "正在转换字符串列和检测数据质量")

        # 尝试将字符串列转换为数值类型
        converted_cols = []
        non_numeric_cols = []
        for col in columns:
            if col not in df.columns:
                continue
            if pd.api.types.is_numeric_dtype(df[col]):
                converted_cols.append(col)
            else:
                try:
                    converted = pd.to_numeric(df[col], errors='coerce')
                    # 检查转换后是否有有效数值（不是全部NaN）
                    if converted.notna().any():
                        df[col] = converted
                        converted_cols.append(col)
                    else:
                        non_numeric_cols.append(col)
                except Exception:
                    non_numeric_cols.append(col)

        if missing_cols or non_numeric_cols:
            error_msg = "特征缩放执行失败："
            if missing_cols:
                error_msg += f"【列不存在】以下列在数据集中不存在: {', '.join(missing_cols)}。"
            if non_numeric_cols:
                error_msg += f"【非数值列】以下列不是数值类型（无法转换为数值）: {', '.join(non_numeric_cols)}。"
            error_msg += f"当前可用的数值列: {', '.join(all_numeric_cols) if all_numeric_cols else '无'}。"
            raise ValueError(error_msg)

        if not converted_cols:
            error_msg = "特征缩放执行失败：没有可缩放的数值列。"
            error_msg += f"当前可用的数值列: {', '.join(all_numeric_cols) if all_numeric_cols else '无'}。"
            raise ValueError(error_msg)

        # 数据质量检测：特征缩放不允许输入包含无穷大值、缺失值或常量列
        # 常量列方差为0，StandardScaler会除以0产生NaN，MinMaxScaler也会除以0
        quality_issues = check_data_quality(df, converted_cols)
        # 过滤出真正在 converted_cols 中的常量列（check_data_quality 可能返回非数值常量列）
        constant_in_converted = [c for c in quality_issues['constant_columns'] if c in converted_cols]
        has_quality_issue = (
            quality_issues['infinite_columns'] or
            quality_issues['nan_columns'] or
            constant_in_converted
        )
        if has_quality_issue:
            error_msg = "特征缩放执行失败，当前数据存在质量问题："
            if quality_issues['infinite_columns']:
                error_msg += f"【无穷大值】以下列包含无穷大值: {', '.join(quality_issues['infinite_columns'])}（通常是除法构造特征时分母为0导致）。"
            if quality_issues['nan_columns']:
                nan_cols = quality_issues['nan_columns']
                nan_details = []
                for col in nan_cols:
                    nan_count = int(df[col].isna().sum())
                    nan_details.append(f"{col}({nan_count}个缺失值)")
                if is_all_numeric_mode:
                    error_msg += f"【缺失值】您未选择列，系统默认对全部数值列进行缩放，但以下列包含缺失值: {', '.join(nan_details)}。"
                else:
                    error_msg += f"【缺失值】您选择的列中包含缺失值: {', '.join(nan_details)}。"
            if constant_in_converted:
                error_msg += f"【常量列】以下列为常量列（所有值相同，方差为0，缩放会除以0产生NaN）: {', '.join(constant_in_converted)}。"
            error_msg += "请先在数据清洗模块处理上述问题，或删除包含问题的列后重试。"
            raise ValueError(error_msg)

        # ===== 阶段3：执行缩放 =====
        update_task_progress(db, task_record_id, "执行缩放", 80, "正在执行 StandardScaler 或 MinMaxScaler 训练与变换")

        # 校验缩放后的新列名是否与现有列重名，避免覆盖原列
        prefix = "std_" if method == "standard" else "norm_"
        existing_cols_set = set(df.columns)
        name_conflicts = []
        for col in converted_cols:
            nc = custom_names.get(col, f"{prefix}{col}")
            if nc in existing_cols_set:
                name_conflicts.append(nc)
        if name_conflicts:
            raise ValueError(f"以下缩放列名已存在，请更换名称避免覆盖原列: {', '.join(name_conflicts)}")

        scaler = StandardScaler() if method == "standard" else MinMaxScaler()
        scaled_values = scaler.fit_transform(df[converted_cols])

        new_cols = []
        for i, col in enumerate(converted_cols):
            nc = custom_names.get(col, f"{prefix}{col}")
            df[nc] = scaled_values[:, i]
            new_cols.append(nc)

        # ===== 阶段4：保存结果 =====
        update_task_progress(db, task_record_id, "保存结果", 100, "特征缩放完成，正在保存结果")

        # 远程模式：保存/更新工作副本，使新列可被其他模块动态使用（模拟本地原地更新）
        if not is_remote:
            # 本地模式：原地更新
            _update_dataset_file(dataset, df, db)
            _update_tags(dataset, {nc: {"module": "scale", "label": "特征缩放"} for nc in new_cols}, db)
            # 数据集已修改，失效预检缓存
            _clear_precheck_cache(user_id, dataset_id)
        else:
            if new_cols:
                _save_remote_workcopy(db, user_id, remote_config, df, [], new_cols, "scale")
                clear_user_dataset_cache(user_id)
                _clear_precheck_cache(user_id, dataset_id, remote_config)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        # 构造结构化 result_summary（含列池变化和新增列详情）
        fe_summary = _build_fe_result_summary(
            operation="scale_features",
            pool_before=pool_before,
            pool_after=list(df.columns),
            new_columns=new_cols,
            df_after=df,
            extra={
                "new_columns_count": len(new_cols),
                "method": method,
                "scaling_method": method,  # 存英文（standard/minmax/robust），由 _label_value 转中文
                "scaled_columns_count": len(converted_cols),
                "success": True,
                "new_columns": new_cols,
                "exec_errors": []
            }
        )
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=dataset_id,
            result_summary=fe_summary,
            execution_time=execution_time
        )

        method_cn = "标准化" if method == "standard" else "归一化"
        return {
            "success": True, "message": f"特征{method_cn}完成",
            "new_columns": new_cols, "method": method,
            "scaled_columns": converted_cols,
        }
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"特征缩放任务执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed，便于前端展示失败原因和重试
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
        except Exception:
            pass
        raise
    finally:
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("feature_engineering_scale", _execute_scale_features)


# ============================================================
# 模块4: 特征降维（只增不删，保留原列）
# ============================================================

@router.post("/reduce")
async def reduce_features(
    dataset_id: Optional[int] = None,
    remote: Optional[str] = Query(None, description="远程配置JSON字符串"),
    config: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """特征降维：新增 pca_/tsne_ 列，保留原列

    智能异步执行（≥1万行异步，<1万行同步，Celery 不可用且≥1万行报503不降级）：
    - 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id
    - 数据集 < 1万行：同步执行，直接返回结果
    - Celery 不可用且 ≥ 1万行：返回 HTTP 503，不降级到同步
    - 远程模式：强制同步执行

    config: {
        "method": "pca" | "tsne",
        "n_components": 2,
        "columns": ["age", "income"],  // 可选，要降维的列，默认全部数值列
        "names": ["pca_1", "pca_2"]  // 可选，自定义列名
    }
    remote: 远程数据源配置JSON字符串 {"use_remote": True, "connection_id": N, "table_name": "..."}
    """
    # 解析 remote 查询参数（JSON字符串）
    remote_config = json.loads(remote) if remote else None
    is_remote = remote_config and remote_config.get("use_remote")

    # 至少需要一个数据源
    if not dataset_id and not is_remote:
        raise HTTPException(status_code=400, detail="请指定 dataset_id 或 remote 参数")

    # 统一数据加载
    data_service = DataService(db)
    try:
        df, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 远程模式：跳过本地数据集验证（本地来源校验已在前置参数校验中完成）

    # 埋点：创建任务记录（status=running）
    # task_type="feature_engineering_reduce" 与 retry_task 注册表键匹配，便于失败后手动重试时查找处理函数
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="feature_engineering_reduce",
        user_id=current_user.id,
        dataset_id=dataset_id,
        params={
            "dataset_name": original_dataset.name if original_dataset else remote_config.get("table_name", "远程表"),
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "reduce_features",
            "config": config
        }
    )

    # 远程模式强制同步执行
    if is_remote:
        row_count = len(df)
        return _execute_reduce_features(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            preloaded_df=df,
            remote_config=remote_config
        )

    # 本地数据集模式
    dataset = original_dataset
    # 优先使用 dataset.row_count（数据库存储）决定同步/异步，避免加载大数据集
    row_count = dataset.row_count or 0

    # 智能异步分发：≥1万行必须异步提交，<1万行同步执行
    if row_count >= ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集"
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
            # 立即执行：异步提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            task_result = task_manager.run_task(
                _execute_reduce_features,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                config=config,
                no_degrade=True
            )

            # 写入 celery_task_id，供后续取消任务时反查
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)

            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "特征降维任务已提交，请在右上角任务面板查看进度",
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
                "message": f"特征降维任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 小数据集：同步执行，直接返回结果
    return _execute_reduce_features(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        config=config
    )


@task_manager.register_task
def _execute_reduce_features(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                              preloaded_df: pd.DataFrame = None, remote_config: dict = None):
    """特征降维核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载(20%)：加载数据集、解析降维配置
    - 列类型转换(50%)：字符串列转数值、校验可降维列、数据质量检测
    - 执行降维(80%)：StandardScaler 标准化后 PCA 或 t-SNE 降维
    - 保存结果(100%)：原地更新数据集文件、记录生成列来源

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下为 None）
        config: 降维配置（与 reduce_features 接口入参一致）
        preloaded_df: 远程模式下预加载的 DataFrame（跳过 MinIO 加载）
        remote_config: 远程数据源配置

    Returns:
        降维结果字典（与原同步接口返回结构保持一致）
    """
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    from sklearn.preprocessing import StandardScaler

    is_remote = remote_config and remote_config.get("use_remote")

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载 =====
        update_task_progress(db, task_record_id, "数据加载", 20, "正在加载数据集和降维配置")

        # 远程模式：使用预加载的 df，跳过本地数据集查询
        if is_remote and preloaded_df is not None:
            df = preloaded_df.copy()
        else:
            dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
            if not dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")
            df = _read_csv_from_minio(dataset.file_path)
        # 记录操作前列池，用于操作历史展示列池变化
        pool_before = list(df.columns)
        method = config.get("method", "pca")
        n_components = config.get("n_components", 2)
        user_columns = config.get("columns", [])
        custom_names = config.get("names", [])

        # 远程模式下数值列可能被加载为object类型，先做类型转换
        df = _coerce_numeric_columns(df)
        all_numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        # 记录用户是否主动选择了列：空列表表示全部数值列
        is_all_numeric_mode = not user_columns
        columns = user_columns if user_columns else all_numeric_cols

        missing_cols = [c for c in columns if c not in df.columns]

        # ===== 阶段2：列类型转换 =====
        update_task_progress(db, task_record_id, "列类型转换", 50, "正在转换字符串列和检测数据质量")

        # 尝试将字符串列转换为数值类型
        converted_cols = []
        non_numeric_cols = []
        for col in columns:
            if col not in df.columns:
                continue
            if pd.api.types.is_numeric_dtype(df[col]):
                converted_cols.append(col)
            else:
                try:
                    converted = pd.to_numeric(df[col], errors='coerce')
                    if converted.notna().any():
                        df[col] = converted
                        converted_cols.append(col)
                    else:
                        non_numeric_cols.append(col)
                except Exception:
                    non_numeric_cols.append(col)

        if missing_cols or non_numeric_cols:
            error_msg = "特征降维执行失败："
            if missing_cols:
                error_msg += f"【列不存在】以下列在数据集中不存在: {', '.join(missing_cols)}。"
            if non_numeric_cols:
                error_msg += f"【非数值列】以下列不是数值类型（无法转换为数值）: {', '.join(non_numeric_cols)}。"
            error_msg += f"当前可用的数值列: {', '.join(all_numeric_cols) if all_numeric_cols else '无'}。"
            raise ValueError(error_msg)

        if len(converted_cols) < 2:
            error_msg = "特征降维执行失败：降维需要至少2个数值列。"
            error_msg += f"当前有效的数值列数量: {len(converted_cols)}。"
            error_msg += f"当前可用的数值列: {', '.join(all_numeric_cols) if all_numeric_cols else '无'}。"
            raise ValueError(error_msg)

        # 数据质量检测：特征降维不允许输入包含无穷大值、缺失值或常量列
        # 常量列方差为0，StandardScaler会除以0产生NaN，PCA/t-SNE也会因NaN崩溃
        quality_issues = check_data_quality(df, converted_cols)
        # 过滤出真正在 converted_cols 中的常量列
        constant_in_converted = [c for c in quality_issues['constant_columns'] if c in converted_cols]
        has_quality_issue = (
            quality_issues['infinite_columns'] or
            quality_issues['nan_columns'] or
            constant_in_converted
        )
        if has_quality_issue:
            error_msg = "特征降维执行失败，当前数据存在质量问题："
            if quality_issues['infinite_columns']:
                error_msg += f"【无穷大值】以下列包含无穷大值: {', '.join(quality_issues['infinite_columns'])}（通常是除法构造特征时分母为0导致）。"
            if quality_issues['nan_columns']:
                nan_cols = quality_issues['nan_columns']
                nan_details = []
                for col in nan_cols:
                    nan_count = int(df[col].isna().sum())
                    nan_details.append(f"{col}({nan_count}个缺失值)")
                if is_all_numeric_mode:
                    error_msg += f"【缺失值】您未选择列，系统默认对全部数值列进行降维，但以下列包含缺失值: {', '.join(nan_details)}。"
                else:
                    error_msg += f"【缺失值】您选择的列中包含缺失值: {', '.join(nan_details)}。"
            if constant_in_converted:
                error_msg += f"【常量列】以下列为常量列（所有值相同，方差为0，标准化会除以0产生NaN）: {', '.join(constant_in_converted)}。"
            error_msg += "请先在数据清洗模块处理上述问题，或删除包含问题的列后重试。"
            raise ValueError(error_msg)

        # ===== 阶段3：执行降维 =====
        update_task_progress(db, task_record_id, "执行降维", 80, "正在执行标准化和 PCA/t-SNE 降维")

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(df[converted_cols])

        # n_components 需同时不超过特征数和样本数（PCA 要求 n_components ≤ min(n_samples, n_features)）
        n_samples = len(df)
        n_components = min(n_components, len(converted_cols), n_samples)
        if n_components < 1:
            raise ValueError(f"特征降维执行失败：n_components 计算后为 {n_components}，需≥1。当前样本数: {n_samples}，特征数: {len(converted_cols)}")
        explained_variance = None

        if method == "pca":
            reducer = PCA(n_components=n_components, random_state=42)
            X_reduced = reducer.fit_transform(X_scaled)
            explained_variance = [round(v, 4) for v in reducer.explained_variance_ratio_.tolist()]
        elif method == "tsne":
            # t-SNE 的 n_components 上限为3，perplexity 必须 < n_samples 且 > 0
            n_components = min(n_components, 3)
            # perplexity 下限保护：n_samples≤1 时无法降维；n_samples 较小时 perplexity 也需相应减小
            if n_samples <= 1:
                raise ValueError(f"特征降维执行失败：t-SNE 要求样本数>1，当前样本数: {n_samples}")
            # perplexity 必须 < n_samples，取 min(30, n_samples-1)，且至少为1
            perplexity = max(1, min(30, n_samples - 1))
            reducer = TSNE(n_components=n_components, random_state=42, perplexity=perplexity)
            X_reduced = reducer.fit_transform(X_scaled)
        else:
            raise ValueError(f"不支持的方法: {method}，支持的方法: pca, tsne")

        # 生成新列名：n_components 可能被 clamp（特征数/样本数不足），
        # 自定义名按实际数量截取，不足部分用默认前缀补齐，避免整组自定义名被静默丢弃
        default_prefix = "pca_" if method == "pca" else "tsne_"
        if custom_names:
            col_names = [
                custom_names[i] if i < len(custom_names) else f"{default_prefix}{i+1}"
                for i in range(n_components)
            ]
        else:
            col_names = [f"{default_prefix}{i+1}" for i in range(n_components)]

        # 校验降维后的新列名是否与现有列重名，避免覆盖原列
        existing_cols_set = set(df.columns)
        name_conflicts = [n for n in col_names if n in existing_cols_set]
        if name_conflicts:
            raise ValueError(f"以下降维列名已存在，请更换名称避免覆盖原列: {', '.join(name_conflicts)}")

        # 追加新列，不删除原列
        for i, nc in enumerate(col_names):
            df[nc] = X_reduced[:, i]

        # ===== 阶段4：保存结果 =====
        update_task_progress(db, task_record_id, "保存结果", 100, "特征降维完成，正在保存结果")

        # 远程模式：保存/更新工作副本，使新列可被其他模块动态使用（模拟本地原地更新）
        if not is_remote:
            # 本地模式：原地更新
            _update_dataset_file(dataset, df, db)
            _update_tags(dataset, {nc: {"module": "reduce", "label": "特征降维"} for nc in col_names}, db)
            # 数据集已修改，失效预检缓存
            _clear_precheck_cache(user_id, dataset_id)
        else:
            if col_names:
                _save_remote_workcopy(db, user_id, remote_config, df, [], col_names, "reduce")
                clear_user_dataset_cache(user_id)
                _clear_precheck_cache(user_id, dataset_id, remote_config)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        # 构造结构化 result_summary（含列池变化和新增列详情）
        fe_summary = _build_fe_result_summary(
            operation="reduce_features",
            pool_before=pool_before,
            pool_after=list(df.columns),
            new_columns=col_names,
            df_after=df,
            extra={
                "new_columns_count": len(col_names),
                "method": method,
                "n_components": n_components,
                "explained_variance": explained_variance,
                "success": True,
                "new_columns": col_names,
                "exec_errors": []
            }
        )
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=dataset_id,
            result_summary=fe_summary,
            execution_time=execution_time
        )

        method_cn = "PCA" if method == "pca" else "t-SNE"
        return {
            "success": True, "message": f"特征降维完成({method_cn})",
            "new_columns": col_names, "method": method,
            "n_components": n_components,
            "explained_variance": explained_variance,
            "reduced_columns": converted_cols,
        }
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"特征降维任务执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed，便于前端展示失败原因和重试
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
        except Exception:
            pass
        raise
    finally:
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("feature_engineering_reduce", _execute_reduce_features)


# ============================================================
# 预检接口：加载数据集后对所有列进行全方位检测，返回结构化的问题清单和操作可行性
# ============================================================

# OneHot 编码的高基数列上限（与 encode 内部保持一致）
_ONEHOT_CARDINALITY_LIMIT = 100
# 高基数列判定阈值：唯一值 > 100 或 唯一值/总行数 > 0.5
_HIGH_CARDINALITY_UNIQUE_THRESHOLD = 100
_HIGH_CARDINALITY_RATIO_THRESHOLD = 0.5


@router.get("/precheck/{dataset_id}")
async def precheck_dataset(dataset_id: int,
                           remote: Optional[str] = Query(None, description="远程配置JSON字符串: {use_remote, connection_id, table_name}"),
                           db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """预检数据集：检测所有列的数据质量问题，并判断 5 类特征工程操作的可行性

    在前端选择数据集后自动调用，结果缓存到 Redis 5 分钟。
    construct/encode/scale/reduce 执行后会通过 _clear_precheck_cache 失效缓存。
    远程模式（remote 参数）下预检远程表数据（工作副本优先），与本地预检结果结构一致。

    返回结构：
    - columns: 每列的详细检测结果（类型/NaN/inf/常量/0值/唯一值/最值）
    - summary: 按问题类型汇总
    - operation_feasibility: 5 类操作的可行性判断（feasible/warnings/blocked_columns）
    - recommendations: 给用户的处理建议
    """
    # 远程模式：remote 参数携带 {use_remote, connection_id, table_name}
    remote_config = json.loads(remote) if remote else None
    is_remote = remote_config and remote_config.get("use_remote")

    if is_remote:
        cache_key = (f"feature_engineering:precheck:user:{current_user.id}:"
                     f"remote:{remote_config.get('connection_id')}:{remote_config.get('table_name')}")
    else:
        cache_key = f"feature_engineering:precheck:user:{current_user.id}:dataset:{dataset_id}"
    # 尝试命中缓存
    cached = cache_manager.get(cache_key)
    if cached:
        return cached

    workcopy = None
    if is_remote:
        # 远程模式：加载远程表数据（工作副本优先），无 Dataset 对象
        try:
            data_service = DataService(db)
            df, _ = data_service.load_module_data(
                remote_config=remote_config, user_id=current_user.id
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        workcopy = _find_remote_workcopy(db, current_user.id, remote_config)
    else:
        dataset = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.user_id == current_user.id,
            Dataset.status == "active"
        ).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
        df = _read_csv_from_minio(dataset.file_path)
    row_count = len(df)

    # 从 tags 读取原始列信息（本地数据集 / 远程工作副本的 tags 结构一致）
    original_columns = set()
    generated_columns = {}
    tags_source = workcopy if is_remote else dataset
    if tags_source and tags_source.tags:
        try:
            tags_data = json.loads(tags_source.tags)
            original_columns = set(tags_data.get("original_columns", []))
            generated_columns = tags_data.get("generated_columns", {})
        except (json.JSONDecodeError, TypeError):
            pass
    if is_remote and not original_columns:
        # 无工作副本（直接查库）：全部列为数据库原始列
        original_columns = set(df.columns)

    # ===== 逐列检测 =====
    columns_info = []
    summary = {
        "numeric_columns": 0,
        "string_columns": 0,
        "datetime_columns": 0,
        "columns_with_nan": 0,
        "columns_with_inf": 0,
        "constant_columns": 0,
        "high_cardinality_columns": 0,
        "rows_with_nan": int(df.isna().any(axis=1).sum())
    }

    for col in df.columns:
        series = df[col]
        col_type = _get_column_type(series)
        nan_count = int(series.isna().sum())
        unique_count = int(series.nunique())
        is_constant = unique_count <= 1

        col_info = {
            "name": col,
            "type": col_type,
            "is_original": col in original_columns,
            "module": generated_columns.get(col, {}).get("module", ""),
            "source_label": generated_columns.get(col, {}).get("label", ""),
            "nan_count": nan_count,
            "unique_count": unique_count,
            "is_constant": is_constant,
            "issues": []
        }

        # 数值列额外检测 inf/0值/最值
        if col_type == "numeric":
            # 尝试转为数值（object 类型的数值列需要转换才能检测 inf）
            numeric_series = pd.to_numeric(series, errors='coerce')
            inf_count = int(np.isinf(numeric_series).sum())
            zero_count = int((numeric_series == 0).sum())
            col_info["inf_count"] = inf_count
            col_info["zero_count"] = zero_count
            # 计算最值时排除 inf 和 NaN，避免 JSON 序列化失败（JSON 不支持 inf）
            valid_numeric = numeric_series.replace([np.inf, -np.inf], np.nan).dropna()
            if len(valid_numeric) > 0:
                min_val = float(valid_numeric.min())
                max_val = float(valid_numeric.max())
                # 二次保护：确保不是 inf/nan（理论上已排除，防御性编程）
                col_info["min_value"] = min_val if np.isfinite(min_val) else None
                col_info["max_value"] = max_val if np.isfinite(max_val) else None
            if inf_count > 0:
                col_info["issues"].append("infinite_values")
                summary["columns_with_inf"] += 1
        else:
            col_info["inf_count"] = 0
            col_info["zero_count"] = 0

        # 汇总问题
        if nan_count > 0:
            col_info["issues"].append("missing_values")
            summary["columns_with_nan"] += 1
        if is_constant:
            col_info["issues"].append("constant_column")
            summary["constant_columns"] += 1

        # 高基数列检测（仅对非数值列，数值列高基数是正常的）
        if col_type != "numeric":
            ratio = unique_count / row_count if row_count > 0 else 0
            if unique_count > _HIGH_CARDINALITY_UNIQUE_THRESHOLD or ratio > _HIGH_CARDINALITY_RATIO_THRESHOLD:
                col_info["issues"].append("high_cardinality")
                summary["high_cardinality_columns"] += 1

        # 类型计数
        if col_type == "numeric":
            summary["numeric_columns"] += 1
        elif col_type == "datetime":
            summary["datetime_columns"] += 1
        else:
            summary["string_columns"] += 1

        columns_info.append(col_info)

    # ===== 操作可行性判断 =====
    # select_features：需要≥1个数值特征列（排除目标列后），自动排除含NaN/inf/常量的列
    # 注意：实际执行时会先排除目标列，因此预检需考虑目标列占用1个数值列的情况
    numeric_feature_cols = [c for c in columns_info
                            if c["type"] == "numeric"
                            and not c["is_constant"]
                            and "missing_values" not in c["issues"]
                            and "infinite_values" not in c["issues"]]
    select_warnings = []
    excluded_in_select = [c["name"] for c in columns_info
                          if c["type"] == "numeric" and
                          (c["is_constant"] or "missing_values" in c["issues"] or "infinite_values" in c["issues"])]
    if excluded_in_select:
        select_warnings.append(f"{len(excluded_in_select)}列含缺失值/无穷大/常量将被自动排除")
    # 可用数值列 ≤ 1 时：用户若选该列作为目标列，排除后将无可用特征列
    # 预检无法预知用户选哪列作目标列，因此降级为警告而非直接判定不可用
    if len(numeric_feature_cols) <= 1:
        select_warnings.append(
            f"可用数值列仅 {len(numeric_feature_cols)} 列，"
            f"若将其选为目标列则无可用特征，请确保目标列外还有可用数值特征"
        )
    select_feasible = len(numeric_feature_cols) >= 1

    # construct：无硬性限制，但含NaN/inf的列构造的新列可能继承NaN
    construct_warnings = []
    cols_with_issues = [c["name"] for c in columns_info if c["issues"]]
    if cols_with_issues:
        construct_warnings.append(f"{len(cols_with_issues)}列存在数据质量问题，构造的新列可能继承NaN/inf")
    construct_feasible = True

    # encode：OneHot不适合高基数列，Label编码无限制
    encode_warnings = []
    onehot_not_recommended = [c["name"] for c in columns_info if "high_cardinality" in c["issues"]]
    onehot_recommended = [c["name"] for c in columns_info
                          if c["type"] != "numeric" and "high_cardinality" not in c["issues"]
                          and not c["is_constant"]]
    if onehot_not_recommended:
        encode_warnings.append(f"{len(onehot_not_recommended)}列基数过高，不建议OneHot编码")
    encode_feasible = len([c for c in columns_info if c["type"] != "numeric"]) >= 1

    # scale：需要≥1个可用数值列（无NaN/inf/常量）
    scale_blocked = [c["name"] for c in columns_info
                     if c["type"] == "numeric" and
                     (c["is_constant"] or "missing_values" in c["issues"] or "infinite_values" in c["issues"])]
    scale_available = [c["name"] for c in columns_info
                       if c["type"] == "numeric"
                       and not c["is_constant"]
                       and "missing_values" not in c["issues"]
                       and "infinite_values" not in c["issues"]]
    scale_feasible = len(scale_available) >= 1
    scale_reason = ""
    if not scale_feasible:
        scale_reason = "没有可缩放的数值列（所有数值列均含缺失值/无穷大/常量），需先清洗"

    # reduce：需要≥2个可用数值列（无NaN/inf/常量）
    reduce_blocked = scale_blocked  # 与 scale 相同的判定
    reduce_available = scale_available
    reduce_feasible = len(reduce_available) >= 2
    reduce_reason = ""
    if not reduce_feasible:
        reduce_reason = f"可用数值列不足（需≥2列），当前仅{len(reduce_available)}列可用，需先清洗"

    operation_feasibility = {
        "select_features": {
            "feasible": select_feasible,
            "warnings": select_warnings,
            "excluded_columns": excluded_in_select,
            "available_columns": [c["name"] for c in numeric_feature_cols]
        },
        "construct": {
            "feasible": construct_feasible,
            "warnings": construct_warnings,
            "problem_columns": cols_with_issues
        },
        "encode": {
            "feasible": encode_feasible,
            "warnings": encode_warnings,
            "onehot_recommended_columns": onehot_recommended,
            "onehot_not_recommended": onehot_not_recommended
        },
        "scale": {
            "feasible": scale_feasible,
            "reason": scale_reason,
            "blocked_columns": scale_blocked,
            "available_columns": scale_available
        },
        "reduce": {
            "feasible": reduce_feasible,
            "reason": reduce_reason,
            "blocked_columns": reduce_blocked,
            "available_columns": reduce_available
        }
    }

    # ===== 综合建议 =====
    recommendations = []
    if summary["columns_with_nan"] > 0:
        recommendations.append(f"建议先在数据清洗模块处理 {summary['columns_with_nan']} 列的缺失值")
    if summary["columns_with_inf"] > 0:
        recommendations.append(f"建议处理 {summary['columns_with_inf']} 列的无穷大值（通常是除法构造时分母为0导致）")
    if summary["constant_columns"] > 0:
        recommendations.append(f"建议删除 {summary['constant_columns']} 个常量列（无信息量，影响缩放/降维/特征选择）")
    if summary["high_cardinality_columns"] > 0:
        recommendations.append(f"{summary['high_cardinality_columns']} 列基数过高，不建议OneHot编码（可用Label编码或先分箱）")
    if not recommendations:
        recommendations.append("数据质量良好，所有特征工程操作均可正常执行")

    result = {
        "dataset_id": dataset_id if not is_remote else (workcopy.id if workcopy else None),
        "row_count": row_count,
        "column_count": len(df.columns),
        "columns": columns_info,
        "summary": summary,
        "operation_feasibility": operation_feasibility,
        "recommendations": recommendations
    }

    # 缓存 5 分钟
    cache_manager.set(cache_key, result, ttl=300)

    return result


# ============================================================
# 任务进度查询接口（供前端轮询异步任务进度）
# ============================================================

@router.get("/progress/{record_id}")
async def get_task_progress(record_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """查询特征工程任务进度

    供前端轮询异步任务执行进度，返回 task_records 中的 status 和 result_summary。

    Args:
        record_id: 任务记录ID（执行接口返回的 task_record_id）

    Returns:
        任务状态、进度信息、最终结果（若已完成）
    """
    from app.models import TaskRecord
    record = db.query(TaskRecord).filter(
        TaskRecord.id == record_id,
        TaskRecord.user_id == current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="任务记录不存在")

    # 解析 result_summary 中的进度信息
    result_summary = record.result_summary if isinstance(record.result_summary, dict) else {}
    current_stage = result_summary.get("current_stage", "")
    current_progress = result_summary.get("current_progress", 0)
    current_message = result_summary.get("current_message", "")

    # 任务完成时附带最终结果，便于前端直接展示
    final_result = None
    if record.status == "success":
        final_result = result_summary

    return {
        "task_record_id": record.id,
        "status": record.status,  # running/success/failed
        "current_stage": current_stage,
        "current_progress": current_progress,
        "current_message": current_message,
        "error_message": record.error_message,
        "execution_time": record.execution_time,
        "result_summary": result_summary,
        "final_result": final_result,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None
    }