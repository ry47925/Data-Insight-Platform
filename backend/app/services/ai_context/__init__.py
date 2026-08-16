"""AI 上下文注入模块

提供上下文包构建、产物内容提取、任务配置摘要、会话压缩能力。
"""
from app.services.ai_context.builder import (
    ContextItem,
    ContextBundle,
    build_context_bundle,
    build_system_prompt,
)
from app.services.ai_context.extractors import extract_context
from app.services.ai_context.task_summarizer import summarize_task
from app.services.ai_context.conversation_compressor import compress_conversation

__all__ = [
    "ContextItem",
    "ContextBundle",
    "build_context_bundle",
    "build_system_prompt",
    "extract_context",
    "summarize_task",
    "compress_conversation",
]
