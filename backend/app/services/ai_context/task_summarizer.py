"""任务记录配置摘要模板

将 TaskRecord.params 和 result_summary 渲染为人类可读的文本摘要，
便于 AI 理解用户当时的操作配置和执行结果。
按 task_type 分发到对应的摘要模板。

改进点：
1. 过滤进度跟踪字段（current_stage/current_progress/current_message/progress_history），避免噪音
2. 任务失败时优先输出 error_message，帮助 AI 诊断失败原因
3. result_summary 只提取诊断相关字段，过滤进度字段
"""
import json
import re
from typing import Dict, Callable, Any
from app.models import TaskRecord
from app.utils.task_labels import FAILURE_CATEGORY_LABELS, is_retryable_failure


# 需要过滤的进度跟踪字段（对 AI 诊断无价值，反而干扰判断）
_PROGRESS_FIELDS = {
    "current_stage", "current_progress", "current_message",
    "progress_history", "current_step", "total_steps"
}

# 大字段过滤集：这些字段可能包含完整 HTML/数据块，注入 AI 上下文会撑爆 token 上限
# generate_report 阶段会把完整 preview_html 写入 result_summary，可能达几百 KB
# 过滤后在摘要中追加提示，让 AI 知道报告存在但内容未注入
_LARGE_BLOB_FIELDS = {
    "preview_html", "report_html", "dynamic_data", "html", "report_content"
}


def _filter_progress_fields(data: Any) -> Any:
    """递归过滤字典中的进度跟踪字段

    Args:
        data: 可能是 dict/list/其他类型

    Returns:
        过滤后的数据（不修改原数据）
    """
    if isinstance(data, dict):
        return {k: _filter_progress_fields(v) for k, v in data.items() if k not in _PROGRESS_FIELDS}
    if isinstance(data, list):
        return [_filter_progress_fields(item) for item in data]
    return data


def _filter_large_blob_fields(data: Any) -> Any:
    """递归过滤字典中的大字段（HTML/数据块），避免注入 AI 上下文撑爆 token"""
    if isinstance(data, dict):
        return {k: _filter_large_blob_fields(v) for k, v in data.items() if k not in _LARGE_BLOB_FIELDS}
    if isinstance(data, list):
        return [_filter_large_blob_fields(item) for item in data]
    return data


def _source_line(task: TaskRecord) -> str:
    """任务数据来源行：本地 / 远程（连接ID + 表名）

    远程数据库功能上线后，AI 需区分操作的执行对象来源：
    - 本地：上传的 CSV/Excel/JSON 数据集
    - 远程：连接 MySQL/PostgreSQL 的表（params.is_remote=true + remote_config）
    """
    p = task.params or {}
    if not isinstance(p, dict):
        return "数据来源: 本地"
    if p.get("is_remote"):
        cfg = p.get("remote_config")
        if isinstance(cfg, dict) and cfg.get("table_name"):
            return (f"数据来源: 远程数据库（连接ID={cfg.get('connection_id')}"
                    f" / 表={cfg.get('table_name')}）")
        return "数据来源: 远程数据库"
    return "数据来源: 本地"


def summarize_task(task: TaskRecord) -> str:
    """根据任务类型生成配置摘要文本

    Args:
        task: TaskRecord 模型实例

    Returns:
        人类可读的任务配置摘要文本（末尾统一追加数据来源行）
    """
    task_type = task.task_type or "unknown"

    # 失败任务优先输出错误信息，但仍包含配置信息便于 AI 诊断
    if task.status == "failed" and task.error_message:
        summary = _summarize_failed_task(task, task_type)
    else:
        # 特征工程有多个子类型（feature_engineering_select/construct/encode/scale/reduce）
        if task_type.startswith("feature_engineering"):
            summarizer = _summarize_feature_engineering
        else:
            summarizer = _SUMMARIZERS.get(task_type, _summarize_generic)

        try:
            summary = summarizer(task)
        except Exception as e:
            summary = f"[任务摘要生成失败: {task_type} #{task.id}, 错误: {str(e)}]"

    # 统一追加数据来源，AI 据此区分本地/远程操作
    summary += "\n" + _source_line(task)
    return summary


def _summarize_failed_task(task: TaskRecord, task_type: str) -> str:
    """失败任务摘要：含 failure_category + 配置信息 + 错误信息（核心）

    failure_category 帮助 AI 区分"参数错误需修改参数"vs"系统错误可重试"，
    给出更准确的改进建议。复用 task_labels 中的常量与函数避免双重维护。
    """
    p = task.params or {}
    lines = [f"[操作记录-失败] 任务#{task.id} ({task_type})"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")

    # 失败分类（帮助 AI 判断是否可重试及改进方向）
    # 复用 task_labels 中的常量与函数，避免双重维护
    failure_category = getattr(task, "failure_category", None)
    if failure_category:
        label = FAILURE_CATEGORY_LABELS.get(failure_category, failure_category)
        retry_hint = "可重试" if is_retryable_failure(failure_category) else "需修改后重新执行"
        lines.append(f"失败分类: {label}（{retry_hint}）")

    if p.get("algorithm"):
        lines.append(f"算法: {p.get('algorithm')}")
    if p.get("operation"):
        lines.append(f"操作: {p.get('operation')}")
    # 简要参数（过滤进度字段）
    filtered_params = _filter_progress_fields(p)
    if filtered_params:
        lines.append(f"参数: {_params_to_str(filtered_params)}")
    # 错误信息（核心）- 过滤内部路径和 task_id，避免干扰 AI 判断
    if task.error_message:
        cleaned_error = _clean_error_message(task.error_message)
        lines.append(f"错误信息: {cleaned_error}")
    return "\n".join(lines)


def _clean_error_message(error_msg: str) -> str:
    """清理错误信息中的内部路径和 task_id，避免干扰 AI 判断"""
    if not error_msg:
        return ""
    # 过滤 MinIO/本地文件路径（如 /app/data/uploads/xxx.csv）
    error_msg = re.sub(r"/app/[^\s']+\.(?:csv|xlsx?|parquet|json)", "<数据文件>", error_msg)
    # 过滤 Windows 路径（如 C:\app\data\uploads\xxx.csv）
    error_msg = re.sub(r"[A-Za-z]:\\[^\s']+\.(?:csv|xlsx?|parquet|json)", "<数据文件>", error_msg)
    # 过滤 Celery task_id（如 task_id: abc123def456）
    error_msg = re.sub(r"task_id[:\s]+[a-f0-9-]{8,}", "task_id: <已隐藏>", error_msg, flags=re.IGNORECASE)
    return error_msg


def _params_to_str(params) -> str:
    """安全将 params 转为 JSON 字符串"""
    if not params:
        return "{}"
    if isinstance(params, str):
        return params
    return json.dumps(params, ensure_ascii=False)


def _clean_result_summary(rs) -> dict:
    """过滤 result_summary 中的进度字段和大字段，只保留诊断相关字段"""
    if not rs:
        return {}
    if isinstance(rs, str):
        try:
            rs = json.loads(rs)
        except (json.JSONDecodeError, TypeError):
            return {}
    rs = _filter_progress_fields(rs)
    rs = _filter_large_blob_fields(rs)
    return rs


def _summarize_cleaning(task: TaskRecord) -> str:
    """数据清洗任务摘要"""
    p = task.params or {}
    lines = [f"[操作记录-数据清洗] 任务#{task.id}"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")
    lines.append(f"清洗方式: {p.get('method', '未知')} | 模式: {p.get('mode', '未知')}")

    config = p.get("config", {})
    if config:
        # config 可能是 pipeline（列表）或 problem_strategies（字典）
        if isinstance(config, list):
            lines.append(f"清洗管道: {_params_to_str(config)}")
        elif isinstance(config, dict):
            lines.append(f"清洗策略: {_params_to_str(config)}")

    # 结果摘要（过滤进度字段）
    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"清洗结果: 新数据集#{rs.get('new_dataset_id', '未保存')} | 行数: {rs.get('row_count', '未知')} | 处理量: {rs.get('processed_count', '未知')}")

    return "\n".join(lines)


def _summarize_ml_training(task: TaskRecord) -> str:
    """机器学习训练任务摘要（核心：AI 诊断准确率的关键依据）"""
    p = task.params or {}
    inner_params = p.get("params", {})
    lines = [f"[操作记录-ML训练] 任务#{task.id}"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")
    lines.append(f"算法: {p.get('algorithm', '未知')}")
    lines.append(f"任务类型: {inner_params.get('task_type', '未知')} | 目标列: {inner_params.get('target_column', '未知')}")
    lines.append(f"特征列: {inner_params.get('feature_columns', '未知')}")
    lines.append(f"test_size={inner_params.get('test_size', '未知')} | cv_folds={inner_params.get('cv_folds', '未知')} | auto_tune={inner_params.get('auto_tune', '未知')}")
    if inner_params.get("tune_method"):
        lines.append(f"调参方法: {inner_params.get('tune_method')}")

    # 结果摘要（含评估指标，过滤进度字段）
    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"训练结果: 模型#{rs.get('model_name', '未知')}")
        accuracy = rs.get("accuracy")
        if accuracy is not None:
            lines.append(f"准确率/R2: {accuracy}")
        metrics = rs.get("metrics", {})
        if metrics:
            lines.append(f"完整指标: {_params_to_str(metrics)}")

    return "\n".join(lines)


def _summarize_ml(task: TaskRecord) -> str:
    """旧版 ML 操作摘要（聚类/异常检测/关联规则/随机森林/线性回归）"""
    p = task.params or {}
    inner_params = p.get("params", {})
    lines = [f"[操作记录-ML分析] 任务#{task.id}"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")
    lines.append(f"算法: {p.get('algorithm', '未知')}")
    if inner_params:
        lines.append(f"参数: {_params_to_str(inner_params)}")

    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"结果: {_params_to_str(rs)}")

    return "\n".join(lines)


def _summarize_data_mining(task: TaskRecord) -> str:
    """数据挖掘任务摘要"""
    p = task.params or {}
    lines = [f"[操作记录-数据挖掘] 任务#{task.id}"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")
    lines.append(f"操作: {p.get('operation', '未知')} | 算法: {p.get('algorithm', '未知')}")

    # 按操作类型补充关键参数
    operation = p.get("operation", "")
    if operation == "cluster_analysis":
        lines.append(f"聚类列: {p.get('columns', '未知')} | 自动参数: {p.get('auto_params', '未知')}")
    elif operation == "association_rules_mining":
        lines.append(f"min_support={p.get('min_support')} | min_confidence={p.get('min_confidence')} | min_lift={p.get('min_lift')}")
    elif operation == "sequence_pattern_mining":
        lines.append(f"序列列: {p.get('seq_id_column')} | 时间列: {p.get('time_column')} | 事件列: {p.get('event_column')} | min_support={p.get('min_support')}")

    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"挖掘结果: {_params_to_str(rs)}")

    return "\n".join(lines)


def _summarize_feature_engineering(task: TaskRecord) -> str:
    """特征工程任务摘要（覆盖 select/construct/encode/scale/reduce）"""
    p = task.params or {}
    lines = [f"[操作记录-特征工程] 任务#{task.id}"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")
    lines.append(f"操作: {p.get('operation', '未知')}")
    if p.get("target_column"):
        lines.append(f"目标列: {p.get('target_column')}")
    config = p.get("config", {})
    if config:
        lines.append(f"配置: {_params_to_str(config)}")

    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"结果: {_params_to_str(rs)}")

    return "\n".join(lines)


def _summarize_data_analysis(task: TaskRecord) -> str:
    """数据分析任务摘要"""
    p = task.params or {}
    lines = [f"[操作记录-数据分析] 任务#{task.id}"]
    lines.append(f"数据集: {p.get('dataset_name', '未知')}")
    lines.append(f"操作: {p.get('operation', '未知')}")
    if p.get("sections"):
        lines.append(f"分析板块: {p.get('sections')}")
    if p.get("charts_count") is not None:
        lines.append(f"图表数量: {p.get('charts_count')}")

    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"结果: {_params_to_str(rs)}")

    # 原始 result_summary 中可能含 preview_html（大字段，已被过滤）
    # 追加提示让 AI 知道报告 HTML 已生成但内容未注入，避免 AI 误以为报告内容缺失
    raw_rs = task.result_summary
    if isinstance(raw_rs, str):
        try:
            raw_rs = json.loads(raw_rs)
        except (json.JSONDecodeError, TypeError):
            raw_rs = {}
    if isinstance(raw_rs, dict) and raw_rs.get("preview_html"):
        html_len = raw_rs.get("report_html_length", len(str(raw_rs["preview_html"])))
        lines.append(f"报告HTML已生成（长度{html_len}字符），内容未注入上下文，可在数据管理查看")

    return "\n".join(lines)


def _summarize_upload(task: TaskRecord) -> str:
    """数据上传任务摘要"""
    p = task.params or {}
    lines = [f"[操作记录-数据上传] 任务#{task.id}"]
    lines.append(f"文件名: {p.get('filename', '未知')} | 模块: {p.get('module_source', '未知')} | 类型: {p.get('artifact_type', '未知')}")

    # 上传结果包含数据集ID、行数、文件大小等信息，对AI诊断有价值
    rs = _clean_result_summary(task.result_summary)
    if rs:
        parts = []
        if rs.get("dataset_name"):
            parts.append(f"数据集名: {rs.get('dataset_name')}")
        if rs.get("row_count") is not None:
            parts.append(f"行数: {rs.get('row_count')}")
        if rs.get("file_size") is not None:
            parts.append(f"文件大小: {rs.get('file_size')}字节")
        if parts:
            lines.append("上传结果: " + " | ".join(parts))

    return "\n".join(lines)


def _summarize_generic(task: TaskRecord) -> str:
    """通用任务摘要（未匹配到专用模板时使用）"""
    p = task.params or {}
    lines = [f"[操作记录-{task.task_type}] 任务#{task.id}"]
    if p:
        # 过滤进度字段后再输出
        filtered_p = _filter_progress_fields(p)
        if filtered_p:
            lines.append(f"参数: {_params_to_str(filtered_p)}")
    rs = _clean_result_summary(task.result_summary)
    if rs:
        lines.append(f"结果: {_params_to_str(rs)}")
    if task.error_message:
        lines.append(f"错误: {task.error_message}")
    return "\n".join(lines)


# task_type → 摘要函数的分发表
_SUMMARIZERS: Dict[str, Callable[[TaskRecord], str]] = {
    "cleaning": _summarize_cleaning,
    "ml_training": _summarize_ml_training,
    "ml": _summarize_ml,
    "data_mining": _summarize_data_mining,
    "data_analysis": _summarize_data_analysis,
    "upload": _summarize_upload,
}
