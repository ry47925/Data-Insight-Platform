from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.models import User, AIConversation
from app.schemas.ai import (
    AIConfigSaveRequest, AIConfigTestRequest,
    AIConfigResponse, AIConfigSaveResponse, AIConfigTestResponse,
    AIConversationItem, AIConversationDetail,
    AIUsageStatsResponse,
    AIChatRequest, AIChatResponse
)
from app.services.ai_service import AIService
from app.utils.db import get_db
from app.utils.security import get_current_user
from app.utils.task_records import create_task_record, update_task_record
import time

router = APIRouter()


# ==================== 智能对话接口 ====================

@router.post("/chat", response_model=AIChatResponse)
async def ai_chat(
    request: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """智能对话 - 基于上下文注入的多轮对话

    用户可通过 context_items 选择数据产物和操作记录作为上下文，
    AI 会基于这些真实数据进行诊断分析；上下文不足时返回 [NEEDS_CONTEXT] 引导用户补充。
    """
    # 验证会话属于当前用户（如果有conversation_id）
    if request.conversation_id:
        conv = db.query(AIConversation).filter(
            AIConversation.id == request.conversation_id,
            AIConversation.user_id == current_user.id
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")

    ai_service = AIService(db)

    # 将 ContextItemRequest schema 转为 dict 列表，供 service 层使用
    context_items_dict = [
        {"type": item.type, "ref_id": item.ref_id}
        for item in request.context_items
    ]

    # 埋点：创建任务记录（status=running）
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="ai",
        user_id=current_user.id,
        dataset_id=request.dataset_id,
        params={
            "operation": "ai_chat",
            "question": request.question,
            "conversation_id": request.conversation_id,
            "context_items": context_items_dict,
            "start_new_topic": request.start_new_topic
        }
    )

    try:
        result = ai_service.chat_with_context(
            question=request.question,
            context_items=context_items_dict,
            conversation_id=request.conversation_id,
            user_id=current_user.id,
            start_new_topic=request.start_new_topic
        )

        if "error" in result:
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message=result["error"],
                execution_time=execution_time
            )
            raise HTTPException(status_code=400, detail=result["error"])

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="success",
            result_summary={
                "operation": "ai_chat",
                "conversation_id": result.get("conversation_id"),
                "context_count": len(context_items_dict),
                "needs_context": result.get("needs_context", [])
            },
            execution_time=execution_time
        )

        return result
    except HTTPException:
        raise
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="failed",
            error_message=str(e),
            execution_time=execution_time
        )
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 上下文注入辅助接口 ====================

@router.get("/context/options")
async def get_context_options(
    task_page: int = 1,
    task_page_size: int = 20,
    is_remote: bool = None,
    task_type: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前用户可选的上下文项列表

    返回数据产物（按模块分组）和操作记录（分页，含成功/失败，过滤AI类型）。
    查询参数：
      task_page: 任务记录页码（默认1）
      task_page_size: 每页任务记录数（默认20）
      is_remote: 数据来源筛选，None=全部，true=远程数据库，false=本地
      task_type: 模块筛选，归一化值（cleaning/data_analysis/data_mining/feature_engineering/ml）
    """
    ai_service = AIService(db)
    try:
        return ai_service.get_context_options(
            user_id=current_user.id,
            task_page=task_page,
            task_page_size=task_page_size,
            is_remote=is_remote,
            task_type=task_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/blood-ops")
async def get_bloodline_operations(
    dataset_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取指定数据产物血缘链上的最近操作记录（前端"选产物自动带出血缘操作"用）

    查询参数：
      dataset_id: 数据产物（Dataset）ID
      limit: 返回最近任务条数（默认 10）
    """
    ai_service = AIService(db)
    try:
        result = ai_service.get_bloodline_operations(
            dataset_id=dataset_id,
            user_id=current_user.id,
            limit=limit
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/preview")
async def preview_context_item(
    type: str,
    ref_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """预览单个上下文项的摘要内容（不真正注入对话）

    查询参数：
      type: 上下文项类型，"dataset" 或 "operation"
      ref_id: 数据集 ID 或任务记录 ID
    """
    if type not in ("dataset", "operation"):
        raise HTTPException(status_code=400, detail="type 必须为 dataset 或 operation")

    ai_service = AIService(db)
    try:
        result = ai_service.preview_context_item(
            item_type=type,
            ref_id=ref_id,
            user_id=current_user.id
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI配置接口 ====================

@router.get("/config", response_model=AIConfigResponse)
async def get_ai_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取AI配置状态"""
    ai_service = AIService(db)
    try:
        return ai_service.get_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config", response_model=AIConfigSaveResponse)
async def save_ai_config(
    request: AIConfigSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """保存AI配置 - 先删除旧的激活配置，创建新的并设为激活"""
    ai_service = AIService(db)
    try:
        result = ai_service.save_config(
            provider=request.provider,
            api_key=request.api_key,
            model=request.model,
            base_url=request.base_url
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/test", response_model=AIConfigTestResponse)
async def test_ai_config(
    request: AIConfigTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """测试AI配置连接"""
    ai_service = AIService(db)
    try:
        result = ai_service.test_config(
            provider=request.provider,
            api_key=request.api_key,
            model=request.model,
            base_url=request.base_url
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 会话管理接口 ====================

@router.get("/conversations", response_model=List[AIConversationItem])
async def get_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取会话列表 - 按时间倒序"""
    ai_service = AIService(db)
    try:
        conversations = ai_service.get_conversations(user_id=current_user.id)
        return conversations
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}", response_model=AIConversationDetail)
async def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取单条会话详情"""
    ai_service = AIService(db)
    try:
        conv = ai_service.get_conversation(conversation_id, user_id=current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 优先从 ai_messages 表读取消息（避免 conversation JSON 与表数据重复）
        db_messages = ai_service._load_conversation_messages(conv)
        messages_data = [
            {
                "role": m["role"],
                "content": m["content"],
                "created_at": m.get("created_at")
            }
            for m in db_messages
        ] if db_messages else []

        # 将原始模型转换为前端期望的格式
        return {
            "id": conv.id,
            "title": conv.title,
            "module_type": conv.module_type,
            "dataset_id": conv.dataset_id,
            "conversation": messages_data,
            "follow_up_remaining": conv.follow_up_remaining,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除会话"""
    ai_service = AIService(db)
    try:
        success = ai_service.delete_conversation(conversation_id, user_id=current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/conversations/{conversation_id}/rename")
async def rename_conversation(
    conversation_id: int,
    rename_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """重命名会话标题（支持重名校验）

    请求体：{"title": "新标题"}
    """
    new_title = rename_data.get("title", "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    ai_service = AIService(db)
    try:
        result = ai_service.rename_conversation(
            conversation_id=conversation_id,
            new_title=new_title,
            user_id=current_user.id
        )
        if not result["success"]:
            # 重名校验失败或其他业务错误，返回400
            raise HTTPException(status_code=400, detail=result["error"])
        return {"success": True, "title": new_title}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 使用统计接口 ====================

@router.get("/usage/stats", response_model=AIUsageStatsResponse)
async def get_usage_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取使用统计"""
    ai_service = AIService(db)
    try:
        return ai_service.get_usage_stats(user_id=current_user.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
