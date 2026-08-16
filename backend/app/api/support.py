"""联系管理员公开接口（无需登录）

提供：
- 算术验证码生成（答案存 Redis，5 分钟有效）
- 截图上传（存 MinIO，限制图片格式与大小）
- 提交申请（验证码校验 + 同 IP/用户名 10 分钟频率限制）

申请数据存 support_messages 表，管理员在「用户管理-用户申请」Tab 处理。
"""
import os
import random
import uuid as uuid_lib
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models import SupportMessage
from app.utils.db import get_db
from app.config import settings
from app.services.cache_manager import cache_manager
from app.services.storage_manager import storage_manager

router = APIRouter(prefix="/api/support", tags=["联系管理员"])

# 截图上传限制
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB

# 频率限制：同 IP 或用户名窗口内限 1 条（秒，0 表示不限制，配置项 SUPPORT_RATE_LIMIT_SECONDS）
def _get_rate_limit_seconds() -> int:
    return max(0, settings.SUPPORT_RATE_LIMIT_SECONDS)

VALID_CATEGORIES = {"restore_dataset", "unlock", "error_report"}


class SupportMessageCreate(BaseModel):
    """提交申请请求体"""
    category: str
    username: str = ""
    contact: str = ""
    content: dict = {}
    attachment_path: str | None = None
    attachment_name: str | None = None
    captcha_id: str
    captcha_answer: str


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（考虑代理转发）"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:50]
    return (request.client.host if request.client else "unknown")[:50]


@router.get("/captcha")
def get_captcha():
    """生成算术验证码（如 3 + 5 = ?），答案存 Redis 5 分钟"""
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    captcha_id = uuid_lib.uuid4().hex[:16]
    cache_manager.set(f"support:captcha:{captcha_id}", str(a + b), ttl=300)
    return {"captcha_id": captcha_id, "question": f"{a} + {b} = ?"}


@router.post("/upload")
async def upload_attachment(file: UploadFile = File(...)):
    """上传错误上报截图（存 MinIO，支持 jpg/png/gif/webp，≤5MB）"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持图片格式: {', '.join(sorted(ALLOWED_IMAGE_EXTS))}"
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")

    # 存 MinIO support/ 目录（storage_manager 会自动注入 UUID 保证路径唯一）
    object_name = f"support/{uuid_lib.uuid4().hex}{ext}"
    path = storage_manager.save_bytes(object_name, data)
    return {"path": path, "name": file.filename or "screenshot"}


@router.post("/messages")
def create_support_message(
    body: SupportMessageCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """提交联系管理员申请（无需登录）

    校验顺序：分类 → 验证码 → 频率限制，全部通过后写入 support_messages。
    """
    # 1. 分类校验
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="无效的申请类型")

    # 2. 验证码校验（一次性，校验后立即删除防重放）
    answer = cache_manager.get(f"support:captcha:{body.captcha_id}")
    if answer is None:
        raise HTTPException(status_code=400, detail="验证码已过期，请刷新后重试")
    if str(answer).strip() != str(body.captcha_answer).strip():
        raise HTTPException(status_code=400, detail="验证码错误，请重试")
    cache_manager.delete(f"support:captcha:{body.captcha_id}")

    # 3. 频率限制：同 IP 或用户名窗口内限 1 条（可配置，开发阶段可设为 0 关闭）
    rate_limit_seconds = _get_rate_limit_seconds()
    client_ip = _get_client_ip(request)
    if rate_limit_seconds > 0:
        since = datetime.utcnow() - timedelta(seconds=rate_limit_seconds)
        rate_query = db.query(SupportMessage).filter(SupportMessage.created_at >= since)
        if body.username.strip():
            rate_query = rate_query.filter(or_(
                SupportMessage.client_ip == client_ip,
                SupportMessage.username == body.username.strip()
            ))
        else:
            rate_query = rate_query.filter(SupportMessage.client_ip == client_ip)
        if rate_query.count() > 0:
            # 时长按秒取整显示，避免配置非整分钟时出现"0 分钟后再试"的误导提示
            if rate_limit_seconds < 60:
                wait_hint = f"{rate_limit_seconds} 秒"
            else:
                import math
                wait_hint = f"{math.ceil(rate_limit_seconds / 60)} 分钟"
            raise HTTPException(
                status_code=429,
                detail=f"提交过于频繁，请 {wait_hint} 后再试"
            )

    # 4. 写入申请记录
    message = SupportMessage(
        category=body.category,
        username=body.username.strip()[:100] if body.username else "",
        contact=body.contact.strip()[:200] if body.contact else "",
        content=body.content or {},
        attachment_path=body.attachment_path,
        attachment_name=body.attachment_name,
        client_ip=client_ip,
        status="pending",
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return {
        "success": True,
        "message": "申请已提交，管理员将尽快处理",
        "id": message.id
    }
