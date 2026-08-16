from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class AIConfigResponse(BaseModel):
    """AI配置状态响应schema"""
    is_configured: bool
    provider: Optional[str] = None
    model: Optional[str] = None


class AIConfigSaveRequest(BaseModel):
    """AI配置保存请求schema"""
    provider: str
    api_key: str
    model: str
    base_url: Optional[str] = None


class AIConfigSaveResponse(BaseModel):
    """AI配置保存响应schema"""
    success: bool
    message: str


class AIConfigTestRequest(BaseModel):
    """AI配置测试请求schema"""
    provider: str
    api_key: str
    model: str
    base_url: Optional[str] = None


class AIConfigTestResponse(BaseModel):
    """AI配置测试响应schema"""
    success: bool
    message: str


class AIConversationItem(BaseModel):
    """会话列表项schema"""
    id: int
    title: str
    module_type: str
    dataset_id: Optional[int] = None
    message_count: int = 0
    follow_up_remaining: int = 10
    created_at: datetime
    updated_at: Optional[datetime] = None


class AIConversationDetail(BaseModel):
    """会话详情schema"""
    id: int
    title: str
    module_type: str
    dataset_id: Optional[int] = None
    conversation: List[Dict[str, Any]]
    follow_up_remaining: int
    created_at: datetime
    updated_at: datetime


class AIUsageStatsResponse(BaseModel):
    """使用统计响应schema"""
    today_tokens: int
    week_tokens: int
    total_tokens: int
    today_calls: int


class ContextItemRequest(BaseModel):
    """上下文项请求schema"""
    type: str  # "dataset" | "operation"
    ref_id: int


class AIChatRequest(BaseModel):
    """对话请求schema"""
    question: str
    dataset_id: Optional[int] = None  # 兼容旧前端，不作为主要上下文来源
    conversation_id: Optional[int] = None
    context_items: List[ContextItemRequest] = []  # 用户选择的上下文项列表
    start_new_topic: bool = False  # 是否开始新话题（清空之前的上下文关联）


class AIChatResponse(BaseModel):
    """对话响应schema"""
    answer: str
    conversation_id: int
    usage: Dict[str, Any]
    needs_context: Optional[List[str]] = None  # AI 请求的补充上下文类型
    suggested_questions: Optional[List[str]] = None  # AI 生成的追问建议列表（preset + dynamic）
