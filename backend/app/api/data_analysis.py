from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import io
import html
import time
import json
import re
from datetime import datetime, timezone, timedelta

SHANGHAI_TZ = timezone(timedelta(hours=8))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# 中文字体配置：按优先级尝试加载系统中可用的中文字体，避免 Docker 容器中文字体缺失导致的乱码
def _get_chinese_font():
    """检测系统中可用的中文字体，返回字体名称列表。
    若没有可用中文字体，则返回 ['DejaVu Sans'] 作为后备（需配合英文标签降级方案）。"""
    preferred_fonts = [
        'SimHei', 'Microsoft YaHei', 'WenQuanYi Zen Hei',
        'Noto Sans CJK SC', 'Noto Sans SC', 'Source Han Sans SC',
        'PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS'
    ]
    # 收集系统中所有已注册的字体名称
    available_fonts = set()
    for font in fm.fontManager.ttflist:
        available_fonts.add(font.name)

    result = [f for f in preferred_fonts if f in available_fonts]
    if not result:
        # 未找到中文字体，使用 DejaVu Sans 作为后备
        result = ['DejaVu Sans']
    return result


# 模块加载时检测一次即可，避免重复扫描字体列表
_CHINESE_FONTS = _get_chinese_font()
# 是否有可用中文字体（False 时使用英文标签降级方案）
_HAS_CHINESE_FONT = _CHINESE_FONTS != ['DejaVu Sans']

# 中文标签对应的英文降级文案：当容器中没有中文字体时使用，避免乱码
_LABEL_ZH_TO_EN = {
    "频数": "Frequency",
    "值": "Value",
    "密度": "Density",
    "理论分位数": "Theoretical Quantiles",
    "样本分位数": "Sample Quantiles",
    "箱线图": "Boxplot",
    "相关性热力图": "Correlation Heatmap",
    "表格热力图": "Table Heatmap",
    "雷达图": "Radar Chart",
    "多折线图": "Multi-Line Chart",
    "双 Y 轴图": "Dual Y-Axis Chart",
    "堆叠柱状图": "Stacked Bar Chart",
    "面积图": "Area Chart",
    "散点图": "Scatter Plot",
    "折线图": "Line Chart",
    "饼图": "Pie Chart",
    "分布直方图": "Distribution Histogram",
    "KDE 密度图": "KDE Density Plot",
    "QQ 图": "QQ Plot",
    "各分类": "by Category",
    "总和柱状图": "Sum Bar Chart",
    "参考线": "Reference Line",
    "样本": "Sample",
    "大小": "Size",
    "分箱": "Bins",
}

# 图表类型代码 → 中文标签（与前端 allChartTypeOptions 一致）
# 用于报告 HTML 中图表标题的 fallback：前端未传 title 时用中文标签代替英文 chart_type
_CHART_TYPE_LABELS_ZH = {
    "histogram": "频数直方图",
    "boxplot": "箱线图",
    "pie": "饼图",
    "heatmap": "热力图",
    "bar": "柱状图",
    "stacked_bar": "堆叠柱状图",
    "area": "面积图",
    "kde": "单变量KDE密度图",
    "qq": "标准化QQ图",
    "bubble": "气泡图",
    "multi_line": "多折线图",
    "dual_axis": "双Y轴图",
    "radar": "雷达图",
    "table_heatmap": "表格热力图",
    "scatter": "散点图",
}


def _build_chart_title(chart_type: str, params: Dict[str, Any], frontend_title: str = None) -> str:
    """根据图表类型和参数构建带列关系信息的标题，与前端 buildChartTitle 逻辑一致。

    优先使用前端传来的 title；若无则按图表类型从 params 提取列关系信息，
    生成类似 "单变量KDE密度图：销量" 或 "气泡图：单价 vs 销量（大小：客户数）" 的标题。
    """
    # 前端已构建好标题时直接使用
    if frontend_title and frontend_title.strip() and frontend_title.strip() != chart_type:
        return frontend_title.strip()

    label = _CHART_TYPE_LABELS_ZH.get(chart_type, f"{chart_type} 图表")
    p = params or {}

    # X 轴列名转换：__index__ 或空值显示为"行索引"
    def _x_name(col):
        if not col or col == "__index__":
            return "行索引"
        return col

    if chart_type in ("histogram", "boxplot", "kde"):
        cols = p.get("columns") or ([p["column"]] if p.get("column") else [])
        return f"{label}：{'、'.join(cols) if cols else '数值列'}"
    if chart_type == "pie":
        return f"{label}：{p.get('column', '')}"
    if chart_type == "qq":
        cols = p.get("columns") or ([p["column"]] if p.get("column") else [])
        return f"{label}：{'、'.join(cols) if cols else '数值列'}"
    if chart_type in ("scatter", "bar", "area"):
        y_cols = p.get("y_columns") or []
        return f"{label}：{_x_name(p.get('x_column'))} vs {'、'.join(y_cols) if y_cols else ''}"
    if chart_type == "bubble":
        return f"{label}：{p.get('x_column', '')} vs {p.get('y_column', '')}（大小：{p.get('size_column', '')}）"
    if chart_type == "dual_axis":
        return f"{label}：{_x_name(p.get('x_column'))}（{p.get('y1_column', '')} / {p.get('y2_column', '')}）"
    if chart_type == "stacked_bar":
        cols = p.get("y_columns") or p.get("columns") or []
        return f"{label}：{_x_name(p.get('x_column'))} / {'、'.join(cols) if cols else ''}"
    if chart_type == "multi_line":
        cols = p.get("columns") or []
        return f"{label}：{_x_name(p.get('x_column'))} / {'、'.join(cols) if cols else ''}"
    if chart_type == "radar":
        cols = p.get("columns") or []
        return f"{label}：{'、'.join(cols) if cols else '数值列'}"
    if chart_type == "table_heatmap":
        parts = [v for v in [p.get("x_column"), p.get("y_column"), p.get("value_column")] if v]
        return f"{label}：{' × '.join(parts) if parts else '全表'}"
    if chart_type == "heatmap":
        cols = p.get("columns") or []
        return f"{label}：{'、'.join(cols) if cols else '数值列相关性'}"
    if chart_type == "line":
        y_cols = p.get("y_columns") or []
        return f"{label}：{_x_name(p.get('x_column'))} vs {'、'.join(y_cols) if y_cols else ''}"
    return label


def _tr(label: str) -> str:
    """根据当前字体可用性返回标签文本。
    有中文字体时返回原文；否则返回英文降级文案（找不到映射则原样返回）。"""
    if _HAS_CHINESE_FONT:
        return label
    return _LABEL_ZH_TO_EN.get(label, label)

from app.models import Dataset, User
from app.schemas.dataset import DatasetResponse
from app.services.data_service import DataService
from app.services.storage_manager import storage_manager
from app.services.clickhouse_service import clickhouse_service, ClickHouseUnavailable
from app.utils.db import get_db, SessionLocal
from app.utils.security import get_current_user
from app.utils.common import clean_dataset_name, build_product_name, get_dataset_or_404, compute_numeric_stats, get_numeric_columns, to_numeric_if_possible, check_data_quality, clear_user_dataset_cache, MODULE_LABEL_MAP, validate_upload_file, safe_value
from app.utils.task_records import (
    create_task_record, update_task_record, update_task_progress,
    mark_task_running, classify_failure, check_task_queue_capacity
)
from app.services.task_manager import task_manager
from app.config import settings
from celery.exceptions import SoftTimeLimitExceeded

router = APIRouter()


# ========== 请求模型 ==========

class ChartRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    remote: Optional[Dict[str, Any]] = None  # 远程数据源配置
    chart_type: str
    params: Dict[str, Any] = {}


class ReportRequest(BaseModel):
    """数据分析报告请求模型：支持选择章节与自定义图表"""
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    remote: Optional[Dict[str, Any]] = None  # 远程数据源配置
    sections: Optional[List[str]] = None
    charts: Optional[List[Dict[str, Any]]] = None
    options: Optional[Dict[str, Any]] = None


class SaveReportRequest(BaseModel):
    """保存报告请求模型"""
    report_html: str
    report_type: str = "static"
    report_data: Optional[Dict[str, Any]] = None
    # 远程数据源配置（远程模式保存报告时使用，与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None


# ========== 辅助函数 ==========

def _is_numeric_column(series: pd.Series) -> bool:
    """判断一列是否为数值列（尝试转换，成功率>80%视为数值）。

    布尔列和日期时间列不参与数值判断，确保与 get_numeric_columns 保持一致。
    """
    if pd.api.types.is_numeric_dtype(series):
        return True
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return False
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    converted = pd.to_numeric(non_null, errors='coerce')
    success_rate = converted.notna().sum() / len(non_null)
    return success_rate > 0.8


def _clean_json_data(obj):
    """递归清洗数据中的 NaN, Inf, -Inf，使其可被 JSON 序列化"""
    if isinstance(obj, dict):
        return {k: _clean_json_data(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_json_data(item) for item in obj]
    elif isinstance(obj, pd.Series):
        return _clean_json_data(obj.tolist())
    elif isinstance(obj, np.ndarray):
        return _clean_json_data(obj.tolist())
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, bool):
        return obj
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj) or np.isneginf(obj):
            return None
        return obj
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        if np.isnan(obj) or np.isinf(obj) or np.isneginf(obj):
            return None
        return float(obj)
    else:
        return obj


def _is_datetime_column(series: pd.Series) -> bool:
    """判断一列是否为时间列"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    try:
        pd.to_datetime(non_null, errors='raise')
        return True
    except (ValueError, TypeError):
        return False


def _get_column_tags(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    """获取列的标签信息，用于图表推荐和限制"""
    series = df[column]
    is_numeric = _is_numeric_column(series)
    is_datetime = _is_datetime_column(series)
    
    total = len(df)
    non_null = series.dropna()
    missing_count = total - len(non_null)
    missing_rate = missing_count / total if total > 0 else 0
    
    unique_count = len(non_null.unique())
    uniqueness = unique_count / len(non_null) if len(non_null) > 0 else 0
    
    tags = {
        "name": column,
        "is_numeric": is_numeric,
        "is_categorical": not is_numeric and not is_datetime,
        "is_datetime": is_datetime,
        "is_constant": unique_count == 1,
        "is_identifier": uniqueness > 0.9 and is_numeric is False,
        "high_cardinality": unique_count > 20 and not is_numeric,
        "missing_rate": round(missing_rate, 4),
        "unique_count": unique_count,
        "uniqueness": round(uniqueness, 4),
        "quality_score": 0,
        "availability": "available",
        "availability_reason": ""
    }
    
    quality_score = 100
    issues = []
    
    if tags["is_constant"]:
        quality_score -= 50
        tags["availability"] = "disabled"
        tags["availability_reason"] = "该列所有值相同，无法生成有意义的图表"
        issues.append("常量列")
    
    if tags["is_identifier"]:
        quality_score -= 80
        tags["availability"] = "disabled"
        tags["availability_reason"] = "该列是唯一标识符，不适合作为分类轴"
        issues.append("标识符列")
    
    if tags["missing_rate"] > 0.5:
        quality_score -= 50
        tags["availability"] = "disabled"
        tags["availability_reason"] = f"缺失值超过50%({round(missing_rate*100,1)}%)，无法生成有意义的图表"
        issues.append("缺失值过多")
    elif tags["missing_rate"] > 0.3:
        quality_score -= 20
        tags["availability"] = "warning"
        tags["availability_reason"] = f"缺失值较多({round(missing_rate*100,1)}%)，结果可能有偏差"
        issues.append("缺失值较多")
    elif tags["missing_rate"] > 0.1:
        quality_score -= 10
        tags["availability"] = "warning"
        tags["availability_reason"] = f"存在缺失值({round(missing_rate*100,1)}%)"
    
    if tags["high_cardinality"]:
        quality_score -= 20
        tags["availability_reason"] = f"类别过多({unique_count}个)，图表可能拥挤"
    
    if is_numeric:
        num_data = to_numeric_if_possible(series).dropna()
        if len(num_data) > 0:
            q1 = num_data.quantile(0.25)
            q3 = num_data.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outlier_count = len(num_data[(num_data < lower) | (num_data > upper)])
            outlier_rate = outlier_count / len(num_data)
            tags["outlier_rate"] = round(outlier_rate, 4)
            if outlier_rate > 0.2:
                quality_score -= 15
                tags["availability_reason"] = f"存在较多极端值({round(outlier_rate*100,1)}%)"
    
    tags["quality_score"] = max(0, min(100, int(quality_score)))
    
    return tags


def _get_column_tags_all(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """获取所有列的标签信息"""
    return {col: _get_column_tags(df, col) for col in df.columns}


def _validate_chart_params(df: pd.DataFrame, chart_type: str, params: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """统一校验图表参数，非法参数直接抛出 HTTPException(400)。

    该校验覆盖：列是否存在、列是否可用（常量/标识符/缺失过多禁用）、
    图表类型所需列数与列类型是否满足。

    返回所有列的标签信息，供调用方复用。
    """
    if df is None or df.empty or len(df.columns) == 0:
        raise HTTPException(status_code=400, detail="数据集为空，无法生成图表")

    supported_types = {
        "histogram", "scatter", "boxplot", "line", "pie", "heatmap",
        "bar", "stacked_bar", "area", "kde", "qq", "bubble",
        "multi_line", "dual_axis", "radar", "table_heatmap"
    }
    if chart_type not in supported_types:
        raise HTTPException(status_code=400, detail=f"不支持的图表类型: {chart_type}")

    column_tags = _get_column_tags_all(df)

    # 收集所有被引用的列名
    cols = set()
    x_col = params.get("x_column")
    y_col = params.get("y_column")
    y1_col = params.get("y1_column")
    y2_col = params.get("y2_column")
    size_col = params.get("size_column")
    value_col = params.get("value_column")
    column = params.get("column")

    y_columns = params.get("y_columns") or []
    if isinstance(y_columns, str):
        y_columns = [c.strip() for c in y_columns.split(",") if c.strip()]
    columns = params.get("columns") or []
    if isinstance(columns, str):
        columns = [c.strip() for c in columns.split(",") if c.strip()]

    # 统一归一化新旧参数格式，确保单参数与数组参数都能被后续校验识别
    if not y_col and y_columns:
        y_col = y_columns[0]
    if not column and columns:
        column = columns[0]

    if x_col:
        cols.add(x_col)
    if y_col:
        cols.add(y_col)
    if y1_col:
        cols.add(y1_col)
    if y2_col:
        cols.add(y2_col)
    if size_col:
        cols.add(size_col)
    if value_col:
        cols.add(value_col)
    if column:
        cols.add(column)
    cols.update(y_columns)
    cols.update(columns)

    # 校验列存在与可用性
    for col in cols:
        if col not in df.columns:
            raise HTTPException(status_code=400, detail=f"列 '{col}' 不存在")
        tags = column_tags[col]
        if tags.get("availability") == "disabled":
            reason = tags.get("availability_reason") or "暂不可用"
            raise HTTPException(status_code=400, detail=f"列 '{col}' {reason}")

    # 辅助校验函数
    def _require_numeric(cols_to_check, axis_name=""):
        for col in cols_to_check:
            if not column_tags[col]["is_numeric"]:
                prefix = f"{axis_name}" if axis_name else "图表"
                raise HTTPException(status_code=400, detail=f"{prefix}需要数值列，'{col}' 不是数值列")

    def _require_categorical(cols_to_check, axis_name=""):
        for col in cols_to_check:
            if not column_tags[col]["is_categorical"]:
                prefix = f"{axis_name}" if axis_name else "图表"
                raise HTTPException(status_code=400, detail=f"{prefix}需要分类列，'{col}' 不是分类列")

    # 按图表类型校验
    if chart_type in {"histogram", "boxplot", "kde", "qq"}:
        target = columns if columns else ([column] if column else [])
        if not target:
            raise HTTPException(status_code=400, detail="请至少选择一个数值列")
        _require_numeric(target)
    elif chart_type in {"scatter", "bubble"}:
        if not x_col or not y_col:
            detail = "气泡图需要设置 X 轴列和 Y 轴列" if chart_type == "bubble" else "散点图需要设置 X 轴列和 Y 轴列"
            raise HTTPException(status_code=400, detail=detail)
        _require_numeric([x_col, y_col], "气泡图" if chart_type == "bubble" else "散点图")
        if chart_type == "bubble":
            if not size_col:
                raise HTTPException(status_code=400, detail="气泡图需要设置大小列")
            _require_numeric([size_col], "气泡图大小")
    elif chart_type in {"line", "bar", "area", "stacked_bar"}:
        # X 轴列为空时允许使用行索引，由 _get_chart_data 自动补充
        y_cols = y_columns if y_columns else ([y_col] if y_col else [])
        if not y_cols:
            raise HTTPException(status_code=400, detail="请至少设置一个 Y 轴列")
        _require_numeric(y_cols, f"{chart_type}图 Y 轴")
    elif chart_type == "multi_line":
        # 多折线图使用 columns 作为多个 Y 轴列
        target_cols = columns if columns else []
        if not target_cols:
            raise HTTPException(status_code=400, detail="请至少设置一个 Y 轴列")
        _require_numeric(target_cols, "多折线图 Y 轴")
    elif chart_type == "dual_axis":
        # X 轴列为空时允许使用行索引
        if not y1_col or not y2_col:
            raise HTTPException(status_code=400, detail="双 Y 轴图需要设置 Y1 轴列和 Y2 轴列")
        _require_numeric([y1_col, y2_col], "双 Y 轴图")
    elif chart_type == "pie":
        target = column or (columns[0] if columns else None)
        if not target:
            raise HTTPException(status_code=400, detail="请选择要展示的分类列")
        _require_categorical([target], "饼图")
    elif chart_type in {"heatmap", "radar"}:
        # 未显式指定列时默认使用全部数值列（与生成逻辑一致），仅在显式指定时校验数量与类型
        # heatmap 至少 2 个数值列；radar 至少 3 个数值列作为维度
        if columns:
            min_required = 2 if chart_type == "heatmap" else 3
            if len(columns) < min_required:
                raise HTTPException(status_code=400, detail=f"{chart_type}图需要至少 {min_required} 个数值列")
            _require_numeric(columns)
    elif chart_type == "table_heatmap":
        # 完整设置（行/列/值）时走透视表模式，值列必须为数值列；
        # 未完整设置时走简单模式（展示前 20 行数值列），两种模式均合法
        if x_col and y_col and value_col:
            _require_numeric([value_col], "表格热力图值")

    return column_tags


def _detect_dual_axis_needed(df: pd.DataFrame, y_columns: list, col_minmax: Optional[dict] = None) -> bool:
    """检测是否需要双Y轴：当多列Y轴数据量纲差异超过10倍时返回True

    col_minmax: 可选。CH 加速分支传入 {列名: {"min":.., "max":..}}，df 为 None 时使用。
    """
    if len(y_columns) < 2:
        return False

    ranges = []
    for col in y_columns:
        if col_minmax is not None:
            cm = col_minmax.get(col)
            if cm is None or cm.get("min") is None or cm.get("max") is None:
                continue
            col_range = float(cm["max"]) - float(cm["min"])
            if col_range > 0:
                ranges.append(col_range)
            continue
        if col not in df.columns or not _is_numeric_column(df[col]):
            continue
        col_data = to_numeric_if_possible(df[col]).dropna()
        if len(col_data) == 0:
            continue
        col_range = float(col_data.max() - col_data.min())
        if col_range > 0:
            ranges.append(col_range)
    
    if len(ranges) < 2:
        return False
    
    min_range = min(ranges)
    max_range = max(ranges)

    # 当最小值范围为 0 或最大值范围为 0 时，量纲差异无法通过比值衡量，直接返回 False
    if min_range == 0 or max_range == 0:
        return False

    return max_range / min_range > 10


def _get_chart_categorical_columns(df: pd.DataFrame) -> List[str]:
    """获取图表模块可用的分类列：所有非数值列都可作为 X 轴/分类轴。

    注意：这里不过滤 identifier 列，因为高唯一性的时间、ID、名称等列在可视化中仍可作为分类轴。
    """
    return [c for c in df.columns if not _is_numeric_column(df[c])]


def _validate_recommendation_params(df: pd.DataFrame, chart_type: str, params: Dict[str, Any],
                                    col_is_numeric: Optional[Dict[str, bool]] = None) -> bool:
    """校验推荐参数是否真的能成功生成图表，避免推荐不可执行的方案。

    col_is_numeric: 可选。CH 加速分支传入 {列名: 是否数值列}，df 为 None 时使用。
    """
    try:
        # 收集所有涉及的列
        cols = set()
        x_col = params.get("x_column") or ""
        if x_col:
            cols.add(x_col)

        # 收集 Y 轴列（数值列）；column 是饼图的分类维度列，不属于 Y 轴
        y_cols = []
        for key in ("y_columns", "columns"):
            val = params.get(key)
            if isinstance(val, (list, tuple)):
                y_cols.extend(val)
            elif val:
                y_cols.append(val)
        for key in ("y_column", "y1_column", "y2_column", "size_column", "value_column"):
            val = params.get(key)
            if val:
                y_cols.append(val)

        for c in y_cols:
            if c:
                cols.add(c)

        # 饼图的维度列 column 单独纳入存在性校验
        pie_column = params.get("column")
        if pie_column:
            cols.add(pie_column)

        all_cols = set(df.columns) if df is not None else set((col_is_numeric or {}).keys())

        def _is_num(c):
            if df is not None:
                return _is_numeric_column(df[c])
            return bool(col_is_numeric.get(c, False))

        # 所有列必须存在
        for c in cols:
            if c not in all_cols:
                return False

        # X 轴列不能和 Y 轴列重叠
        if x_col and x_col in y_cols:
            return False

        # Y 轴列必须都是数值列
        for c in y_cols:
            if c and not _is_num(c):
                return False

        # bar/stacked_bar 需要分类列作为 X 轴
        if chart_type in ("bar", "stacked_bar"):
            if not x_col or x_col not in all_cols:
                return False

        # pie 使用 column 作为维度列（而非 x_column），且必须是分类列
        if chart_type == "pie":
            if not pie_column or pie_column not in all_cols or _is_num(pie_column):
                return False

        # 趋势类图表的 X 轴不应使用数值列，避免把指标误当作维度
        if chart_type in ("line", "area", "multi_line") and x_col:
            if _is_num(x_col):
                return False

        return True
    except Exception:
        return False


def _sanitize_recommendation_params(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """清洗推荐参数：移除 X 轴列与 Y 轴列的重叠，并保证列表型列参数无重复。

    若清洗后没有任何可用的 Y 轴/数值列，则返回 None，表示该推荐无法执行。
    """
    params = dict(params)
    x_col = params.get("x_column") or ""

    if not x_col:
        # 没有 X 轴列时，只需对列表型参数去重
        for key in ("y_columns", "columns"):
            val = params.get(key)
            if isinstance(val, (list, tuple)):
                seen = []
                for c in val:
                    if c and c not in seen:
                        seen.append(c)
                params[key] = seen
        return params

    # 从列表型 Y 轴列中移除与 X 轴重复的列
    for key in ("y_columns", "columns"):
        val = params.get(key)
        if isinstance(val, (list, tuple)):
            deduped = []
            for c in val:
                if c and c != x_col and c not in deduped:
                    deduped.append(c)
            params[key] = deduped

    # 单值型 Y 轴列：若与 X 轴相同则清空
    for key in ("y_column", "y1_column", "y2_column", "size_column", "value_column"):
        if params.get(key) == x_col:
            params[key] = ""

    # 检查是否仍存在有效 Y 轴/数值列
    has_y = False
    for key in ("y_columns", "columns"):
        val = params.get(key)
        if isinstance(val, (list, tuple)) and len(val) > 0:
            has_y = True
    for key in ("y_column", "y1_column", "y2_column", "size_column", "value_column"):
        if params.get(key):
            has_y = True

    if not has_y:
        return None

    return params


def _rec_variant_key(chart_type: str, params: Dict[str, Any]) -> str:
    """基于图表类型和参数生成推荐变体的唯一键，用于区分同一图表类型的不同搭配方案。"""
    parts = []
    for key in sorted(params.keys()):
        val = params[key]
        if isinstance(val, (list, tuple)):
            parts.append(f"{key}={','.join(sorted(map(str, val)))}")
        else:
            parts.append(f"{key}={val}")
    return f"{chart_type}:{','.join(parts)}"


def _get_chart_recommendations(df: pd.DataFrame, columns: Optional[List[str]] = None, chart_type: Optional[str] = None) -> Dict[str, Any]:
    """根据数据特征智能推荐图表类型和参数（pandas 全量计算，CH 加速分支共用 _build_chart_recommendations）。

    参数:
        columns: 可选，指定只考虑哪些列（如用户已选中某些列时）。
        chart_type: 可选，指定只返回某种图表类型的推荐。
    """
    column_tags = _get_column_tags_all(df)
    chart_cat_cols = _get_chart_categorical_columns(df)
    return _build_chart_recommendations(
        column_tags, chart_cat_cols,
        df=df, col_minmax=None, col_is_numeric=None,
        columns=columns, chart_type=chart_type,
    )


def _build_chart_recommendations(column_tags: Dict[str, Dict[str, Any]],
                                 categorical_cols: List[str],
                                 df: Optional[pd.DataFrame] = None,
                                 col_minmax: Optional[Dict[str, Dict[str, Any]]] = None,
                                 col_is_numeric: Optional[Dict[str, bool]] = None,
                                 columns: Optional[List[str]] = None,
                                 chart_type: Optional[str] = None) -> Dict[str, Any]:
    """根据列标签信息智能推荐图表类型和参数。

    供 pandas 全量计算与 CH 加速分支共用，保证两套数据源的推荐逻辑一致。

    参数:
        column_tags: 每列的标签信息（_get_column_tags_all 或 CH 画像构造）。
        categorical_cols: 分类列（非数值列，identifier 在可视化里仍可当分类轴用）。
        df: 可选。pandas 分支传入，用于 _detect_dual_axis_needed/_validate_recommendation_params。
        col_minmax: 可选。CH 分支传入 {列名: {"min":.., "max":..}}。
        col_is_numeric: 可选。CH 分支传入 {列名: 是否数值列}。
        columns: 可选，指定只考虑哪些列。
        chart_type: 可选，指定只返回某种图表类型的推荐。
    """
    # 若指定了列，则只考虑这些列；否则考虑全部列
    if columns:
        column_tags = {col: tags for col, tags in column_tags.items() if col in columns}
        categorical_cols = [c for c in categorical_cols if c in columns]

    numeric_cols = [col for col, tags in column_tags.items() if tags["is_numeric"] and tags["availability"] != "disabled"]
    datetime_cols = [col for col, tags in column_tags.items() if tags["is_datetime"] and tags["availability"] != "disabled"]

    top_numeric_cols = sorted(numeric_cols, key=lambda c: column_tags[c]["quality_score"], reverse=True)[:3]
    top_cat_cols = sorted(categorical_cols, key=lambda c: min(column_tags.get(c, {}).get("unique_count", 9999), 15), reverse=False)[:2]

    # 折线/面积/多折线图的 X 轴只使用分类列，与前端下拉框（categorical）保持一致，
    # 避免把时间戳误判列或数值列当作维度推荐。
    x_axis_col = top_cat_cols[0] if top_cat_cols else ""

    # 趋势类图表（折线/面积/多折线）的 X 轴应只使用分类列
    trend_x_col = x_axis_col if x_axis_col in categorical_cols else ""

    recommendations = []

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "数据分布",
            "chart_type": "histogram",
            "columns": top_numeric_cols[:2],
            "params": {"columns": top_numeric_cols[:2]},
            "reason": f"您的数据有{len(numeric_cols)}个数值列，推荐查看分布情况",
            "score": 0.9
        })
        
        recommendations.append({
            "purpose": "数据分布",
            "chart_type": "boxplot",
            "columns": top_numeric_cols[:3],
            "params": {"columns": top_numeric_cols[:3]},
            "reason": f"箱线图可以展示{', '.join(top_numeric_cols[:3])}的分布和异常值",
            "score": 0.85
        })
    
    if len(categorical_cols) >= 1 and len(numeric_cols) >= 1 and len(top_cat_cols) > 0:
        recommendations.append({
            "purpose": "类别对比",
            "chart_type": "bar",
            "columns": [top_cat_cols[0]] + top_numeric_cols[:2],
            "params": {
                "x_column": top_cat_cols[0],
                "y_columns": top_numeric_cols[:2]
            },
            "reason": f"用{top_cat_cols[0]}分组对比{', '.join(top_numeric_cols[:2])}",
            "score": 0.8
        })
    
    if len(numeric_cols) >= 1:
        line_cols = top_numeric_cols[:2]
        recommendations.append({
            "purpose": "趋势变化",
            "chart_type": "multi_line",
            "columns": ([trend_x_col] if trend_x_col else []) + line_cols,
            "params": {
                "x_column": trend_x_col,
                "columns": line_cols
            },
            "reason": f"查看{', '.join(line_cols)}的变化趋势" if not trend_x_col else f"查看{trend_x_col}维度下{', '.join(line_cols)}的变化趋势",
            "score": 0.75
        })

    if len(numeric_cols) >= 2:
        recommendations.append({
            "purpose": "变量关系",
            "chart_type": "scatter",
            "columns": top_numeric_cols[:2],
            "params": {
                "x_column": top_numeric_cols[0],
                "y_column": top_numeric_cols[1]
            },
            "reason": f"查看{top_numeric_cols[0]}和{top_numeric_cols[1]}的相关性",
            "score": 0.7
        })
        
        recommendations.append({
            "purpose": "变量关系",
            "chart_type": "heatmap",
            "columns": top_numeric_cols[:5],
            "params": {"columns": top_numeric_cols[:5]},
            "reason": f"查看{len(top_numeric_cols[:5])}个数值列之间的相关性矩阵",
            "score": 0.65
        })
    
    if len(categorical_cols) >= 1:
        top_cat_for_pie = [c for c in categorical_cols if column_tags[c]["unique_count"] <= 8]
        if top_cat_for_pie:
            recommendations.append({
                "purpose": "占比构成",
                "chart_type": "pie",
                "columns": [top_cat_for_pie[0]],
                "params": {"column": top_cat_for_pie[0]},
                "reason": f"{top_cat_for_pie[0]}有{column_tags[top_cat_for_pie[0]]['unique_count']}个类别，适合用饼图展示占比",
                "score": 0.6
            })

    # 扩展推荐：面积图、多折线图、双Y轴图、KDE图、QQ图、雷达图、气泡图、堆叠柱状图

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "趋势变化",
            "chart_type": "area",
            "columns": ([trend_x_col] if trend_x_col else []) + top_numeric_cols[:2],
            "params": {
                "x_column": trend_x_col,
                "y_columns": top_numeric_cols[:2]
            },
            "reason": f"面积图可展示{', '.join(top_numeric_cols[:2])}的累积趋势" if not trend_x_col else f"面积图可展示{trend_x_col}维度下{', '.join(top_numeric_cols[:2])}的累积趋势",
            "score": 0.72
        })
        # 若已有维度列，再补充一个以行索引为 X 轴的搭配方案，供用户选择
        if trend_x_col:
            recommendations.append({
                "purpose": "趋势变化",
                "chart_type": "area",
                "columns": top_numeric_cols[:2],
                "params": {
                    "x_column": "",
                    "y_columns": top_numeric_cols[:2]
                },
                "reason": f"面积图可展示{', '.join(top_numeric_cols[:2])}按行索引的累积趋势",
                "score": 0.70
            })

    if len(numeric_cols) >= 2:
        recommendations.append({
            "purpose": "趋势变化",
            "chart_type": "multi_line",
            "columns": top_numeric_cols[:3],
            "params": {
                "x_column": "",
                "columns": top_numeric_cols[:3]
            },
            "reason": f"多折线图可同时对比{len(top_numeric_cols[:3])}个数值列的变化",
            "score": 0.71
        })

    if len(numeric_cols) >= 2:
        dual_cols = top_numeric_cols[:2]
        if _detect_dual_axis_needed(df, dual_cols, col_minmax=col_minmax):
            dual_score = 0.82
            dual_reason = f"{dual_cols[0]}与{dual_cols[1]}量纲差异大，建议使用双Y轴"
        else:
            dual_score = 0.60
            dual_reason = f"双Y轴图可同时展示{dual_cols[0]}与{dual_cols[1]}两个指标"
        recommendations.append({
            "purpose": "趋势变化",
            "chart_type": "dual_axis",
            "columns": dual_cols,
            "params": {
                "x_column": x_axis_col,
                "y1_column": dual_cols[0],
                "y2_column": dual_cols[1]
            },
            "reason": dual_reason,
            "score": dual_score
        })

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "数据分布",
            "chart_type": "kde",
            "columns": top_numeric_cols[:2],
            "params": {"columns": top_numeric_cols[:2]},
            "reason": f"KDE图可平滑展示{', '.join(top_numeric_cols[:2])}的概率密度",
            "score": 0.68
        })

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "数据分布",
            "chart_type": "qq",
            "columns": [top_numeric_cols[0]],
            "params": {"columns": [top_numeric_cols[0]]},
            "reason": f"QQ图可检验{top_numeric_cols[0]}是否符合正态分布",
            "score": 0.55
        })

    if len(numeric_cols) >= 3:
        radar_cols = top_numeric_cols[:5]
        recommendations.append({
            "purpose": "类别对比",
            "chart_type": "radar",
            "columns": radar_cols,
            "params": {"columns": radar_cols},
            "reason": f"雷达图可多维对比{len(radar_cols)}个数值指标",
            "score": 0.62
        })

    if len(numeric_cols) >= 3:
        bubble_cols = top_numeric_cols[:3]
        recommendations.append({
            "purpose": "变量关系",
            "chart_type": "bubble",
            "columns": bubble_cols,
            "params": {
                "x_column": bubble_cols[0],
                "y_column": bubble_cols[1],
                "size_column": bubble_cols[2]
            },
            "reason": f"气泡图可展示{bubble_cols[0]}、{bubble_cols[1]}与大小{bubble_cols[2]}的关系",
            "score": 0.58
        })

    if len(categorical_cols) >= 1 and len(numeric_cols) >= 2 and len(top_cat_cols) > 0:
        recommendations.append({
            "purpose": "类别对比",
            "chart_type": "stacked_bar",
            "columns": [top_cat_cols[0]] + top_numeric_cols[:3],
            "params": {
                "x_column": top_cat_cols[0],
                "y_columns": top_numeric_cols[:3]
            },
            "reason": f"堆叠柱状图可展示{top_cat_cols[0]}分组下多个指标的累积对比",
            "score": 0.65
        })

    # 清洗推荐参数：移除 X/Y 轴重叠、去重列名；清洗后无效的推荐直接丢弃
    sanitized_recommendations = []
    for r in recommendations:
        ctype = r.get("chart_type", "")
        params = _sanitize_recommendation_params(r.get("params", {}))
        if params is None:
            continue
        # 根据清洗后的参数重新整理 columns 字段，避免前端展示重复列
        involved_cols = []
        x_col = params.get("x_column") or ""
        if x_col:
            involved_cols.append(x_col)
        for key in ("y_columns", "columns"):
            val = params.get(key)
            if isinstance(val, (list, tuple)):
                for c in val:
                    if c and c not in involved_cols:
                        involved_cols.append(c)
        for key in ("y_column", "y1_column", "y2_column", "size_column", "value_column", "column"):
            c = params.get(key)
            if c and c not in involved_cols:
                involved_cols.append(c)
        r["params"] = params
        r["columns"] = involved_cols
        if _validate_recommendation_params(df, ctype, params, col_is_numeric=col_is_numeric):
            sanitized_recommendations.append(r)
    recommendations = sanitized_recommendations

    # 同一种图表类型保留评分最高的 2 个不同参数搭配方案
    MAX_VARIANTS_PER_TYPE = 2
    type_variants: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in sorted(recommendations, key=lambda x: x["score"], reverse=True):
        ctype = r.get("chart_type", "")
        vkey = _rec_variant_key(ctype, r.get("params", {}))
        if ctype not in type_variants:
            type_variants[ctype] = {}
        if vkey not in type_variants[ctype] and len(type_variants[ctype]) < MAX_VARIANTS_PER_TYPE:
            type_variants[ctype][vkey] = r
    recommendations = [r for variants in type_variants.values() for r in variants.values()]

    # 若指定了图表类型，仅保留该类型的推荐
    if chart_type:
        recommendations = [r for r in recommendations if r.get("chart_type") == chart_type]

    # 计算各图表类型的支持状态，供前端分类展示与智能禁用
    supported_chart_types = {}
    chart_type_configs = [
        ("histogram", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("boxplot", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("kde", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("qq", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("scatter", "变量关系", "至少2个数值列", len(numeric_cols) >= 2),
        ("bubble", "变量关系", "至少3个数值列", len(numeric_cols) >= 3),
        ("area", "趋势变化", "至少1个数值列", len(numeric_cols) >= 1),
        ("multi_line", "趋势变化", "至少1个数值列", len(numeric_cols) >= 1),
        ("bar", "类别对比", "至少1个分类列和1个数值列", len(categorical_cols) >= 1 and len(numeric_cols) >= 1),
        ("stacked_bar", "类别对比", "至少1个分类列和2个数值列", len(categorical_cols) >= 1 and len(numeric_cols) >= 2),
        ("dual_axis", "趋势变化", "至少2个数值列", len(numeric_cols) >= 2),
        ("pie", "占比构成", "至少1个分类列", len(categorical_cols) >= 1),
        ("heatmap", "变量关系", "至少2个数值列", len(numeric_cols) >= 2),
        ("radar", "类别对比", "至少3个数值列", len(numeric_cols) >= 3),
        ("table_heatmap", "变量关系", "至少2个分类列和1个数值列", len(categorical_cols) >= 2 and len(numeric_cols) >= 1),
    ]
    for ctype, category, requirement, supported in chart_type_configs:
        if supported:
            reason = f"满足{requirement}"
        else:
            reason = f"当前数据不满足：{requirement}"
        supported_chart_types[ctype] = {
            "supported": supported,
            "category": category,
            "requirement": requirement,
            "reason": reason
        }

    return {
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "datetime_columns": datetime_cols,
        "recommendations": recommendations[:10],
        "column_tags": column_tags,
        "supported_chart_types": supported_chart_types
    }


def _ch_synced_registry(dataset_id: int) -> Optional[dict]:
    """判断本地数据集能否走 CH 加速，返回已同步注册记录（不可用/未同步/小表返回 None）

    判定条件：同步开关开启 + CH 可用 + registry synced + 行数 ≥ CLICKHOUSE_MIN_ROWS。
    任何异常都返回 None，由调用方回退 pandas，保证功能完整无报错。
    """
    if not (settings.CLICKHOUSE_SYNC_ENABLED and clickhouse_service.is_enabled()):
        return None
    try:
        if not clickhouse_service.is_available():
            return None
        reg = clickhouse_service.registry_get(dataset_id)
    except Exception as e:
        print(f"⚠️ ClickHouse 加速判定失败（回退 pandas）: {e}")
        return None
    if not reg or str(reg.get("status")) != "synced":
        return None
    try:
        if int(reg.get("row_count") or 0) < int(settings.CLICKHOUSE_MIN_ROWS):
            return None
    except (TypeError, ValueError):
        return None
    return reg


def _parse_ch_schema(reg: dict) -> Dict[str, str]:
    """解析注册记录中的 columns_json 为 {列名: dtype}；非法时返回空 dict（走 pandas）"""
    try:
        schema = json.loads(reg.get("columns_json") or "{}")
        return schema if isinstance(schema, dict) else {}
    except (ValueError, TypeError):
        return {}


def _get_column_tags_from_profiles(p: Dict[str, Any], outlier_rate: Optional[float] = None) -> Dict[str, Any]:
    """用 CH 列画像构造列标签（复刻 _get_column_tags，供 CH 加速分支复用）

    p: compute_column_profiles 返回的单列画像。
    outlier_rate: 数值列离群值比例（IQR 法，由 count_outliers 补充计算），None 表示不评估。
    """
    column = p["name"]
    is_numeric = p["is_numeric"]
    is_datetime = p["is_datetime"]
    total = p["total"]
    non_null_count = total - p["missing_count"]
    missing_rate = p["missing_count"] / total if total > 0 else 0
    unique_count = p["unique_count"]
    uniqueness = unique_count / non_null_count if non_null_count > 0 else 0

    tags = {
        "name": column,
        "is_numeric": is_numeric,
        "is_categorical": not is_numeric and not is_datetime,
        "is_datetime": is_datetime,
        "is_constant": unique_count == 1,
        "is_identifier": uniqueness > 0.9 and is_numeric is False,
        "high_cardinality": unique_count > 20 and not is_numeric,
        "missing_rate": round(missing_rate, 4),
        "unique_count": unique_count,
        "uniqueness": round(uniqueness, 4),
        "quality_score": 0,
        "availability": "available",
        "availability_reason": ""
    }

    quality_score = 100
    issues = []

    if tags["is_constant"]:
        quality_score -= 50
        tags["availability"] = "disabled"
        tags["availability_reason"] = "该列所有值相同，无法生成有意义的图表"
        issues.append("常量列")

    if tags["is_identifier"]:
        quality_score -= 80
        tags["availability"] = "disabled"
        tags["availability_reason"] = "该列是唯一标识符，不适合作为分类轴"
        issues.append("标识符列")

    if tags["missing_rate"] > 0.5:
        quality_score -= 50
        tags["availability"] = "disabled"
        tags["availability_reason"] = f"缺失值超过50%({round(missing_rate*100,1)}%)，无法生成有意义的图表"
        issues.append("缺失值过多")
    elif tags["missing_rate"] > 0.3:
        quality_score -= 20
        tags["availability"] = "warning"
        tags["availability_reason"] = f"缺失值较多({round(missing_rate*100,1)}%)，结果可能有偏差"
        issues.append("缺失值较多")
    elif tags["missing_rate"] > 0.1:
        quality_score -= 10
        tags["availability"] = "warning"
        tags["availability_reason"] = f"存在缺失值({round(missing_rate*100,1)}%)"

    if tags["high_cardinality"]:
        quality_score -= 20
        tags["availability_reason"] = f"类别过多({unique_count}个)，图表可能拥挤"

    if is_numeric and outlier_rate is not None:
        tags["outlier_rate"] = round(outlier_rate, 4)
        if outlier_rate > 0.2:
            quality_score -= 15
            tags["availability_reason"] = f"存在较多极端值({round(outlier_rate*100,1)}%)"

    tags["quality_score"] = max(0, min(100, int(quality_score)))

    return tags


def _compute_ch_recommendations(ch_svc, dataset_id: int, schema: Dict[str, str],
                                columns: Optional[List[str]] = None,
                                chart_type: Optional[str] = None) -> Dict[str, Any]:
    """CH 加速的图表智能推荐：列画像走 SQL 全量聚合，推荐组装复用 _build_chart_recommendations

    object 列（同步后为 String）通过抽样判定数值/日期语义，与 pandas 的
    _is_numeric_column/_is_datetime_column 判定对齐，保证数值列/分类列划分一致。
    """
    profiles = ch_svc.compute_column_profiles(dataset_id, schema, columns=columns)
    # object 列抽样判定 + 数值类 object 列补充分位数（与 pandas 判定对齐）
    numeric_object_cols = []
    for col, p in profiles.items():
        if p["dtype"] in ("object", "str"):
            t = ch_svc.object_column_type(dataset_id, col)
            p["is_numeric"] = (t == "numeric")
            p["is_datetime"] = (t == "datetime")
            if t == "numeric":
                numeric_object_cols.append(col)
    if numeric_object_cols:
        extras = ch_svc.numeric_extras(dataset_id, numeric_object_cols)
        for col, vals in extras.items():
            if col in profiles:
                profiles[col].update(vals)
    # IQR 离群阈值（q1/q3 来自 CH 分位数，与 pandas quantile 线性插值存在微小差异）
    thresholds = {}
    for col, p in profiles.items():
        if p["is_numeric"] and p.get("q1") is not None and p.get("q3") is not None:
            iqr = float(p["q3"]) - float(p["q1"])
            thresholds[col] = (float(p["q1"]) - 1.5 * iqr, float(p["q3"]) + 1.5 * iqr)
    out_counts = ch_svc.count_outliers(dataset_id, thresholds) if thresholds else {}
    column_tags = {}
    for col, p in profiles.items():
        nn = p["total"] - p["missing_count"]
        outlier_rate = None
        if col in out_counts and nn > 0:
            outlier_rate = out_counts[col] / nn
        column_tags[col] = _get_column_tags_from_profiles(p, outlier_rate=outlier_rate)
    chart_cat_cols = [c for c, p in profiles.items() if not p["is_numeric"]]
    col_minmax = {
        c: {"min": p.get("min"), "max": p.get("max")}
        for c, p in profiles.items() if p.get("min") is not None or p.get("max") is not None
    }
    col_is_numeric = {c: p["is_numeric"] for c, p in profiles.items()}
    return _build_chart_recommendations(
        column_tags, chart_cat_cols,
        df=None, col_minmax=col_minmax, col_is_numeric=col_is_numeric,
        columns=columns, chart_type=chart_type,
    )


def _ch_can_chart(chart_type: str, params: Dict[str, Any], schema: Dict[str, str]) -> bool:
    """图表请求能否走 CH 加速

    规则：仅聚合型图表（histogram/bar/stacked_bar/pie）；涉及列必须存在且无判定分歧
    （object 列在 pandas 视角可能是数字字符串，走 pandas 保底以保持行为一致）；
    X 轴与 Y 轴不重叠；Y 轴必须为数值列。
    """
    if chart_type not in {"histogram", "bar", "stacked_bar", "pie"}:
        return False

    def _is_num(c):
        return str(schema.get(c, "")).startswith(("int", "float", "bool"))

    cols = set()
    for key in ("x_column", "y_column", "y1_column", "y2_column", "size_column", "value_column", "column"):
        v = params.get(key)
        if isinstance(v, str) and v:
            cols.add(v)
    for key in ("y_columns", "columns"):
        v = params.get(key)
        if isinstance(v, list):
            cols.update(x for x in v if isinstance(x, str))

    for c in cols:
        if c not in schema:
            return False
        dtype = str(schema[c])
        if dtype.startswith("datetime"):
            # 时间列 toString 格式与 pandas str() 不同（如毫秒后缀），走 pandas 保底
            return False
        if dtype in ("object", "str"):
            # 字符串列可作为分类轴（compute_chart_agg 内部抽样区分数字字符串并回退）；
            # 若被当数值列使用，由下方类型规则拒绝
            continue

    if chart_type == "histogram":
        target = params.get("columns") or ([params.get("column")] if params.get("column") else [])
        if not target:
            # 空目标 → 取第一个数值列，可 CH 化
            return True
        return all(_is_num(c) for c in target if c)

    if chart_type == "pie":
        c = params.get("column") or (params.get("columns") or [None])[0]
        return bool(c) and c in schema and not _is_num(c)

    # bar / stacked_bar
    x_col = params.get("x_column")
    if not x_col or x_col not in schema:
        return False
    y_cols = params.get("y_columns") or []
    if not y_cols and params.get("y_column"):
        y_cols = [params.get("y_column")]
    if not y_cols:
        return False
    if x_col in y_cols:
        return False
    return all(c in schema and _is_num(c) for c in y_cols)


def _get_categorical_columns(df: pd.DataFrame) -> list:
    """获取所有分类列（非数值列）"""
    numeric_cols = set(get_numeric_columns(df))
    return [col for col in df.columns if col not in numeric_cols]


def _compute_categorical_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """计算分类列的统计信息"""
    categorical_cols = _get_categorical_columns(df)
    stats = {}
    for col in categorical_cols:
        missing_count = int(df[col].isna().sum())
        total = len(df)
        non_null = df[col].dropna()
        value_counts = non_null.value_counts().head(10)
        top_values = []
        for val, cnt in value_counts.items():
            top_values.append({
                "value": str(val),
                "count": int(cnt),
                "rate": round(int(cnt) / len(non_null) * 100, 2) if len(non_null) > 0 else 0
            })
        stats[col] = {
            "unique_count": int(non_null.nunique()),
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total * 100, 2) if total > 0 else 0,
            "top_values": top_values
        }
    return stats


def _compute_basic_info(df: pd.DataFrame) -> Dict[str, Any]:
    """计算基本信息"""
    numeric_cols = set(get_numeric_columns(df))
    columns_info = []
    total = len(df)
    for col in df.columns:
        missing_count = int(df[col].isna().sum())
        non_null = df[col].dropna()
        unique_count = int(non_null.nunique(dropna=True))
        is_numeric = col in numeric_cols
        columns_info.append({
            "name": col,
            "type": str(df[col].dtype),
            "is_numeric": is_numeric,
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total * 100, 2) if total > 0 else 0,
            "unique_count": unique_count,
            "is_constant": unique_count == 1,
            "missing_too_many": (missing_count / total) > 0.5 if total > 0 else False
        })
    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "numeric_count": len(numeric_cols),
        "categorical_count": len(df.columns) - len(numeric_cols),
        "columns": columns_info
    }


def _get_chart_data(df: pd.DataFrame, chart_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """根据图表类型计算图表数据。
    兼容新旧前端参数格式：
    - 单列类：column（字符串）或 columns（数组，取第一个，空数组=所有数值列）
    - 双列类：x_column + y_column，或 x_column + y_columns（数组，取第一个）
    - 多列类：columns 数组 + 可选 x_column
    通用扩展参数：topN、show_data_labels、show_legend（透传给前端用于绘图控制）"""
    # 对需要 X 轴的图表类型，若用户未指定 X 轴列，自动使用行索引
    if chart_type in {"line", "area", "multi_line", "bar", "stacked_bar", "dual_axis"}:
        if not params.get("x_column"):
            df = df.copy()
            # 行索引补零对齐：保证字符串字典序与数值序一致，避免 sort 后 1,10,11,2,3… 乱序（修复）
            idx_width = len(str(len(df)))
            df["__index__"] = [str(i + 1).zfill(idx_width) for i in range(len(df))]
            params = dict(params)
            params["x_column"] = "__index__"

    column_tags = _validate_chart_params(df, chart_type, params)

    show_data_labels = bool(params.get("show_data_labels", False))
    show_legend = bool(params.get("show_legend", True))

    def _return_chart_data(data):
        """返回图表数据前进行 JSON 序列化清洗"""
        return _clean_json_data(data)

    if chart_type == "histogram":
        # 支持多列直方图：columns 是数组（多选），空数组=第一个数值列
        columns_param = params.get("columns") or []
        column = params.get("column")
        if column:
            columns_param = [column]
        elif not columns_param:
            numeric_cols = get_numeric_columns(df)
            if not numeric_cols:
                raise HTTPException(status_code=400, detail="没有可用的数值列")
            columns_param = [numeric_cols[0]]
        # 过滤有效数值列
        valid_cols = [c for c in columns_param if c in df.columns and _is_numeric_column(df[c])]
        if not valid_cols:
            raise HTTPException(status_code=400, detail="没有有效的数值列")
        # 自动计算 bins 数量（基于第一列）
        bins = int(params.get("bins", 0))
        if bins <= 0:
            first_col_data = to_numeric_if_possible(df[valid_cols[0]]).dropna()
            bins = max(5, min(50, int(np.sqrt(len(first_col_data)))))
        # 获取所有列的公共 bin 边界（基于所有数据的范围）
        all_data = []
        for col in valid_cols:
            col_data = to_numeric_if_possible(df[col]).dropna().values
            if len(col_data) > 0:
                all_data.extend(col_data)
        if not all_data:
            return _return_chart_data({"labels": [], "series": [], "show_data_labels": True, "show_legend": show_legend})
        min_val = np.min(all_data)
        max_val = np.max(all_data)
        bin_edges = np.linspace(min_val, max_val, bins + 1)
        labels = [f"{round(bin_edges[i], 2)}-{round(bin_edges[i+1], 2)}" for i in range(len(bin_edges)-1)]
        # 为每列计算直方图
        series = []
        for col in valid_cols:
            col_data = to_numeric_if_possible(df[col]).dropna().values
            if len(col_data) == 0:
                series.append({"name": col, "values": [0] * len(labels)})
                continue
            hist, _ = np.histogram(col_data, bins=bin_edges)
            series.append({"name": col, "values": hist.tolist()})
        return _return_chart_data({
            "labels": labels,
            "series": series,
            "show_data_labels": True,
            "show_legend": show_legend
        })

    elif chart_type == "scatter":
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        # 兼容新格式：y_columns 是数组（多选），取第一个作为 y_column
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"x 列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"y 列 '{y_col}' 不存在")
        if not _is_numeric_column(df[x_col]):
            raise HTTPException(status_code=400, detail=f"散点图X轴需要数值列，'{x_col}' 不是数值列")
        if not _is_numeric_column(df[y_col]):
            raise HTTPException(status_code=400, detail=f"散点图Y轴需要数值列，'{y_col}' 不是数值列")
        x_data = to_numeric_if_possible(df[x_col])
        y_data = to_numeric_if_possible(df[y_col])
        temp_df = pd.DataFrame({"x": x_data, "y": y_data}).dropna()
        return _return_chart_data({
            "x": temp_df["x"].tolist(),
            "y": temp_df["y"].tolist(),
            "show_data_labels": False,
            "show_legend": show_legend
        })

    elif chart_type == "boxplot":
        # 兼容新格式：columns 是数组，空数组=所有数值列；同时支持 column 单列参数
        columns = params.get("columns", [])
        column = params.get("column")
        # 优先使用单列参数，否则使用多列参数，最后用默认所有数值列
        if column:
            columns = [column]
        if not columns:
            columns = get_numeric_columns(df)[:10]
        # 过滤不存在且非数值的列
        valid_cols = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if not valid_cols:
            raise HTTPException(status_code=400, detail="没有有效的数值列")
        series = []
        for col in valid_cols:
            col_data = to_numeric_if_possible(df[col]).dropna()
            if len(col_data) < 4:
                series.append({"name": col, "data": [None, None, None, None, None, []]})
                continue
            q1 = float(col_data.quantile(0.25))
            q3 = float(col_data.quantile(0.75))
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outliers = col_data[(col_data < lower) | (col_data > upper)].tolist()
            series.append({
                "name": col,
                "data": [
                    float(col_data.min()),
                    q1,
                    float(col_data.median()),
                    q3,
                    float(col_data.max()),
                    outliers
                ]
            })
        return _return_chart_data({
            "series": series,
            "show_data_labels": True,
            "show_legend": show_legend
        })

    elif chart_type == "line":
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"Y 轴列 '{y_col}' 不存在")
        if not _is_numeric_column(df[y_col]):
            raise HTTPException(status_code=400, detail=f"折线图 Y 轴需要数值列，'{y_col}' 不是数值列")
        
        # 支持多列 Y 轴
        y_cols_to_use = y_columns if y_columns else [y_col]
        for col in y_cols_to_use:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Y 轴列 '{col}' 不存在")
            if not _is_numeric_column(df[col]):
                raise HTTPException(status_code=400, detail=f"折线图 Y 轴需要数值列，'{col}' 不是数值列")

        labels = df[x_col].astype(str).tolist()
        
        if len(y_cols_to_use) > 1:
            series = []
            for yc in y_cols_to_use:
                y_data = to_numeric_if_possible(df[yc]).tolist()
                series.append({
                    "name": yc,
                    "values": y_data
                })
            return _return_chart_data({
                "labels": labels,
                "series": series,
                "show_data_labels": show_data_labels,
                "show_legend": show_legend,
                "dual_axis_needed": _detect_dual_axis_needed(df, y_cols_to_use)
            })
        else:
            temp_df = pd.DataFrame({
                "x": df[x_col],
                "y": to_numeric_if_possible(df[y_col])
            }).dropna()

            if _is_numeric_column(df[x_col]):
                temp_df = temp_df.sort_values(by="x")
                x_values = temp_df["x"].astype(str).tolist()
                y_values = temp_df["y"].tolist()
            else:
                grouped = temp_df.groupby("x")["y"].mean().reset_index()
                grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
                x_values = grouped["x"].astype(str).tolist()
                y_values = grouped["y"].round(2).tolist()

            return _return_chart_data({
                "labels": x_values,
                "values": y_values,
                "show_data_labels": show_data_labels,
                "show_legend": show_legend
            })

    elif chart_type == "pie":
        column = params.get("column")
        if not column or column not in df.columns:
            raise HTTPException(status_code=400, detail=f"列 '{column}' 不存在")
        if _is_numeric_column(df[column]):
            raise HTTPException(status_code=400, detail=f"饼图需要分类列，'{column}' 是数值列")
        # topN 限制返回前 N 项分类，默认 10
        top_n = int(params.get("topN", 10) or 10)
        if top_n <= 0:
            top_n = 10
        value_counts = df[column].dropna().value_counts().head(top_n)
        return _return_chart_data({
            "labels": [str(k) for k in value_counts.index.tolist()],
            "values": value_counts.tolist(),
            "show_data_labels": True,
            "show_legend": show_legend
        })

    elif chart_type == "heatmap":
        columns = params.get("columns", [])
        if not columns:
            columns = get_numeric_columns(df)
        # 过滤掉不存在和非数值的列
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if len(columns) < 2:
            raise HTTPException(status_code=400, detail="需要至少 2 个数值列")
        numeric_df = df[columns].apply(to_numeric_if_possible)
        corr = numeric_df.corr().round(4)
        return _return_chart_data({
            "labels": columns,
            "data": corr.values.tolist(),
            "show_data_labels": True,
            "show_legend": show_legend
        })

    elif chart_type == "bar":
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"Y 轴列 '{y_col}' 不存在")
        if not _is_numeric_column(df[y_col]):
            raise HTTPException(status_code=400, detail=f"柱状图 Y 轴需要数值列，'{y_col}' 不是数值列")
        
        y_cols_to_use = y_columns if y_columns else [y_col]
        for col in y_cols_to_use:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Y 轴列 '{col}' 不存在")
            if not _is_numeric_column(df[col]):
                raise HTTPException(status_code=400, detail=f"柱状图 Y 轴需要数值列，'{col}' 不是数值列")

        if len(y_cols_to_use) > 1:
            temp_df = df[[x_col] + y_cols_to_use].copy()
            for col in y_cols_to_use:
                temp_df[col] = to_numeric_if_possible(temp_df[col])
            grouped = temp_df.groupby(x_col)[y_cols_to_use].sum()
            grouped = grouped.sort_index(key=lambda col: col.astype(str))
            categories = [str(idx) for idx in grouped.index]
            series = []
            for col in y_cols_to_use:
                series.append({
                    "name": col,
                    "values": grouped[col].round(2).tolist()
                })
            return _return_chart_data({
                "labels": categories,
                "series": series,
                "show_data_labels": show_data_labels,
                "show_legend": show_legend,
                "dual_axis_needed": _detect_dual_axis_needed(df, y_cols_to_use)
            })
        else:
            temp_df = pd.DataFrame({
                "x": df[x_col],
                "y": to_numeric_if_possible(df[y_col])
            }).dropna()
            if len(temp_df) == 0:
                return _return_chart_data({"labels": [], "values": [], "show_data_labels": show_data_labels, "show_legend": show_legend})
            grouped = temp_df.groupby("x")["y"].sum().reset_index()
            grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
            top_n = int(params.get("topN", 0) or 0)
            if top_n > 0 and len(grouped) > top_n:
                grouped = grouped.nlargest(top_n, "y")
            return _return_chart_data({
                "labels": grouped["x"].astype(str).tolist(),
                "values": grouped["y"].round(2).tolist(),
                "show_data_labels": show_data_labels,
                "show_legend": show_legend
            })

    elif chart_type == "stacked_bar":
        # 堆叠柱状图：分类列 X 轴 + 多个数值列 Y 轴，堆叠展示
        x_col = params.get("x_column")
        columns = params.get("columns", [])
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not columns:
            columns = get_numeric_columns(df)
        # 过滤出有效的数值列
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if not columns:
            raise HTTPException(status_code=400, detail="堆叠柱状图需要至少 1 个数值列")
        # 按 X 分组，对每个数值列求和
        temp_df = df[[x_col] + columns].copy()
        for col in columns:
            temp_df[col] = to_numeric_if_possible(temp_df[col])
        grouped = temp_df.groupby(x_col)[columns].sum()
        grouped = grouped.sort_index(key=lambda col: col.astype(str))
        categories = [str(idx) for idx in grouped.index]
        series = []
        for col in columns:
            series.append({
                "name": col,
                "data": grouped[col].round(2).tolist()
            })
        return _return_chart_data({
            "categories": categories,
            "series": series,
            "show_data_labels": True,
            "show_legend": show_legend
        })

    elif chart_type == "area":
        # 面积图：支持多列 Y 轴，数值列 X 轴 + 数值列 Y 轴，类似折线图但填充面积
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"Y 轴列 '{y_col}' 不存在")
        if not _is_numeric_column(df[y_col]):
            raise HTTPException(status_code=400, detail=f"面积图 Y 轴需要数值列，'{y_col}' 不是数值列")
        
        y_cols_to_use = y_columns if y_columns else [y_col]
        for col in y_cols_to_use:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Y 轴列 '{col}' 不存在")
            if not _is_numeric_column(df[col]):
                raise HTTPException(status_code=400, detail=f"面积图 Y 轴需要数值列，'{col}' 不是数值列")

        if len(y_cols_to_use) > 1:
            temp_df = df[[x_col] + y_cols_to_use].copy()
            for col in y_cols_to_use:
                temp_df[col] = to_numeric_if_possible(temp_df[col])
            temp_df = temp_df.dropna()
            if len(temp_df) == 0:
                return _return_chart_data({"x": [], "series": [], "show_data_labels": False, "show_legend": show_legend, "message": "所选数据为空或全部缺失，无法生成面积图"})
            if _is_numeric_column(df[x_col]):
                temp_df = temp_df.sort_values(by=x_col)
                x_values = temp_df[x_col].astype(str).tolist()
                series = []
                for yc in y_cols_to_use:
                    series.append({"name": yc, "values": temp_df[yc].tolist()})
            else:
                grouped = temp_df.groupby(x_col)[y_cols_to_use].mean()
                grouped = grouped.sort_index(key=lambda col: col.astype(str))
                x_values = [str(idx) for idx in grouped.index]
                series = []
                for yc in y_cols_to_use:
                    series.append({"name": yc, "values": grouped[yc].round(2).tolist()})
            return _return_chart_data({
                "x": x_values,
                "series": series,
                "show_data_labels": False,
                "show_legend": show_legend,
                "dual_axis_needed": _detect_dual_axis_needed(df, y_cols_to_use)
            })
        else:
            temp_df = pd.DataFrame({
                "x": df[x_col],
                "y": to_numeric_if_possible(df[y_col])
            }).dropna()
            if len(temp_df) == 0:
                return _return_chart_data({"x": [], "y": [], "show_data_labels": False, "show_legend": show_legend, "message": "所选数据为空或全部缺失，无法生成面积图"})
            if _is_numeric_column(df[x_col]):
                temp_df = temp_df.sort_values(by="x")
                x_values = temp_df["x"].astype(str).tolist()
                y_values = temp_df["y"].tolist()
            else:
                grouped = temp_df.groupby("x")["y"].mean().reset_index()
                grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
                x_values = grouped["x"].astype(str).tolist()
                y_values = grouped["y"].round(2).tolist()
            return _return_chart_data({
                "x": x_values,
                "y": y_values,
                "show_data_labels": False,
                "show_legend": show_legend
            })

    elif chart_type == "kde":
        # KDE 密度图：支持多列数值列的核密度估计曲线
        columns_param = params.get("columns") or []
        column = params.get("column")
        if column:
            columns_param = [column]
        elif not columns_param:
            numeric_cols = get_numeric_columns(df)
            if not numeric_cols:
                raise HTTPException(status_code=400, detail="没有可用的数值列")
            columns_param = [numeric_cols[0]]
        # 过滤有效数值列
        valid_cols = [c for c in columns_param if c in df.columns and _is_numeric_column(df[c])]
        if not valid_cols:
            raise HTTPException(status_code=400, detail="没有有效的数值列")
        from scipy.stats import gaussian_kde
        # 获取所有列的公共 x 范围
        all_data = []
        for col in valid_cols:
            col_data = to_numeric_if_possible(df[col]).dropna().values
            if len(col_data) >= 2:
                all_data.extend(col_data)
        if not all_data:
            return _return_chart_data({"x": [], "series": [], "show_data_labels": False, "show_legend": show_legend})
        x_min, x_max = np.min(all_data), np.max(all_data)
        x = np.linspace(x_min, x_max, 200)
        # 为每列计算 KDE
        series = []
        for col in valid_cols:
            col_data = to_numeric_if_possible(df[col]).dropna().values
            if len(col_data) < 2:
                series.append({"name": col, "values": [0.0] * len(x)})
                continue
            kde = gaussian_kde(col_data)
            y = kde(x)
            series.append({"name": col, "values": y.tolist()})
        return _return_chart_data({
            "x": x.tolist(),
            "series": series,
            "show_data_labels": False,
            "show_legend": show_legend
        })

    elif chart_type == "qq":
        # QQ 图：支持多列数值列与正态分布的分位数对比
        columns_param = params.get("columns") or []
        column = params.get("column")
        if column:
            columns_param = [column]
        elif not columns_param:
            numeric_cols = get_numeric_columns(df)
            if not numeric_cols:
                raise HTTPException(status_code=400, detail="没有可用的数值列")
            columns_param = [numeric_cols[0]]
        # 过滤有效数值列
        valid_cols = [c for c in columns_param if c in df.columns and _is_numeric_column(df[c])]
        if not valid_cols:
            raise HTTPException(status_code=400, detail="没有有效的数值列")
        from scipy.stats import probplot
        series = []
        for col in valid_cols:
            col_data = to_numeric_if_possible(df[col]).dropna()
            if len(col_data) < 4:
                series.append({"name": col, "theoretical": [], "sample": []})
                continue
            # 对样本进行标准化，使理论分位数（标准正态 z 分数）与样本分位数同尺度，
            # 避免理论分位数范围过小导致点全部挤在 y 轴附近
            mean = float(col_data.mean())
            std = float(col_data.std())
            if std == 0:
                series.append({"name": col, "theoretical": [], "sample": []})
                continue
            standardized = (col_data - mean) / std
            (theoretical, sample), _ = probplot(standardized, dist="norm")
            series.append({"name": col, "theoretical": theoretical.tolist(), "sample": sample.tolist()})
        return _return_chart_data({
            "series": series,
            "show_data_labels": False,
            "show_legend": show_legend
        })

    elif chart_type == "bubble":
        # 气泡图：三个数值列(X/Y/大小)
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        size_col = params.get("size_column")
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"Y 轴列 '{y_col}' 不存在")
        if not size_col or size_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"大小列 '{size_col}' 不存在")
        # 校验三列均为数值列
        for label, col in [("X 轴", x_col), ("Y 轴", y_col), ("大小", size_col)]:
            if not _is_numeric_column(df[col]):
                raise HTTPException(status_code=400, detail=f"气泡图{label}需要数值列，'{col}' 不是数值列")
        temp_df = pd.DataFrame({
            "x": to_numeric_if_possible(df[x_col]),
            "y": to_numeric_if_possible(df[y_col]),
            "size": to_numeric_if_possible(df[size_col])
        }).dropna()
        if len(temp_df) == 0:
            return _return_chart_data({"x": [], "y": [], "size": [], "show_data_labels": False, "show_legend": show_legend})
        # size 归一化到合理范围 [10, 110]，便于前端展示
        size_data = temp_df["size"]
        size_min = size_data.min()
        size_max = size_data.max()
        if size_max > size_min:
            normalized_size = ((size_data - size_min) / (size_max - size_min) * 100 + 10).round(2)
        else:
            normalized_size = pd.Series([50] * len(size_data))
        return _return_chart_data({
            "x": temp_df["x"].tolist(),
            "y": temp_df["y"].tolist(),
            "size": normalized_size.tolist(),
            "show_data_labels": False,
            "show_legend": show_legend
        })

    elif chart_type == "multi_line":
        # 多折线图：X 轴列 + 多个数值列 Y 轴
        x_col = params.get("x_column")
        columns = params.get("columns", [])
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not columns:
            columns = get_numeric_columns(df)
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if not columns:
            raise HTTPException(status_code=400, detail="多折线图需要至少 1 个数值列")
        # 构造临时 DataFrame 并转换为数值
        temp_df = df[[x_col] + columns].copy()
        for col in columns:
            temp_df[col] = to_numeric_if_possible(temp_df[col])
        temp_df = temp_df.dropna(subset=[x_col])
        # X 是数值列则按 X 排序，否则按 X 分组取均值
        if _is_numeric_column(df[x_col]):
            temp_df = temp_df.sort_values(by=x_col)
            x_values = temp_df[x_col].astype(str).tolist()
            series = [{"name": col, "data": temp_df[col].tolist()} for col in columns]
        else:
            grouped = temp_df.groupby(x_col)[columns].mean()
            grouped = grouped.sort_index(key=lambda col: col.astype(str))
            x_values = [str(idx) for idx in grouped.index]
            series = [{"name": col, "data": grouped[col].round(2).tolist()} for col in columns]
        return _return_chart_data({
            "x": x_values,
            "series": series,
            "show_data_labels": show_data_labels,
            "show_legend": show_legend,
            "dual_axis_needed": _detect_dual_axis_needed(df, columns)
        })

    elif chart_type == "dual_axis":
        # 双 Y 轴图：X 轴列 + 两个数值列分别在不同 Y 轴
        # 兼容新格式：y1_column/y2_column 优先于 y_column/y2_column
        x_col = params.get("x_column")
        y1_col = params.get("y1_column") or params.get("y_column")
        y2_col = params.get("y2_column")
        if not x_col or x_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"X 轴列 '{x_col}' 不存在")
        if not y1_col or y1_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"Y1 轴列 '{y1_col}' 不存在")
        if not y2_col or y2_col not in df.columns:
            raise HTTPException(status_code=400, detail=f"Y2 轴列 '{y2_col}' 不存在")
        if not _is_numeric_column(df[y1_col]):
            raise HTTPException(status_code=400, detail=f"双 Y 轴 Y1 需要数值列，'{y1_col}' 不是数值列")
        if not _is_numeric_column(df[y2_col]):
            raise HTTPException(status_code=400, detail=f"双 Y 轴 Y2 需要数值列，'{y2_col}' 不是数值列")
        temp_df = pd.DataFrame({
            "x": df[x_col],
            "y1": to_numeric_if_possible(df[y1_col]),
            "y2": to_numeric_if_possible(df[y2_col])
        }).dropna()
        if len(temp_df) == 0:
            return _return_chart_data({"x": [], "y1": [], "y2": [], "y1_name": y1_col, "y2_name": y2_col,
                    "show_data_labels": show_data_labels, "show_legend": show_legend})
        # X 是数值列则直接排序，否则分组取均值
        if _is_numeric_column(df[x_col]):
            temp_df = temp_df.sort_values(by="x")
            x_values = temp_df["x"].astype(str).tolist()
            y1_values = temp_df["y1"].tolist()
            y2_values = temp_df["y2"].tolist()
        else:
            grouped = temp_df.groupby("x")[["y1", "y2"]].mean().reset_index()
            grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
            x_values = grouped["x"].astype(str).tolist()
            y1_values = grouped["y1"].round(2).tolist()
            y2_values = grouped["y2"].round(2).tolist()
        return _return_chart_data({
            "x": x_values,
            "y1": y1_values,
            "y2": y2_values,
            "y1_name": y1_col,
            "y2_name": y2_col,
            "show_data_labels": show_data_labels,
            "show_legend": show_legend
        })

    elif chart_type == "radar":
        # 雷达图：多个数值列作为维度，按分类列分组聚合后对比
        # 修复说明：原实现取前 5 行作为"样本"无业务含义，改为按分类列 groupby+mean 聚合
        columns = params.get("columns", [])
        if not columns:
            columns = get_numeric_columns(df)
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if len(columns) < 3:
            raise HTTPException(status_code=400, detail="雷达图需要至少 3 个数值列作为维度")
        numeric_df = df[columns].apply(to_numeric_if_possible)

        # 分组列：优先使用用户指定的 group_column，否则自动选取唯一值≤8 的分类列
        group_col = params.get("group_column")
        if not group_col or group_col not in df.columns:
            cat_cols = _get_categorical_columns(df)
            group_col = None
            for c in cat_cols:
                if df[c].nunique(dropna=True) <= 8:
                    group_col = c
                    break

        # 按分组列做 groupby + mean 聚合，每组对应雷达图上一个多边形
        if group_col:
            # 聚合后按出现频率排序，最多保留前 8 个分组避免图形过于拥挤
            grouped = numeric_df.groupby(df[group_col], dropna=True).mean()
            # 按组内样本数排序，让主要类别优先展示
            counts = df[group_col].value_counts(dropna=True)
            ordered_groups = [g for g in counts.index if g in grouped.index][:8]
            grouped = grouped.loc[ordered_groups]
        else:
            # 没有合适分类列时，展示全部数据均值作为单条参考线
            grouped = numeric_df.mean().to_frame(name="全部数据").T

        # 每列做 min-max 归一化到 0-100，便于雷达图展示
        normalized = pd.DataFrame(index=grouped.index)
        for col in columns:
            col_data = numeric_df[col]
            col_min = col_data.min()
            col_max = col_data.max()
            if col_max > col_min:
                normalized[col] = ((grouped[col] - col_min) / (col_max - col_min) * 100).round(2)
            else:
                normalized[col] = 50.0

        # 每个分组作为一个 series，名称使用分组值，有业务含义
        series = []
        for idx, (group_value, row) in enumerate(normalized.iterrows()):
            series.append({
                "name": str(group_value),
                "value": row.tolist()
            })
        return _return_chart_data({
            "indicators": columns,
            "series": series,
            "group_column": group_col,
            "show_data_labels": True,
            "show_legend": show_legend
        })

    elif chart_type == "table_heatmap":
        # 表格热力图：数值表格按值着色
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        value_col = params.get("value_column")
        if x_col and y_col and value_col:
            # 透视表模式：X 作为行，Y 作为列，value 作为值
            if x_col not in df.columns:
                raise HTTPException(status_code=400, detail=f"行维度列 '{x_col}' 不存在")
            if y_col not in df.columns:
                raise HTTPException(status_code=400, detail=f"列维度列 '{y_col}' 不存在")
            if value_col not in df.columns:
                raise HTTPException(status_code=400, detail=f"值列 '{value_col}' 不存在")
            if not _is_numeric_column(df[value_col]):
                raise HTTPException(status_code=400, detail=f"值列 '{value_col}' 需要数值列")
            # 限制行/列维度基数，避免单元格过多导致渲染重叠
            max_categories = 20
            x_unique = df[x_col].nunique(dropna=True)
            y_unique = df[y_col].nunique(dropna=True)
            if x_unique > max_categories:
                raise HTTPException(status_code=400, detail=f"表格热力图行维度 '{x_col}' 类别数过多（{x_unique} 个），请选择唯一值不超过 {max_categories} 的列")
            if y_unique > max_categories:
                raise HTTPException(status_code=400, detail=f"表格热力图列维度 '{y_col}' 类别数过多（{y_unique} 个），请选择唯一值不超过 {max_categories} 的列")
            temp_df = pd.DataFrame({
                "x": df[x_col],
                "y": df[y_col],
                "value": to_numeric_if_possible(df[value_col])
            }).dropna()
            pivot = temp_df.pivot_table(
                index="x", columns="y", values="value", aggfunc="mean"
            ).round(2)
            rows = [str(idx) for idx in pivot.index]
            col_labels = [str(col) for col in pivot.columns]
            data = pivot.values.tolist()
            # 将 nan 替换为 None，便于 JSON 序列化
            data = [[None if pd.isna(v) else float(v) for v in row] for row in data]
        else:
            # 简单模式：展示数值列数据（前 20 行）
            columns = params.get("columns", [])
            if not columns:
                columns = get_numeric_columns(df)
            columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
            if not columns:
                raise HTTPException(status_code=400, detail="表格热力图需要至少 1 个数值列")
            numeric_df = df[columns].apply(to_numeric_if_possible).head(20)
            rows = [str(idx) for idx in numeric_df.index]
            col_labels = columns
            data = numeric_df.values.tolist()
            data = [[None if pd.isna(v) else float(v) for v in row] for row in data]
        return _return_chart_data({
            "columns": col_labels,
            "rows": rows,
            "data": data,
            "show_data_labels": True,
            "show_legend": show_legend
        })

    else:
        raise HTTPException(status_code=400, detail=f"不支持的图表类型: {chart_type}")


def _generate_chart_image(df: pd.DataFrame, chart_type: str, params: Dict[str, Any]) -> io.BytesIO:
    """使用 matplotlib 生成图表 PNG 图片。
    兼容新旧前端参数格式（与 _get_chart_data 一致）：
    - 单列类：column 或 columns（数组，取第一个）
    - 双列类：x_column + y_column，或 x_column + y_columns（数组，取第一个）
    - 双 Y 轴：y1_column/y2_column 优先于 y_column/y2_column
    数据标注：show_data_labels=True 时折线/柱状/双Y轴/多折线显示数值；
    热力图、表格热力图、堆叠柱状图、雷达图等默认显示数值。"""
    # 统一参数校验，确保非法参数以 HTTPException(400) 抛出而不是生成时 500
    _validate_chart_params(df, chart_type, params)

    # 设置中文字体（使用模块加载时检测到的可用字体列表）
    plt.rcParams['font.sans-serif'] = _CHINESE_FONTS
    plt.rcParams['axes.unicode_minus'] = False

    # 获取所有数值列（包括可转换为数值的字符串列）
    numeric_columns = get_numeric_columns(df)

    # 解析通用绘图控制参数
    show_data_labels = bool(params.get("show_data_labels", False))
    show_legend = bool(params.get("show_legend", True))

    fig, ax = plt.subplots(figsize=(10, 6))

    if chart_type == "histogram":
        # 兼容新格式：columns 是数组（多选），空数组=第一个数值列
        columns_param = params.get("columns") or []
        column = params.get("column")
        if columns_param:
            column = columns_param[0]
        elif not column:
            numeric_cols = get_numeric_columns(df)
            if not numeric_cols:
                raise ValueError("没有可用的数值列")
            column = numeric_cols[0]
        if column not in df.columns:
            raise ValueError(f"列 '{column}' 不存在")
        col_data = to_numeric_if_possible(df[column]).dropna()
        bins = int(params.get("bins", 0))
        if bins <= 0:
            bins = max(5, min(50, int(np.sqrt(len(col_data)))))
        # 使用 ax.hist 返回值以便在柱子上方显示频数
        n_counts, bin_edges, patches = ax.hist(col_data, bins=bins, edgecolor='black', alpha=0.7)
        ax.set_xlabel(column)
        ax.set_ylabel(_tr("频数"))
        ax.set_title(_tr(f"{column} 分布直方图"))
        # 直方图默认在柱子上方显示频数（用 enumerate 避免重复值定位错误）
        for idx, count in enumerate(n_counts):
            if count > 0:
                x_center = (bin_edges[idx] + bin_edges[idx + 1]) / 2
                ax.text(x_center, count, str(int(count)),
                        ha='center', va='bottom', fontsize=7)

    elif chart_type == "scatter":
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        # 兼容新格式：y_columns 是数组（多选），取第一个作为 y_column
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise ValueError(f"Y 轴列 '{y_col}' 不存在")
        valid = df[[x_col, y_col]].dropna()
        ax.scatter(valid[x_col], valid[y_col], alpha=0.6, s=20)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(_tr(f"{x_col} vs {y_col} 散点图"))

    elif chart_type == "boxplot":
        # 兼容新格式：columns 数组，空数组=所有数值列；同时支持 column 单列参数
        columns = params.get("columns", [])
        column = params.get("column")
        if column and column in df.columns:
            columns = [column]
        if not columns:
            columns = numeric_columns[:10]
        columns = [c for c in columns if c in df.columns]
        if not columns:
            raise ValueError("没有有效的数值列")
        # 计算每列异常值数量，用于在标题中显示
        outlier_counts = []
        data_list = []
        for col in columns:
            col_data = to_numeric_if_possible(df[col]).dropna()
            data_list.append(col_data.values)
            if len(col_data) >= 4:
                q1 = col_data.quantile(0.25)
                q3 = col_data.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                outliers = int(((col_data < lower) | (col_data > upper)).sum())
                outlier_counts.append(outliers)
            else:
                outlier_counts.append(0)
        bp = ax.boxplot(data_list, tick_labels=columns, patch_artist=True)
        for patch in bp['boxes']:
            patch.set_facecolor('lightblue')
        # 标题显示异常值总数
        total_outliers = sum(outlier_counts)
        ax.set_title(_tr(f"箱线图 (异常值: {total_outliers})"))
        ax.set_ylabel(_tr("值"))

    elif chart_type == "line":
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        # 兼容新格式：y_columns 是数组（多选），取第一个作为 y_column
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise ValueError(f"Y 轴列 '{y_col}' 不存在")
        temp_df = pd.DataFrame({
            "x": df[x_col],
            "y": to_numeric_if_possible(df[y_col])
        }).dropna()
        if _is_numeric_column(df[x_col]):
            temp_df = temp_df.sort_values(by="x")
            x_labels = temp_df["x"].astype(str).tolist()
            y_values = temp_df["y"].tolist()
        else:
            grouped = temp_df.groupby("x")["y"].mean().reset_index()
            grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
            x_labels = grouped["x"].astype(str).tolist()
            y_values = grouped["y"].round(2).tolist()
        ax.plot(range(len(y_values)), y_values, linewidth=1, color='#4361ee')
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(_tr(f"{x_col} vs {y_col} 折线图"))
        # show_data_labels=True 时在数据点上方显示数值
        if show_data_labels and len(y_values) <= 50:
            for idx, val in enumerate(y_values):
                ax.text(idx, val, str(round(val, 2)), ha='center', va='bottom', fontsize=7)
        # X轴标签较多时旋转
        if len(x_labels) > 10:
            ax.set_xticks(range(0, len(x_labels), max(1, len(x_labels) // 10)))
            ax.set_xticklabels([x_labels[i] for i in range(0, len(x_labels), max(1, len(x_labels) // 10))],
                               rotation=30, ha='right', fontsize=8)

    elif chart_type == "pie":
        column = params.get("column")
        if not column or column not in df.columns:
            raise ValueError(f"列 '{column}' 不存在")
        # topN 限制返回前 N 项分类，默认 10
        top_n = int(params.get("topN", 10) or 10)
        if top_n <= 0:
            top_n = 10
        value_counts = df[column].dropna().value_counts().head(top_n)
        # 扇形旁显示百分比（autopct 自动控制百分比显示）
        ax.pie(
            value_counts.values, labels=value_counts.index, autopct='%1.1f%%',
            startangle=90, pctdistance=0.85
        )
        ax.set_title(_tr(f"{column} 饼图"))

    elif chart_type == "heatmap":
        columns = params.get("columns", [])
        if not columns:
            columns = numeric_columns
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if len(columns) < 2:
            raise ValueError("需要至少 2 个数值列")
        numeric_df = df[columns].apply(to_numeric_if_possible)
        corr = numeric_df.corr()
        im = ax.imshow(corr.values, cmap='RdYlBu_r', aspect='auto', vmin=-1, vmax=1)
        ax.set_xticks(range(len(columns)))
        ax.set_yticks(range(len(columns)))
        ax.set_xticklabels(columns, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(columns, fontsize=8)
        # 在每个单元格显示相关系数（热力图默认显示数值）
        for i in range(len(columns)):
            for j in range(len(columns)):
                val = corr.iloc[i, j]
                if pd.notna(val):
                    ax.text(j, i, f"{val:.2f}", ha='center', va='center',
                            fontsize=7, color='white' if abs(val) > 0.5 else 'black')
        ax.set_title(_tr("相关性热力图"))
        fig.colorbar(im, ax=ax)

    elif chart_type == "bar":
        # 柱状图：分类列 X 轴 + 数值列 Y 轴，按分类分组求和
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        # 兼容新格式：y_columns 是数组（多选），取第一个作为 y_column
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise ValueError(f"Y 轴列 '{y_col}' 不存在")
        if not _is_numeric_column(df[y_col]):
            raise ValueError(f"柱状图 Y 轴需要数值列，'{y_col}' 不是数值列")
        temp_df = pd.DataFrame({
            "x": df[x_col],
            "y": to_numeric_if_possible(df[y_col])
        }).dropna()
        grouped = temp_df.groupby("x")["y"].sum().reset_index()
        grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
        # topN 限制返回前 N 项分类
        top_n = int(params.get("topN", 0) or 0)
        if top_n > 0 and len(grouped) > top_n:
            grouped = grouped.nlargest(top_n, "y")
        categories = grouped["x"].astype(str).tolist()
        values = grouped["y"].tolist()
        bars = ax.bar(range(len(categories)), values, color='#4361ee', alpha=0.8)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(_tr(f"{x_col} 各分类 {y_col} 总和柱状图"))
        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels(categories, rotation=30 if len(categories) > 5 else 0, ha='right', fontsize=9)
        # show_data_labels=True 时在柱子上方显示数值
        if show_data_labels:
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, val,
                        str(round(val, 2)), ha='center', va='bottom', fontsize=8)

    elif chart_type == "stacked_bar":
        # 堆叠柱状图：分类列 X 轴 + 多个数值列 Y 轴，堆叠展示
        x_col = params.get("x_column")
        columns = params.get("columns", [])
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not columns:
            columns = numeric_columns
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if not columns:
            raise ValueError("堆叠柱状图需要至少 1 个数值列")
        temp_df = df[[x_col] + columns].copy()
        for col in columns:
            temp_df[col] = to_numeric_if_possible(temp_df[col])
        grouped = temp_df.groupby(x_col)[columns].sum()
        grouped = grouped.sort_index(key=lambda col: col.astype(str))
        categories = [str(idx) for idx in grouped.index]
        # 堆叠绘制：每个数值列叠加在前一个之上
        bottom = np.zeros(len(categories))
        colors = plt.cm.tab10(np.linspace(0, 1, len(columns)))
        for i, col in enumerate(columns):
            ax.bar(range(len(categories)), grouped[col].values, bottom=bottom,
                   label=col, color=colors[i], alpha=0.8)
            bottom += grouped[col].values
        ax.set_xlabel(x_col)
        ax.set_ylabel(_tr("值"))
        ax.set_title(_tr(f"{x_col} 堆叠柱状图"))
        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels(categories, rotation=30 if len(categories) > 5 else 0, ha='right', fontsize=9)
        # 堆叠柱状图默认在柱子上方显示总值
        totals = grouped.sum(axis=1).values
        for idx, total in enumerate(totals):
            ax.text(idx, total, str(round(float(total), 2)),
                    ha='center', va='bottom', fontsize=8)
        if show_legend:
            ax.legend(fontsize=8)

    elif chart_type == "area":
        # 面积图：数值列 X 轴 + 数值列 Y 轴，类似折线图但填充面积
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        # 兼容新格式：y_columns 是数组（多选），取第一个作为 y_column
        y_columns = params.get("y_columns") or []
        if y_columns and not y_col:
            y_col = y_columns[0]
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise ValueError(f"Y 轴列 '{y_col}' 不存在")
        if not _is_numeric_column(df[y_col]):
            raise ValueError(f"面积图 Y 轴需要数值列，'{y_col}' 不是数值列")
        temp_df = pd.DataFrame({
            "x": df[x_col],
            "y": to_numeric_if_possible(df[y_col])
        }).dropna()
        if len(temp_df) == 0:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return buf
        if _is_numeric_column(df[x_col]):
            temp_df = temp_df.sort_values(by="x")
        else:
            # X 是分类列则分组取均值
            grouped = temp_df.groupby("x")["y"].mean().reset_index()
            grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
            temp_df = grouped
        x_values = temp_df["x"].astype(str).tolist()
        y_values = temp_df["y"].tolist()
        ax.fill_between(range(len(y_values)), y_values, alpha=0.4, color='#4361ee')
        ax.plot(range(len(y_values)), y_values, color='#4361ee', linewidth=1)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(_tr(f"{x_col} vs {y_col} 面积图"))
        if len(x_values) > 10:
            step = max(1, len(x_values) // 10)
            ax.set_xticks(range(0, len(x_values), step))
            ax.set_xticklabels([x_values[i] for i in range(0, len(x_values), step)],
                               rotation=30, ha='right', fontsize=8)

    elif chart_type == "kde":
        # KDE 密度图：单个数值列的核密度估计曲线
        # 兼容新格式：columns 是数组（多选），取第一个
        columns_param = params.get("columns") or []
        column = params.get("column")
        if columns_param and not column:
            column = columns_param[0]
        if not column or column not in df.columns:
            raise ValueError(f"列 '{column}' 不存在")
        if not _is_numeric_column(df[column]):
            raise ValueError(f"KDE 图需要数值列，'{column}' 不是数值列")
        col_data = to_numeric_if_possible(df[column]).dropna()
        if len(col_data) >= 2:
            from scipy.stats import gaussian_kde
            kde = gaussian_kde(col_data.values)
            x = np.linspace(col_data.min(), col_data.max(), 200)
            y = kde(x)
            ax.plot(x, y, color='#4361ee', linewidth=2)
            ax.fill_between(x, y, alpha=0.4, color='#4361ee')
        ax.set_xlabel(column)
        ax.set_ylabel(_tr("密度"))
        ax.set_title(_tr(f"{column} KDE 密度图"))

    elif chart_type == "qq":
        # QQ 图：单个数值列与正态分布的分位数对比
        column = params.get("column")
        if not column or column not in df.columns:
            raise ValueError(f"列 '{column}' 不存在")
        if not _is_numeric_column(df[column]):
            raise ValueError(f"QQ 图需要数值列，'{column}' 不是数值列")
        col_data = to_numeric_if_possible(df[column]).dropna()
        if len(col_data) < 4:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return buf
        from scipy.stats import probplot
        (theoretical, sample), (slope, intercept, r) = probplot(col_data, dist="norm")
        ax.scatter(theoretical, sample, alpha=0.6, s=20, color='#4361ee')
        # 绘制理论参考线
        x_line = np.array([theoretical.min(), theoretical.max()])
        y_line = slope * x_line + intercept
        ax.plot(x_line, y_line, 'r--', linewidth=1, label=_tr(f'参考线 (R²={r**2:.3f})'))
        ax.set_xlabel(_tr("理论分位数"))
        ax.set_ylabel(_tr("样本分位数"))
        ax.set_title(_tr(f"{column} QQ 图"))
        if show_legend:
            ax.legend(fontsize=8)

    elif chart_type == "bubble":
        # 气泡图：三个数值列(X/Y/大小)
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        size_col = params.get("size_column")
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not y_col or y_col not in df.columns:
            raise ValueError(f"Y 轴列 '{y_col}' 不存在")
        if not size_col or size_col not in df.columns:
            raise ValueError(f"大小列 '{size_col}' 不存在")
        temp_df = pd.DataFrame({
            "x": to_numeric_if_possible(df[x_col]),
            "y": to_numeric_if_possible(df[y_col]),
            "size": to_numeric_if_possible(df[size_col])
        }).dropna()
        if len(temp_df) == 0:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return buf
        # 归一化 size 到 [10, 500] 范围用于 matplotlib 散点大小
        size_data = temp_df["size"]
        size_min = size_data.min()
        size_max = size_data.max()
        if size_max > size_min:
            sizes = ((size_data - size_min) / (size_max - size_min) * 490 + 10).values
        else:
            sizes = np.full(len(size_data), 50)
        ax.scatter(temp_df["x"], temp_df["y"], s=sizes, alpha=0.5,
                   color='#4361ee', edgecolors='white', linewidth=0.5)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(_tr(f"{x_col} vs {y_col} (大小: {size_col}) 气泡图"))

    elif chart_type == "multi_line":
        # 多折线图：X 轴列 + 多个数值列 Y 轴
        x_col = params.get("x_column")
        columns = params.get("columns", [])
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not columns:
            columns = numeric_columns
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if not columns:
            raise ValueError("多折线图需要至少 1 个数值列")
        temp_df = df[[x_col] + columns].copy()
        for col in columns:
            temp_df[col] = to_numeric_if_possible(temp_df[col])
        temp_df = temp_df.dropna(subset=[x_col])
        # X 是数值列则按 X 排序，否则按 X 分组取均值
        if _is_numeric_column(df[x_col]):
            temp_df = temp_df.sort_values(by=x_col)
            x_values = temp_df[x_col].astype(str).tolist()
            plot_data = {col: temp_df[col].tolist() for col in columns}
        else:
            grouped = temp_df.groupby(x_col)[columns].mean()
            grouped = grouped.sort_index(key=lambda col: col.astype(str))
            x_values = [str(idx) for idx in grouped.index]
            plot_data = {col: grouped[col].tolist() for col in columns}
        colors = plt.cm.tab10(np.linspace(0, 1, len(columns)))
        for i, col in enumerate(columns):
            ax.plot(range(len(x_values)), plot_data[col], linewidth=1.5, label=col, color=colors[i])
            # show_data_labels=True 时在数据点显示数值
            if show_data_labels and len(x_values) <= 50:
                for idx, val in enumerate(plot_data[col]):
                    if pd.notna(val):
                        ax.text(idx, val, str(round(val, 2)),
                                ha='center', va='bottom', fontsize=6, color=colors[i])
        ax.set_xlabel(x_col)
        ax.set_ylabel(_tr("值"))
        ax.set_title(_tr(f"{x_col} 多折线图"))
        if len(x_values) > 10:
            step = max(1, len(x_values) // 10)
            ax.set_xticks(range(0, len(x_values), step))
            ax.set_xticklabels([x_values[i] for i in range(0, len(x_values), step)],
                               rotation=30, ha='right', fontsize=8)
        if show_legend:
            ax.legend(fontsize=8)

    elif chart_type == "dual_axis":
        # 双 Y 轴图：X 轴列 + 两个数值列分别在不同 Y 轴
        # 兼容新格式：y1_column/y2_column 优先于 y_column/y2_column
        x_col = params.get("x_column")
        y1_col = params.get("y1_column") or params.get("y_column")
        y2_col = params.get("y2_column")
        if not x_col or x_col not in df.columns:
            raise ValueError(f"X 轴列 '{x_col}' 不存在")
        if not y1_col or y1_col not in df.columns:
            raise ValueError(f"Y1 轴列 '{y1_col}' 不存在")
        if not y2_col or y2_col not in df.columns:
            raise ValueError(f"Y2 轴列 '{y2_col}' 不存在")
        temp_df = pd.DataFrame({
            "x": df[x_col],
            "y1": to_numeric_if_possible(df[y1_col]),
            "y2": to_numeric_if_possible(df[y2_col])
        }).dropna()
        if len(temp_df) == 0:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return buf
        if _is_numeric_column(df[x_col]):
            temp_df = temp_df.sort_values(by="x")
            x_values = temp_df["x"].astype(str).tolist()
            y1_values = temp_df["y1"].tolist()
            y2_values = temp_df["y2"].tolist()
        else:
            grouped = temp_df.groupby("x")[["y1", "y2"]].mean().reset_index()
            grouped = grouped.sort_values(by="x", key=lambda col: col.astype(str))
            x_values = grouped["x"].astype(str).tolist()
            y1_values = grouped["y1"].tolist()
            y2_values = grouped["y2"].tolist()
        # 创建双 Y 轴
        ax2 = ax.twinx()
        line1 = ax.plot(range(len(x_values)), y1_values, color='#4361ee', linewidth=1.5, label=y1_col)
        line2 = ax2.plot(range(len(x_values)), y2_values, color='#e63946', linewidth=1.5, label=y2_col)
        # show_data_labels=True 时在数据点显示数值
        if show_data_labels and len(x_values) <= 50:
            for idx, (v1, v2) in enumerate(zip(y1_values, y2_values)):
                ax.text(idx, v1, str(round(v1, 2)), ha='center', va='bottom',
                        fontsize=6, color='#4361ee')
                ax2.text(idx, v2, str(round(v2, 2)), ha='center', va='top',
                         fontsize=6, color='#e63946')
        ax.set_xlabel(x_col)
        ax.set_ylabel(y1_col, color='#4361ee')
        ax2.set_ylabel(y2_col, color='#e63946')
        ax.tick_params(axis='y', labelcolor='#4361ee')
        ax2.tick_params(axis='y', labelcolor='#e63946')
        ax.set_title(_tr(f"{x_col} 双 Y 轴图 ({y1_col} & {y2_col})"))
        # 合并图例
        if show_legend:
            lines = line1 + line2
            labels = [l.get_label() for l in lines]
            ax.legend(lines, labels, fontsize=8)
        if len(x_values) > 10:
            step = max(1, len(x_values) // 10)
            ax.set_xticks(range(0, len(x_values), step))
            ax.set_xticklabels([x_values[i] for i in range(0, len(x_values), step)],
                               rotation=30, ha='right', fontsize=8)

    elif chart_type == "radar":
        # 雷达图：多个数值列作为维度，按分类列分组聚合后对比（需极坐标）
        # 修复说明：原实现取前 5 行作为"样本"无业务含义，改为按分类列 groupby+mean 聚合
        columns = params.get("columns", [])
        if not columns:
            columns = numeric_columns
        columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
        if len(columns) < 3:
            raise ValueError("雷达图需要至少 3 个数值列作为维度")
        numeric_df = df[columns].apply(to_numeric_if_possible)

        # 分组列：优先使用用户指定的 group_column，否则自动选取唯一值≤8 的分类列
        group_col = params.get("group_column")
        if not group_col or group_col not in df.columns:
            cat_cols = _get_categorical_columns(df)
            group_col = None
            for c in cat_cols:
                if df[c].nunique(dropna=True) <= 8:
                    group_col = c
                    break

        # 按分组列做 groupby + mean 聚合，每组对应雷达图上一个多边形
        if group_col:
            grouped = numeric_df.groupby(df[group_col], dropna=True).mean()
            counts = df[group_col].value_counts(dropna=True)
            ordered_groups = [g for g in counts.index if g in grouped.index][:8]
            grouped = grouped.loc[ordered_groups]
        else:
            # 没有合适分类列时，展示全部数据均值作为单条参考线
            grouped = numeric_df.mean().to_frame(name="全部数据").T

        # 每列归一化到 0-100（基于原始数据范围）
        normalized = pd.DataFrame(index=grouped.index)
        for col in columns:
            col_data = numeric_df[col]
            col_min = col_data.min()
            col_max = col_data.max()
            if col_max > col_min:
                normalized[col] = (grouped[col] - col_min) / (col_max - col_min) * 100
            else:
                normalized[col] = 50.0

        # 雷达图需要极坐标，替换原有 axes
        ax.remove()
        ax = fig.add_subplot(111, projection='polar')
        N = len(columns)
        # 计算每个维度的角度，并闭合多边形
        angles = [n / float(N) * 2 * np.pi for n in range(N)]
        angles += angles[:1]
        group_count = len(normalized)
        colors = plt.cm.tab10(np.linspace(0, 1, max(group_count, 1)))
        for i in range(group_count):
            values = normalized.iloc[i].tolist()
            values += values[:1]
            group_name = str(normalized.index[i])
            ax.plot(angles, values, linewidth=1.5, label=group_name, color=colors[i])
            ax.fill(angles, values, alpha=0.15, color=colors[i])
            # 雷达图顶点默认显示数值
            for j, val in enumerate(values[:-1]):
                ax.text(angles[j], val, str(round(val, 2)),
                        fontsize=6, ha='center', va='bottom', color=colors[i])
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(columns, fontsize=9)
        title_text = _tr("雷达图") + (f"（按 {_tr(group_col)} 分组）" if group_col else _tr("（全部数据均值）"))
        ax.set_title(title_text, pad=20)
        if show_legend:
            ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=8)

    elif chart_type == "table_heatmap":
        # 表格热力图：数值表格按值着色
        x_col = params.get("x_column")
        y_col = params.get("y_column")
        value_col = params.get("value_column")
        if x_col and y_col and value_col:
            # 透视表模式
            if value_col not in df.columns:
                raise ValueError(f"值列 '{value_col}' 不存在")
            if not _is_numeric_column(df[value_col]):
                raise ValueError(f"值列 '{value_col}' 需要数值列")
            temp_df = pd.DataFrame({
                "x": df[x_col],
                "y": df[y_col],
                "value": to_numeric_if_possible(df[value_col])
            }).dropna()
            pivot = temp_df.pivot_table(index="x", columns="y", values="value", aggfunc="mean")
            row_labels = [str(idx) for idx in pivot.index]
            col_labels = [str(col) for col in pivot.columns]
            data = pivot.values
        else:
            # 简单模式：展示数值列前 20 行
            columns = params.get("columns", [])
            if not columns:
                columns = numeric_columns
            columns = [c for c in columns if c in df.columns and _is_numeric_column(df[c])]
            if not columns:
                raise ValueError("表格热力图需要至少 1 个数值列")
            numeric_df = df[columns].apply(to_numeric_if_possible).head(20)
            row_labels = [str(idx) for idx in numeric_df.index]
            col_labels = columns
            data = numeric_df.values
        # 计算颜色映射范围（忽略 nan）
        valid_data = data[~np.isnan(data)]
        if len(valid_data) > 0:
            vmin, vmax = float(valid_data.min()), float(valid_data.max())
        else:
            vmin, vmax = 0.0, 1.0
        # 设置 nan 显示为白色
        cmap = plt.cm.YlOrRd.copy()
        cmap.set_bad('white')
        im = ax.imshow(data, cmap=cmap, aspect='auto', vmin=vmin, vmax=vmax)
        ax.set_xticks(range(len(col_labels)))
        ax.set_yticks(range(len(row_labels)))
        ax.set_xticklabels(col_labels, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(row_labels, fontsize=8)
        # 在每个单元格显示数值（表格热力图默认显示数值）
        for i in range(len(row_labels)):
            for j in range(len(col_labels)):
                val = data[i, j]
                if not np.isnan(val):
                    ax.text(j, i, f"{val:.2f}", ha='center', va='center',
                            fontsize=7, color='white' if val > (vmin + vmax) / 2 else 'black')
        ax.set_title(_tr("表格热力图"))
        fig.colorbar(im, ax=ax)

    else:
        raise HTTPException(status_code=400, detail=f"不支持的图表类型: {chart_type}")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _build_analysis_report(df: pd.DataFrame, sections: Optional[List[str]] = None,
                            charts: Optional[List[Dict[str, Any]]] = None,
                            options: Optional[Dict[str, Any]] = None) -> tuple:
    """根据 DataFrame 与指定章节、图表生成数据分析报告，返回 (html, dynamic_data)"""
    plt.rcParams['font.sans-serif'] = _CHINESE_FONTS
    plt.rcParams['axes.unicode_minus'] = False

    all_sections = ["data_preview", "quality", "column_info", "numeric_stats", "categorical_stats", "charts"]
    if sections is None:
        sections = all_sections
    section_set = set(sections)
    options = options or {}

    numeric_cols = get_numeric_columns(df)
    categorical_cols = _get_categorical_columns(df)
    esc = html.escape

    basic_info = _compute_basic_info(df)
    numeric_stats = compute_numeric_stats(df) if "numeric_stats" in section_set else None
    categorical_stats = _compute_categorical_stats(df) if "categorical_stats" in section_set else None

    body_parts = []
    section_counter = 0

    def add_section(title: str, content: str):
        nonlocal section_counter
        section_counter += 1
        body_parts.append(f"<h2>{section_counter}. {title}</h2>{content}")

    # 1. 数据预览
    if "data_preview" in section_set:
        sample_rows = options.get("dataPreview", {}).get("sampleRows", 5)
        if sample_rows > 0:
            preview_df = df.head(sample_rows)
            preview_cols = preview_df.columns.tolist()
            preview_header = "<tr>" + "".join(f"<th>{esc(col)}</th>" for col in preview_cols) + "</tr>"
            preview_rows = ""
            for _, row in preview_df.iterrows():
                preview_rows += "<tr>" + "".join(
                    f"<td>{esc(str(cell))}</td>" for cell in row
                ) + "</tr>"
            add_section("数据预览", f"<div class='table-wrapper'><table><caption>前 {sample_rows} 行数据</caption>{preview_header}{preview_rows}</table></div>")
        else:
            add_section("数据预览", "<p>未选择预览行数</p>")

    # 2. 数据质量概览
    if "quality" in section_set:
        total_cells = df.shape[0] * df.shape[1]
        missing_cells = int(df.isna().sum().sum())
        missing_rate = round(missing_cells / total_cells * 100, 2) if total_cells > 0 else 0
        
        inf_count = 0
        for col in numeric_cols:
            col_numeric = to_numeric_if_possible(df[col])
            inf_count += int(np.isinf(col_numeric).sum())
        
        duplicate_rows = int(df.duplicated().sum())
        
        constant_cols = [col for col in df.columns if df[col].nunique() <= 1]
        constant_count = len(constant_cols)
        
        missing_cols = [col for col in df.columns if df[col].isna().any()]
        missing_cols_count = len(missing_cols)

        metrics = options.get("quality", {}).get("metrics", [
            "missing_rate", "missing_columns", "infinite_columns", "duplicate_rows", 
            "constant_columns", "row_count", "column_count", "numeric_count", "categorical_count"
        ])

        metric_map = {
            "missing_rate": ("总体缺失率", f"{missing_rate}%"),
            "missing_columns": ("含缺失值列数", str(missing_cols_count)),
            "infinite_columns": ("含无穷大列数", str(inf_count)),
            "duplicate_rows": ("重复行数", str(duplicate_rows)),
            "constant_columns": ("常量列数", str(constant_count)),
            "row_count": ("总行数", str(basic_info['row_count'])),
            "column_count": ("总列数", str(basic_info['column_count'])),
            "numeric_count": ("数值列数", str(basic_info['numeric_count'])),
            "categorical_count": ("分类列数", str(basic_info['categorical_count'])),
        }

        quality_cards = ""
        for metric_key in metrics:
            if metric_key in metric_map:
                label, value = metric_map[metric_key]
                quality_cards += f"""
                <div class='quality-card'>
                    <div class='quality-card-value'>{esc(value)}</div>
                    <div class='quality-card-label'>{esc(label)}</div>
                </div>"""
        
        add_section("数据质量概览", f"<div class='quality-grid'>{quality_cards}</div>")

    # 3. 列信息
    if "column_info" in section_set:
        columns_info = []
        for col in df.columns:
            col_data = to_numeric_if_possible(df[col]) if col in numeric_cols else df[col]
            missing_count = int(col_data.isna().sum())
            missing_rate_val = round(missing_count / len(df) * 100, 2) if len(df) > 0 else 0
            col_type = "数值" if col in numeric_cols else "分类"
            
            unique_count = int(col_data.nunique(dropna=True))
            non_null_count = int(len(df) - missing_count)
            unique_ratio = unique_count / non_null_count if non_null_count > 0 else 0
            
            completeness_level = "高" if missing_rate_val < 10 else ("中" if missing_rate_val < 50 else "低")
            uniqueness_level = "高" if unique_ratio > 0.9 else ("中" if unique_ratio > 0.5 else "低")
            
            completeness_score = (1 - missing_rate_val / 100) * 60
            uniqueness_score = unique_ratio * 20
            type_score = 20 if col_type == "数值" else 15
            quality_score = max(0, min(100, round(completeness_score + uniqueness_score + type_score)))
            
            columns_info.append({
                "name": col,
                "type": col_type,
                "missing_count": missing_count,
                "missing_rate": missing_rate_val,
                "completeness": completeness_level,
                "uniqueness": uniqueness_level,
                "quality_score": quality_score
            })
        
        col_header = "<tr><th>列名</th><th>类型</th><th>缺失数</th><th>缺失率(%)</th><th>完整性</th><th>唯一性</th><th>质量评分</th></tr>"
        col_rows = ""
        for info in columns_info:
            col_rows += f"""
            <tr>
                <td>{esc(info['name'])}</td>
                <td>{esc(info['type'])}</td>
                <td>{info['missing_count']}</td>
                <td>{info['missing_rate']}</td>
                <td>{esc(info['completeness'])}</td>
                <td>{esc(info['uniqueness'])}</td>
                <td>{info['quality_score']}</td>
            </tr>
            """
        weight_note = "<p class='weight-note'>质量评分权重：完整性60% + 唯一性20% + 类型20%</p>"
        add_section("列信息", f"{weight_note}<div class='table-wrapper'><table>{col_header}{col_rows}</table></div>")

    # 4. 数值列统计
    if "numeric_stats" in section_set:
        if numeric_stats:
            selected_metrics = options.get("numericStats", {}).get("metrics", [
                "mean", "median", "std", "min", "max", "missing_count", "missing_rate",
                "skewness", "kurtosis", "p90", "p95", "p99", "cv", "mode", "zero_count", "zero_rate"
            ])
            
            metric_label_map = {
                "mean": "均值", "median": "中位数", "std": "标准差", "min": "最小值", 
                "max": "最大值", "missing_count": "缺失数", "missing_rate": "缺失率(%)",
                "skewness": "偏度", "kurtosis": "峰度", "p90": "P90", "p95": "P95", 
                "p99": "P99", "cv": "变异系数(CV)", "mode": "众数", "zero_count": "零值数", 
                "zero_rate": "零值率(%)"
            }
            
            header_cols = ["列名"] + [metric_label_map[m] for m in selected_metrics if m in metric_label_map]
            numeric_header = "<tr>" + "".join(f"<th>{esc(col)}</th>" for col in header_cols) + "</tr>"
            
            numeric_rows = ""
            for col, stat in numeric_stats.items():
                row_cells = [f"<td>{esc(col)}</td>"]
                for m in selected_metrics:
                    if m in metric_label_map:
                        val = stat.get(m, '-')
                        row_cells.append(f"<td>{esc(str(val))}</td>")
                numeric_rows += "<tr>" + "".join(row_cells) + "</tr>"
            
            add_section("数值列统计", f"<div class='table-wrapper'><table><caption>数值列统计</caption>{numeric_header}{numeric_rows}</table></div>")
        else:
            add_section("数值列统计", "<p>无可用数值列</p>")

    # 5. 分类列统计（改为表格，与数值列统计风格一致）
    if "categorical_stats" in section_set:
        if categorical_stats:
            selected_metrics = options.get("categoricalStats", {}).get("metrics", [
                "unique_count", "missing_count", "missing_rate", "top_values"
            ])
            top_n = options.get("categoricalStats", {}).get("topN", 10)

            metric_label_map = {
                "unique_count": "唯一值数",
                "missing_count": "缺失数",
                "missing_rate": "缺失率(%)",
                "top_values": f"TOP {top_n} 值"
            }

            header_cols = ["列名"] + [metric_label_map[m] for m in selected_metrics if m in metric_label_map]
            cat_header = "<tr>" + "".join(f"<th>{esc(col)}</th>" for col in header_cols) + "</tr>"

            cat_rows = ""
            for col, stat in categorical_stats.items():
                row_cells = [f"<td>{esc(col)}</td>"]
                for m in selected_metrics:
                    if m == "top_values":
                        top_items = stat.get('top_values', [])[:top_n]
                        items_html = "、".join(
                            f"{esc(str(item['value']))}({item['count']})"
                            for item in top_items
                        ) if top_items else "-"
                        row_cells.append(f"<td>{items_html}</td>")
                    elif m in metric_label_map:
                        val = stat.get(m, '-')
                        row_cells.append(f"<td>{esc(str(val))}</td>")
                cat_rows += "<tr>" + "".join(row_cells) + "</tr>"

            add_section("分类列统计", f"<div class='table-wrapper'><table><caption>分类列统计</caption>{cat_header}{cat_rows}</table></div>")
        else:
            add_section("分类列统计", "<p>无可用分类列</p>")

    # 6. 自定义图表（动态渲染）
    # 合并 charts_html 和 charts_data 的生成到同一循环，确保索引一致
    # 避免某个图表生成失败时 charts_data 索引与 HTML 容器 ID 错位导致后续图表渲染失败
    charts_data = []
    if "charts" in section_set:
        charts_html = ""
        if charts is not None:
            for idx, chart in enumerate(charts):
                chart_type = chart.get("type", "")
                params = chart.get("params", {})
                # 标题生成：优先使用前端传的 title，否则按图表类型+列关系信息构建
                title = _build_chart_title(chart_type, params, chart.get("title"))
                try:
                    chart_data = _get_chart_data(df, chart_type, params)
                    charts_data.append({
                        "title": title,
                        "type": chart_type,
                        "data": chart_data
                    })
                    # 成功时添加图表容器，索引与 charts_data 保持一致
                    charts_html += f"<h3>{esc(title)}</h3><div id='chart-container-{len(charts_data) - 1}' class='chart-container'></div>"
                except Exception as e:
                    # 失败时显示错误提示，不添加到 charts_data，避免索引错位
                    charts_html += f"<h3>{esc(title)}</h3><p style='color:#999;padding:10px 0;'>图表生成失败：{esc(str(e))}</p>"
        else:
            charts_html = "<p>暂无已添加的图表</p>"
        add_section("自定义图表", charts_html)



    generated_at = datetime.now(SHANGHAI_TZ).strftime('%Y-%m-%d %H-%M-%S')

    report_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>数据分析报告</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        .report-body {{ font-family: "Microsoft YaHei", "SimHei", Arial, sans-serif; margin: 0; background: #f5f7fa; color: #333; padding: 20px; }}
        .report-body h1 {{ color: #2c3e50; border-bottom: 3px solid #4361ee; padding-bottom: 10px; }}
        .report-body h2 {{ color: #2c3e50; margin-top: 30px; border-left: 4px solid #4361ee; padding-left: 10px; }}
        .report-body h3 {{ color: #34495e; }}
        .report-body .table-wrapper {{ overflow-x: auto; margin: 15px 0; border-radius: 6px; border: 1px solid #ddd; }}
        .report-body table {{ border-collapse: collapse; min-width: 100%; background: #fff; }}
        .report-body th, .report-body td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 12px; white-space: nowrap; }}
        .report-body th {{ background-color: #f8fafc; color: #374151; font-weight: 600; position: sticky; left: 0; z-index: 1; }}
        .report-body tr:nth-child(even) {{ background: #f9f9f9; }}
        .report-body caption {{ font-weight: bold; padding: 8px; color: #2c3e50; text-align: left; }}
        .report-body img {{ max-width: 100%; height: auto; border: 1px solid #ddd; margin: 10px 0; }}
        .report-body .cat-block {{ background: #fff; padding: 15px; margin: 10px 0; border-radius: 6px; border: 1px solid #eee; }}
        .report-body ul {{ margin: 5px 0; padding-left: 20px; }}
        .report-body .footer {{ margin-top: 40px; color: #888; font-size: 12px; text-align: center; }}
        .report-body .quality-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 15px 0; }}
        .report-body .quality-card {{ background: #fff; border-radius: 8px; padding: 16px; text-align: center; border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .report-body .quality-card-value {{ font-size: 24px; font-weight: 700; color: #4361ee; margin-bottom: 8px; }}
        .report-body .quality-card-label {{ font-size: 14px; color: #666; }}
        .report-body .weight-note {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 8px 12px; margin: 10px 0; font-size: 13px; color: #856404; }}
        .report-body .chart-container {{ width: 100%; height: 400px; margin: 10px 0; border: 1px solid #ddd; border-radius: 6px; background: #fff; }}
        @media (max-width: 768px) {{ .report-body .quality-grid {{ grid-template-columns: repeat(2, 1fr); }} .report-body .chart-container {{ height: 300px; }} }}
        @media (max-width: 480px) {{ .report-body .quality-grid {{ grid-template-columns: 1fr; }} .report-body .chart-container {{ height: 250px; }} }}
    </style>
</head>
<body>
    <div class="report-body">
        <h1>数据分析报告</h1>
        <p>生成时间：{generated_at}</p>

        {''.join(body_parts)}

        <div class="footer">本报告由数据分析模块自动生成</div>
    </div>
    <script>
        var seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607'];

        // 为支持缩放的笛卡尔坐标系图表统一生成 dataZoom 配置
        function getDataZoom() {{
            return [
                {{ type: 'inside', xAxisIndex: [0], start: 0, end: 100 }},
                {{ type: 'slider', xAxisIndex: [0], start: 0, end: 100, bottom: 10, height: 24 }}
            ];
        }}

        function buildChartOption(type, data) {{
            switch (type) {{
                case 'histogram': {{
                    var hasSeries = data.series && data.series.length > 0;
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: hasSeries ? {{ top: 10 }} : undefined,
                        grid: {{ top: hasSeries ? 60 : 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.labels || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: {{ type: 'value', name: '频数' }},
                        series: hasSeries ? data.series.map(function(s, i) {{
                            return {{
                                name: s.name,
                                type: 'bar',
                                data: s.values || [],
                                itemStyle: {{ color: seriesColors[i % seriesColors.length] }},
                                barGap: 0,
                                barCategoryGap: '10%'
                            }};
                        }}) : [{{ type: 'bar', data: data.values || [], itemStyle: {{ color: '#4361ee' }} }}]
                    }};
                }}
                case 'scatter':
                    return {{
                        tooltip: {{ trigger: 'item' }},
                        grid: {{ top: 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'value' }},
                        yAxis: {{ type: 'value' }},
                        series: [{{
                            type: 'scatter',
                            data: (data.x || []).map(function(xi, i) {{ return [xi, (data.y || [])[i]]; }}),
                            symbolSize: 8,
                            itemStyle: {{ color: '#4361ee' }}
                        }}]
                    }};
                case 'boxplot': {{
                    var seriesData = (data.series || []).map(function(s) {{
                        var d = s.data || [];
                        return [d[0], d[1], d[2], d[3], d[4]];
                    }});
                    var outlierData = [];
                    (data.series || []).forEach(function(s, idx) {{
                        var outliers = (s.data || [])[5] || [];
                        outliers.forEach(function(val) {{ outlierData.push([idx, val]); }});
                    }});
                    return {{
                        tooltip: {{ trigger: 'item' }},
                        grid: {{ top: 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: (data.series || []).map(function(s) {{ return s.name; }}) }},
                        yAxis: {{ type: 'value' }},
                        series: [
                            {{ type: 'boxplot', data: seriesData, itemStyle: {{ color: '#4361ee' }} }},
                            {{ type: 'scatter', data: outlierData, symbolSize: 6, itemStyle: {{ color: '#e63946' }} }}
                        ]
                    }};
                }}
                case 'line': {{
                    var hasSeries = data.series && data.series.length > 0;
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: hasSeries ? {{ top: 10 }} : undefined,
                        grid: {{ top: hasSeries ? 60 : 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.labels || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: {{ type: 'value' }},
                        series: hasSeries ? data.series.map(function(s, i) {{
                            return {{
                                name: s.name,
                                type: 'line',
                                data: s.values || [],
                                smooth: true,
                                areaStyle: {{ color: seriesColors[i % seriesColors.length] + '30' }},
                                itemStyle: {{ color: seriesColors[i % seriesColors.length] }}
                            }};
                        }}) : [{{ type: 'line', data: data.values || [], smooth: true, itemStyle: {{ color: '#4361ee' }} }}]
                    }};
                }}
                case 'pie':
                    return {{
                        tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
                        legend: {{ top: 10 }},
                        series: [{{
                            type: 'pie',
                            radius: ['40%', '70%'],
                            data: (data.labels || []).map(function(label, i) {{
                                return {{ name: label, value: (data.values || [])[i] }};
                            }}),
                            emphasis: {{ itemStyle: {{ shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' }} }}
                        }}]
                    }};
                case 'heatmap': {{
                    var labels = data.labels || [];
                    var matrix = data.data || [];
                    var heatData = [];
                    var maxVal = 1;
                    for (var i = 0; i < matrix.length; i++) {{
                        for (var j = 0; j < (matrix[i]?.length || 0); j++) {{
                            heatData.push([j, i, matrix[i][j]]);
                            maxVal = Math.max(maxVal, Math.abs(matrix[i][j]));
                        }}
                    }}
                    return {{
                        tooltip: {{ position: 'top' }},
                        grid: {{ top: 30, left: 80, right: 120, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: labels, axisLabel: {{ rotate: 45 }} }},
                        yAxis: {{ type: 'category', data: labels }},
                        visualMap: {{
                            min: -maxVal, max: maxVal, calculable: true,
                            orient: 'vertical', right: 10, top: 'center'
                        }},
                        series: [{{ type: 'heatmap', data: heatData, label: {{ show: true, formatter: function(p) {{ return p.value[2].toFixed(2); }} }} }}]
                    }};
                }}
                case 'bar': {{
                    var hasSeries = data.series && data.series.length > 0;
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: hasSeries ? {{ top: 10 }} : undefined,
                        grid: {{ top: hasSeries ? 60 : 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.labels || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: {{ type: 'value' }},
                        series: hasSeries ? data.series.map(function(s, i) {{
                            return {{
                                name: s.name,
                                type: 'bar',
                                data: s.values || [],
                                itemStyle: {{ color: seriesColors[i % seriesColors.length] }}
                            }};
                        }}) : [{{ type: 'bar', data: data.values || [], itemStyle: {{ color: '#4361ee' }} }}]
                    }};
                }}
                case 'stacked_bar':
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: {{ top: 10 }},
                        grid: {{ top: 60, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.categories || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: {{ type: 'value' }},
                        series: (data.series || []).map(function(s, i) {{
                            return {{
                                name: s.name, type: 'bar', stack: 'total',
                                data: s.data || [],
                                emphasis: {{ focus: 'series' }}
                            }};
                        }})
                    }};
                case 'area': {{
                    var hasSeries = data.series && data.series.length > 0;
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: hasSeries ? {{ top: 10 }} : undefined,
                        grid: {{ top: hasSeries ? 60 : 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.x || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: {{ type: 'value' }},
                        series: hasSeries ? data.series.map(function(s, i) {{
                            return {{
                                name: s.name, type: 'line',
                                data: s.values || [], smooth: true,
                                areaStyle: {{ color: seriesColors[i % seriesColors.length] + '30' }},
                                itemStyle: {{ color: seriesColors[i % seriesColors.length] }}
                            }};
                        }}) : [{{ type: 'line', data: data.y || [], smooth: true, areaStyle: {{ color: 'rgba(67,97,238,0.3)' }}, itemStyle: {{ color: '#4361ee' }} }}]
                    }};
                }}
                case 'kde': {{
                    var hasSeries = data.series && data.series.length > 0;
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: hasSeries ? {{ top: 10 }} : undefined,
                        grid: {{ top: hasSeries ? 60 : 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'value' }},
                        yAxis: {{ type: 'value', name: '密度' }},
                        series: hasSeries ? data.series.map(function(s, i) {{
                            return {{
                                name: s.name, type: 'line',
                                data: (data.x || []).map(function(xi, idx) {{ return [xi, (s.values || [])[idx]]; }}),
                                smooth: true,
                                areaStyle: {{ color: seriesColors[i % seriesColors.length] + '30' }},
                                itemStyle: {{ color: seriesColors[i % seriesColors.length] }}
                            }};
                        }}) : [{{ type: 'line', data: (data.x || []).map(function(xi, i) {{ return [xi, (data.y || [])[i]]; }}), smooth: true, areaStyle: {{ color: 'rgba(67,97,238,0.3)' }}, itemStyle: {{ color: '#4361ee' }} }}]
                    }};
                }}
                case 'qq': {{
                    var hasSeries = data.series && data.series.length > 0;
                    var allVals = [];
                    if (hasSeries) {{
                        data.series.forEach(function(s) {{ allVals = allVals.concat(s.theoretical || [], s.sample || []); }});
                    }} else {{
                        allVals = (data.theoretical || []).concat(data.sample || []);
                    }}
                    var minVal = allVals.length > 0 ? Math.min.apply(Math, allVals) : 0;
                    var maxVal = allVals.length > 0 ? Math.max.apply(Math, allVals) : 1;
                    var series = [];
                    if (hasSeries) {{
                        data.series.forEach(function(s, i) {{
                            series.push({{
                                name: s.name, type: 'scatter',
                                data: (s.theoretical || []).map(function(t, idx) {{ return [t, (s.sample || [])[idx]]; }}),
                                symbolSize: 6,
                                itemStyle: {{ color: seriesColors[i % seriesColors.length] }}
                            }});
                        }});
                    }} else {{
                        series.push({{
                            type: 'scatter',
                            data: (data.theoretical || []).map(function(t, i) {{ return [t, (data.sample || [])[i]]; }}),
                            symbolSize: 6,
                            itemStyle: {{ color: '#4361ee' }}
                        }});
                    }}
                    series.push({{ type: 'line', data: [[minVal, minVal], [maxVal, maxVal]], symbol: 'none', lineStyle: {{ type: 'dashed', color: '#999' }} }});
                    return {{
                        tooltip: {{ trigger: 'item' }},
                        legend: hasSeries ? {{ top: 10 }} : undefined,
                        grid: {{ top: hasSeries ? 60 : 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'value', name: '理论分位数', min: minVal, max: maxVal }},
                        yAxis: {{ type: 'value', name: '样本分位数', min: minVal, max: maxVal }},
                        series: series
                    }};
                }}
                case 'bubble':
                    return {{
                        tooltip: {{ trigger: 'item' }},
                        grid: {{ top: 30, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'value' }},
                        yAxis: {{ type: 'value' }},
                        series: [{{
                            type: 'scatter',
                            data: (data.x || []).map(function(xi, i) {{ return [xi, (data.y || [])[i], (data.size || [])[i]]; }}),
                            symbolSize: function(val) {{ return Math.max(5, val[2] || 10); }},
                            itemStyle: {{ color: '#4361ee', opacity: 0.7 }}
                        }}]
                    }};
                case 'multi_line':
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: {{ top: 10 }},
                        grid: {{ top: 60, left: 60, right: 30, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.x || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: {{ type: 'value' }},
                        series: (data.series || []).map(function(s) {{
                            return {{ name: s.name, type: 'line', data: s.data || [], smooth: true }};
                        }})
                    }};
                case 'dual_axis':
                    return {{
                        tooltip: {{ trigger: 'axis' }},
                        legend: {{ top: 10 }},
                        grid: {{ top: 60, left: 60, right: 80, bottom: 80 }},
                        dataZoom: getDataZoom(),
                        xAxis: {{ type: 'category', data: data.x || [], axisLabel: {{ rotate: 30 }} }},
                        yAxis: [{{ type: 'value', name: data.y1_name || 'Y1', position: 'left' }}, {{ type: 'value', name: data.y2_name || 'Y2', position: 'right' }}],
                        series: [{{ name: data.y1_name || 'Y1', type: 'bar', data: data.y1 || [], itemStyle: {{ color: '#4361ee' }} }}, {{ name: data.y2_name || 'Y2', type: 'line', data: data.y2 || [], yAxisIndex: 1, smooth: true, itemStyle: {{ color: '#e63946' }} }}]
                    }};
                case 'radar': {{
                    var indicators = (data.indicators || []).map(function(name) {{ return {{ name: name, max: 100 }}; }});
                    return {{
                        tooltip: {{}},
                        legend: {{ top: 10 }},
                        radar: {{ indicator: indicators }},
                        series: [{{
                            type: 'radar',
                            data: (data.series || []).map(function(s) {{
                                return {{ name: s.name, value: s.value || s.data || [] }};
                            }})
                        }}]
                    }};
                }}
                case 'table_heatmap': {{
                    var rowLabels = data.rows || [];
                    var colLabels = data.columns || [];
                    var matrix = data.data || [];
                    var heatData = [];
                    var maxVal = 0;
                    for (var i = 0; i < matrix.length; i++) {{
                        for (var j = 0; j < (matrix[i]?.length || 0); j++) {{
                            var val = matrix[i][j];
                            if (val !== null && val !== undefined) {{
                                heatData.push([j, i, val]);
                                maxVal = Math.max(maxVal, Math.abs(val));
                            }}
                        }}
                    }}
                    return {{
                        tooltip: {{ position: 'top' }},
                        grid: {{ top: 30, left: 100, right: 30, bottom: 100 }},
                        xAxis: {{ type: 'category', data: colLabels, axisLabel: {{ rotate: 45 }} }},
                        yAxis: {{ type: 'category', data: rowLabels }},
                        visualMap: {{
                            min: 0, max: maxVal || 1, calculable: true,
                            orient: 'horizontal', left: 'center', bottom: 10
                        }},
                        series: [{{ type: 'heatmap', data: heatData, label: {{ show: true }} }}]
                    }};
                }}
                default:
                    return {{}};
            }}
        }}
        
        var chartsData = {json.dumps(charts_data)};
        
        window.addEventListener('load', function() {{
            chartsData.forEach(function(chart, index) {{
                var container = document.getElementById('chart-container-' + index);
                if (container) {{
                    var chartInstance = echarts.init(container);
                    var option = buildChartOption(chart.type, chart.data);
                    chartInstance.setOption(option);
                    window.addEventListener('resize', function() {{ chartInstance.resize(); }});
                }}
            }});
        }});
    </script>
</body>
</html>"""

    # 构建动态数据
    dynamic_data = {
        "config": {
            "title": "数据分析报告",
            "generated_at": generated_at,
            "sections": sections
        },
        "data_preview": None,
        "quality": None,
        "column_info": None,
        "numeric_stats": None,
        "categorical_stats": None,
        "charts": None
    }

    if "data_preview" in section_set:
        sample_rows = options.get("dataPreview", {}).get("sampleRows", 5)
        if sample_rows > 0:
            preview_df = df.head(sample_rows)
            dynamic_data["data_preview"] = {
                "columns": preview_df.columns.tolist(),
                "rows": preview_df.fillna("").astype(str).to_dict('records')
            }

    if "quality" in section_set:
        total_cells = df.shape[0] * df.shape[1]
        missing_cells = int(df.isna().sum().sum())
        missing_rate = round(missing_cells / total_cells * 100, 2) if total_cells > 0 else 0
        inf_count = 0
        for col in numeric_cols:
            col_numeric = to_numeric_if_possible(df[col])
            inf_count += int(np.isinf(col_numeric).sum())
        duplicate_rows = int(df.duplicated().sum())
        constant_cols = [col for col in df.columns if df[col].nunique() <= 1]
        missing_cols = [col for col in df.columns if df[col].isna().any()]
        
        # 数据质量概览：与前端选项和 HTML 报告保持一致的指标映射
        metrics = options.get("quality", {}).get("metrics", [
            "missing_rate", "missing_columns", "infinite_columns", "duplicate_rows",
            "constant_columns", "row_count", "column_count", "numeric_count", "categorical_count"
        ])
        metric_map = {
            "missing_rate": ("总体缺失率", f"{missing_rate}%"),
            "missing_columns": ("含缺失值列数", str(len(missing_cols))),
            "infinite_columns": ("含无穷大列数", str(inf_count)),
            "duplicate_rows": ("重复行数", str(duplicate_rows)),
            "constant_columns": ("常量列数", str(len(constant_cols))),
            "row_count": ("总行数", str(df.shape[0])),
            "column_count": ("总列数", str(df.shape[1])),
            "numeric_count": ("数值列数", str(len(numeric_cols))),
            "categorical_count": ("分类列数", str(len(categorical_cols))),
        }
        quality_metrics = []
        for metric_key in metrics:
            if metric_key in metric_map:
                label, value = metric_map[metric_key]
                quality_metrics.append({"label": label, "value": value})
        dynamic_data["quality"] = {"metrics": quality_metrics}

    if "column_info" in section_set:
        columns_info = []
        for col in df.columns:
            col_data = to_numeric_if_possible(df[col]) if col in numeric_cols else df[col]
            missing_count = int(col_data.isna().sum())
            missing_rate_val = round(missing_count / len(df) * 100, 2) if len(df) > 0 else 0
            col_type = "数值" if col in numeric_cols else "分类"
            unique_count = int(col_data.nunique(dropna=True))
            non_null_count = int(len(df) - missing_count)
            unique_ratio = unique_count / non_null_count if non_null_count > 0 else 0
            completeness_level = "高" if missing_rate_val < 10 else ("中" if missing_rate_val < 50 else "低")
            uniqueness_level = "高" if unique_ratio > 0.9 else ("中" if unique_ratio > 0.5 else "低")
            completeness_score = (1 - missing_rate_val / 100) * 60
            uniqueness_score = unique_ratio * 20
            type_score = 20 if col_type == "数值" else 15
            quality_score = max(0, min(100, round(completeness_score + uniqueness_score + type_score)))
            columns_info.append({
                "name": col,
                "type": col_type,
                "missing_count": missing_count,
                "missing_rate": missing_rate_val,
                "completeness": completeness_level,
                "uniqueness": uniqueness_level,
                "quality_score": quality_score
            })
        dynamic_data["column_info"] = columns_info

    if "numeric_stats" in section_set and numeric_stats:
        # 转换为数组结构，便于动态报告中的 el-table 渲染
        dynamic_data["numeric_stats"] = [
            {"column": col, **stat} for col, stat in numeric_stats.items()
        ]

    if "categorical_stats" in section_set and categorical_stats:
        # 转换为数组结构，便于动态报告中的 el-table 渲染
        dynamic_data["categorical_stats"] = [
            {"column": col, **stat} for col, stat in categorical_stats.items()
        ]

    if "charts" in section_set and charts:
        dynamic_charts = []
        for chart in charts:
            # 前端 reportCharts 使用字段名 type，这里兼容 chart_type 别名
            chart_type = chart.get("type") or chart.get("chart_type")
            params = chart.get("params", {})
            if not chart_type:
                continue
            try:
                chart_data = _get_chart_data(df, chart_type, params)
                # 使用与前端 buildChartTitle 一致的标题生成逻辑，包含列关系信息
                chart_title = _build_chart_title(chart_type, params, chart.get("title"))
                dynamic_charts.append({
                    "title": chart_title,
                    "chart_type": chart_type,
                    "data": chart_data,
                    "params": params
                })
            except Exception:
                pass
        dynamic_data["charts"] = dynamic_charts

    return report_html, dynamic_data


# ========== API 端点 ==========

@router.post("/upload", response_model=DatasetResponse)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传文件到数据分析模块，artifact_type=raw_data, module_source=data_analysis"""
    import time as _time
    start_time = _time.time()
    validate_upload_file(file)

    name = clean_dataset_name(file.filename)

    # 埋点：创建上传任务记录
    task_record = create_task_record(
        db=db,
        task_type="upload",
        user_id=current_user.id,
        params={"filename": name, "module_source": "data_analysis", "artifact_type": "raw_data"}
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
            db=db, record_id=task_record.id, status="failed",
            error_message=str(e), execution_time=execution_time,
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
        module_source="data_analysis",
        module_label=MODULE_LABEL_MAP.get("data_analysis", "数据分析"),
        artifact_type="raw_data",
        user_id=current_user.id
    )
    db.add(new_dataset)
    db.commit()
    db.refresh(new_dataset)

    execution_time = int((_time.time() - start_time) * 1000)
    update_task_record(
        db=db, record_id=task_record.id, status="success",
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


@router.get("/raw-data", response_model=list[DatasetResponse])
async def get_raw_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据分析模块的数据列表"""
    datasets = db.query(Dataset).filter(
        Dataset.module_source == "data_analysis",
        Dataset.artifact_type == "raw_data",
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).all()
    return datasets


@router.get("/{id}/data")
async def get_data_preview(
    id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    use_remote: Optional[bool] = Query(None, description="是否使用远程数据"),
    connection_id: Optional[int] = Query(None, description="远程连接ID"),
    table_name: Optional[str] = Query(None, description="远程表名"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据预览（分页，支持远程数据源）"""
    # 构造远程配置
    remote_config = None
    if use_remote and connection_id and table_name:
        remote_config = {"use_remote": True, "connection_id": connection_id, "table_name": table_name}

    data_service = DataService(db)

    if remote_config:
        # 远程模式：加载全量数据后分页
        df, dataset = data_service.load_module_data(
            dataset_id=None,
            remote_config=remote_config,
            user_id=current_user.id
        )
        total = len(df)
        start = (page - 1) * page_size
        page_df = df.iloc[start:start + page_size]
    else:
        # 本地模式：使用分页加载
        dataset = get_dataset_or_404(db, id, current_user.id)
        page_df, total = data_service.load_dataset_page(id, page, page_size)

    columns = list(page_df.columns)
    rows = page_df.replace({np.nan: None}).to_dict('records')

    return {
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size)
    }


@router.get("/{id}/statistics")
async def get_statistics(
    id: int,
    use_remote: Optional[bool] = Query(None, description="是否使用远程数据"),
    connection_id: Optional[int] = Query(None, description="远程连接ID"),
    table_name: Optional[str] = Query(None, description="远程表名"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取统计摘要（支持远程数据源）

    远程模式优先 SQL 下推（基础统计在 DB 侧聚合），失败回退采样计算。
    大表场景下高级统计（分位数/偏度/峰度）为 None，仅返回基础统计。
    """
    # 构造远程配置
    remote_config = None
    if use_remote and connection_id and table_name:
        remote_config = {"use_remote": True, "connection_id": connection_id, "table_name": table_name}

    is_remote = remote_config and remote_config.get("use_remote")

    data_service = DataService(db)

    # 远程模式：优先 SQL 下推，避免大表全量加载
    # 存在特征工程工作副本时跳过下推（工作副本含动态新增列，数据库聚合看不到）
    if is_remote and not data_service.has_remote_workcopy(current_user.id, connection_id, table_name):
        try:
            return _compute_remote_statistics(
                data_service, connection_id, table_name, current_user.id
            )
        except Exception as e:
            # SQL 下推失败，回退到采样计算
            print(f"[statistics] SQL 下推失败，回退采样: {e}")
            import traceback as _tb
            _tb.print_exc()

    # 本地数据集 + ClickHouse 已同步：CH 全量聚合优先（大表加速），失败回退 pandas
    if not is_remote:
        try:
            get_dataset_or_404(db, id, current_user.id)
        except HTTPException:
            raise
        _reg = _ch_synced_registry(id)
        if _reg:
            try:
                _schema = _parse_ch_schema(_reg)
                if _schema:
                    return clickhouse_service.compute_statistics(id, _schema)
            except Exception as _e:
                print(f"[statistics] ClickHouse 聚合失败，回退 pandas: {_e}")

    # 本地模式 或 远程下推失败回退：加载 df 内存计算
    df, dataset = data_service.load_module_data(
        dataset_id=id if not is_remote else None,
        remote_config=remote_config,
        user_id=current_user.id
    )

    if not is_remote and dataset:
        if dataset.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="数据集不存在")

    return {
        "numeric_stats": compute_numeric_stats(df),
        "categorical_stats": _compute_categorical_stats(df),
        "basic_info": _compute_basic_info(df)
    }


@router.get("/{id}/quality")
async def get_data_quality(
    id: int,
    use_remote: Optional[bool] = Query(None, description="是否使用远程数据"),
    connection_id: Optional[int] = Query(None, description="远程连接ID"),
    table_name: Optional[str] = Query(None, description="远程表名"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据质量检测结果（支持远程数据源）

    远程模式优先 SQL 下推（缺失/常量/重复全在 DB 侧聚合），失败回退采样计算。
    """
    # 构造远程配置
    remote_config = None
    if use_remote and connection_id and table_name:
        remote_config = {"use_remote": True, "connection_id": connection_id, "table_name": table_name}

    is_remote = remote_config and remote_config.get("use_remote")

    data_service = DataService(db)

    # 远程模式：优先 SQL 下推，避免大表全量加载
    # 存在特征工程工作副本时跳过下推（工作副本含动态新增列，数据库聚合看不到）
    if is_remote and not data_service.has_remote_workcopy(current_user.id, connection_id, table_name):
        try:
            return _compute_remote_quality(
                data_service, connection_id, table_name, current_user.id
            )
        except Exception as e:
            # SQL 下推失败（DB 不可达/语法不兼容），回退到采样计算
            print(f"[quality] SQL 下推失败，回退采样: {e}")

    # 本地数据集 + ClickHouse 已同步：CH 全量质量检测优先（大表加速），失败回退 pandas
    if not is_remote:
        try:
            get_dataset_or_404(db, id, current_user.id)
        except HTTPException:
            raise
        _reg = _ch_synced_registry(id)
        if _reg:
            try:
                _schema = _parse_ch_schema(_reg)
                if _schema:
                    return clickhouse_service.compute_quality(id, _schema)
            except Exception as _e:
                print(f"[quality] ClickHouse 质量检测失败，回退 pandas: {_e}")

    # 本地模式 或 远程下推失败回退：加载 df 内存计算
    df, dataset = data_service.load_module_data(
        dataset_id=id if not is_remote else None,
        remote_config=remote_config,
        user_id=current_user.id
    )

    if not is_remote and dataset:
        if dataset.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="数据集不存在")

    # 调用通用工具函数检测数据质量
    quality = check_data_quality(df)

    # 计算总体缺失率：全部缺失单元格数 / 总单元格数
    total_cells = df.shape[0] * df.shape[1]
    total_missing = int(df.isna().sum().sum())
    overall_missing_rate = round(total_missing / total_cells * 100, 2) if total_cells > 0 else 0

    return {
        "overall_missing_rate": overall_missing_rate,
        "missing_columns_count": len(quality['nan_columns']),
        "infinite_columns": quality['infinite_columns'],
        "duplicate_rows": quality['duplicate_rows'],
        "constant_columns": quality['constant_columns']
    }


@router.post("/{id}/chart")
async def get_chart_data(
    id: int,
    body: ChartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取图表数据（支持远程数据源）"""
    # 确定数据源：body 中的 remote / dataset_id 优先，否则使用路径参数 id
    dataset_id = body.dataset_id or id
    remote_config = body.remote
    is_remote = remote_config and remote_config.get("use_remote")

    # 本地数据集 + ClickHouse 已同步：聚合型图表 CH 全量计算优先（大表加速），失败回退 pandas
    if not is_remote:
        try:
            get_dataset_or_404(db, dataset_id, current_user.id)
        except HTTPException:
            raise
        _reg = _ch_synced_registry(dataset_id)
        if _reg:
            try:
                _schema = _parse_ch_schema(_reg)
                if _schema and _ch_can_chart(body.chart_type, body.params, _schema):
                    return _clean_json_data(
                        clickhouse_service.compute_chart_agg(
                            dataset_id, body.chart_type, body.params, _schema
                        )
                    )
            except Exception as _e:
                print(f"[chart] ClickHouse 图表计算失败，回退 pandas: {_e}")

    data_service = DataService(db)
    df, dataset = data_service.load_module_data(
        dataset_id=dataset_id,
        remote_config=remote_config,
        user_id=current_user.id
    )

    if not is_remote and dataset:
        # 本地模式：验证数据集归属
        if dataset.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="数据集不存在")

    return _get_chart_data(df, body.chart_type, body.params)


@router.get("/{id}/chart-recommendations")
async def get_chart_recommendations(
    id: int,
    columns: Optional[str] = Query(None, description="指定列名，逗号分隔"),
    chart_type: Optional[str] = Query(None, description="指定图表类型"),
    use_remote: Optional[bool] = Query(None, description="是否使用远程数据"),
    connection_id: Optional[int] = Query(None, description="远程连接ID"),
    table_name: Optional[str] = Query(None, description="远程表名"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取图表智能推荐。支持传入指定列或图表类型进行过滤。

    远程模式优先 SQL 下推（列基数/缺失率/数值 min-max 在 DB 侧聚合），
    失败回退到采样计算。大表场景下 outlier_rate 为 None，不影响主流推荐。
    """
    try:
        # 构造远程配置
        remote_config = None
        if use_remote and connection_id and table_name:
            remote_config = {"use_remote": True, "connection_id": connection_id, "table_name": table_name}

        is_remote = remote_config and remote_config.get("use_remote")

        # 解析逗号分隔的列名
        column_list = None
        if columns:
            column_list = [c.strip() for c in columns.split(",") if c.strip()]

        data_service = DataService(db)

        # 远程模式：优先 SQL 下推，避免大表全量加载
        # 存在特征工程工作副本时跳过下推（工作副本含动态新增列，数据库聚合看不到）
        if is_remote and not data_service.has_remote_workcopy(current_user.id, connection_id, table_name):
            try:
                result = _compute_remote_recommendations(
                    data_service, connection_id, table_name,
                    current_user.id, columns=column_list, chart_type=chart_type
                )
                return _clean_json_data(result)
            except Exception as e:
                # SQL 下推失败（DB 不可达/语法不兼容），回退到采样计算
                print(f"[chart-recommendations] SQL 下推失败，回退采样: {e}")

        # 本地数据集 + ClickHouse 已同步：CH 列画像全量聚合优先（大表加速），失败回退 pandas
        if not is_remote:
            try:
                get_dataset_or_404(db, id, current_user.id)
            except HTTPException:
                raise
            _reg = _ch_synced_registry(id)
            if _reg:
                try:
                    _schema = _parse_ch_schema(_reg)
                    if _schema:
                        return _clean_json_data(
                            _compute_ch_recommendations(
                                clickhouse_service, id, _schema, column_list, chart_type
                            )
                        )
                except Exception as _e:
                    print(f"[chart-recommendations] ClickHouse 计算失败，回退 pandas: {_e}")

        # 本地模式 或 远程下推失败回退：加载 df 内存计算
        df, dataset = data_service.load_module_data(
            dataset_id=id if not is_remote else None,
            remote_config=remote_config,
            user_id=current_user.id
        )

        if not is_remote and dataset:
            if dataset.user_id != current_user.id:
                raise HTTPException(status_code=404, detail="数据集不存在")

        result = _get_chart_recommendations(df, columns=column_list, chart_type=chart_type)
        cleaned_result = _clean_json_data(result)

        return cleaned_result
    except Exception as e:
        import traceback
        print(f"chart-recommendations error: {str(e)}")
        print(f"traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取图表推荐失败: {str(e)}")


@router.get("/{id}/chart-export")
async def export_chart(
    id: int,
    chart_type: str = Query(..., description="图表类型"),
    column: Optional[str] = Query(None, description="单列参数"),
    x_column: Optional[str] = Query(None, description="x 轴列"),
    y_column: Optional[str] = Query(None, description="y 轴列"),
    y_columns: Optional[str] = Query(None, description="y 轴多列参数，逗号分隔（多选）"),
    y1_column: Optional[str] = Query(None, description="y1 轴列（双 Y 轴图用）"),
    y2_column: Optional[str] = Query(None, description="y2 轴列（双 Y 轴图用）"),
    size_column: Optional[str] = Query(None, description="大小列（气泡图用）"),
    value_column: Optional[str] = Query(None, description="值列（表格热力图透视用）"),
    columns: Optional[str] = Query(None, description="多列参数，逗号分隔"),
    bins: Optional[int] = Query(None, description="直方图分箱数"),
    top_n: Optional[int] = Query(None, alias="topN", description="Top N 限制（柱状图、饼图）"),
    show_data_labels: Optional[bool] = Query(None, description="是否显示数据标签"),
    show_legend: Optional[bool] = Query(None, description="是否显示图例"),
    use_remote: Optional[bool] = Query(None, description="是否使用远程数据"),
    connection_id: Optional[int] = Query(None, description="远程连接ID"),
    table_name: Optional[str] = Query(None, description="远程表名"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """导出图表为 PNG 图片。
    兼容新旧参数格式：支持单列(column)、多列(columns)、双列(x_column+y_column/y_columns)等。"""
    # 构造远程配置
    remote_config = None
    if use_remote and connection_id and table_name:
        remote_config = {"use_remote": True, "connection_id": connection_id, "table_name": table_name}

    data_service = DataService(db)
    df, dataset = data_service.load_module_data(
        dataset_id=id if not remote_config else None,
        remote_config=remote_config,
        user_id=current_user.id
    )

    is_remote = remote_config and remote_config.get("use_remote")
    if not is_remote and dataset:
        if dataset.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="数据集不存在")

    # 构建 params 字典（仅放入非空参数，便于函数内做默认值处理）
    params = {}
    if column is not None:
        params["column"] = column
    if x_column is not None:
        params["x_column"] = x_column
    if y_column is not None:
        params["y_column"] = y_column
    if y_columns is not None:
        params["y_columns"] = [c.strip() for c in y_columns.split(",") if c.strip()]
    if y1_column is not None:
        params["y1_column"] = y1_column
    if y2_column is not None:
        params["y2_column"] = y2_column
    if size_column is not None:
        params["size_column"] = size_column
    if value_column is not None:
        params["value_column"] = value_column
    if columns is not None:
        params["columns"] = [c.strip() for c in columns.split(",") if c.strip()]
    if bins is not None:
        params["bins"] = bins
    if top_n is not None:
        params["topN"] = top_n
    if show_data_labels is not None:
        params["show_data_labels"] = show_data_labels
    if show_legend is not None:
        params["show_legend"] = show_legend

    buf = _generate_chart_image(df, chart_type, params)

    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=chart_{chart_type}.png"}
    )





@task_manager.register_task
def _execute_generate_report(task_record_id: int, user_id: int, dataset_id: int, config: dict, remote_config: dict = None):
    """生成分析报告核心执行函数（同步/异步共用入口，支持远程数据源）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载(20%)：加载数据集
    - 生成报告(50%)：渲染报告 HTML（含图表，计算密集型）
    - 结果汇总(80%)：报告渲染完成，准备存储
    - 完成(100%)：报告生成完成

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式可为 None）
        config: 原请求 body 的 dict 表示（含 sections/charts/options），可为 None
        remote_config: 远程数据源配置，可为 None

    Returns:
        报告预览字典（与原同步接口返回结构保持一致）
    """
    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    is_remote = remote_config and remote_config.get("use_remote") if remote_config else False

    try:
        # ===== 阶段1：数据加载（20%） =====
        update_task_progress(db, task_record_id, "数据加载", 20, "正在加载数据")

        data_service = DataService(db)
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id if not is_remote else None,
            remote_config=remote_config,
            user_id=user_id
        )

        # 提取可选的请求参数（config 为原 body 的 dict 表示，body 可为 None）
        sections = config.get("sections") if config else None
        charts = config.get("charts") if config else None
        options = config.get("options") if config else None

        # ===== 阶段2：生成报告（50%） =====
        update_task_progress(db, task_record_id, "生成报告", 50, "正在生成分析报告")

        report_html, dynamic_data = _build_analysis_report(df, sections=sections, charts=charts, options=options)

        # ===== 阶段3：结果汇总（80%） =====
        update_task_progress(db, task_record_id, "结果汇总", 80, "报告渲染完成，正在存储结果")

        # ===== 阶段4：完成（100%） =====
        update_task_progress(db, task_record_id, "完成", 100, "报告生成完成")

        # 更新任务记录为成功
        # 异步任务成功后，前端通过轮询获取 result_summary 中的 preview_html 渲染到 iframe
        # 同步任务通过函数返回值获取 preview_html，不走 result_summary
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            result_summary={
                "operation": "generate_report",
                "preview_html": report_html,
                "dynamic_data": dynamic_data,
                "report_html_length": len(report_html),
                "charts_count": len(charts) if charts else 0,
                "row_count": len(df),
                "column_count": len(df.columns),
            },
            execution_time=execution_time
        )

        return {"preview_html": report_html, "dynamic_data": dynamic_data}

    except HTTPException:
        # 参数/数据校验失败，直接传播异常
        # 同步调用时 FastAPI 会将 HTTPException 转为对应 HTTP 状态码
        # 异步调用时 Celery 会记录任务失败，前端通过轮询 task_record 看到 failed 状态
        raise
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"报告生成超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
            execution_time=execution_time,
            failure_category="timeout"
        )
        raise
    except Exception as e:
        # 未预期的系统异常（报告渲染失败、数据加载失败等）
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"生成报告失败: {str(e)}",
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise
    finally:
        # Celery Worker 是独立进程，必须显式关闭 db 会话，避免连接泄漏
        db.close()


@router.post("/{id}/report")
async def generate_analysis_report(
    id: int,
    body: Optional[ReportRequest] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """生成数据分析报告（HTML）- 预览模式，不自动保存

    智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
    报告生成涉及图表渲染，是计算密集型操作，大数据集必须异步执行避免阻塞请求
    支持远程数据源（通过 body.remote 传入）
    """
    # 确定数据源：body 中的 remote / dataset_id 优先，否则使用路径参数 id
    remote_config = body.remote if body else None
    is_remote = remote_config and remote_config.get("use_remote")
    dataset_id = (body.dataset_id if body else None) or id

    # 快速校验数据集归属（不加载全量数据，避免大数据集时阻塞）
    # 远程模式：跳过本地数据集校验
    if not is_remote:
        dataset = get_dataset_or_404(db, dataset_id, current_user.id)
        dataset_name = dataset.name
        row_count = dataset.row_count or 0
    else:
        dataset = None
        dataset_name = remote_config.get("table_name", "远程表")
        row_count = 0  # 远程模式：行数未知，先设为 0（后续加载时获取）

    # 埋点：创建任务记录（status=running）
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="data_analysis",
        user_id=current_user.id,
        dataset_id=dataset_id if not is_remote else None,
        params={
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "generate_report",
            "sections": body.sections if body else None,
            "charts_count": len(body.charts) if body and body.charts else 0,
            # 完整配置：供任务调度器激活 pending 任务 / 失败重试时重建执行参数（修复）
            "config": body.dict() if body else None
        }
    )

    # 准备 config：将 body 转为 dict 传给 _execute_generate_report（body 可为 None）
    config = body.dict() if body else None

    # 远程模式：跳过异步分发，直接同步执行
    if is_remote:
        return _execute_generate_report(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            remote_config=remote_config
        )

    # 智能异步分发：≥1万行异步提交到 Celery，<1万行同步执行
    # 阈值与 cleaning/feature_engineering/ml 保持一致（ASYNC_THRESHOLD=settings.ASYNC_THRESHOLD）
    if row_count >= settings.ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message="Celery 不可用，无法处理大数据集报告生成，请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集报告生成，请启动 Celery 服务或使用小数据集"
            )

        # 任务排队机制：检查用户队列容量，决定立即执行还是进入等待队列
        try:
            can_run_now, queue_msg = check_task_queue_capacity(
                db, current_user.id, exclude_task_id=task_record.id
            )
        except HTTPException as queue_err:
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message=str(queue_err.detail),
                execution_time=execution_time,
                failure_category="param_error"
            )
            raise queue_err

        if can_run_now:
            # 立即执行：异步提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            task_result = task_manager.run_task(
                _execute_generate_report,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                config=config,
                remote_config=None,
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
                "message": "报告生成任务已提交，请在右上角任务面板查看进度",
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
                "message": f"分析报告生成任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 同步执行
    return _execute_generate_report(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        config=config
    )


@router.post("/{id}/report/save")
async def save_analysis_report(
    id: int,
    body: SaveReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """保存数据分析报告到数据管理，写入文件并创建 Dataset 记录

    支持两种模式：
    - 本地模式：id 为数据集ID，通过 get_dataset_or_404 校验归属权
    - 远程模式：body.remote.use_remote=True，id 可为0，不依赖本地数据集
    """
    # 判断是否远程模式
    remote_config = body.remote
    is_remote = remote_config and remote_config.get("use_remote")

    # 本地模式需要校验数据集存在性和归属权
    dataset = None
    if not is_remote:
        dataset = get_dataset_or_404(db, id, current_user.id)
        parent_id = dataset.id
        root_dataset_id = getattr(dataset, 'root_dataset_id', None) or dataset.id
        source_name = dataset.name or "数据分析报告"
        task_dataset_id = id
    else:
        # 远程模式：parent_id 为 None（血缘通过 connection_id 维护）
        parent_id = None
        root_dataset_id = None
        source_name = remote_config.get("table_name") or "远程数据分析报告"
        task_dataset_id = None

    # 埋点：创建任务记录（status=running）
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="data_analysis",
        user_id=current_user.id,
        dataset_id=task_dataset_id,
        params={
            "dataset_name": source_name,
            "operation": "save_report",
            "report_html_length": len(body.report_html),
            "is_remote": bool(is_remote)
        }
    )

    try:
        report_html = body.report_html
        report_data = body.report_data

        # 产物命名：保留源名（去原扩展名 + 真实内容后缀 .html），不拼时间戳，靠 #id/颜色区分
        file_name = re.sub(r'[\\/:*?"<>|]', '_', build_product_name(source_name, "html"))

        report_bytes = report_html.encode('utf-8')
        object_name = f"reports/user_{current_user.id}/{file_name}"
        file_path = storage_manager.save_bytes(object_name, report_bytes)
        file_size = len(report_bytes)

        report_content = json.dumps({
            "type": "analysis_report",
            "html": report_html,
            "dynamic_data": report_data or {}
        }, ensure_ascii=False)

        new_dataset = Dataset(
            name=file_name,
            file_path=file_path,
            file_size=file_size,
            report_content=report_content,
            module_source="data_analysis",
            module_label=MODULE_LABEL_MAP.get("data_analysis", "数据分析"),
            artifact_type="analysis_report",
            parent_id=parent_id,
            root_dataset_id=root_dataset_id,
            user_id=current_user.id,
            # 远程来源血缘字段：设置后 lineage 接口可显示远程数据源虚拟根节点
            connection_id=remote_config.get("connection_id") if is_remote else None,
            table_name=remote_config.get("table_name") if is_remote else None,
            root_connection_id=remote_config.get("connection_id") if is_remote else None,
            source_type="derived" if is_remote else None
        )
        db.add(new_dataset)
        db.commit()
        db.refresh(new_dataset)

        clear_user_dataset_cache(current_user.id)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="success",
            dataset_id=new_dataset.id,
            result_summary={
                "operation": "save_report",
                "report_id": new_dataset.id,
                "report_name": new_dataset.name,
                "report_html_length": len(report_html),
                "file_size": file_size,
                "new_dataset_id": new_dataset.id,
                "new_dataset_name": new_dataset.name,
                "is_remote": bool(is_remote)
            },
            execution_time=execution_time
        )

        return {
            "report_id": new_dataset.id,
            "file_path": file_path
        }
    except Exception as e:
        # 失败时回滚未提交的数据库变更，避免连接残留（符合 project 约束：rollback before close）
        db.rollback()
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="failed",
            error_message=str(e),
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise HTTPException(status_code=500, detail=f"保存报告失败: {e}")


# ====== 远程模式 SQL 下推：统计与质量检测 ======
# 以下两个函数在远程模式下通过 SQL 聚合查询完成统计与质量检测，
# 避免大表全量加载导致 OOM。返回结构与本地内存计算保持一致，
# 保证前端无感切换。大表场景下高级统计（分位数/偏度/峰度/中位数/众数）
# 为 None，仅返回基础统计——这是 SQL 下推的已知限制（见修改方案文档第五节）。


def _is_remote_numeric_col(type_str: str) -> bool:
    """判断远程列是否为数值列（基于数据库类型字符串）

    统计与图表推荐两处共用，保证布尔列判定一致：
    - BOOL/BOOLEAN 不含数值关键字，天然排除
    - TINYINT(1) 含 'TINYINT' 数值关键字会被误判，需显式排除
    与本地 _get_column_type 的 bool 判定行为对齐。
    """
    type_str = (type_str or "").upper()
    if "BOOL" in type_str:
        return False
    if "TINYINT(1)" in type_str:
        return False
    return any(kw in type_str for kw in (
        'INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'TINYINT', 'MEDIUMINT',
        'DECIMAL', 'NUMERIC', 'NUMBER', 'FLOAT', 'DOUBLE', 'REAL', 'BIT',
        'SERIAL', 'BIGSERIAL',
    ))


def _compute_remote_statistics(data_service: DataService, connection_id: int,
                                table_name: str, user_id: int) -> Dict[str, Any]:
    """远程模式统计摘要：SQL 下推聚合，返回结构与本地统计一致

    通过 get_remote_table_schema 读取数据库元数据判断列类型，
    再调用 query_remote_aggregate 在数据库侧执行聚合查询。
    大表场景下高级统计字段为 None。

    注意：不使用 LIMIT 0 + pd.read_sql 的方式判断列类型，
    因为空结果集会导致 pandas 将所有列推断为 object 类型，
    数值列识别失败进而导致前端图表参数下拉框为空。

    Args:
        data_service: 数据服务实例
        connection_id: 远程数据源连接 ID
        table_name: 远程表名
        user_id: 当前用户 ID（权限验证）

    Returns:
        {numeric_stats, categorical_stats, basic_info} — 与本地统计结构兼容
    """
    # 1. 通过数据库元数据（inspector）获取列类型，避免 LIMIT 0 的类型推断问题
    schema_info = data_service.get_remote_table_schema(connection_id, table_name, user_id=user_id)
    all_cols = [col["name"] for col in schema_info]
    # 根据数据库类型字符串判断是否为数值列（与图表推荐共用 _is_remote_numeric_col，
    # 布尔列 BOOL/TINYINT(1) 统一不作为数值列，避免统计与推荐结论矛盾）
    numeric_cols = [
        col["name"] for col in schema_info
        if _is_remote_numeric_col(str(col["type"]))
    ]
    numeric_set = set(numeric_cols)
    categorical_cols = [c for c in all_cols if c not in numeric_set]

    # 2. 构造聚合指标：行数 + 数值列统计 + 分类列统计 + 全列缺失值
    metrics = [{"type": "count"}]
    if numeric_cols:
        metrics.append({"type": "numeric_stats", "columns": numeric_cols})
    if categorical_cols:
        metrics.append({"type": "categorical_stats", "columns": categorical_cols, "top_n": 10})
    # 全列缺失值统计（数值列和分类列都需要）
    metrics.append({"type": "null_count", "columns": all_cols})

    # 3. 执行 SQL 下推
    agg = data_service.query_remote_aggregate(
        connection_id=connection_id,
        table_name=table_name,
        user_id=user_id,
        metrics=metrics
    )

    total_count = agg.get("count", 0)
    null_counts = agg.get("null_count", {})
    raw_num = agg.get("numeric_stats", {})
    raw_cat = agg.get("categorical_stats", {})

    # 4. 转换 numeric_stats：基础统计用SQL下推结果，高级统计用pandas抽样计算
    # SQL下推能快速得到 mean/std/min/max/count，但中位数/分位数/偏度/峰度等
    # 在SQL中难以表达（需要窗口函数），因此抽样加载1万行到本地用pandas计算
    numeric_stats = {}
    # 先用SQL基础统计填充所有数值列
    for col in numeric_cols:
        ns = raw_num.get(col, {})
        missing_count = null_counts.get(col, 0)
        numeric_stats[col] = {
            "mean": ns.get("mean"),
            "median": None,
            "std": ns.get("std"),
            "min": ns.get("min"),
            "max": ns.get("max"),
            "q25": None, "q50": None, "q75": None,
            "p90": None, "p95": None, "p99": None,
            "skewness": None, "kurtosis": None,
            "cv": None,
            "mode": None,
            "zero_count": None,
            "zero_rate": None,
            "unique_count": ns.get("unique_count", 0),
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total_count * 100, 2) if total_count > 0 else 0
        }

    # 抽样加载最多1万行数值列数据到本地，用pandas计算高级统计字段
    # 基础统计（mean/std/min/max）仍用SQL下推结果（基于全表，更准确）
    # 高级统计（中位数/分位数/偏度/峰度/众数/零值）基于抽样数据计算
    if numeric_cols:
        try:
            import random as _random
            import logging as _logging
            _logger = _logging.getLogger(__name__)
            sample_limit = 10000
            sample_offset = _random.randint(0, max(0, total_count - sample_limit)) if total_count > sample_limit else 0
            # 先尝试只查询数值列（减少数据传输量），失败则降级为 SELECT *
            try:
                sample_df = data_service.query_remote_table(
                    connection_id, table_name, user_id=user_id,
                    columns=numeric_cols, limit=sample_limit, offset=sample_offset
                )
            except Exception as col_err:
                # columns 参数查询失败（可能是列名含特殊字符或为保留字），降级为全量查询
                _logger.warning("远程高级统计: columns 参数查询失败(%s)，降级为 SELECT *", str(col_err))
                sample_df = data_service.query_remote_table(
                    connection_id, table_name, user_id=user_id,
                    limit=sample_limit, offset=sample_offset
                )
            for col in numeric_cols:
                if col not in sample_df.columns:
                    continue
                col_data = pd.to_numeric(sample_df[col], errors='coerce').dropna()
                if len(col_data) == 0:
                    continue
                ns_entry = numeric_stats[col]
                # 覆盖高级统计字段（基础统计仍用SQL结果）
                ns_entry["median"] = round(float(col_data.median()), 4)
                ns_entry["q25"] = round(float(col_data.quantile(0.25)), 4)
                ns_entry["q50"] = round(float(col_data.quantile(0.50)), 4)
                ns_entry["q75"] = round(float(col_data.quantile(0.75)), 4)
                ns_entry["p90"] = round(float(col_data.quantile(0.90)), 4)
                ns_entry["p95"] = round(float(col_data.quantile(0.95)), 4)
                ns_entry["p99"] = round(float(col_data.quantile(0.99)), 4)
                ns_entry["skewness"] = round(float(col_data.skew()), 4)
                ns_entry["kurtosis"] = round(float(col_data.kurtosis()), 4)
                # 变异系数用SQL的mean和std计算（基于全表）
                mean_val = ns_entry.get("mean")
                std_val = ns_entry.get("std")
                if mean_val is not None and std_val is not None and mean_val != 0:
                    ns_entry["cv"] = round(std_val / mean_val, 4)
                # 众数：捕获所有异常，确保后续零值统计不受影响
                try:
                    _mode_series = col_data.mode()
                    if len(_mode_series) > 0:
                        ns_entry["mode"] = safe_value(_mode_series.iloc[0])
                    else:
                        ns_entry["mode"] = None
                except Exception:
                    ns_entry["mode"] = None
                # 零值统计
                zero_count = int((col_data == 0).sum())
                ns_entry["zero_count"] = zero_count
                ns_entry["zero_rate"] = round(zero_count / len(col_data) * 100, 2) if len(col_data) > 0 else 0
        except Exception as e:
            # 抽样失败时记录日志，保持高级统计为None，不影响基础统计的返回
            import logging as _logging2
            _logging2.getLogger(__name__).warning("远程高级统计抽样计算失败: %s", str(e), exc_info=True)

    # 5. 转换 categorical_stats：与 _compute_categorical_stats 返回结构一致
    categorical_stats = {}
    for col in categorical_cols:
        cs = raw_cat.get(col, {})
        missing_count = null_counts.get(col, 0)
        non_null_count = total_count - missing_count
        top_values = cs.get("top_values", [])
        # 补充 rate 字段（与本地结构一致）
        for tv in top_values:
            tv["rate"] = round(tv["count"] / non_null_count * 100, 2) if non_null_count > 0 else 0
        categorical_stats[col] = {
            "unique_count": cs.get("unique_count", 0),
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total_count * 100, 2) if total_count > 0 else 0,
            "top_values": top_values
        }

    # 6. 转换 basic_info：与 _compute_basic_info 返回结构一致
    # 构建 列名→数据库类型 的映射，替代之前的 empty_df[col].dtype
    col_type_map = {col["name"]: col["type"] for col in schema_info}
    columns_info = []
    for col in all_cols:
        missing_count = null_counts.get(col, 0)
        # unique_count 从 numeric_stats 或 categorical_stats 中取
        if col in numeric_set:
            uc = raw_num.get(col, {}).get("unique_count", 0)
        else:
            uc = categorical_stats.get(col, {}).get("unique_count", 0)
        is_numeric = col in numeric_set
        columns_info.append({
            "name": col,
            "type": col_type_map.get(col, "unknown"),
            "is_numeric": is_numeric,
            "missing_count": missing_count,
            "missing_rate": round(missing_count / total_count * 100, 2) if total_count > 0 else 0,
            "unique_count": uc,
            "is_constant": uc == 1,
            "missing_too_many": (missing_count / total_count) > 0.5 if total_count > 0 else False
        })

    basic_info = {
        "row_count": total_count,
        "column_count": len(all_cols),
        "numeric_count": len(numeric_cols),
        "categorical_count": len(categorical_cols),
        "columns": columns_info
    }

    return {
        "numeric_stats": numeric_stats,
        "categorical_stats": categorical_stats,
        "basic_info": basic_info
    }


def _compute_remote_quality(data_service: DataService, connection_id: int,
                             table_name: str, user_id: int) -> Dict[str, Any]:
    """远程模式数据质量检测：SQL 下推聚合，返回结构与本地质量检测一致

    通过 SQL 聚合查询检测缺失值、常量列、重复行，避免大表全量加载。
    无穷值检测在 SQL 下推中不实现（MySQL/PostgreSQL 数值列一般不存储 inf），
    返回空列表——这是已知限制。

    Args:
        data_service: 数据服务实例
        connection_id: 远程数据源连接 ID
        table_name: 远程表名
        user_id: 当前用户 ID（权限验证）

    Returns:
        {overall_missing_rate, missing_columns_count, infinite_columns,
         duplicate_rows, constant_columns} — 与本地质量检测结构兼容
    """
    # 1. 获取空 DataFrame 以拿到列名
    empty_df = data_service.query_remote_table(
        connection_id, table_name, user_id=user_id, limit=0
    )
    all_cols = list(empty_df.columns)

    # 2. 构造聚合指标：行数 + 全列缺失值 + 全列唯一值数 + 全列重复行数
    metrics = [
        {"type": "count"},
        {"type": "null_count", "columns": all_cols},
        {"type": "unique_count", "columns": all_cols},
        {"type": "duplicate_count", "columns": all_cols}
    ]

    # 3. 执行 SQL 下推
    agg = data_service.query_remote_aggregate(
        connection_id=connection_id,
        table_name=table_name,
        user_id=user_id,
        metrics=metrics
    )

    total_count = agg.get("count", 0)
    null_counts = agg.get("null_count", {})
    unique_counts = agg.get("unique_count", {})
    duplicate_rows = agg.get("duplicate_count", 0)

    # 4. 计算质量指标
    # 缺失值列：缺失数 > 0 的列
    nan_columns = [col for col, cnt in null_counts.items() if cnt > 0]
    # 常量列：唯一值数 <= 1（与 check_data_quality 的判断逻辑一致）
    constant_columns = [col for col, uc in unique_counts.items() if uc <= 1]
    # 总体缺失率
    total_cells = total_count * len(all_cols) if all_cols else 0
    total_missing = sum(null_counts.values())
    overall_missing_rate = round(total_missing / total_cells * 100, 2) if total_cells > 0 else 0
    # 无穷值列：SQL 下推不检测，返回空列表
    infinite_columns = []

    return {
        "overall_missing_rate": overall_missing_rate,
        "missing_columns_count": len(nan_columns),
        "infinite_columns": infinite_columns,
        "duplicate_rows": duplicate_rows,
        "constant_columns": constant_columns
    }


def _validate_remote_recommendation_params(params: Dict[str, Any], chart_type: str,
                                            all_cols: List[str],
                                            col_is_numeric: Dict[str, bool]) -> bool:
    """基于 schema 信息的推荐参数校验（远程模式无 df 时的替代方案）

    校验规则与 _validate_recommendation_params 一致：
    - 所有涉及的列必须存在
    - X 轴列不能与 Y 轴列重叠
    - Y 轴列必须都是数值列
    - bar/stacked_bar/pie 需要分类列作为 X 轴
    - line/area/multi_line 的 X 轴不应使用数值列
    """
    try:
        cols = set()
        x_col = params.get("x_column") or ""
        if x_col:
            cols.add(x_col)

        # 收集 Y 轴列（数值列）；column 是饼图的分类维度列，不属于 Y 轴
        y_cols = []
        for key in ("y_columns", "columns"):
            val = params.get(key)
            if isinstance(val, (list, tuple)):
                y_cols.extend(val)
            elif val:
                y_cols.append(val)
        for key in ("y_column", "y1_column", "y2_column", "size_column", "value_column"):
            val = params.get(key)
            if val:
                y_cols.append(val)

        for c in y_cols:
            if c:
                cols.add(c)

        # 饼图的维度列 column 单独纳入存在性校验
        pie_column = params.get("column")
        if pie_column:
            cols.add(pie_column)

        # 所有列必须存在
        for c in cols:
            if c not in all_cols:
                return False

        # X 轴列不能和 Y 轴列重叠
        if x_col and x_col in y_cols:
            return False

        # Y 轴列必须都是数值列
        for c in y_cols:
            if c and not col_is_numeric.get(c, False):
                return False

        # bar/stacked_bar 需要分类列作为 X 轴
        if chart_type in ("bar", "stacked_bar"):
            if not x_col or x_col not in all_cols:
                return False

        # pie 使用 column 作为维度列（而非 x_column），且必须是分类列
        if chart_type == "pie":
            if not pie_column or pie_column not in all_cols or col_is_numeric.get(pie_column, False):
                return False

        # 趋势类图表的 X 轴不应使用数值列，避免把指标误当作维度
        if chart_type in ("line", "area", "multi_line") and x_col:
            if col_is_numeric.get(x_col, False):
                return False

        return True
    except Exception:
        return False


def _compute_remote_recommendations(data_service: DataService, connection_id: int,
                                      table_name: str, user_id: int,
                                      columns: Optional[List[str]] = None,
                                      chart_type: Optional[str] = None) -> Dict[str, Any]:
    """远程模式图表智能推荐：SQL 下推聚合，返回结构与本地推荐一致

    通过 SQL 聚合查询获取列基数/缺失率/数值 min-max，在 DB 侧完成计算。
    大表场景下 outlier_rate 为 None（SQL 标准不支持分位数），不影响主流推荐。
    _detect_dual_axis_needed 用 SQL 获取的 min/max 估算量纲差异。

    Args:
        data_service: 数据服务实例
        connection_id: 远程数据源连接 ID
        table_name: 远程表名
        user_id: 当前用户 ID（权限验证）
        columns: 指定列名列表（可选）
        chart_type: 指定图表类型（可选）

    Returns:
        与 _get_chart_recommendations 返回结构一致
    """
    # 1. 通过 schema 查询获取列类型（不拉数据，避免空 df 类型推断失败）
    schema_cols = data_service.get_remote_table_schema(
        connection_id, table_name, user_id=user_id
    )
    all_cols = [c["name"] for c in schema_cols]

    # 若指定了列，只考虑这些列
    if columns:
        all_cols = [c for c in all_cols if c in columns]

    # 2. 根据 SQL 类型字符串判断列类型（避免 LIMIT 0/1 的类型推断问题）
    # 数值类型关键字：INT/FLOAT/DOUBLE/DECIMAL/NUMERIC/REAL
    # 时间类型关键字：DATE/DATETIME/TIMESTAMP
    col_is_numeric = {}
    col_is_datetime = {}
    for c in schema_cols:
        col_name = c["name"]
        if col_name not in all_cols:
            continue
        type_str = c["type"].upper()
        # 与统计共用 _is_remote_numeric_col，布尔列 BOOL/TINYINT(1) 不作为数值列
        is_num = _is_remote_numeric_col(type_str)
        is_dt = any(kw in type_str for kw in ["DATETIME", "TIMESTAMP", "DATE"])
        col_is_numeric[col_name] = is_num
        col_is_datetime[col_name] = is_dt

    numeric_cols_all = [c for c in all_cols if col_is_numeric.get(c, False)]
    categorical_cols = [c for c in all_cols if not col_is_numeric.get(c, False)]
    datetime_cols = [c for c in all_cols if col_is_datetime.get(c, False) and not col_is_numeric.get(c, False)]

    # 3. 构造聚合指标：全列 unique_count + null_count + 数值列 numeric_stats(含 min/max)
    metrics = [
        {"type": "count"},
        {"type": "unique_count", "columns": all_cols},
        {"type": "null_count", "columns": all_cols},
    ]
    if numeric_cols_all:
        metrics.append({"type": "numeric_stats", "columns": numeric_cols_all})

    agg = data_service.query_remote_aggregate(
        connection_id=connection_id,
        table_name=table_name,
        user_id=user_id,
        metrics=metrics
    )

    total_count = agg.get("count", 0)
    unique_counts = agg.get("unique_count", {})
    null_counts = agg.get("null_count", {})
    raw_num = agg.get("numeric_stats", {})

    # 4. 构造 column_tags（与 _get_column_tags 返回结构一致）
    column_tags = {}
    for col in all_cols:
        is_num = col_is_numeric[col]
        is_dt = col_is_datetime[col]
        missing_count = null_counts.get(col, 0)
        non_null_count = total_count - missing_count
        uc = unique_counts.get(col, 0)
        uniqueness = uc / non_null_count if non_null_count > 0 else 0
        missing_rate = missing_count / total_count if total_count > 0 else 0

        is_constant = uc == 1
        is_identifier = uniqueness > 0.9 and not is_num
        high_cardinality = uc > 20 and not is_num

        # 计算 quality_score（与 _get_column_tags 逻辑一致，但 outlier_rate 不扣分）
        quality_score = 100
        availability = "available"
        availability_reason = ""

        if is_constant:
            quality_score -= 50
            availability = "disabled"
            availability_reason = "该列所有值相同，无法生成有意义的图表"
        if is_identifier:
            quality_score -= 80
            availability = "disabled"
            availability_reason = "该列是唯一标识符，不适合作为分类轴"
        if missing_rate > 0.5:
            quality_score -= 50
            availability = "disabled"
            availability_reason = f"缺失值超过50%({round(missing_rate*100,1)}%)，无法生成有意义的图表"
        elif missing_rate > 0.3:
            quality_score -= 20
            availability = "warning"
            availability_reason = f"缺失值较多({round(missing_rate*100,1)}%)，结果可能有偏差"
        elif missing_rate > 0.1:
            quality_score -= 10
            availability = "warning"
            availability_reason = f"存在缺失值({round(missing_rate*100,1)}%)"
        if high_cardinality:
            quality_score -= 20
            availability_reason = f"类别过多({uc}个)，图表可能拥挤"

        # outlier_rate 为 None（SQL 不支持分位数），不扣分
        tags = {
            "name": col,
            "is_numeric": is_num,
            "is_categorical": not is_num and not is_dt,
            "is_datetime": is_dt,
            "is_constant": is_constant,
            "is_identifier": is_identifier,
            "high_cardinality": high_cardinality,
            "missing_rate": round(missing_rate, 4),
            "unique_count": uc,
            "uniqueness": round(uniqueness, 4),
            "quality_score": max(0, min(100, int(quality_score))),
            "availability": availability,
            "availability_reason": availability_reason,
            "outlier_rate": None,  # SQL 下推不支持分位数
        }
        column_tags[col] = tags

    # 5. 过滤可用列（与 _get_chart_recommendations 逻辑一致）
    numeric_cols = [col for col in numeric_cols_all if column_tags[col]["availability"] != "disabled"]
    categorical_cols = [c for c in categorical_cols if c in column_tags]
    datetime_cols = [col for col in datetime_cols if column_tags[col]["availability"] != "disabled"]

    top_numeric_cols = sorted(numeric_cols, key=lambda c: column_tags[c]["quality_score"], reverse=True)[:3]
    top_cat_cols = sorted(categorical_cols, key=lambda c: min(column_tags.get(c, {}).get("unique_count", 9999), 15), reverse=False)[:2]

    x_axis_col = top_cat_cols[0] if top_cat_cols else ""
    trend_x_col = x_axis_col if x_axis_col in categorical_cols else ""

    # 6. 生成推荐列表（与 _get_chart_recommendations 逻辑一致）
    recommendations = []

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "数据分布", "chart_type": "histogram",
            "columns": top_numeric_cols[:2],
            "params": {"columns": top_numeric_cols[:2]},
            "reason": f"您的数据有{len(numeric_cols)}个数值列，推荐查看分布情况",
            "score": 0.9
        })
        recommendations.append({
            "purpose": "数据分布", "chart_type": "boxplot",
            "columns": top_numeric_cols[:3],
            "params": {"columns": top_numeric_cols[:3]},
            "reason": f"箱线图可以展示{', '.join(top_numeric_cols[:3])}的分布和异常值",
            "score": 0.85
        })

    if len(categorical_cols) >= 1 and len(numeric_cols) >= 1 and len(top_cat_cols) > 0:
        recommendations.append({
            "purpose": "类别对比", "chart_type": "bar",
            "columns": [top_cat_cols[0]] + top_numeric_cols[:2],
            "params": {"x_column": top_cat_cols[0], "y_columns": top_numeric_cols[:2]},
            "reason": f"用{top_cat_cols[0]}分组对比{', '.join(top_numeric_cols[:2])}",
            "score": 0.8
        })

    if len(numeric_cols) >= 1:
        line_cols = top_numeric_cols[:2]
        recommendations.append({
            "purpose": "趋势变化", "chart_type": "multi_line",
            "columns": ([trend_x_col] if trend_x_col else []) + line_cols,
            "params": {"x_column": trend_x_col, "columns": line_cols},
            "reason": f"查看{', '.join(line_cols)}的变化趋势" if not trend_x_col else f"查看{trend_x_col}维度下{', '.join(line_cols)}的变化趋势",
            "score": 0.75
        })

    if len(numeric_cols) >= 2:
        recommendations.append({
            "purpose": "变量关系", "chart_type": "scatter",
            "columns": top_numeric_cols[:2],
            "params": {"x_column": top_numeric_cols[0], "y_column": top_numeric_cols[1]},
            "reason": f"查看{top_numeric_cols[0]}和{top_numeric_cols[1]}的相关性",
            "score": 0.7
        })
        recommendations.append({
            "purpose": "变量关系", "chart_type": "heatmap",
            "columns": top_numeric_cols[:5],
            "params": {"columns": top_numeric_cols[:5]},
            "reason": f"查看{len(top_numeric_cols[:5])}个数值列之间的相关性矩阵",
            "score": 0.65
        })

    if len(categorical_cols) >= 1:
        top_cat_for_pie = [c for c in categorical_cols if column_tags[c]["unique_count"] <= 8]
        if top_cat_for_pie:
            recommendations.append({
                "purpose": "占比构成", "chart_type": "pie",
                "columns": [top_cat_for_pie[0]],
                "params": {"column": top_cat_for_pie[0]},
                "reason": f"{top_cat_for_pie[0]}有{column_tags[top_cat_for_pie[0]]['unique_count']}个类别，适合用饼图展示占比",
                "score": 0.6
            })

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "趋势变化", "chart_type": "area",
            "columns": ([trend_x_col] if trend_x_col else []) + top_numeric_cols[:2],
            "params": {"x_column": trend_x_col, "y_columns": top_numeric_cols[:2]},
            "reason": f"面积图可展示{', '.join(top_numeric_cols[:2])}的累积趋势" if not trend_x_col else f"面积图可展示{trend_x_col}维度下{', '.join(top_numeric_cols[:2])}的累积趋势",
            "score": 0.72
        })
        if trend_x_col:
            recommendations.append({
                "purpose": "趋势变化", "chart_type": "area",
                "columns": top_numeric_cols[:2],
                "params": {"x_column": "", "y_columns": top_numeric_cols[:2]},
                "reason": f"面积图可展示{', '.join(top_numeric_cols[:2])}按行索引的累积趋势",
                "score": 0.70
            })

    if len(numeric_cols) >= 2:
        recommendations.append({
            "purpose": "趋势变化", "chart_type": "multi_line",
            "columns": top_numeric_cols[:3],
            "params": {"x_column": "", "columns": top_numeric_cols[:3]},
            "reason": f"多折线图可同时对比{len(top_numeric_cols[:3])}个数值列的变化",
            "score": 0.71
        })

    # 双 Y 轴推荐：用 SQL 获取的 min/max 估算量纲差异
    if len(numeric_cols) >= 2:
        dual_cols = top_numeric_cols[:2]
        # 用 numeric_stats 的 min/max 估算量纲差异（替代 _detect_dual_axis_needed）
        dual_needed = False
        ranges = []
        for col in dual_cols:
            ns = raw_num.get(col, {})
            col_min = ns.get("min")
            col_max = ns.get("max")
            if col_min is not None and col_max is not None:
                col_range = float(col_max) - float(col_min)
                if col_range > 0:
                    ranges.append(col_range)
        if len(ranges) >= 2 and min(ranges) > 0:
            dual_needed = max(ranges) / min(ranges) > 10

        if dual_needed:
            dual_score = 0.82
            dual_reason = f"{dual_cols[0]}与{dual_cols[1]}量纲差异大，建议使用双Y轴"
        else:
            dual_score = 0.60
            dual_reason = f"双Y轴图可同时展示{dual_cols[0]}与{dual_cols[1]}两个指标"
        recommendations.append({
            "purpose": "趋势变化", "chart_type": "dual_axis",
            "columns": dual_cols,
            "params": {"x_column": x_axis_col, "y1_column": dual_cols[0], "y2_column": dual_cols[1]},
            "reason": dual_reason,
            "score": dual_score
        })

    if len(numeric_cols) >= 1:
        recommendations.append({
            "purpose": "数据分布", "chart_type": "kde",
            "columns": top_numeric_cols[:2],
            "params": {"columns": top_numeric_cols[:2]},
            "reason": f"KDE图可平滑展示{', '.join(top_numeric_cols[:2])}的概率密度",
            "score": 0.68
        })
        recommendations.append({
            "purpose": "数据分布", "chart_type": "qq",
            "columns": [top_numeric_cols[0]],
            "params": {"columns": [top_numeric_cols[0]]},
            "reason": f"QQ图可检验{top_numeric_cols[0]}是否符合正态分布",
            "score": 0.55
        })

    if len(numeric_cols) >= 3:
        radar_cols = top_numeric_cols[:5]
        recommendations.append({
            "purpose": "类别对比", "chart_type": "radar",
            "columns": radar_cols,
            "params": {"columns": radar_cols},
            "reason": f"雷达图可多维对比{len(radar_cols)}个数值指标",
            "score": 0.62
        })
        bubble_cols = top_numeric_cols[:3]
        recommendations.append({
            "purpose": "变量关系", "chart_type": "bubble",
            "columns": bubble_cols,
            "params": {"x_column": bubble_cols[0], "y_column": bubble_cols[1], "size_column": bubble_cols[2]},
            "reason": f"气泡图可展示{bubble_cols[0]}、{bubble_cols[1]}与大小{bubble_cols[2]}的关系",
            "score": 0.58
        })

    if len(categorical_cols) >= 1 and len(numeric_cols) >= 2 and len(top_cat_cols) > 0:
        recommendations.append({
            "purpose": "类别对比", "chart_type": "stacked_bar",
            "columns": [top_cat_cols[0]] + top_numeric_cols[:3],
            "params": {"x_column": top_cat_cols[0], "y_columns": top_numeric_cols[:3]},
            "reason": f"堆叠柱状图可展示{top_cat_cols[0]}分组下多个指标的累积对比",
            "score": 0.65
        })

    # 7. 清洗推荐参数（用空 df 做校验，只检查列存在性和类型）
    sanitized_recommendations = []
    for r in recommendations:
        ctype = r.get("chart_type", "")
        params = _sanitize_recommendation_params(r.get("params", {}))
        if params is None:
            continue
        involved_cols = []
        x_col = params.get("x_column") or ""
        if x_col:
            involved_cols.append(x_col)
        for key in ("y_columns", "columns"):
            val = params.get(key)
            if isinstance(val, (list, tuple)):
                for c in val:
                    if c and c not in involved_cols:
                        involved_cols.append(c)
        for key in ("y_column", "y1_column", "y2_column", "size_column", "value_column", "column"):
            c = params.get(key)
            if c and c not in involved_cols:
                involved_cols.append(c)
        r["params"] = params
        r["columns"] = involved_cols
        # 基于 schema 的校验：列存在性 + Y 轴必须为数值列 + X 轴不能与 Y 轴重叠
        if _validate_remote_recommendation_params(params, ctype, all_cols, col_is_numeric):
            sanitized_recommendations.append(r)
    recommendations = sanitized_recommendations

    # 8. 同一种图表类型保留评分最高的 2 个不同参数搭配方案
    MAX_VARIANTS_PER_TYPE = 2
    type_variants: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in sorted(recommendations, key=lambda x: x["score"], reverse=True):
        ctype = r.get("chart_type", "")
        vkey = _rec_variant_key(ctype, r.get("params", {}))
        if ctype not in type_variants:
            type_variants[ctype] = {}
        if vkey not in type_variants[ctype] and len(type_variants[ctype]) < MAX_VARIANTS_PER_TYPE:
            type_variants[ctype][vkey] = r
    recommendations = [r for variants in type_variants.values() for r in variants.values()]

    # 9. 若指定了图表类型，仅保留该类型的推荐
    if chart_type:
        recommendations = [r for r in recommendations if r.get("chart_type") == chart_type]

    # 10. 计算各图表类型的支持状态
    supported_chart_types = {}
    chart_type_configs = [
        ("histogram", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("boxplot", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("kde", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("qq", "数据分布", "至少1个数值列", len(numeric_cols) >= 1),
        ("scatter", "变量关系", "至少2个数值列", len(numeric_cols) >= 2),
        ("bubble", "变量关系", "至少3个数值列", len(numeric_cols) >= 3),
        ("area", "趋势变化", "至少1个数值列", len(numeric_cols) >= 1),
        ("multi_line", "趋势变化", "至少1个数值列", len(numeric_cols) >= 1),
        ("bar", "类别对比", "至少1个分类列和1个数值列", len(categorical_cols) >= 1 and len(numeric_cols) >= 1),
        ("stacked_bar", "类别对比", "至少1个分类列和2个数值列", len(categorical_cols) >= 1 and len(numeric_cols) >= 2),
        ("dual_axis", "趋势变化", "至少2个数值列", len(numeric_cols) >= 2),
        ("pie", "占比构成", "至少1个分类列", len(categorical_cols) >= 1),
        ("heatmap", "变量关系", "至少2个数值列", len(numeric_cols) >= 2),
        ("radar", "类别对比", "至少3个数值列", len(numeric_cols) >= 3),
        ("table_heatmap", "变量关系", "至少2个分类列和1个数值列", len(categorical_cols) >= 2 and len(numeric_cols) >= 1),
    ]
    for ctype, category, requirement, supported in chart_type_configs:
        if supported:
            reason = f"满足{requirement}"
        else:
            reason = f"当前数据不满足：{requirement}"
        supported_chart_types[ctype] = {
            "supported": supported,
            "category": category,
            "requirement": requirement,
            "reason": reason
        }

    return {
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "datetime_columns": datetime_cols,
        "recommendations": recommendations[:10],
        "column_tags": column_tags,
        "supported_chart_types": supported_chart_types
    }


# ====== 任务处理器注册（供任务调度器激活 pending 任务 / 失败重试复用）======
# data_analysis 报告生成任务此前未注册 handler，进入 pending 队列后会被调度器
# 在 5 秒内标记为 failed（"未注册任务类型，无法激活"），本注册修复该问题（2026-08-15）。
task_manager.register_task_handler("data_analysis", _execute_generate_report)