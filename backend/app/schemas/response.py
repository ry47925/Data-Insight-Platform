"""
统一响应格式模块

定义统一的错误响应模型和封装函数，供全局异常处理器使用。
"""

from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ErrorResponse(BaseModel):
    """
    错误响应模型。

    Attributes:
        code: 状态码（非0表示错误）
        error: 错误类型
        message: 错误消息
        detail: 详细错误信息
        timestamp: 响应时间戳
    """
    model_config = ConfigDict(from_attributes=True)

    code: int = Field(..., description="状态码，非0表示错误")
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误消息")
    detail: Optional[str] = Field(None, description="详细错误信息")
    timestamp: str = Field(..., description="响应时间戳")


def error_response(
    code: int = 500,
    error: str = "Internal Server Error",
    message: str = "服务器内部错误",
    detail: Optional[str] = None
) -> ErrorResponse:
    """
    封装错误响应。

    Args:
        code: 状态码（默认500）
        error: 错误类型（默认"Internal Server Error"）
        message: 错误消息（默认"服务器内部错误"）
        detail: 详细错误信息（可选）

    Returns:
        ErrorResponse对象
    """
    from datetime import datetime
    return ErrorResponse(
        code=code,
        error=error,
        message=message,
        detail=detail,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )