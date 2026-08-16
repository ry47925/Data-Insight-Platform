"""
全局异常处理模块

定义统一的异常处理器，捕获并处理各类异常，返回统一格式的错误响应。
"""

import logging
import traceback
from fastapi import Request
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.response import error_response

# 专用 logger: 异常堆栈输出到 stderr(docker logs 可见)
logger = logging.getLogger("exception_handler")
logger.setLevel(logging.ERROR)


async def http_exception_handler(request: Request, exc: HTTPException):
    """
    处理 HTTPException。
    
    Args:
        request: 请求对象
        exc: HTTPException异常
    
    Returns:
        JSONResponse: 统一格式的错误响应
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "error": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            "message": exc.detail if isinstance(exc.detail, str) else "请求处理失败",
            "detail": str(exc.detail) if not isinstance(exc.detail, str) else None,
            "timestamp": error_response().timestamp
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    处理请求参数验证异常。
    
    Args:
        request: 请求对象
        exc: RequestValidationError异常
    
    Returns:
        JSONResponse: 统一格式的错误响应
    """
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        errors.append(f"{field}: {error['msg']}")
    
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "error": "Validation Error",
            "message": "请求参数验证失败",
            "detail": "; ".join(errors),
            "timestamp": error_response().timestamp
        }
    )


async def value_error_handler(request: Request, exc: ValueError):
    """
    处理 ValueError 异常。
    
    Args:
        request: 请求对象
        exc: ValueError异常
    
    Returns:
        JSONResponse: 统一格式的错误响应
    """
    return JSONResponse(
        status_code=400,
        content={
            "code": 400,
            "error": "Value Error",
            "message": str(exc),
            "detail": traceback.format_exc(),
            "timestamp": error_response().timestamp
        }
    )


async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    """
    处理 FileNotFoundError 异常。
    
    Args:
        request: 请求对象
        exc: FileNotFoundError异常
    
    Returns:
        JSONResponse: 统一格式的错误响应
    """
    return JSONResponse(
        status_code=404,
        content={
            "code": 404,
            "error": "File Not Found",
            "message": f"文件不存在: {exc.filename}",
            "detail": str(exc),
            "timestamp": error_response().timestamp
        }
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    """
    处理 SQLAlchemy 数据库异常。

    Args:
        request: 请求对象
        exc: SQLAlchemyError异常

    Returns:
        JSONResponse: 统一格式的错误响应
    """
    # 记录完整堆栈到日志,便于排查数据库问题
    logger.error(
        "数据库异常 [%s %s]: %s\n%s",
        request.method, request.url.path, str(exc), traceback.format_exc()
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "error": "Database Error",
            "message": "数据库操作失败",
            "detail": str(exc),
            "timestamp": error_response().timestamp
        }
    )


async def general_exception_handler(request: Request, exc: Exception):
    """
    处理所有未捕获的异常（兜底处理）。

    Args:
        request: 请求对象
        exc: 任意异常

    Returns:
        JSONResponse: 统一格式的错误响应
    """
    # 记录完整堆栈到日志,便于排查 500 错误根因
    logger.error(
        "未捕获异常 [%s %s]: %s: %s\n%s",
        request.method, request.url.path,
        type(exc).__name__, str(exc), traceback.format_exc()
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "error": "Internal Server Error",
            "message": "服务器内部错误，请稍后重试",
            "detail": traceback.format_exc(),
            "timestamp": error_response().timestamp
        }
    )


def register_exception_handlers(app):
    """
    注册所有全局异常处理器到FastAPI应用。
    
    Args:
        app: FastAPI应用实例
    """
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(FileNotFoundError, file_not_found_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(Exception, general_exception_handler)