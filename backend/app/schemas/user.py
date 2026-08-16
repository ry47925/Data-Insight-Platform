from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    """用户创建schema"""
    username: str
    password: str


class UserResponse(BaseModel):
    """用户响应schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool = True
    # 数据库中早期创建的用户 created_at 可能为 None，设为可选避免响应验证失败
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    last_login_ip: Optional[str] = None


class Token(BaseModel):
    """Token响应schema"""
    access_token: str
    token_type: str


class UserUpdate(BaseModel):
    """用户资料更新schema（当前支持修改邮箱）"""
    email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    """修改密码请求schema"""
    old_password: str
    new_password: str
