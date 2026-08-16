"""AI 追问预设库与动态追问过滤

本模块提供：
1. PRESET_FOLLOWUPS：预设追问模板，按场景分类，AI 可通过 preset ID 引用
2. get_preset_by_ids：根据 preset ID 列表获取文案
3. validate_dynamic_question：校验 AI 动态生成的追问是否合法（防幻觉）
4. filter_dynamic_questions：批量过滤动态追问

设计原则：
- 预设库内容必须基于平台真实功能，不包含系统不支持的能力
- 追问文案必须是"用户追问 AI"的视角，用户点击后是向 AI 提问，而不是 AI 反问用户
- 动态追问过滤规则保守，避免误杀合法追问
"""

from typing import List, Optional, Set


# 不支持的功能关键词（AI 动态追问若包含这些关键词则过滤）
# 注意：同时收录"模型部署"和"部署模型"两种词序，覆盖 AI 可能的变体表达
UNSUPPORTED_FEATURES = {
    "实时流处理", "在线学习", "深度学习", "神经网络训练",
    "生成对抗网络", "GAN", "变分自编码器", "VAE",
    "自然语言生成", "图像识别", "语音识别",
    "自动建模", "AutoML", "模型部署", "部署模型", "API 部署",
    "大模型", "LLM", "微调", "fine-tuning",
}

# 预设追问库
# key 为 preset ID（q1-q26），value 为 {text, scene, priority}
# 文案视角：用户追问 AI（用户点击后是向 AI 提问，不是 AI 反问用户）
PRESET_FOLLOWUPS = {
    # === 通用深入类（q1-q6） ===
    "q1": {
        "text": "这个结果中最值得关注的是什么？",
        "scene": "通用",
        "priority": 1,
    },
    "q2": {
        "text": "结果中有哪些异常或需要注意的地方？",
        "scene": "通用",
        "priority": 1,
    },
    "q3": {
        "text": "如果要进一步分析，应该从哪个方向入手？",
        "scene": "通用",
        "priority": 2,
    },
    "q4": {
        "text": "这个结果可以支撑什么业务决策？",
        "scene": "通用",
        "priority": 2,
    },
    "q5": {
        "text": "结果中有哪些局限性需要补充数据验证？",
        "scene": "通用",
        "priority": 3,
    },
    "q6": {
        "text": "如何把这个分析结果可视化呈现给非技术人员？",
        "scene": "通用",
        "priority": 3,
    },

    # === 数据质量与清洗类（q7-q10） ===
    "q7": {
        "text": "当前数据集存在哪些质量问题？",
        "scene": "数据质量",
        "priority": 1,
    },
    "q8": {
        "text": "当前的缺失值和异常值处理策略是否合理？",
        "scene": "数据质量",
        "priority": 1,
    },
    "q9": {
        "text": "清洗后的数据是否适合直接进入特征工程？",
        "scene": "数据质量",
        "priority": 2,
    },
    "q10": {
        "text": "去重策略是否过度删除了有效数据？",
        "scene": "数据质量",
        "priority": 2,
    },

    # === 模型与机器学习类（q11-q14） ===
    "q11": {
        "text": "当前模型准确率偏低的原因是什么？如何改进？",
        "scene": "模型诊断",
        "priority": 1,
    },
    "q12": {
        "text": "当前特征数量是否合理？是否需要做特征选择？",
        "scene": "模型诊断",
        "priority": 1,
    },
    "q13": {
        "text": "训练集和验证集的指标差距大吗？是否过拟合？",
        "scene": "模型诊断",
        "priority": 2,
    },
    "q14": {
        "text": "模型的超参数还有调优空间吗？",
        "scene": "模型诊断",
        "priority": 2,
    },

    # === 挖掘结果深入类（q15-q18） ===
    "q15": {
        "text": "当前聚类结果的轮廓系数是否达到良好水平？",
        "scene": "挖掘解读",
        "priority": 1,
    },
    "q16": {
        "text": "当前关联规则的提升度是否表明规则有效？",
        "scene": "挖掘解读",
        "priority": 1,
    },
    "q17": {
        "text": "当前簇分布是否均衡？有无过小或过大的簇？",
        "scene": "挖掘解读",
        "priority": 2,
    },
    "q18": {
        "text": "Top 规则的业务含义是什么？如何应用？",
        "scene": "挖掘解读",
        "priority": 2,
    },

    # === 改进与下一步类（q19-q24） ===
    "q19": {
        "text": "如果要提升模型效果，应该从哪些方面入手？",
        "scene": "改进方向",
        "priority": 1,
    },
    "q20": {
        "text": "当前分析流程是否缺少关键步骤？",
        "scene": "改进方向",
        "priority": 1,
    },
    "q21": {
        "text": "下一步建议在哪个模块执行什么操作？",
        "scene": "改进方向",
        "priority": 2,
    },
    "q22": {
        "text": "如何把当前结果作为下一步分析的输入？",
        "scene": "改进方向",
        "priority": 2,
    },
    "q23": {
        "text": "如果数据量增大 10 倍，当前方案是否仍然适用？",
        "scene": "改进方向",
        "priority": 3,
    },
    "q24": {
        "text": "这个失败任务重新执行前应调整哪些参数？",
        "scene": "改进方向",
        "priority": 1,
    },

    # === 上下文不足场景类（q25-q26） ===
    # 适用于用户给了部分上下文但未给原始数据的情况
    "q25": {
        "text": "当前上下文能分析哪些数据问题？",
        "scene": "上下文不足",
        "priority": 1,
    },
    "q26": {
        "text": "基于已有上下文，能给出哪些初步结论？",
        "scene": "上下文不足",
        "priority": 1,
    },
}


def get_preset_by_ids(ids: List[str]) -> List[str]:
    """根据 preset ID 列表获取追问文案

    Args:
        ids: preset ID 列表，如 ["q1", "q8", "q15"]

    Returns:
        文案列表，顺序与输入一致；不存在的 ID 静默跳过
    """
    return [PRESET_FOLLOWUPS[qid]["text"] for qid in ids if qid in PRESET_FOLLOWUPS]


def validate_dynamic_question(question: str, context_params: Optional[Set[str]] = None) -> bool:
    """校验 AI 动态生成的追问是否合法（防幻觉）

    Args:
        question: AI 动态生成的追问
        context_params: 当前上下文中真实存在的参数名和指标名（可选，预留扩展）

    Returns:
        True 表示合法，False 表示需要过滤
    """
    if not question or not question.strip():
        return False

    question = question.strip()

    # 规则1：长度校验（10-60字，上限放宽避免误杀复杂中文追问）
    if len(question) < 10 or len(question) > 60:
        return False

    # 规则2：检查是否包含不支持的功能关键词
    for keyword in UNSUPPORTED_FEATURES:
        if keyword in question:
            return False

    return True


def filter_dynamic_questions(questions: List[str], context_params: Optional[Set[str]] = None) -> List[str]:
    """批量过滤 AI 动态生成的追问

    Args:
        questions: AI 动态生成的追问列表
        context_params: 当前上下文中真实存在的参数名和指标名（可选）

    Returns:
        过滤后的合法追问列表，保持原顺序，最多保留 3 条
    """
    result = []
    for q in questions:
        if validate_dynamic_question(q, context_params):
            result.append(q.strip())
        if len(result) >= 3:  # 动态追问最多保留 3 条
            break
    return result
