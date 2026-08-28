import json
import re
from openai import OpenAI
from datetime import datetime, timedelta
from app.config import settings
from app.services.data_service import DataService
from app.models import AIConfig, AIConversation, AIUsageLog, Dataset, AIMessage, AIConversationContext, TaskRecord, shanghai_now
from app.services.ai_context import build_context_bundle, build_system_prompt, compress_conversation
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List


def _normalize_task_group(task_type: str) -> str:
    """任务类型 → 前端分组 key

    特征工程 5 个子类型（select/construct/encode/scale/reduce）归并为 feature_engineering；
    机器学习两类（ml 分析 / ml_training 训练）归并为 ml。其余 task_type 原样返回。

    Args:
        task_type: 任务记录原始 task_type

    Returns:
        归一化后的分组 key
    """
    if task_type.startswith("feature_engineering"):
        return "feature_engineering"
    if task_type in ("ml", "ml_training"):
        return "ml"
    return task_type


class AIService:
    """AI分析服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.data_service = DataService(db)
        self._clients = None
        self._default_client = None
    
    def _get_clients(self):
        """懒加载AI客户端，优先使用系统API Key"""
        if self._clients is None:
            self._clients = {}
            self._default_client = None
            
            if settings.OPENAI_API_KEY:
                try:
                    kwargs = {"api_key": settings.OPENAI_API_KEY}
                    if settings.OPENAI_API_BASE:
                        kwargs["base_url"] = settings.OPENAI_API_BASE
                    client = OpenAI(**kwargs)
                    self._clients["openai"] = client
                    self._default_client = "openai"
                except Exception:
                    pass
            else:
                db_config = self._get_active_config()
                if db_config:
                    try:
                        client = self._create_client_from_config(db_config)
                        if client:
                            self._clients[db_config.provider] = client
                            self._default_client = db_config.provider
                    except Exception:
                        pass
        
        return self._clients
    
    def _create_client_from_config(self, config: AIConfig) -> Optional[OpenAI]:
        """根据配置创建AI客户端"""
        if not config or not config.api_key:
            return None
        
        base_url = config.base_url
        if not base_url:
            if config.provider == "deepseek":
                base_url = "https://api.deepseek.com"
            elif config.provider == "openai":
                base_url = None
        
        try:
            if base_url:
                return OpenAI(api_key=config.api_key, base_url=base_url)
            else:
                return OpenAI(api_key=config.api_key)
        except Exception:
            return None
    
    # ========== 配置管理方法 ==========

    def _get_active_config(self) -> Optional[AIConfig]:
        """获取当前激活的AI配置"""
        try:
            config = self.db.query(AIConfig).filter(AIConfig.is_active == True).first()
            return config
        except Exception:
            return None

    def get_config(self) -> Dict[str, Any]:
        """获取AI配置状态，优先使用系统API Key"""
        if settings.OPENAI_API_KEY:
            return {
                "is_configured": True,
                "provider": "openai",
                "model": settings.OPENAI_MODEL,
                "is_system_key": True
            }
        
        config = self._get_active_config()
        if config:
            return {
                "is_configured": True,
                "provider": config.provider,
                "model": config.model,
                "is_system_key": False
            }
        return {
            "is_configured": False,
            "provider": None,
            "model": None,
            "is_system_key": False
        }

    def save_config(self, provider: str, api_key: str, model: str, base_url: Optional[str] = None) -> Dict[str, Any]:
        """保存AI配置，先删除旧的激活配置，创建新的并设为激活"""
        try:
            self.db.query(AIConfig).filter(AIConfig.is_active == True).update({"is_active": False})
            
            new_config = AIConfig(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                is_active=True
            )
            self.db.add(new_config)
            self.db.commit()
            
            self._clients = None
            self._default_client = None
            
            return {"success": True, "message": "配置保存成功"}
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"配置保存失败: {str(e)}"}

    def test_config(self, provider: str, api_key: str, model: str, base_url: Optional[str] = None) -> Dict[str, Any]:
        """测试AI配置连接"""
        try:
            temp_config = AIConfig(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url
            )
            client = self._create_client_from_config(temp_config)
            
            if not client:
                return {"success": False, "message": "无法创建客户端，请检查配置"}
            
            test_message = "请回复'连接成功'来确认配置有效。"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": test_message}],
                max_tokens=10,
                temperature=0
            )
            
            if response and response.choices:
                return {"success": True, "message": "连接测试成功"}
            else:
                return {"success": False, "message": "未收到有效响应"}
                
        except Exception as e:
            return {"success": False, "message": f"连接测试失败: {str(e)}"}

    # ========== 会话管理方法 ==========

    def create_conversation(self, dataset_id: int, module_type: str, initial_message: str = "", user_id: int = 1) -> AIConversation:
        """创建新会话

        initial_message 仅用于生成标题，不写入 conversation JSON，
        避免与后续 _save_message 写入的 user 消息产生重复。
        """
        expires_at = datetime.utcnow() + timedelta(minutes=settings.AI_CONVERSATION_TTL_MINUTES)

        module_names = {
            "data_cleaning": "数据清洗",
            "data_mining": "数据挖掘",
            "feature_engineering": "特征工程",
            "machine_learning": "机器学习",
            "comprehensive": "全方位分析",
            "general_chat": "智能对话"
        }
        module_name = module_names.get(module_type, module_type)
        title = f"{module_name}分析 · {shanghai_now().strftime('%Y-%m-%d %H:%M')}"

        new_conv = AIConversation(
            user_id=user_id,
            dataset_id=dataset_id,
            module_type=module_type,
            title=title,
            conversation=[],
            follow_up_remaining=settings.AI_CONVERSATION_FOLLOWUP_MAX,
            expires_at=expires_at
        )
        
        self.db.add(new_conv)
        self.db.commit()
        self.db.refresh(new_conv)
        
        return new_conv

    def get_conversation(self, conversation_id: int, user_id: int = None) -> Optional[AIConversation]:
        """获取会话详情"""
        query = self.db.query(AIConversation).filter(
            AIConversation.id == conversation_id
        )
        if user_id is not None:
            query = query.filter(AIConversation.user_id == user_id)
        conv = query.first()
        return conv

    def update_conversation(self, conversation_id: int, messages: List[Dict[str, Any]] = None,
                            follow_up_remaining: int = None) -> Optional[AIConversation]:
        """更新会话"""
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        if messages is not None:
            conv.conversation = messages

        if follow_up_remaining is not None:
            conv.follow_up_remaining = follow_up_remaining

        conv.expires_at = datetime.utcnow() + timedelta(minutes=settings.AI_CONVERSATION_TTL_MINUTES)
        conv.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(conv)

        return conv

    def rename_conversation(self, conversation_id: int, new_title: str, user_id: int = None) -> Dict[str, Any]:
        """重命名会话标题（支持重名校验）

        Args:
            conversation_id: 会话ID
            new_title: 新标题
            user_id: 用户ID（用于权限校验和重名校验）

        Returns:
            {"success": bool, "error": str}
        """
        if not new_title or not new_title.strip():
            return {"success": False, "error": "标题不能为空"}

        new_title = new_title.strip()
        if len(new_title) > 100:
            return {"success": False, "error": "标题不能超过100个字符"}

        conv = self.get_conversation(conversation_id, user_id=user_id)
        if not conv:
            return {"success": False, "error": "会话不存在或无权限"}

        # 重名校验：同一用户下会话标题不能重复
        existing = self.db.query(AIConversation).filter(
            AIConversation.user_id == conv.user_id,
            AIConversation.title == new_title,
            AIConversation.id != conversation_id
        ).first()
        if existing:
            return {"success": False, "error": "会话名称已存在，请使用其他名称"}

        conv.title = new_title
        conv.updated_at = datetime.utcnow()
        self.db.commit()
        return {"success": True, "error": None}

    def get_conversations(self, user_id: int = None) -> List[Dict[str, Any]]:
        """获取会话列表（按时间倒序），包含消息计数"""
        query = self.db.query(AIConversation)
        if user_id is not None:
            query = query.filter(AIConversation.user_id == user_id)
        conversations = query.order_by(AIConversation.updated_at.desc()).all()

        result = []
        for conv in conversations:
            # 计算消息数量（排除系统消息）
            msg_count = 0
            if conv.conversation and isinstance(conv.conversation, list):
                msg_count = len([
                    msg for msg in conv.conversation
                    if isinstance(msg, dict) and msg.get("role") in ("user", "assistant")
                ])

            result.append({
                "id": conv.id,
                "title": conv.title,
                "module_type": conv.module_type,
                "dataset_id": conv.dataset_id,
                "message_count": msg_count,
                "follow_up_remaining": conv.follow_up_remaining,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at
            })
        return result

    def delete_conversation(self, conversation_id: int, user_id: int = None) -> bool:
        """删除会话"""
        conv = self.get_conversation(conversation_id, user_id=user_id)
        if not conv:
            return False
        
        self.db.delete(conv)
        self.db.commit()
        return True

    def is_conversation_expired(self, conversation: AIConversation) -> bool:
        """检查会话是否过期"""
        if not conversation.expires_at:
            return False
        return datetime.utcnow() > conversation.expires_at

    # ========== 普通对话（带上下文记忆） ==========

    def chat_with_context(
        self,
        question: str,
        context_items: List[Dict] = None,
        conversation_id: int = None,
        user_id: int = None,
        start_new_topic: bool = False
    ) -> Dict[str, Any]:
        """基于上下文包的AI对话（重构版）

        使用 ContextBundle 构建分层上下文（数据+操作+系统知识），
        支持多轮对话压缩和 [NEEDS_CONTEXT] 标记解析。

        Args:
            question: 用户问题
            context_items: 上下文项列表，每项 {"type": "dataset"/"operation", "ref_id": int}
            conversation_id: 会话ID（可选，不传则创建新会话）
            user_id: 用户ID
            start_new_topic: 是否开始新话题（在会话中插入分割标记，清空之前上下文关联）

        Returns:
            包含回答、会话ID、使用情况、needs_context 的字典
        """
        # 检查AI配置
        client = self._get_clients().get(self._default_client)
        if not client:
            return {"error": "请先配置API Key才能使用AI分析功能"}

        context_items = context_items or []
        user_id = user_id or 1

        # 获取或创建会话
        if conversation_id:
            conv = self.get_conversation(conversation_id, user_id=user_id)
            if not conv:
                return {"error": "会话不存在"}
            # 会话过期检查：30 分钟无活动后禁止继续对话（修复）
            if self.is_conversation_expired(conv):
                return {"error": "会话已过期（长时间无活动），请开始新话题"}
            # 追问次数检查：耗尽后要求开启新会话（修复）
            if getattr(conv, "follow_up_remaining", settings.AI_CONVERSATION_FOLLOWUP_MAX) <= 0:
                return {"error": "本话题追问次数已用完，请开启新会话继续提问"}
        else:
            # 创建新会话：标题取问题前30字符
            title = question[:30] + ("..." if len(question) > 30 else "")
            conv = self.create_conversation(
                dataset_id=None,
                module_type="general_chat",
                initial_message=title,
                user_id=user_id
            )

        # 开始新话题：插入分割标记，清空上下文快照
        if start_new_topic and conversation_id:
            topic_marker = "[话题切换] 用户已开始新话题，之前的数据集和操作记录讨论不再相关，请基于新注入的上下文重新分析。"
            self._save_message(conv.id, "system", topic_marker, None)
            # 清空之前的上下文快照
            conv.last_context_items = None
            # 清空之前的摘要（新话题不继承旧摘要）
            conv.summary = None
            self.db.commit()

        # 持久化上下文项到关联表（新会话或追加上下文时）
        self._save_context_items(conv.id, context_items)

        # 构建上下文包
        bundle = build_context_bundle(self.db, user_id, context_items)

        # 构建系统提示词（含系统知识 + 上下文段落 + 诊断/引导模板）
        system_prompt = build_system_prompt(bundle)

        # 加载历史消息（优先从 ai_messages 表读取，回退到 conversation JSON）
        history_messages = self._load_conversation_messages(conv)

        # 构建完整消息列表：系统提示 + 压缩后的历史 + 当前问题
        all_messages = [{"role": "system", "content": system_prompt}]
        history_only = [m for m in history_messages if m["role"] in ("user", "assistant")]

        # 三级压缩：滑动窗口 + 摘要
        historical_summary = getattr(conv, "summary", None)
        compressed = compress_conversation(history_only, historical_summary)

        # 添加压缩后的历史消息
        for msg in compressed["messages"]:
            all_messages.append(msg)

        # 添加当前问题
        all_messages.append({"role": "user", "content": question})

        try:
            model_name = self._get_model_name()
            response = client.chat.completions.create(
                model=model_name,
                messages=all_messages,
                temperature=0.3,    # 降低随机性，提升 [SUGGESTED_FOLLOWUPS] 标记输出稳定性
                max_tokens=2500     # 兜底，避免回复过长截断导致标记丢失
            )

            answer = response.choices[0].message.content

            # 解析 usage
            if hasattr(response, "usage") and response.usage:
                usage = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                    "is_fallback": False
                }
            else:
                usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "is_fallback": False}

            # 解析 [NEEDS_CONTEXT] 标记
            needs_context = self._parse_needs_context(answer)

            # 从回复中移除 [NEEDS_CONTEXT] 标记
            if needs_context:
                answer = re.sub(r"\[NEEDS_CONTEXT:\s*[^\]]+\]", "", answer).strip()

            # 解析 [SUGGESTED_FOLLOWUPS] 标记，获取追问建议
            suggested_questions, answer = self._parse_suggested_followups(answer)

            # 保存用户消息和AI回复到 ai_messages 表
            self._save_message(conv.id, "user", question, context_items)
            self._save_message(conv.id, "assistant", answer, None, usage.get("total_tokens", 0))

            # 同时更新 conversation JSON（兼容旧前端历史记录功能）
            updated_messages = list(conv.conversation) if conv.conversation else []
            updated_messages.append({"role": "user", "content": question})
            updated_messages.append({"role": "assistant", "content": answer})
            self.update_conversation(conv.id, updated_messages)

            # 追问次数递减并刷新过期时间（无活动会话自动过期）（修复）
            conv.follow_up_remaining = max(0, getattr(conv, "follow_up_remaining", settings.AI_CONVERSATION_FOLLOWUP_MAX) - 1)
            conv.expires_at = datetime.utcnow() + timedelta(minutes=settings.AI_CONVERSATION_TTL_MINUTES)
            self.db.commit()

            # 如果压缩产生了新摘要，更新到数据库
            if compressed["new_summary"]:
                conv.summary = compressed["new_summary"]
                self.db.commit()

            # 保存上下文项快照到会话（便于恢复）
            # last_context_items 是 JSON 列，直接赋值 Python 对象由 SQLAlchemy 序列化
            if context_items:
                conv.last_context_items = context_items
                self.db.commit()

            # 记录使用日志
            self._log_usage(
                conversation_id=conv.id,
                module_type=conv.module_type,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0)
            )

            return {
                "answer": answer,
                "conversation_id": conv.id,
                "usage": usage,
                "needs_context": needs_context,
                "suggested_questions": suggested_questions  # 追问建议列表（preset + dynamic）
            }

        except Exception as e:
            return {"error": f"AI回复生成失败: {str(e)}"}

    def _save_context_items(self, conversation_id: int, context_items: List[Dict]):
        """将上下文项持久化到 ai_conversation_contexts 关联表"""
        if not context_items:
            return
        for item in context_items:
            record = AIConversationContext(
                conversation_id=conversation_id,
                item_type=item.get("type", "dataset"),
                ref_id=item.get("ref_id"),
                artifact_type=item.get("artifact_type", "")
            )
            self.db.add(record)
        self.db.commit()

    def _load_conversation_messages(self, conv: AIConversation) -> List[Dict]:
        """加载会话历史消息

        优先从 ai_messages 表读取（新机制），回退到 conversation JSON（旧机制）
        返回的字典包含 role/content/created_at（created_at 可能缺失）
        """
        # 尝试从 ai_messages 表读取
        db_messages = self.db.query(AIMessage).filter(
            AIMessage.conversation_id == conv.id
        ).order_by(AIMessage.created_at).all()

        if db_messages:
            return [
                {
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None
                }
                for m in db_messages
            ]

        # 回退：从 conversation JSON 读取
        if conv.conversation:
            return [m for m in conv.conversation if isinstance(m, dict) and "role" in m and "content" in m]

        return []

    def _save_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        context_items: List[Dict] = None,
        tokens_used: int = 0
    ):
        """保存单条消息到 ai_messages 表"""
        msg = AIMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            context_items=json.dumps(context_items, ensure_ascii=False) if context_items else None,
            tokens_used=tokens_used
        )
        self.db.add(msg)
        self.db.commit()

    def _parse_needs_context(self, answer: str) -> List[str]:
        """解析 AI 回复中的 [NEEDS_CONTEXT] 标记

        返回需要补充的上下文类型列表（已转为中文标签），如 ["机器学习模型", "操作记录"]
        无标记时返回空列表

        转中文规则：
        - 产物类型（raw_data/ml_model 等）用 ARTIFACT_LABEL_MAP 转中文
        - operation 单独映射为"操作记录"（ARTIFACT_LABEL_MAP 中无此 key）
        - 未映射的类型保留原值
        """
        pattern = r"\[NEEDS_CONTEXT:\s*([^\]]+)\]"
        matches = re.findall(pattern, answer)
        if not matches:
            return []

        from app.utils.task_labels import ARTIFACT_LABEL_MAP

        # operation 不在 ARTIFACT_LABEL_MAP 中，单独映射
        OPERATION_LABEL = "操作记录"

        # 合并所有匹配项中的类型（逗号分隔），并转中文
        result = []
        for match in matches:
            types = [t.strip() for t in match.split(",")]
            for t in types:
                if t == "operation":
                    label = OPERATION_LABEL
                else:
                    label = ARTIFACT_LABEL_MAP.get(t, t)
                result.append(label)
        # 去重
        return list(dict.fromkeys(result))

    def _parse_suggested_followups(self, answer: str):
        """解析 AI 回复中的 [SUGGESTED_FOLLOWUPS] 标记

        返回追问建议列表，包含预设追问和动态追问。

        Args:
            answer: AI 完整回复（含标记）

        Returns:
            Tuple[List[str], str]：
                - 追问建议文案列表（preset + dynamic，去重）
                - 移除标记后的回复正文

        容错策略：
        1. 优先匹配 [SUGGESTED_FOLLOWUPS]...[/SUGGESTED_FOLLOWUPS] 完整标签块
        2. 若 AI 未输出标签包裹（只输出 preset:/dynamic: 行），仍尝试解析这些行
           并从 answer 中移除残留的 preset:/dynamic: 行，避免展示给用户
        3. 若无任何 preset:/dynamic: 行，返回空列表，answer 原样返回（清理裸标签）
        """
        # 正则匹配 [SUGGESTED_FOLLOWUPS] ... [/SUGGESTED_FOLLOWUPS] 块
        pattern = r"\[SUGGESTED_FOLLOWUPS\](.*?)\[/SUGGESTED_FOLLOWUPS\]"
        match = re.search(pattern, answer, re.DOTALL)

        preset_ids = []
        dynamic_questions = []

        if match:
            block_content = match.group(1).strip()

            # 解析 preset IDs 和 dynamic questions
            in_dynamic_section = False
            for line in block_content.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.lower().startswith("preset:"):
                    # preset: q1, q8, q15
                    ids_str = line.split(":", 1)[1].strip()
                    preset_ids = [qid.strip() for qid in ids_str.split(",") if qid.strip()]
                    in_dynamic_section = False
                elif line.lower().startswith("dynamic:"):
                    in_dynamic_section = True
                elif in_dynamic_section:
                    # dynamic 区段后的非空行作为动态追问
                    # 去除可能的 markdown 列表标记（如 "- "、"* "、"+ "、"1. "）
                    cleaned = re.sub(r"^[-*+]\s+|^\d+\.\s+", "", line)
                    if cleaned:
                        dynamic_questions.append(cleaned)
                elif not line.lower().startswith("preset:"):
                    # 兼容 AI 不输出 dynamic 标签、直接列动态追问的情况
                    cleaned = re.sub(r"^[-*+]\s+|^\d+\.\s+", "", line)
                    if cleaned:
                        dynamic_questions.append(cleaned)

            # 从回复中移除整个标记块
            cleaned_answer = re.sub(pattern, "", answer, flags=re.DOTALL).strip()
        else:
            # 容错：AI 未输出标签包裹，尝试识别裸的 preset:/dynamic: 行
            # 场景：AI 直接输出 "preset: q3, q8\ndynamic:\n如何..." 而没有标签包裹
            answer_lines = answer.split("\n")
            remaining_lines = []
            in_bare_dynamic = False

            for line in answer_lines:
                stripped = line.strip()
                # 识别裸 preset 行
                if stripped.lower().startswith("preset:"):
                    ids_str = stripped.split(":", 1)[1].strip()
                    preset_ids = [qid.strip() for qid in ids_str.split(",") if qid.strip()]
                    continue  # 不加入 remaining_lines
                # 识别裸 dynamic 行
                if stripped.lower().startswith("dynamic:"):
                    in_bare_dynamic = True
                    continue  # 不加入 remaining_lines
                # 裸 dynamic 后面的行作为动态追问候选
                if in_bare_dynamic:
                    if stripped:
                        cleaned = re.sub(r"^[-*+]\s+|^\d+\.\s+", "", stripped)
                        if cleaned:
                            dynamic_questions.append(cleaned)
                    continue  # 不加入 remaining_lines
                # 其他行保留
                remaining_lines.append(line)

            cleaned_answer = "\n".join(remaining_lines).strip()
            # 清理可能残留的裸标签
            cleaned_answer = re.sub(r"\[/?SUGGESTED_FOLLOWUPS\]", "", cleaned_answer, flags=re.IGNORECASE).strip()

        # 从预设库获取文案
        from app.services.ai_context.preset_followups import get_preset_by_ids, filter_dynamic_questions
        preset_questions = get_preset_by_ids(preset_ids)

        # 过滤动态追问（防幻觉）
        dynamic_questions = filter_dynamic_questions(dynamic_questions)

        # 合并去重（保持顺序）
        all_questions = []
        seen = set()
        for q in preset_questions + dynamic_questions:
            if q not in seen:
                all_questions.append(q)
                seen.add(q)

        return all_questions, cleaned_answer

    def get_context_options(
        self,
        user_id: int,
        task_page: int = 1,
        task_page_size: int = 20,
        is_remote: bool = None,
        task_type: str = None
    ) -> Dict[str, Any]:
        """获取当前用户可选的上下文项列表

        返回数据产物（扁平列表，带 category/sub_type 两级分类字段）和操作记录（分页，含成功/失败）。
        - 数据产物按 category（大类）和 sub_type（小类）分类，前端自行嵌套分组
        - 操作记录过滤 upload/dataset/ai 三大类（AI 分析用不上这些操作）
        - 包含失败任务（用于 AI 诊断失败原因）
        - 操作记录附带 dataset_name、中文 task_type_label、operation、operation_label
        - 支持按数据来源（is_remote：None=全部/True=远程/False=本地）与模块（task_type，归一化值）筛选
        - 每条操作记录附带 is_remote/remote_connection_name/remote_table_name（远程标识）与 group_key（前端分组 key）

        Args:
            user_id: 当前用户ID
            task_page: 任务记录页码（从1开始）
            task_page_size: 每页任务记录数
            is_remote: 数据来源筛选，None=全部，True=远程数据库，False=本地
            task_type: 模块筛选，支持归一化值（feature_engineering 前缀匹配 5 子类型；ml 匹配 ml+ml_training）
        """
        from app.utils.common import MODULE_LABEL_MAP, ARTIFACT_LABEL_MAP, TASK_TYPE_LABEL_MAP
        from app.utils.task_labels import OPERATION_LABELS
        from sqlalchemy import text as sql_text
        from app.models import DataSourceConnection

        # 数据产物大类映射：artifact_type → category
        # 原始数据(raw_data/analysis_data)归为"原始数据"大类，按 module_source 细分小类
        # 数据挖掘产物(cluster/association/sequence)归为"数据挖掘产物"大类，按 artifact_type 细分小类
        # 机器学习产物(ml_model/ml_report/ml_prediction)归为"机器学习产物"大类，按 artifact_type 细分小类
        DATASET_CATEGORY_MAP = {
            "raw_data": "raw_data",
            "analysis_data": "raw_data",
            "cleaning_result": "cleaning_result",
            "analysis_report": "analysis_report",
            "cluster_result": "data_mining",
            "association_rules": "data_mining",
            "sequential_patterns": "data_mining",
            "feature_result": "feature_engineering",
            "ml_model": "ml",
            "ml_report": "ml",
            "ml_prediction": "ml",
            "predict_data": "ml",
        }
        # 大类中文名
        CATEGORY_LABEL_MAP = {
            "raw_data": "原始数据",
            "cleaning_result": "数据清洗产物",
            "analysis_report": "数据分析报告",
            "data_mining": "数据挖掘产物",
            "feature_engineering": "特征工程产物",
            "ml": "机器学习产物",
        }
        # 原始数据小类按 module_source 映射（特征工程的原始数据归"特征工程模块"）
        RAW_DATA_SUBTYPE_BY_MODULE = {
            "upload": "原始数据",
            "cleaning": "数据清洗模块",
            "data_analysis": "数据分析模块",
            "data_mining": "数据挖掘模块",
            "feature_engineering": "特征工程模块",
            "ml": "机器学习模块",
            "batch_predict": "机器学习模块",
        }
        # 数据挖掘小类中文名
        DATA_MINING_SUBTYPE_LABEL = {
            "cluster_result": "聚类结果",
            "association_rules": "关联规则",
            "sequential_patterns": "序列模式",
        }
        # 机器学习小类中文名
        ML_SUBTYPE_LABEL = {
            "ml_model": "机器学习模型",
            "ml_report": "机器学习报告",
            "ml_prediction": "预测结果",
            "predict_data": "预测数据",
        }

        # 查询用户所有 active 数据产物
        datasets = self.db.query(Dataset).filter(
            Dataset.user_id == user_id,
            Dataset.status == "active"
        ).order_by(Dataset.created_at.desc()).all()

        # 构建扁平列表，每项带 category/sub_type 两级分类
        dataset_list = []
        for ds in datasets:
            module = ds.module_source or "other"
            artifact_type = ds.artifact_type or "raw_data"
            category = DATASET_CATEGORY_MAP.get(artifact_type, "raw_data")
            category_label = CATEGORY_LABEL_MAP.get(category, category)

            # 计算小类 sub_type 和 sub_type_label
            sub_type = ""
            sub_type_label = ""
            if category == "raw_data":
                # 原始数据按 module_source 细分小类
                sub_type = module
                sub_type_label = RAW_DATA_SUBTYPE_BY_MODULE.get(module, module)
            elif category == "data_mining":
                # 数据挖掘产物按 artifact_type 细分小类
                sub_type = artifact_type
                sub_type_label = DATA_MINING_SUBTYPE_LABEL.get(artifact_type, artifact_type)
            elif category == "ml":
                # 机器学习产物按 artifact_type 细分小类
                sub_type = artifact_type
                sub_type_label = ML_SUBTYPE_LABEL.get(artifact_type, artifact_type)
            elif category == "feature_engineering":
                # 特征工程产物按 algorithm 字段细分小类（特征选择导出/列池导出）
                algorithm = ds.algorithm or ""
                if "特征选择" in algorithm:
                    sub_type = "feature_selected"
                    sub_type_label = "特征选择导出"
                elif "列池导出" in algorithm or "列池" in algorithm:
                    sub_type = "feature_pool"
                    sub_type_label = "列池导出"
                else:
                    sub_type = "feature_result"
                    sub_type_label = "特征工程产物"
            # cleaning_result 和 analysis_report 无小类

            dataset_list.append({
                "id": ds.id,
                "name": ds.name,
                "artifact_type": artifact_type,
                "artifact_label": ARTIFACT_LABEL_MAP.get(artifact_type, artifact_type),
                "module_source": module,
                "module_label": MODULE_LABEL_MAP.get(module, module),
                "category": category,
                "category_label": category_label,
                "sub_type": sub_type,
                "sub_type_label": sub_type_label,
                "row_count": ds.row_count,
                "algorithm": ds.algorithm,
                "created_at": ds.created_at.isoformat() if ds.created_at else None
            })

        # 操作记录过滤的大类（AI 分析用不上：文件上传、数据治理、AI分析）
        EXCLUDED_TASK_TYPES = {"upload", "dataset", "ai"}

        # 查询任务记录总数（过滤 upload/dataset/ai 三大类）
        task_query = self.db.query(TaskRecord).filter(
            TaskRecord.user_id == user_id,
            ~TaskRecord.task_type.in_(EXCLUDED_TASK_TYPES),
            TaskRecord.status.in_(["success", "failed"])
        )
        # 数据来源筛选（本地/远程），与操作历史模块的 SQL 语义保持一致
        if is_remote is not None:
            if is_remote:
                task_query = task_query.filter(sql_text("params->>'is_remote' = 'true'"))
            else:
                task_query = task_query.filter(sql_text(
                    "((params->>'is_remote') IS NULL OR params->>'is_remote' = 'false')"
                ))
        # 模块筛选：feature_engineering 前缀匹配 5 子类型；ml 匹配 ml + ml_training；其余精确匹配
        if task_type:
            if task_type == "feature_engineering":
                task_query = task_query.filter(TaskRecord.task_type.like("feature_engineering_%"))
            elif task_type == "ml":
                task_query = task_query.filter(TaskRecord.task_type.in_(["ml", "ml_training"]))
            else:
                task_query = task_query.filter(TaskRecord.task_type == task_type)
        total_tasks = task_query.count()

        # 分页查询任务记录
        offset = (task_page - 1) * task_page_size
        tasks = task_query.order_by(TaskRecord.created_at.desc()).offset(offset).limit(task_page_size).all()

        # 收集所有 dataset_id 用于批量查询数据集名和状态
        dataset_ids = {t.dataset_id for t in tasks if t.dataset_id}
        dataset_info_map = {}
        if dataset_ids:
            ds_records = self.db.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()
            dataset_info_map = {d.id: {"name": d.name, "status": d.status} for d in ds_records}

        task_list = []
        for task in tasks:
            task_type = task.task_type or "unknown"
            ds_info = dataset_info_map.get(task.dataset_id, {}) if task.dataset_id else {}
            # 从 params 中提取 operation 字段（操作记录的小类）
            params = task.params or {}
            if not isinstance(params, dict):
                params = {}
            operation = params.get("operation", "")
            operation_label = OPERATION_LABELS.get(operation, operation) if operation else ""
            # 远程标识：params.is_remote + remote_config（连接名反查，连接已删返回 None）
            is_remote_flag = bool(params.get("is_remote"))
            remote_connection_name = None
            remote_table_name = None
            if is_remote_flag:
                remote_config = params.get("remote_config")
                if isinstance(remote_config, dict):
                    remote_table_name = remote_config.get("table_name")
                    conn_id = remote_config.get("connection_id")
                    if conn_id:
                        conn = self.db.query(DataSourceConnection).filter(
                            DataSourceConnection.id == conn_id
                        ).first()
                        if conn:
                            remote_connection_name = conn.name
            # 数据集展示信息：
            # 远程任务的数据源在远程表，数据集名用"连接名/表名"标识，且不依赖本地产物状态（避免误报回收站）
            if is_remote_flag:
                dataset_name_display = remote_table_name or f"远程表（连接:{remote_connection_name or '未知'}）"
                dataset_status_display = None
            elif task.dataset_id:
                dataset_name_display = ds_info.get("name", "未知数据集")
                dataset_status_display = ds_info.get("status", "deleted")
            else:
                dataset_name_display = "无关联数据集"
                dataset_status_display = None

            task_list.append({
                "id": task.id,
                "task_type": task_type,
                "task_type_label": TASK_TYPE_LABEL_MAP.get(task_type, task_type),
                # 前端分组 key：特征工程 5 子类型归并为 feature_engineering，ML 两类归并为 ml
                "group_key": _normalize_task_group(task_type),
                "operation": operation,
                "operation_label": operation_label,
                "is_remote": is_remote_flag,
                "remote_connection_name": remote_connection_name,
                "remote_table_name": remote_table_name,
                "dataset_id": task.dataset_id,
                "dataset_name": dataset_name_display,
                "dataset_status": dataset_status_display,
                "status": task.status,
                "params": task.params,
                "result_summary": task.result_summary,
                "error_message": task.error_message,
                "created_at": task.created_at.isoformat() if task.created_at else None
            })

        return {
            "datasets": dataset_list,
            "recent_tasks": task_list,
            "tasks_pagination": {
                "page": task_page,
                "page_size": task_page_size,
                "total": total_tasks,
                "total_pages": (total_tasks + task_page_size - 1) // task_page_size
            }
        }

    def get_bloodline_operations(self, dataset_id: int, user_id: int, limit: int = 10) -> Dict[str, Any]:
        """按数据产物血缘链返回最近操作记录，每条标注其所属产物

        血缘定义：以产物（或数据）的 root_dataset_id 为根，收集血缘内所有数据集，
        再取这些数据集关联的任务记录（按时间倒序）。用于前端"选产物自动带出血缘操作"，
        让上下文中产物与其清洗/分析/挖掘/保存等操作天然配对，避免手动勾错/漏勾。

        Args:
            dataset_id: 数据产物（Dataset）的 ID
            user_id: 当前用户 ID
            limit: 返回最近任务条数（默认 10，控制注入量）

        Returns:
            含血缘根信息 + 操作列表（每条含所属产物标 identity）
        """
        from app.utils.common import TASK_TYPE_LABEL_MAP
        from app.utils.task_labels import OPERATION_LABELS

        ds = self.db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.user_id == user_id,
            Dataset.status == "active"
        ).first()
        if not ds:
            return {"error": "数据集不存在或不可用"}

        # 血缘根：若产物设置了 root_dataset_id 则用根，否则用自身 ID
        root = getattr(ds, "root_dataset_id", None) or ds.id
        # 血缘内所有数据集（根自身 + 以该根为血缘根的所有产物）
        lineage = self.db.query(Dataset).filter(
            Dataset.user_id == user_id,
            or_(Dataset.id == root, Dataset.root_dataset_id == root)
        ).all()
        lineage_ids = {d.id for d in lineage}
        lineage_names = {d.id: d.name for d in lineage}

        # AI 分析用不上的任务大类，与操作历史/上下文选项口径保持一致
        EXCLUDED_TASK_TYPES = {"upload", "dataset", "ai"}
        ops = self.db.query(TaskRecord).filter(
            TaskRecord.user_id == user_id,
            ~TaskRecord.task_type.in_(EXCLUDED_TASK_TYPES),
            TaskRecord.status.in_(["success", "failed"]),
            TaskRecord.dataset_id.in_(lineage_ids)
        ).order_by(TaskRecord.created_at.desc()).limit(limit).all()

        operation_list = []
        for t in ops:
            t_type = t.task_type or "unknown"
            params = t.params or {}
            if not isinstance(params, dict):
                params = {}
            operation = params.get("operation", "")
            operation_label = OPERATION_LABELS.get(operation, operation) if operation else ""
            owner_id = t.dataset_id
            owner_name = lineage_names.get(owner_id) if owner_id else None
            operation_list.append({
                "id": t.id,
                "task_type": t_type,
                "task_type_label": TASK_TYPE_LABEL_MAP.get(t_type, t_type),
                "operation": operation,
                "operation_label": operation_label,
                "status": t.status,
                "dataset_id": owner_id,
                # 标注该操作所属的产物（血缘内数据集名 + ID），便于用户区分同名产物
                "belongs_to": f"{owner_name} (ID:{owner_id})" if owner_id and owner_name else (f"ID:{owner_id}" if owner_id else ""),
                "created_at": t.created_at.isoformat() if t.created_at else None
            })

        return {
            "dataset_id": dataset_id,
            "dataset_name": ds.name,
            "root_dataset_id": root,
            "operations": operation_list
        }

    def preview_context_item(self, item_type: str, ref_id: int, user_id: int) -> Dict[str, Any]:
        """预览某个上下文项的摘要内容（不真正注入对话）"""
        from app.services.ai_context.extractors import extract_context
        from app.services.ai_context.task_summarizer import summarize_task

        if item_type == "dataset":
            dataset = self.db.query(Dataset).filter(
                Dataset.id == ref_id,
                Dataset.user_id == user_id,
                Dataset.status == "active"
            ).first()
            if not dataset:
                return {"error": "数据集不存在或已删除"}
            return {
                "type": "dataset",
                "ref_id": ref_id,
                "name": dataset.name,
                "artifact_type": dataset.artifact_type,
                "preview": extract_context(dataset)
            }

        elif item_type == "operation":
            task = self.db.query(TaskRecord).filter(
                TaskRecord.id == ref_id,
                TaskRecord.user_id == user_id
            ).first()
            if not task:
                return {"error": "任务记录不存在"}
            return {
                "type": "operation",
                "ref_id": ref_id,
                "task_type": task.task_type,
                "preview": summarize_task(task)
            }

        return {"error": f"不支持的上下文类型: {item_type}"}

    # ========== 使用统计方法 ==========

    def _log_usage(self, conversation_id: int, module_type: str,
                   prompt_tokens: int, completion_tokens: int, total_tokens: int):
        """记录使用日志"""
        usage_log = AIUsageLog(
            conversation_id=conversation_id,
            module_type=module_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens
        )
        self.db.add(usage_log)
        self.db.commit()

    def get_usage_stats(self, user_id: int = None) -> Dict[str, Any]:
        """获取使用统计"""
        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        week_start = today_start - timedelta(days=now.weekday())
        
        conv_query = self.db.query(AIConversation.id)
        if user_id is not None:
            conv_query = conv_query.filter(AIConversation.user_id == user_id)
        conv_ids = [c.id for c in conv_query.all()]
        
        if not conv_ids:
            return {
                "today_tokens": 0,
                "week_tokens": 0,
                "total_tokens": 0,
                "today_calls": 0
            }
        
        today_logs = self.db.query(AIUsageLog).filter(
            AIUsageLog.conversation_id.in_(conv_ids),
            AIUsageLog.created_at >= today_start
        ).all()
        
        week_logs = self.db.query(AIUsageLog).filter(
            AIUsageLog.conversation_id.in_(conv_ids),
            AIUsageLog.created_at >= week_start
        ).all()
        
        all_logs = self.db.query(AIUsageLog).filter(
            AIUsageLog.conversation_id.in_(conv_ids)
        ).all()
        
        today_tokens = sum(log.total_tokens for log in today_logs)
        week_tokens = sum(log.total_tokens for log in week_logs)
        total_tokens = sum(log.total_tokens for log in all_logs)
        today_calls = len(today_logs)
        
        return {
            "today_tokens": today_tokens,
            "week_tokens": week_tokens,
            "total_tokens": total_tokens,
            "today_calls": today_calls
        }

    def _get_model_name(self) -> str:
        """获取当前使用的模型名称"""
        if settings.OPENAI_API_KEY and settings.OPENAI_MODEL:
            return settings.OPENAI_MODEL
        config = self._get_active_config()
        if config and config.model:
            return config.model
        # 默认模型名：DeepSeek 官方模型为 deepseek-chat（非 deepseek-v4-flash）
        return "gpt-3.5-turbo" if self._default_client == "openai" else "deepseek-chat"
