"""上下文包构建器

将用户选择的上下文项（数据产物 + 操作记录）聚合为分层上下文包，
构建可注入 LLM 系统提示词的文本段落。

分层结构：
  Layer 1 - 数据上下文：用户选的数据产物摘要
  Layer 2 - 操作上下文：用户选的任务记录摘要
  Layer 3 - 系统知识：系统模块清单与产物类型说明（自动注入）
"""
import os
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from app.models import Dataset, TaskRecord
from app.services.ai_context.extractors import extract_context
from app.services.ai_context.task_summarizer import summarize_task


# prompts 目录的绝对路径
_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# prompt 文件缓存（避免每次 IO）
_prompt_cache: Dict[str, str] = {}


def _load_prompt(filename: str) -> str:
    """加载 prompt 文件内容，带缓存

    Args:
        filename: prompts 目录下的文件名，如 "system_prompt.txt"

    Returns:
        文件文本内容
    """
    if filename in _prompt_cache:
        return _prompt_cache[filename]

    filepath = os.path.join(_PROMPTS_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        _prompt_cache[filename] = content
        return content
    except FileNotFoundError:
        return f"(提示词文件缺失: {filename})"


class ContextItem:
    """单个上下文项

    type="dataset" 时 ref_id 为 Dataset.id
    type="operation" 时 ref_id 为 TaskRecord.id
    """

    def __init__(self, item_type: str, ref_id: int):
        self.item_type = item_type  # "dataset" | "operation"
        self.ref_id = ref_id
        self.label: str = ""        # 显示名称
        self.artifact_type: str = ""  # 产物类型（dataset 专有）
        self.summary: str = ""      # 提取后的文本摘要

    def to_dict(self) -> dict:
        return {
            "type": self.item_type,
            "ref_id": self.ref_id,
            "label": self.label,
            "artifact_type": self.artifact_type,
        }


class ContextBundle:
    """上下文包：聚合多个 ContextItem，构建注入 prompt 的文本"""

    def __init__(self):
        self.items: List[ContextItem] = []

    def add_item(self, item: ContextItem):
        self.items.append(item)

    def total_chars(self) -> int:
        return sum(len(item.summary) for item in self.items)

    def is_over_limit(self, limit: int = 20000) -> bool:
        return self.total_chars() > limit

    def build_prompt_section(self) -> str:
        """构建注入到 LLM 系统提示词的上下文段落

        分三段：数据上下文 + 操作上下文 + 系统知识
        """
        sections = []

        # Layer 3: 系统知识（自动注入）
        system_knowledge = _load_prompt("system_knowledge.txt")
        if system_knowledge:
            sections.append(system_knowledge)

        # Layer 1: 数据上下文
        dataset_items = [it for it in self.items if it.item_type == "dataset"]
        if dataset_items:
            data_lines = ["[数据上下文]"]
            for item in dataset_items:
                data_lines.append(item.summary)
            sections.append("\n".join(data_lines))

        # Layer 2: 操作上下文
        operation_items = [it for it in self.items if it.item_type == "operation"]
        if operation_items:
            op_lines = ["[操作上下文]"]
            for item in operation_items:
                op_lines.append(item.summary)
            sections.append("\n".join(op_lines))

        return "\n\n".join(sections) if sections else ""


def build_context_bundle(
    db: Session,
    user_id: int,
    context_requests: List[Dict]
) -> ContextBundle:
    """从数据库构建上下文包

    Args:
        db: 数据库会话
        user_id: 当前用户 ID（仅查询该用户的数据）
        context_requests: 上下文项请求列表，每项 {"type": "dataset"/"operation", "ref_id": int}

    Returns:
        填充好的 ContextBundle
    """
    bundle = ContextBundle()

    # 收集所有上下文项的 root_dataset_id，用于数据血缘关联判断
    bloodline_ids = set()

    for req in context_requests:
        item_type = req.get("type", "dataset")
        ref_id = req.get("ref_id")
        if not ref_id:
            continue

        item = ContextItem(item_type, ref_id)

        if item_type == "dataset":
            # 查询数据产物（仅当前用户的 active 数据，回收站不开放）
            dataset = db.query(Dataset).filter(
                Dataset.id == ref_id,
                Dataset.user_id == user_id,
                Dataset.status == "active"
            ).first()
            if dataset:
                # label 带 id，便于前端面板与引用区分同名数据集
                item.label = f"{dataset.name} (ID:{dataset.id})"
                item.artifact_type = dataset.artifact_type or "raw_data"
                item.summary = extract_context(dataset)
                # 收集数据血缘ID
                root_id = getattr(dataset, "root_dataset_id", None) or dataset.id
                bloodline_ids.add(root_id)
            else:
                item.label = f"数据集#{ref_id}(不存在或已删除)"
                item.summary = f"[数据集 #{ref_id} 不存在或已删除]"

        elif item_type == "operation":
            # 查询任务记录
            task = db.query(TaskRecord).filter(
                TaskRecord.id == ref_id,
                TaskRecord.user_id == user_id
            ).first()
            if task:
                item.label = f"任务#{ref_id}({task.task_type})"
                item.artifact_type = task.task_type or "unknown"
                item.summary = summarize_task(task)
                # 收集任务关联数据集的数据血缘ID（仅有效的本地数据集ID）
                params = task.params or {}
                is_remote = bool(params.get("is_remote"))
                dataset_id = task.dataset_id
                if dataset_id and dataset_id > 0:
                    task_ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
                    if task_ds:
                        root_id = getattr(task_ds, "root_dataset_id", None) or task_ds.id
                        bloodline_ids.add(root_id)
                        # 标记数据集状态，用于AI提示。
                        # 仅本地数据源任务会提示回收站/已删除；远程任务的数据源在远程表，
                        # 本地产物/载体即使被删也不代表数据丢失，不应误导用户去恢复。
                        if not is_remote and task_ds.status in ("deleted", "purged"):
                            status_text = "回收站" if task_ds.status == "deleted" else "已永久删除"
                            item.summary += f"\n[注：关联数据集'{task_ds.name}'当前在{status_text}]"
            else:
                item.label = f"任务#{ref_id}(不存在)"
                item.summary = f"[任务记录 #{ref_id} 不存在]"

        bundle.add_item(item)

    # 数据血缘关联判断：如果用户同时选了多个上下文项，检查它们是否属于同一数据血缘
    if len(bloodline_ids) > 1:
        _add_bloodline_warning(bundle, bloodline_ids)

    return bundle


def _add_bloodline_warning(bundle: "ContextBundle", bloodline_ids: set):
    """为上下文包添加数据血缘关联警告

    当用户选择的上下文项来自不同数据血缘时，在摘要中标注，帮助 AI 判断是否应该关联分析。

    Args:
        bundle: 上下文包
        bloodline_ids: 所有上下文项的 root_dataset_id 集合
    """
    # 在每个操作记录项的摘要末尾追加血缘警告
    for item in bundle.items:
        if item.item_type == "operation" and item.summary and not item.summary.startswith("[任务记录"):
            item.summary += "\n[注意: 此操作记录与所选数据产物不属于同一数据血缘，可能无关联]"


def build_system_prompt(bundle: ContextBundle, conversation_id: Optional[int] = None) -> str:
    """构建完整的系统提示词

    组合顺序：系统主提示词 + 上下文格式说明 + 上下文段落 + 诊断/引导模板

    Args:
        bundle: 上下文包
        conversation_id: 会话 ID（用于让 AI 知道当前会话）

    Returns:
        完整的系统提示词文本
    """
    parts = []

    # 系统主提示词（定义 AI 角色、能力边界、输出格式要求）
    main_prompt = _load_prompt("system_prompt.txt")
    if main_prompt:
        parts.append(main_prompt)

    # 上下文格式说明（让 AI 理解注入的上下文结构，放在实际上下文之前）
    context_format = _load_prompt("context_format.txt")
    if context_format:
        parts.append(context_format)

    # 上下文段落（数据上下文 + 操作上下文 + 系统知识）
    context_section = bundle.build_prompt_section()
    if context_section:
        parts.append(context_section)

    # 诊断/引导模板（同时注入，让 AI 根据上下文充分度自行选择模式）
    diagnosis_template = _load_prompt("diagnosis_template.txt")
    if diagnosis_template:
        parts.append(diagnosis_template)

    guidance_template = _load_prompt("guidance_template.txt")
    if guidance_template:
        parts.append(guidance_template)

    return "\n\n".join(parts)
