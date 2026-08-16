"""
公共工具函数模块

提取项目中多个文件重复定义的函数，统一管理，减少代码冗余。
"""

import os
import re
from datetime import datetime, timezone, timedelta

from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models import Dataset
from app.services.cache_manager import cache_manager
from app.utils.task_labels import MODULE_LABEL_MAP, ARTIFACT_LABEL_MAP

# 任务类型中文标签映射（task_type → 中文显示名）
# 统一使用完整模块名，避免缩写造成理解困难
# 注意：此映射用于 AI 分析上下文展示，与 task_labels.TASK_TYPE_LABELS（操作历史使用）语义不同，故保留在此
TASK_TYPE_LABEL_MAP = {
    "upload": "数据上传",
    "cleaning": "数据清洗",
    "ml_training": "机器学习训练",
    "ml": "机器学习分析",
    "data_mining": "数据挖掘",
    "feature_engineering": "特征工程",
    "feature_engineering_select": "特征工程",
    "feature_engineering_construct": "特征工程",
    "feature_engineering_encode": "特征工程",
    "feature_engineering_scale": "特征工程",
    "feature_engineering_reduce": "特征工程",
    "data_analysis": "数据分析",
}

# 允许上传的文件扩展名白名单（前后端需保持一致）
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


def validate_upload_file(file: UploadFile) -> None:
    """校验上传文件扩展名是否在白名单内，不在则抛出 400。"""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext or '无扩展名'}，仅支持 CSV/Excel/JSON"
        )


def clear_user_dataset_cache(user_id: int):
    """清理用户的所有数据集列表缓存（支持通配符匹配）
    
    Args:
        user_id: 用户ID
    """
    cache_prefix = f"datasets:user:{user_id}:list"
    cache_manager.delete_pattern(f"{cache_prefix}*")


def clean_dataset_name(name: str) -> str:
    """
    清理数据集名称：剥离历史拼接模式（时间戳/导入/产物后缀），返回干净名称。

    命名原则（2026-08-13 起）：名称即用户所起，系统不再追加时间戳、序号、算法名等后缀。
    同名数据集允许存在，区分靠 dataset_id + 按 id 派生的颜色 + 创建时间。
    历史数据中已存在的拼接模式在此处一次性剥离（如 ` · 2026-08-13 14-30-22`、
    `_import_2026-08-13 14-30-22`、`_clean_2026-08-13 14-30-22` 等）。

    Args:
        name: 原始名称（文件名或远程表名）

    Returns:
        清理后的干净名称
    """
    if not name:
        return name
    # 剥离 ensure_unique_name 旧格式：` · 2026-08-13 14-30-22`
    name = re.sub(r' · \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}', '', name)
    # 剥离导入旧格式：`_import_2026-08-13 14-30-22`
    name = re.sub(r'_import_\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}', '', name)
    # 剥离产物旧格式：`_2026-08-13 14-30-22` / `_clean_2026-08-13 14-30-22`
    name = re.sub(r'_(clean_)?\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}', '', name)
    return name.strip()


def build_product_name(source_name: str, ext: str) -> str:
    """
    构造产物名称：源名去扩展名后追加真实内容后缀。

    命名原则（2026-08-13 起）：产物保留源名（不拼算法名/时间戳/英文前缀等用户不知情的字样），
    仅按真实内容替换后缀，保证展示、下载、预览时名实相符。
    例如 `销售数据.csv` 的聚类产物 -> `销售数据.csv`（内容仍为 CSV）、
    关联规则产物 -> `销售数据.json`、ML 模型产物 -> `销售数据.pkl`。

    Args:
        source_name: 源数据集名称（可能含原扩展名，如 `销售数据.csv`）或远程表名
        ext: 真实内容后缀（如 "csv"/"json"/"pkl"/"html"，可带点也可不带）

    Returns:
        产物名称，如 `销售数据.csv` / `销售数据.pkl`
    """
    base = clean_dataset_name(source_name or "")
    base = os.path.splitext(base)[0]  # 去掉源名自身的扩展名，避免双后缀
    return f"{base}.{ext.lstrip('.')}"


def get_dataset_or_404(db: Session, dataset_id: int, user_id: int) -> Dataset:
    """
    获取数据集，不存在则抛出404异常。
    
    Args:
        db: 数据库会话
        dataset_id: 数据集ID
        user_id: 用户ID
    
    Returns:
        Dataset对象
    
    Raises:
        HTTPException: 数据集不存在时抛出404异常
    """
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.user_id == user_id,
        Dataset.status == "active"
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return dataset


def get_numeric_columns(df: pd.DataFrame) -> List[str]:
    """
    获取所有数值列。
    
    判断逻辑：
    1. 直接是数值类型的列
    2. 非数值类型但超过80%的值可以转换为数值的列
    
    Args:
        df: 数据框
    
    Returns:
        数值列名列表
    """
    cols = []
    for col in df.columns:
        # 布尔列和日期时间列不应被当作数值列，避免与图表模块的列分类不一致
        if pd.api.types.is_bool_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(col)
        else:
            non_null = df[col].dropna()
            if len(non_null) > 0:
                converted = pd.to_numeric(non_null, errors='coerce')
                if converted.notna().sum() / len(non_null) > 0.8:
                    cols.append(col)
    return cols


def to_numeric_if_possible(series: pd.Series) -> pd.Series:
    """
    如果列可以转为数值，则转换。
    
    判断逻辑：超过80%的非空值可以转换为数值时进行转换。
    
    Args:
        series: 数据列
    
    Returns:
        转换后的数据列（可能保持原类型）
    """
    if pd.api.types.is_numeric_dtype(series):
        return series
    non_null = series.dropna()
    if len(non_null) == 0:
        return series
    converted = pd.to_numeric(non_null, errors='coerce')
    if converted.notna().sum() / len(non_null) > 0.8:
        return pd.to_numeric(series, errors='coerce')
    return series


def safe_value(value: Any) -> Any:
    """
    安全地处理值，避免JSON序列化错误。
    
    将numpy类型转换为Python原生类型，处理无穷值。
    
    Args:
        value: 任意值
    
    Returns:
        安全的可序列化值
    """
    import numpy as np
    
    if isinstance(value, np.integer):
        return int(value)
    elif isinstance(value, np.floating):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    elif isinstance(value, np.ndarray):
        return value.tolist()
    elif isinstance(value, pd.Series):
        return value.tolist()
    elif isinstance(value, pd.DataFrame):
        return value.to_dict(orient='records')
    elif isinstance(value, (datetime,)):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    else:
        # pd.isna 对标量值正常工作，但对列表/字典等类型可能抛 TypeError
        # 用 try-except 保护，确保不会因类型检查异常中断调用方的循环
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value


def check_data_quality(df: pd.DataFrame, columns: List[str] = None) -> Dict[str, Any]:
    """
    检测数据质量问题。
    
    检测以下问题：
    - 无穷大值（inf/-inf）
    - NaN缺失值
    - 非数值列
    - 重复行数（数据集整体）
    - 常量列（唯一值数量≤1的列）
    
    Args:
        df: 数据框
        columns: 需要检测的列名列表（None表示检测所有列）
    
    Returns:
        检测结果字典，包含问题类型和受影响的列名列表
    """
    import numpy as np
    
    result = {
        'infinite_columns': [],
        'nan_columns': [],
        'non_numeric_columns': [],
        'duplicate_rows': 0,
        'constant_columns': []
    }
    
    check_cols = columns if columns else df.columns
    
    for col in check_cols:
        if col not in df.columns:
            continue
        
        series = df[col]
        
        # 常量列检测：非空唯一值数量≤1 视为常量列
        # nunique() 默认不统计 NaN，全空列返回0、单值列返回1
        if series.nunique() <= 1:
            result['constant_columns'].append(col)
        
        if not pd.api.types.is_numeric_dtype(series):
            result['non_numeric_columns'].append(col)
            continue
        
        has_infinite = np.isinf(series).any()
        has_nan = series.isna().any()
        
        if has_infinite:
            result['infinite_columns'].append(col)
        if has_nan:
            result['nan_columns'].append(col)
    
    # 重复行检测：针对整个数据框，与 columns 参数无关
    result['duplicate_rows'] = int(df.duplicated().sum())
    
    return result


def get_root_dataset_id(db: Session, input_dataset: Dataset) -> int:
    """
    获取根数据ID：继承或使用输入数据集自己的id。
    
    Args:
        db: 数据库会话
        input_dataset: 输入数据集
    
    Returns:
        根数据集ID
    """
    if input_dataset.root_dataset_id:
        return input_dataset.root_dataset_id
    return input_dataset.id


def compute_numeric_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算数值列的统计信息。
    
    包含基础统计量（均值、中位数、标准差等）以及增强统计量：
    - 偏度（skewness）和峰度（kurtosis）
    - 高阶分位数 P90/P95/P99
    - 变异系数 CV
    - 众数（取第一个众数值）
    - 零值数量与零值率
    
    Args:
        df: 数据框
    
    Returns:
        统计信息字典
    """
    numeric_cols = get_numeric_columns(df)
    stats = {}
    for col in numeric_cols:
        col_data = to_numeric_if_possible(df[col]).dropna()
        missing_count = int(df[col].isna().sum())
        total = len(df)
        if len(col_data) > 0:
            mean_val = float(col_data.mean())
            std_val = float(col_data.std())

            # 变异系数：均值接近0时无意义，返回 None 避免除零
            cv = round(std_val / mean_val, 4) if mean_val != 0 else None

            # 众数：可能存在多个众数，取第一个；数据全相同或不足时返回 None
            try:
                mode_val = col_data.mode().iloc[0]
                # 转为 Python 原生类型，避免 numpy 类型序列化问题
                mode_val = safe_value(mode_val)
            except (IndexError, ValueError):
                mode_val = None

            # 零值统计：仅在数值列中存在 0 时统计
            zero_count = int((col_data == 0).sum())
            zero_rate = round(zero_count / len(col_data) * 100, 2) if len(col_data) > 0 else 0

            stats[col] = {
                "mean": round(mean_val, 4),
                "median": round(float(col_data.median()), 4),
                "std": round(std_val, 4),
                "min": round(float(col_data.min()), 4),
                "max": round(float(col_data.max()), 4),
                "q25": round(float(col_data.quantile(0.25)), 4),
                "q50": round(float(col_data.quantile(0.50)), 4),
                "q75": round(float(col_data.quantile(0.75)), 4),
                "p90": round(float(col_data.quantile(0.90)), 4),
                "p95": round(float(col_data.quantile(0.95)), 4),
                "p99": round(float(col_data.quantile(0.99)), 4),
                "skewness": round(float(col_data.skew()), 4),
                "kurtosis": round(float(col_data.kurtosis()), 4),
                "cv": cv,
                "mode": mode_val,
                "zero_count": zero_count,
                "zero_rate": zero_rate,
                "unique_count": int(col_data.nunique()),
                "missing_count": missing_count,
                "missing_rate": round(missing_count / total * 100, 2) if total > 0 else 0
            }
        else:
            stats[col] = {
                "mean": None, "median": None, "std": None,
                "min": None, "max": None,
                "q25": None, "q50": None, "q75": None,
                "p90": None, "p95": None, "p99": None,
                "skewness": None, "kurtosis": None,
                "cv": None, "mode": None,
                "zero_count": 0, "zero_rate": 0,
                "unique_count": 0,
                "missing_count": missing_count,
                "missing_rate": round(missing_count / total * 100, 2) if total > 0 else 0
            }
    return stats