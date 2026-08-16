from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
import re
from app.models import User
from app.schemas.user import UserCreate, UserResponse, Token, UserUpdate, ChangePasswordRequest
from app.schemas.dataset import _format_shanghai
from app.utils.security import verify_password, get_password_hash, create_access_token, get_current_user
from app.utils.db import get_db
from app.config import settings

router = APIRouter()

# 登录防暴力破解参数：连续失败 MAX_LOGIN_FAILURES 次后锁定 LOCKOUT_MINUTES 分钟
MAX_LOGIN_FAILURES = 5
LOCKOUT_MINUTES = 15


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    """用户注册（用户名+密码）"""
    # 用户名白名单校验：仅允许字母/数字/下划线/中划线/中文，长度 2-20（与前端注册表单规则一致）
    # 避免用户名含 @、空格等字符时生成非法占位邮箱（email=f"{username}@local"）
    import re as _re
    if not _re.fullmatch(r"[\w\u4e00-\u9fff-]{2,20}", user.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名仅支持字母、数字、下划线、中划线或中文，且长度为 2-20 个字符"
        )
    # 检查用户名是否已存在
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该用户名已被使用"
        )
    
    # 创建新用户
    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        email=f"{user.username}@local",
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/login", response_model=Token)
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """用户登录（含账号禁用校验与失败锁定）"""
    user = db.query(User).filter(User.username == form_data.username).first()

    # 账号存在性校验：统一返回"用户名或密码错误"避免用户名枚举
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 账号被管理员禁用后禁止登录（任务/数据接口由 get_current_user 一并拦截）
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        )

    # 登录锁定校验：连续失败次数达到阈值后锁定一段时间
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining_minutes = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号已锁定，请联系管理员解锁（约 {remaining_minutes} 分钟后自动解锁）",
        )

    # 密码校验失败：累加失败次数，达到阈值则锁定账号
    if not verify_password(form_data.password, user.hashed_password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_LOGIN_FAILURES:
            # 达到阈值：锁定账号并清零计数（锁定期间不再累加，解锁后重新计数）
            user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"登录失败次数过多，账号已锁定，请联系管理员解锁（约 {LOCKOUT_MINUTES} 分钟后自动解锁）",
            )
        # 未达阈值：提示剩余尝试次数，让用户知道还有几次机会
        remaining = MAX_LOGIN_FAILURES - user.failed_login_count
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"用户名或密码错误，还可尝试 {remaining} 次",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 登录成功：清除失败计数与锁定状态，更新最后登录信息
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    # 获取客户端IP（考虑代理）
    client_ip = request.client.host if request.client else "unknown"
    # 处理代理转发的真实IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    user.last_login_ip = client_ip
    db.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


def _user_dict(user: User) -> dict:
    """用户信息返回字典（时间统一为上海时区 ISO 字符串）

    数据库存储 UTC naive datetime，直接序列化会导致前端按浏览器本地时区解析
    出现 8 小时偏差；统一用 _format_shanghai 转成带 +08:00 的 ISO 字符串。
    """
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": bool(user.is_active),
        "created_at": _format_shanghai(user.created_at) if user.created_at else None,
        "last_login_at": _format_shanghai(user.last_login_at) if user.last_login_at else None,
        "last_login_ip": user.last_login_ip,
    }


@router.get("/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前用户信息（含邮箱/账号状态/登录信息，时间为上海时区）"""
    return _user_dict(current_user)


@router.put("/me")
async def update_current_user_info(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新当前用户资料（当前支持修改邮箱）"""
    if body.email is not None:
        email = body.email.strip()
        # 邮箱格式校验（避免引入 email-validator 依赖，使用基础正则）
        if not re.match(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$", email):
            raise HTTPException(status_code=400, detail="邮箱格式不正确")
        # 唯一性校验：其他账号已使用该邮箱
        existing = db.query(User).filter(User.email == email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="该邮箱已被其他账号使用")
        current_user.email = email
        db.commit()
        db.refresh(current_user)
    return _user_dict(current_user)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """修改当前用户密码（需验证旧密码）"""
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    new_password = body.new_password
    if len(new_password) < 6 or len(new_password) > 32:
        raise HTTPException(status_code=400, detail="新密码长度需为 6-32 位")
    if new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    return {"success": True, "message": "密码已修改，下次登录请使用新密码"}
