"""各产物类型的内容提取器

按 artifact_type 分发到对应的提取函数，每个函数返回文本摘要。
摘要字符上限按产物类型分级（见重构方案决策2）。
优先从数据库字段(report_content)读取，避免频繁访问MinIO。
"""
import json
from typing import Dict, Callable
from app.models import Dataset
from app.services.storage_manager import storage_manager


# 各产物类型的摘要字符上限
CHAR_LIMITS: Dict[str, int] = {
    "raw_data": 1500,
    "cleaning_result": 1000,
    "ml_model": 2500,
    "ml_report": 2000,
    "analysis_report": 3000,
    "cluster_result": 1500,
    "association_rules": 3000,
    "sequential_patterns": 3000,
    "feature_result": 1000,
    "analysis_data": 1500,
    "ml_prediction": 1000,
    "predict_data": 1000,
}


def extract_context(dataset: Dataset) -> str:
    """根据产物类型提取上下文摘要文本

    Args:
        dataset: Dataset 模型实例

    Returns:
        提取后的文本摘要，超限时自动截断
    """
    artifact_type = dataset.artifact_type or "raw_data"
    extractor = _EXTRACTORS.get(artifact_type, _extract_raw_data)
    try:
        content = extractor(dataset)
        limit = CHAR_LIMITS.get(artifact_type, 1500)
        if len(content) > limit:
            content = content[:limit] + "\n... (内容已截断)"
        return content
    except Exception as e:
        return f"[提取失败: {artifact_type} #{dataset.id}, 错误: {str(e)}]"


def _parse_json_safe(raw: str) -> dict:
    """安全解析 JSON 字符串，失败时返回空字典"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_schema_fields(schema) -> str:
    """格式化 schema 为"字段名(类型)"列表，减少 token 并避免注入真实数据值

    Args:
        schema: dataset.schema 字段值，已是 Python 对象（JSON Column 自动反序列化）

    Returns:
        格式化后的字符串，如 "age(int64), income(float64), gender(object)"
        schema 为空或异常时返回空字符串
    """
    if not schema:
        return ""
    if isinstance(schema, list):
        field_lines = []
        for field in schema[:30]:  # 最多展示30个字段
            if isinstance(field, dict):
                name = field.get("name", field.get("column", "未知"))
                dtype = field.get("type", field.get("dtype", "未知"))
                field_lines.append(f"{name}({dtype})")
            elif isinstance(field, str):
                field_lines.append(field)
        result = ", ".join(field_lines)
        if len(schema) > 30:
            result += f" (共 {len(schema)} 个字段，已展示前30个)"
        return result
    # dict 或其他格式，保留原样但截断
    try:
        return json.dumps(schema, ensure_ascii=False)[:800]
    except (TypeError, ValueError):
        return ""


def _read_minio_json(file_path: str) -> dict:
    """从 MinIO 读取 JSON 文件并解析"""
    if not file_path:
        return {}
    file_bytes = storage_manager.get_file_bytes(file_path)
    return json.loads(file_bytes.decode("utf-8"))


def _extract_raw_data(dataset: Dataset) -> str:
    """原始数据：名称 + 行数 + 字段结构（不注入真实数据值）

    设计说明：AI 给"使用建议"不需要看真实数据值，只需看字段结构、数据类型。
    """
    lines = [f"[数据集] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"类型: 原始数据 | 行数: {dataset.row_count or '未知'} | 模块: {dataset.module_label or dataset.module_source}")
    if dataset.schema:
        # schema 已是 JSON Column 自动反序列化的 Python 对象，无需 _parse_json_safe
        formatted = _format_schema_fields(dataset.schema)
        if formatted:
            lines.append(f"字段结构: {formatted}")
    # 移除数据预览（不注入真实数据值）
    return "\n".join(lines)


def _extract_cleaning_result(dataset: Dataset) -> str:
    """清洗产物：算法 + 行数 + 字段结构（不注入真实数据值）"""
    lines = [f"[清洗产物] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"行数: {dataset.row_count or '未知'} | 算法: {dataset.algorithm or '未知'}")
    if dataset.schema:
        formatted = _format_schema_fields(dataset.schema)
        if formatted:
            lines.append(f"清洗后字段: {formatted}")
    # 移除数据预览
    return "\n".join(lines)


def _extract_ml_model(dataset: Dataset) -> str:
    """ML模型产物：评估指标 + 超参数 + 特征重要性 + 数据集划分"""
    lines = [f"[机器学习模型] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"算法: {dataset.algorithm or '未知'} | 训练数据量: {dataset.row_count or '未知'}")

    report = _parse_json_safe(dataset.report_content)
    if not report:
        lines.append("(无详细训练报告)")
        return "\n".join(lines)

    # 模型信息
    model_info = report.get("model_info", {})
    if model_info:
        lines.append(f"任务类型: {model_info.get('task_type', '未知')}")
        lines.append(f"目标列: {model_info.get('target_column', '未知')}")
        lines.append(f"特征数: {model_info.get('feature_count', '未知')}")
        feature_cols = model_info.get("feature_columns", [])
        if feature_cols:
            lines.append(f"特征列: {feature_cols}")

    # 训练参数
    training_params = report.get("training_params", {})
    if training_params:
        lines.append(f"训练参数: test_size={training_params.get('test_size')}, cv_folds={training_params.get('cv_folds')}, auto_tune={training_params.get('auto_tune')}")
        if training_params.get("tune_method"):
            lines.append(f"调参方法: {training_params.get('tune_method')}")
        hyperparams = training_params.get("hyperparams", {})
        if hyperparams:
            lines.append(f"超参数: {json.dumps(hyperparams, ensure_ascii=False)}")

    # 评估指标（核心，AI 诊断准确率低的关键依据）
    metrics = report.get("performance_metrics", {})
    if metrics:
        lines.append(f"评估指标: {json.dumps(metrics, ensure_ascii=False)}")

    # 特征重要性 Top10
    feature_importance = report.get("feature_importance", [])
    if feature_importance:
        top10 = feature_importance[:10] if isinstance(feature_importance, list) else feature_importance
        lines.append(f"特征重要性Top10: {json.dumps(top10, ensure_ascii=False)}")

    # 数据集划分
    split_info = report.get("dataset_split", {})
    if split_info:
        lines.append(f"数据集划分: {json.dumps(split_info, ensure_ascii=False)}")

    # 最优参数（调参后）
    best_params = report.get("best_params", {})
    if best_params:
        lines.append(f"最优参数: {json.dumps(best_params, ensure_ascii=False)}")

    return "\n".join(lines)


def _extract_ml_report(dataset: Dataset) -> str:
    """ML报告产物：直接读取 report_content"""
    lines = [f"[ML分析报告] {dataset.name} (ID:{dataset.id})"]
    report = _parse_json_safe(dataset.report_content)
    if report:
        lines.append(f"算法: {report.get('algorithm', '未知')}")
        lines.append(f"报告内容: {json.dumps(report, ensure_ascii=False)}")
    else:
        lines.append("(报告内容为空)")
    return "\n".join(lines)


def _extract_analysis_report(dataset: Dataset) -> str:
    """分析报告产物：提取 HTML 摘要 + dynamic_data 关键字段"""
    lines = [f"[数据分析报告] {dataset.name} (ID:{dataset.id})"]
    report = _parse_json_safe(dataset.report_content)
    if not report:
        lines.append("(报告内容为空)")
        return "\n".join(lines)

    # dynamic_data 包含图表数据等结构化信息，优先提取
    dynamic_data = report.get("dynamic_data", {})
    if dynamic_data:
        lines.append(f"动态数据: {json.dumps(dynamic_data, ensure_ascii=False)[:2000]}")

    # HTML 报告提取纯文本摘要（去除标签）
    html = report.get("html", "")
    if html:
        # 简易去标签：提取文本内容
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 1000:
            text = text[:1000] + "..."
        lines.append(f"报告摘要: {text}")

    return "\n".join(lines)


def _extract_cluster_result(dataset: Dataset) -> str:
    """聚类产物：统计报告（轮廓系数/簇分布）+ 参数

    依赖阶段1补丁：report_content 中保存了 cluster_report
    """
    lines = [f"[聚类结果] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"算法: {dataset.algorithm or '未知'} | 结果行数: {dataset.row_count or '未知'}")

    report = _parse_json_safe(dataset.report_content)
    if report:
        lines.append(f"实际簇数: {report.get('n_clusters', '未知')}")
        silhouette = report.get("silhouette")
        lines.append(f"轮廓系数: {silhouette if silhouette is not None else '未计算'}")
        noise_count = report.get("noise_count", 0)
        if noise_count:
            lines.append(f"噪声点: {noise_count} ({report.get('noise_percentage', 0)}%)")
        cluster_stats = report.get("cluster_stats", [])
        if cluster_stats:
            lines.append(f"簇分布: {json.dumps(cluster_stats, ensure_ascii=False)}")
        params_used = report.get("params_used", {})
        if params_used:
            lines.append(f"使用参数: {json.dumps(params_used, ensure_ascii=False)}")
    else:
        lines.append("(无统计报告，可能为旧数据)")

    return "\n".join(lines)


def _extract_association_rules(dataset: Dataset) -> str:
    """关联规则产物：Top10规则 + 统计范围

    优先从 report_content 读取（阶段1补丁后），回退到 MinIO JSON 文件
    """
    lines = [f"[关联规则] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"算法: {dataset.algorithm or '未知'} | 规则数: {dataset.row_count or '未知'}")

    report = _parse_json_safe(dataset.report_content)
    if not report:
        # 回退：从 MinIO 读取 JSON 文件
        report = _read_minio_json(dataset.file_path)

    if report:
        total = report.get("total_rules", dataset.row_count or 0)
        lines.append(f"总规则数: {total}")

        support_range = report.get("support_range", [None, None])
        confidence_range = report.get("confidence_range", [None, None])
        lift_range = report.get("lift_range", [None, None])
        if support_range[0] is not None:
            lines.append(f"支持度范围: {support_range[0]} ~ {support_range[1]}")
        if confidence_range[0] is not None:
            lines.append(f"置信度范围: {confidence_range[0]} ~ {confidence_range[1]}")
        if lift_range[0] is not None:
            lines.append(f"提升度范围: {lift_range[0]} ~ {lift_range[1]}")

        top_rules = report.get("top_rules", [])
        if not top_rules:
            # MinIO 回退路径下 top_rules 可能在 rules 字段
            all_rules = report.get("rules", [])
            top_rules = all_rules[:10]
        if top_rules:
            lines.append(f"Top规则: {json.dumps(top_rules[:10], ensure_ascii=False)}")

        parameters = report.get("parameters", {})
        if parameters:
            lines.append(f"挖掘参数: {json.dumps(parameters, ensure_ascii=False)}")
    else:
        lines.append("(无规则数据)")

    return "\n".join(lines)


def _extract_sequential_patterns(dataset: Dataset) -> str:
    """序列模式产物：Top10模式 + 统计范围

    优先从 report_content 读取（阶段1补丁后），回退到 MinIO JSON 文件
    """
    lines = [f"[序列模式] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"算法: {dataset.algorithm or '未知'} | 模式数: {dataset.row_count or '未知'}")

    report = _parse_json_safe(dataset.report_content)
    if not report:
        report = _read_minio_json(dataset.file_path)

    if report:
        total = report.get("total_patterns", dataset.row_count or 0)
        lines.append(f"总模式数: {total}")

        support_range = report.get("support_range", [None, None])
        if support_range[0] is not None:
            lines.append(f"支持度范围: {support_range[0]} ~ {support_range[1]}")

        top_patterns = report.get("top_patterns", [])
        if not top_patterns:
            all_patterns = report.get("patterns", [])
            top_patterns = all_patterns[:10]
        if top_patterns:
            lines.append(f"Top模式: {json.dumps(top_patterns[:10], ensure_ascii=False)}")

        parameters = report.get("parameters", {})
        if parameters:
            lines.append(f"挖掘参数: {json.dumps(parameters, ensure_ascii=False)}")
    else:
        lines.append("(无模式数据)")

    return "\n".join(lines)


def _extract_feature_result(dataset: Dataset) -> str:
    """特征工程产物：选中特征列名 + schema（不注入真实数据值）"""
    lines = [f"[特征工程产物] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"行数: {dataset.row_count or '未知'} | 算法: {dataset.algorithm or '未知'}")
    if dataset.schema:
        # schema 中包含选中后的字段列表
        formatted = _format_schema_fields(dataset.schema)
        if formatted:
            lines.append(f"特征列: {formatted}")
    # 移除数据预览
    return "\n".join(lines)


def _extract_ml_prediction(dataset: Dataset) -> str:
    """预测结果产物：行数 + 算法（不注入真实数据值）

    说明：预测结果的真实值对 AI 给"使用建议"无价值，且可能含敏感信息。
    """
    lines = [f"[预测结果] {dataset.name} (ID:{dataset.id})"]
    lines.append(f"预测行数: {dataset.row_count or '未知'} | 模型: {dataset.algorithm or '未知'}")
    # 移除数据预览
    return "\n".join(lines)


# 产物类型 → 提取函数的分发表
_EXTRACTORS: Dict[str, Callable[[Dataset], str]] = {
    "raw_data": _extract_raw_data,
    "cleaning_result": _extract_cleaning_result,
    "ml_model": _extract_ml_model,
    "ml_report": _extract_ml_report,
    "analysis_report": _extract_analysis_report,
    "cluster_result": _extract_cluster_result,
    "association_rules": _extract_association_rules,
    "sequential_patterns": _extract_sequential_patterns,
    "feature_result": _extract_feature_result,
    "analysis_data": _extract_raw_data,
    "ml_prediction": _extract_ml_prediction,
    "predict_data": _extract_raw_data,
}
