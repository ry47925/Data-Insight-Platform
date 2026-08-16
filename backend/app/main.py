"""
Data Insight Platform - 主应用入口

AI驱动的通用数据分析平台，提供数据清洗、特征工程、机器学习、数据挖掘、AI分析等功能。
"""

import os
import sys
import json
from datetime import datetime
from contextlib import asynccontextmanager

# 将 backend 目录加入模块搜索路径，确保能找到 app 包
_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_current_dir)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
import time

from app.config import settings
from app.api import users, datasets, ml, ai, cleaning, feature_engineering, data_analysis, data_mining, admin, data_sources, support
from app.utils.db import init_db
from app.utils.exception_handlers import register_exception_handlers
from app.utils.logger import log_system, log_api_request, log_error
from app.services.task_scheduler import task_scheduler

# 确保能找到 static 目录（Windows 兼容性）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期事件处理 - 替代旧的 on_event 方式"""
    # 启动时初始化
    try:
        init_db()
        print(" 数据库初始化完成")
    except Exception as e:
        print(f" 数据库初始化警告: {e}")

    log_system("应用启动")

    print(f"\n{settings.PROJECT_NAME} v{settings.PROJECT_VERSION} 启动成功!")
    print(f"前端页面: http://localhost:8000")
    print(f"API文档: http://localhost:8000/docs")
    print(f"健康检查: http://localhost:8000/health")
    print(f"\n项目结构优化已完成:")
    print(f"   - 公共工具模块: app/utils/common.py")
    print(f"   - 统一响应格式: app/schemas/response.py")
    print(f"   - 全局异常处理: app/utils/exception_handlers.py")

    # 启动任务调度器（后台线程，定时激活 pending 任务）
    if settings.CELERY_ENABLED:
        task_scheduler.start()
        print(f"   - 任务调度器已启动（排队机制: running={settings.MAX_RUNNING_PER_USER}, pending={settings.MAX_PENDING_PER_USER}）")

    yield

    # 关闭时清理
    if settings.CELERY_ENABLED:
        task_scheduler.stop()
    log_system("应用停止")
    print(f"\n{settings.PROJECT_NAME} 服务已停止")


class CustomJSONEncoder(json.JSONEncoder):
    """自定义JSON编码器，处理datetime类型返回带时区标识的格式"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        return super().default(obj)


# 创建应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="AI驱动的通用数据分析平台",
    json_encoder=CustomJSONEncoder,
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册全局异常处理器
register_exception_handlers(app)

# 日志中间件
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)
        client_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        log_api_request(request.method, str(request.url), response.status_code, duration_ms, client_ip)
        return response
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        log_error(f"Request failed: {request.method} {request.url} | {duration_ms}ms | {str(e)}")
        raise

# 挂载静态文件目录 - 前端资源
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 注册API路由
app.include_router(users.router, prefix="/api/users", tags=["用户管理"])
app.include_router(datasets.router, prefix="/api/datasets", tags=["数据集管理"])
app.include_router(ml.router, prefix="/api/ml", tags=["机器学习"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI分析"])
app.include_router(cleaning.router, prefix="/api/cleaning", tags=["数据清洗"])
app.include_router(feature_engineering.router, prefix="/api/feature_engineering", tags=["特征工程"])
app.include_router(data_analysis.router, prefix="/api/data-analysis", tags=["数据分析"])
app.include_router(data_mining.router, prefix="/api/data-mining", tags=["数据挖掘"])
app.include_router(data_sources.router, tags=["数据源管理"])
app.include_router(admin.router, tags=["管理后台"])
app.include_router(support.router, tags=["联系管理员"])


@app.get("/")
async def root():
    """根路径 - 返回前端页面"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(content={
        "code": 0,
        "message": "前端页面未找到",
        "data": {
            "name": settings.PROJECT_NAME,
            "version": settings.PROJECT_VERSION,
            "docs": "/docs",
            "api": "/api/"
        },
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return JSONResponse(content={
        "code": 0,
        "message": "success",
        "data": {
            "status": "healthy",
            "service": settings.PROJECT_NAME,
            "version": settings.PROJECT_VERSION
        },
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.get("/api")
async def api_root():
    """API根路径 - 返回所有可用端点"""
    return JSONResponse(content=jsonable_encoder({
        "code": 0,
        "message": "success",
        "data": {
            "name": settings.PROJECT_NAME,
            "version": settings.PROJECT_VERSION,
            "description": "AI驱动的通用数据分析平台API",
            "endpoints": {
                "用户管理": "/api/users",
                "数据集管理": "/api/datasets",
                "数据清洗": "/api/cleaning",
                "数据分析": "/api/data-analysis",
                "数据挖掘": "/api/data-mining",
                "机器学习": "/api/ml",
                "AI分析": "/api/ai"
            },
            "documentation": {
                "swagger": "/docs",
                "redoc": "/redoc"
            }
        },
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }))


if __name__ == "__main__":
    import uvicorn
    print(f"启动 {settings.PROJECT_NAME} 服务...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
