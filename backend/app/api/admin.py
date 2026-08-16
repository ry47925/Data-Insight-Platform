from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, Request
import json
import re
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func, or_
from app.models import User, Dataset, TaskRecord, DataSourceConnection, SupportMessage
from app.utils.crypto import decrypt_password
from app.schemas.dataset import _format_shanghai
from app.utils.db import get_db
from app.utils.security import create_access_token, get_password_hash, verify_password
from app.services.cache_manager import cache_manager, MIN_HIT_RATE_SAMPLE
from app.services.storage_manager import storage_manager
from app.services.task_manager import task_manager
from app.services.clickhouse_service import clickhouse_service
from app.config import settings, dataset_color
from app.utils.common import clear_user_dataset_cache
from app.utils.task_records import create_task_record, update_task_record, check_task_queue_capacity
from app.utils.task_labels import get_failure_category_label, is_retryable_failure
from app.utils.logger import LOG_DIR
from app.api.users import MAX_LOGIN_FAILURES, LOCKOUT_MINUTES
from datetime import timedelta, datetime, timezone
from urllib.parse import quote
SHANGHAI_TZ = timezone(timedelta(hours=8))
import io
import subprocess
import os
import time
import secrets
import string
try:
    import docker as docker_lib
    DOCKER_CLIENT = docker_lib.from_env()
except Exception:
    DOCKER_CLIENT = None

router = APIRouter(prefix="/admin", tags=["管理后台"])

admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/auth/login", auto_error=False)


def ensure_admin_user(db: Session):
    """确保管理员用户存在"""
    admin = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
    if not admin:
        admin = User(
            username=settings.ADMIN_USERNAME,
            email=f"{settings.ADMIN_USERNAME}@admin.local",
            hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
            role="admin"
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print(f"✅ 默认管理员用户已创建: {settings.ADMIN_USERNAME}")
    elif admin.role != "admin":
        admin.role = "admin"
        db.commit()
    return admin


def get_current_admin(
    token: str = Depends(admin_oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """获取当前管理员用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        from jose import jwt, JWTError
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception
    
    user = db.query(User).filter(User.username == username, User.role == "admin").first()
    if user is None:
        raise HTTPException(status_code=403, detail="无权访问管理后台")
    return user


@router.post("/auth/login")
def admin_login(
    request: Request,
    username: str = Body(...),
    password: str = Body(...),
    db: Session = Depends(get_db)
):
    """管理员登录（含失败锁定防暴力破解，2026-08-15 修复）

    与用户端登录一致的锁定策略：连续失败 MAX_LOGIN_FAILURES 次锁定 LOCKOUT_MINUTES 分钟。
    """
    ensure_admin_user(db)

    user = db.query(User).filter(User.username == username, User.role == "admin").first()
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 账号禁用拦截
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 登录锁定校验：连续失败次数达到阈值后锁定一段时间
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining_minutes = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1)
        raise HTTPException(
            status_code=403,
            detail=f"账号已锁定，请联系管理员解锁（约 {remaining_minutes} 分钟后自动解锁）",
        )

    # 密码校验失败：累加失败次数，达到阈值则锁定账号
    if not verify_password(password, user.hashed_password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_LOGIN_FAILURES:
            # 达到阈值：锁定账号并清零计数（锁定期间不再累加，解锁后重新计数）
            user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
            db.commit()
            raise HTTPException(
                status_code=403,
                detail=f"登录失败次数过多，账号已锁定（约 {LOCKOUT_MINUTES} 分钟后自动解锁）",
            )
        # 未达阈值：提示剩余尝试次数
        remaining = MAX_LOGIN_FAILURES - user.failed_login_count
        db.commit()
        raise HTTPException(
            status_code=401,
            detail=f"用户名或密码错误，还可尝试 {remaining} 次",
        )

    # 登录成功：清除失败计数与锁定状态，更新最后登录信息
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    user.last_login_ip = client_ip
    db.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": "admin"},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/auth/me")
def admin_me(current_admin: User = Depends(get_current_admin)):
    """获取当前管理员信息"""
    return {"username": current_admin.username, "role": current_admin.role}


def _postgres_available() -> bool:
    """真实检测 PostgreSQL 连接（执行 SELECT 1），避免状态硬编码"""
    try:
        from app.utils.db import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/services/status")
def get_services_status(current_admin: User = Depends(get_current_admin)):
    """获取所有服务状态"""
    services = []

    services.append({
        "name": "Redis",
        "icon": "cache",
        "status": "online" if cache_manager.get_stats().get("redis_available") else "offline",
        "message": "Redis 缓存可用" if cache_manager.get_stats().get("redis_available") else "Redis 不可用，使用内存缓存",
        "backend": "redis" if cache_manager.get_stats().get("redis_available") else "memory"
    })

    services.append({
        "name": "MinIO",
        "icon": "cloud",
        "status": "online" if storage_manager.get_stats().get("minio_available") else "offline",
        "message": "MinIO 对象存储可用" if storage_manager.get_stats().get("minio_available") else "MinIO 不可用",
        "backend": "minio" if storage_manager.get_stats().get("minio_available") else "unavailable"
    })

    services.append({
        "name": "Celery",
        "icon": "tasks",
        "status": "online" if task_manager.is_async_available() else "offline",
        "message": "Celery 异步任务可用" if task_manager.is_async_available() else "Celery 不可用，使用同步执行",
        "backend": "celery" if task_manager.is_async_available() else "sync"
    })

    services.append({
        "name": "PostgreSQL",
        "icon": "database",
        "status": "online" if _postgres_available() else "offline",
        "message": "PostgreSQL 数据库可用" if _postgres_available() else "PostgreSQL 数据库不可用",
        "backend": "postgresql"
    })

    services.append({
        "name": "ClickHouse",
        "icon": "bar-chart",
        # 真实探测（refresh=True 绕过 10s 缓存）：容器停止后立即显示离线，而非仅看配置开关
        # 单次探测结果复用，避免同一次响应内重复网络往返
        "status": "online" if (_ch_ok := clickhouse_service.is_available(refresh=True)) else "offline",
        "message": "ClickHouse 分析引擎可用" if _ch_ok else "ClickHouse 不可用，使用 Pandas 分析",
        "backend": "clickhouse" if _ch_ok else "pandas"
    })

    return {"services": services}


# ==================== Docker 服务控制 API ====================

def _run_docker_compose(command: str, service: str = None) -> dict:
    """执行 docker-compose 命令"""
    if DOCKER_CLIENT is None:
        return {"success": False, "error": "Docker 客户端未初始化"}
    
    try:
        container_name = f"data-insight-{service}"
        container = DOCKER_CLIENT.containers.get(container_name)
        
        if command == "start":
            container.start()
            return {"success": True, "stdout": f"{service} started"}
        elif command == "stop":
            container.stop(timeout=10)
            return {"success": True, "stdout": f"{service} stopped"}
        elif command == "restart":
            container.restart(timeout=10)
            return {"success": True, "stdout": f"{service} restarted"}
        else:
            return {"success": False, "error": f"未知命令: {command}"}
    except docker_lib.errors.NotFound:
        return {"success": False, "error": f"容器 {container_name} 不存在"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_docker_container_status(service_name: str) -> dict:
    """获取 Docker 容器状态"""
    if DOCKER_CLIENT is None:
        return {"exists": False, "running": False, "status": "docker_unavailable"}
    
    try:
        container = DOCKER_CLIENT.containers.get(f"data-insight-{service_name}")
        container.reload()
        state = container.attrs.get("State", {})
        return {
            "exists": True,
            "running": state.get("Running", False),
            "status": state.get("Status", "unknown"),
            "started_at": state.get("StartedAt", ""),
            "health": state.get("Health", {}).get("Status", "unknown") if state.get("Health") else "none"
        }
    except docker_lib.errors.NotFound:
        return {"exists": False, "running": False, "status": "not_found"}
    except Exception as e:
        return {"exists": False, "running": False, "status": f"error: {e}"}


SERVICE_NAME_MAP = {
    "redis": "redis",
    "postgres": "postgres",
    # 前端 key（与 /services/metrics 返回键一致）为 postgresql，映射到 compose 服务名 postgres
    "postgresql": "postgres",
    "clickhouse": "clickhouse",
    "minio": "minio",
    "celery": "celery"
}

# 关键服务：无降级，停止将导致系统崩溃/数据不可用，禁止停止操作
_CRITICAL_SERVICES = {"postgres", "postgresql", "minio"}


@router.post("/services/{service_name}/start")
def start_service(
    service_name: str,
    current_admin: User = Depends(get_current_admin)
):
    """启动单个 Docker 服务"""
    if service_name not in SERVICE_NAME_MAP:
        raise HTTPException(status_code=400, detail=f"未知服务: {service_name}")
    if service_name in _CRITICAL_SERVICES:
        raise HTTPException(status_code=400, detail=f"{service_name.upper()} 为关键服务，请通过 docker compose start 管理，页面不提供启动操作")
    
    docker_service = SERVICE_NAME_MAP[service_name]
    result = _run_docker_compose("start", docker_service)
    
    if result["success"]:
        # 等待服务启动并刷新状态
        time.sleep(2)
        if service_name == "redis":
            cache_manager._init_redis()
        elif service_name == "minio":
            storage_manager._init_minio()
        elif service_name == "celery":
            if hasattr(task_manager, '_init_celery'):
                task_manager._init_celery()
        
        return {"message": f"{service_name.upper()} 启动完成", "details": result["stdout"]}
    else:
        raise HTTPException(status_code=500, detail=f"启动失败: {result.get('stderr', result.get('error', '未知错误'))}")


@router.post("/services/{service_name}/stop")
def stop_service(
    service_name: str,
    current_admin: User = Depends(get_current_admin)
):
    """停止单个 Docker 服务"""
    if service_name not in SERVICE_NAME_MAP:
        raise HTTPException(status_code=400, detail=f"未知服务: {service_name}")
    # 关键服务禁止停止（无降级，停止即系统崩溃），只读环境不提供停止入口
    if service_name in _CRITICAL_SERVICES:
        raise HTTPException(status_code=400, detail=f"{service_name.upper()} 为关键服务，禁止停止（停止将导致系统不可用）")
    
    docker_service = SERVICE_NAME_MAP[service_name]
    result = _run_docker_compose("stop", docker_service)
    
    if result["success"]:
        time.sleep(2)
        if service_name == "redis":
            cache_manager._redis_available = False
        elif service_name == "minio":
            storage_manager._minio_available = False
        elif service_name == "celery":
            if hasattr(task_manager, '_celery_available'):
                task_manager._celery_available = False
        
        status_map = {
            "redis": "缓存服务将使用内存模式",
            "postgres": "数据库服务已停止，系统将无法正常工作",
            "minio": "存储服务已停止，上传功能不可用",
            "celery": "异步任务服务已停止，将使用同步执行",
            "clickhouse": "分析引擎已停止，使用Pandas分析"
        }
        return {
            "message": f"{service_name.upper()} 已停止，{status_map.get(service_name, '')}",
            "details": result["stdout"]
        }
    else:
        raise HTTPException(status_code=500, detail=f"停止失败: {result.get('stderr', result.get('error', '未知错误'))}")


@router.post("/services/restart-all")
def restart_all_services(current_admin: User = Depends(get_current_admin)):
    """重启所有服务（Docker + 后端）"""
    results = []
    services = ["redis", "postgres", "clickhouse", "minio", "celery"]
    
    for service in services:
        # 停止服务
        stop_result = _run_docker_compose("stop", SERVICE_NAME_MAP[service])
        if stop_result["success"]:
            results.append({"service": service, "action": "stop", "status": "success"})
        else:
            results.append({"service": service, "action": "stop", "status": "failed", "error": stop_result.get("stderr", "")})
        time.sleep(1)
        
        # 启动服务
        start_result = _run_docker_compose("start", SERVICE_NAME_MAP[service])
        if start_result["success"]:
            results.append({"service": service, "action": "start", "status": "success"})
        else:
            results.append({"service": service, "action": "start", "status": "failed", "error": start_result.get("stderr", "")})
        time.sleep(2)
    
    # 刷新所有服务连接
    cache_manager._init_redis()
    storage_manager._init_minio()
    if hasattr(task_manager, '_init_celery'):
        task_manager._init_celery()
    
    return {
        "message": "所有服务重启完成",
        "timestamp": datetime.now().isoformat(),
        "results": results
    }


@router.get("/services/metrics")
def get_services_metrics(current_admin: User = Depends(get_current_admin)):
    """获取所有服务详细指标"""
    metrics = {}
    
    # Redis 指标
    redis_container = _get_docker_container_status("redis")
    if redis_container["running"]:
        try:
            import redis as redis_lib
            r = redis_lib.from_url(settings.REDIS_URL)
            info = r.info()
            metrics["redis"] = {
                "status": "online",
                "container": redis_container,
                "memory_used_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
                "memory_peak_mb": round(info.get("used_memory_peak", 0) / 1024 / 1024, 2),
                "keys_count": r.dbsize(),
                "expiring_keys": info.get("expires", 0),
                "uptime_days": info.get("uptime_in_days", 0),
                "connected_clients": info.get("connected_clients", 0),
                "total_connections": info.get("total_connections_received", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                # 命中率：hits+misses 均为 0 时（重启后暂无查询）返回 0，避免分母默认 1 造成误导
                "hit_rate": round(
                    hits / (hits + misses) * 100, 2
                ) if (hits := info.get("keyspace_hits", 0)) + (misses := info.get("keyspace_misses", 0)) > 0 else 0.0
            }
        except Exception as e:
            metrics["redis"] = {"status": "error", "error": str(e), "container": redis_container}
    else:
        cache_stats = cache_manager.get_stats()
        metrics["redis"] = {
            "status": "offline",
            "container": redis_container,
            "fallback": "memory_cache",
            # 内存缓存键数取 get_stats 返回的真实字段 memory_cache_size（修复）
            "memory_cache_keys": cache_stats.get("memory_cache_size", 0),
            "memory_cache_size": cache_stats.get("memory_size", 0)
        }
    
    # PostgreSQL 指标
    postgres_container = _get_docker_container_status("postgres")
    if postgres_container["running"]:
        try:
            # 直接使用 db.py 中的 engine 实例（原 get_db_instance 已废弃并删除）
            from app.utils.db import engine
            with engine.connect() as conn:
                # 数据库大小
                db_size = conn.execute(text("SELECT pg_database_size(current_database()) / 1024 / 1024 as size_mb")).fetchone()[0]
                # 连接数
                connections = conn.execute(text("SELECT count(*) FROM pg_stat_activity")).fetchone()[0]
                # 表数量
                tables = conn.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")).fetchone()[0]
                # 最大连接数（SHOW 输出为字符串，转 int）
                try:
                    max_conn = int(conn.execute(text("SHOW max_connections")).fetchone()[0])
                except Exception:
                    max_conn = 0
                # 数据库版本（如 "PostgreSQL 16.x (Debian...) on x86_64"）
                try:
                    version = conn.execute(text("SELECT version()")).fetchone()[0]
                    version = re.match(r"PostgreSQL\s+[\d.]+", version).group(0) if version else ""
                except Exception:
                    version = ""
                
                metrics["postgresql"] = {
                    "status": "online",
                    "container": postgres_container,
                    "database_size_mb": db_size,
                    "active_connections": connections,
                    "max_connections": max_conn,
                    "connection_rate": round(connections / max_conn * 100, 1) if max_conn else 0,
                    "table_count": tables,
                    "database_version": version
                }
        except Exception as e:
            metrics["postgresql"] = {"status": "error", "error": str(e), "container": postgres_container}
    else:
        metrics["postgresql"] = {
            "status": "offline",
            "container": postgres_container
        }
    
    # MinIO 指标
    minio_container = _get_docker_container_status("minio")
    if minio_container["running"]:
        try:
            storage_stats = storage_manager.get_stats()
            metrics["minio"] = {
                "status": "online",
                "container": minio_container,
                "buckets": storage_stats.get("buckets", 0),
                "objects": storage_stats.get("objects", 0),
                "total_size_mb": storage_stats.get("total_size_mb", 0),
                "endpoint": settings.MINIO_ENDPOINT
            }
        except Exception as e:
            metrics["minio"] = {"status": "error", "error": str(e), "container": minio_container}
    else:
        metrics["minio"] = {
            "status": "offline",
            "container": minio_container,
            "message": "MinIO 不可用，文件上传功能不可用"
        }
    
    # Celery 指标
    celery_container = _get_docker_container_status("celery")
    if celery_container["running"]:
        try:
            task_stats = task_manager.get_stats() if hasattr(task_manager, 'get_stats') else {}
            metrics["celery"] = {
                "status": "online",
                "container": celery_container,
                "workers": task_stats.get("workers", 0),
                "pending_tasks": task_stats.get("pending", 0),
                "active_tasks": task_stats.get("active", 0),
                "completed_tasks": task_stats.get("completed", 0),
                "failed_tasks": task_stats.get("failed", 0)
            }
        except Exception as e:
            metrics["celery"] = {"status": "error", "error": str(e), "container": celery_container}
    else:
        metrics["celery"] = {
            "status": "offline",
            "container": celery_container,
            "fallback": "sync_execution"
        }
    
    # ClickHouse 指标
    clickhouse_container = _get_docker_container_status("clickhouse")
    if clickhouse_container["running"] and clickhouse_service.is_available(refresh=True):
        try:
            # 业务库副本概况（库数/表数/总行数/存储占用），复用 clickhouse_service 的查询入口
            db = settings.CLICKHOUSE_DATABASE
            db_rows = clickhouse_service.query(
                "SELECT count(DISTINCT database) AS databases, "
                "countIf(database = {db:String}) AS tables, "
                "sumIf(total_rows, database = {db:String}) AS total_rows, "
                "formatReadableSize(sumIf(total_bytes, database = {db:String})) AS total_bytes_readable "
                "FROM system.tables", parameters={"db": db})
            row = db_rows[0] if db_rows else {}
            metrics["clickhouse"] = {
                "status": "online",
                "container": clickhouse_container,
                "host": settings.CLICKHOUSE_HOST,
                "port": settings.CLICKHOUSE_PORT,
                "databases": row.get("databases") or 0,
                "tables": row.get("tables") or 0,
                "total_rows": row.get("total_rows") or 0,
                "total_bytes_readable": row.get("total_bytes_readable") or "0 B"
            }
        except Exception as e:
            metrics["clickhouse"] = {"status": "error", "error": str(e), "container": clickhouse_container}
    else:
        metrics["clickhouse"] = {
            "status": "offline",
            "container": clickhouse_container,
            "fallback": "pandas_analysis"
        }
    
    return {"metrics": metrics, "timestamp": datetime.now().isoformat()}


@router.get("/cache/stats")
def get_cache_stats(current_admin: User = Depends(get_current_admin)):
    """获取缓存统计信息"""
    return cache_manager.get_stats()


# 缓存键前缀（与 cache_manager._make_key 中保持一致）
_CACHE_KEY_PREFIX = "data-insight:"

# 缓存键业务分类映射表：key 前缀 -> 中文标签
# 注意：前缀较长/较具体的应排在前面，避免被短前缀误吞
# 实际键前缀来源：datasets.py(datasets:user:{id}:list)、ml.py(ml:precheck/ml:featrec)、
# feature_engineering.py(feature_engineering:precheck)、support.py(support:captcha)
_CACHE_KEY_CATEGORY_MAP = {
    "feature_engineering:": "特征工程缓存",
    "support:": "验证码缓存",
    "datasets:": "数据集缓存",
    "cleaning:": "清洗缓存",
    "users:": "用户缓存",
    "ai:": "AI缓存",
    "ml:": "ML缓存",
}


def _classify_cache_key(key: str) -> str:
    """根据缓存 key 的业务前缀归类，返回中文标签"""
    if not key:
        return "通用缓存"
    for prefix, label in _CACHE_KEY_CATEGORY_MAP.items():
        if key.startswith(prefix):
            return label
    return "通用缓存"


def _strip_cache_prefix(key: str) -> str:
    """去除缓存键的 data-insight: 前缀，返回业务原始键名"""
    if key.startswith(_CACHE_KEY_PREFIX):
        return key[len(_CACHE_KEY_PREFIX):]
    return key


@router.get("/cache/keys")
def list_cache_keys(
    prefix: str = Query(None, description="键前缀过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_admin: User = Depends(get_current_admin)
):
    """列出缓存键（返回的 key 不带 data-insight: 前缀，便于前端展示业务原始键名）"""
    stats = cache_manager.get_stats()
    redis_available = stats.get("redis_available")

    keys = []
    if redis_available:
        import redis
        try:
            r = redis.from_url(settings.REDIS_URL)
            pattern = f"{_CACHE_KEY_PREFIX}{prefix}*" if prefix else f"{_CACHE_KEY_PREFIX}*"
            # scan_iter 迭代避免 keys() 全量阻塞 Redis
            raw_keys = [k.decode('utf-8') for k in r.scan_iter(match=pattern, count=500)]
            all_keys = [_strip_cache_prefix(k) for k in raw_keys]
            total = len(all_keys)
            start = (page - 1) * page_size
            end = start + page_size
            paginated_keys = all_keys[start:end]

            for key in paginated_keys:
                # 查询 TTL、类型、值大小时需用带前缀的完整键名
                full_key = cache_manager._make_key(key)
                ttl = r.ttl(full_key)
                key_type = r.type(full_key).decode('utf-8')
                # 值大小：优先 memory_usage（Redis 4.0+），不可用时降级为值长度估算
                size_bytes = 0
                try:
                    size_bytes = r.memory_usage(full_key) or 0
                except Exception:
                    v = r.get(full_key)
                    size_bytes = len(v) if v else 0
                keys.append({
                    "key": key,
                    "ttl": ttl,
                    "type": key_type,
                    "category": _classify_cache_key(key),
                    "size_bytes": size_bytes,
                })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Redis 操作失败: {e}")
    else:
        memory_cache = cache_manager._memory
        # 内存缓存内部使用带前缀的键，这里同样 strip 掉前缀
        raw_keys = list(memory_cache._cache.keys())
        all_keys = [_strip_cache_prefix(k) for k in raw_keys]
        # 内存缓存分支也应用前缀过滤，保持与 Redis 分支行为一致
        if prefix:
            all_keys = [k for k in all_keys if k.startswith(prefix)]
        total = len(all_keys)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_keys = all_keys[start:end]

        for key in paginated_keys:
            # 内存缓存内部用带前缀的键存储 TTL，需还原前缀查询
            full_key = cache_manager._make_key(key)
            ttl = memory_cache._ttl.get(full_key)
            if ttl:
                remaining = max(0, int(ttl - datetime.now().timestamp()))
            else:
                remaining = -1
            value = memory_cache._cache.get(full_key)
            size_bytes = 0
            try:
                size_bytes = len(json.dumps(value, default=str)) if value is not None else 0
            except Exception:
                size_bytes = 0
            keys.append({
                "key": key,
                "ttl": remaining,
                "type": "string",
                "category": _classify_cache_key(key),
                "size_bytes": size_bytes,
            })

    return {"keys": keys, "total": total, "page": page, "page_size": page_size}


@router.get("/cache/keys/{key}")
def get_cache_key_detail(
    key: str,
    current_admin: User = Depends(get_current_admin)
):
    """获取缓存键详情"""
    value = cache_manager.get(key)
    if value is None:
        raise HTTPException(status_code=404, detail="键不存在")
    
    return {"key": key, "value": value}


@router.delete("/cache/keys/{key}")
def delete_cache_key(
    key: str,
    current_admin: User = Depends(get_current_admin)
):
    """删除指定缓存键"""
    cache_manager.delete(key)
    return {"message": f"缓存键 {key} 已删除"}


@router.post("/cache/clear")
def clear_all_cache(current_admin: User = Depends(get_current_admin)):
    """清空所有缓存"""
    cache_manager.clear()
    return {"message": "所有缓存已清空"}


class ClearCacheCategoryRequest(BaseModel):
    """按业务分类清理缓存请求体"""
    category: str


@router.get("/cache/category-stats")
def get_cache_category_stats(current_admin: User = Depends(get_current_admin)):
    """缓存键按业务分类全量统计（2026-08-15 新增：后端聚合，替代前端当前页聚合的失真统计）"""
    stats = cache_manager.get_stats()
    redis_available = stats.get("redis_available")

    # 初始化分类计数（含通用缓存兜底）
    categories = {label: 0 for label in _CACHE_KEY_CATEGORY_MAP.values()}
    categories["通用缓存"] = 0
    total = 0

    if redis_available:
        import redis
        try:
            r = redis.from_url(settings.REDIS_URL)
            for raw in r.scan_iter(match=f"{_CACHE_KEY_PREFIX}*", count=500):
                key = _strip_cache_prefix(raw.decode('utf-8'))
                label = _classify_cache_key(key)
                categories[label] = categories.get(label, 0) + 1
                total += 1
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Redis 操作失败: {e}")
    else:
        for raw in cache_manager._memory._cache.keys():
            key = _strip_cache_prefix(raw)
            label = _classify_cache_key(key)
            categories[label] = categories.get(label, 0) + 1
            total += 1

    result = []
    for label, count in categories.items():
        # 通用缓存恒展示（可能为空）；其余分类仅展示有键的
        if count > 0 or label == "通用缓存":
            result.append({
                "category": label,
                "count": count,
                "ratio": round(count / total * 100, 1) if total else 0,
            })
    result.sort(key=lambda x: x["count"], reverse=True)
    return {"categories": result, "total": total}


@router.post("/cache/clear-category")
def clear_cache_category(
    body: ClearCacheCategoryRequest,
    current_admin: User = Depends(get_current_admin)
):
    """按业务分类清理缓存（2026-08-15 新增：只删该分类前缀的键，不影响其他模块与验证码等临时键）

    "通用缓存"特殊处理：清理不属于任何已知分类前缀的键（按扫描收集逐个删除）。
    """
    # 通用缓存：收集所有不在已知前缀内的键删除
    if body.category == "通用缓存":
        stats = cache_manager.get_stats()
        redis_available = stats.get("redis_available")
        known_prefixes = tuple(_CACHE_KEY_CATEGORY_MAP.keys())
        deleted = 0

        if redis_available:
            import redis
            try:
                r = redis.from_url(settings.REDIS_URL)
                for raw in r.scan_iter(match=f"{_CACHE_KEY_PREFIX}*", count=500):
                    key = _strip_cache_prefix(raw.decode('utf-8'))
                    if not key.startswith(known_prefixes):
                        r.delete(raw)
                        deleted += 1
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Redis 操作失败: {e}")
        else:
            for raw in list(cache_manager._memory._cache.keys()):
                key = _strip_cache_prefix(raw)
                if not key.startswith(known_prefixes):
                    cache_manager._memory.delete(raw)
                    deleted += 1
        return {"message": f"通用缓存已清理（{deleted} 个键）"}

    prefix = None
    for p, label in _CACHE_KEY_CATEGORY_MAP.items():
        if label == body.category:
            prefix = p
            break
    if not prefix:
        raise HTTPException(status_code=400, detail=f"未知缓存分类: {body.category}")
    cache_manager.delete_pattern(f"{prefix}*")
    return {"message": f"{body.category}已清理"}


@router.get("/storage/stats")
def get_storage_stats(current_admin: User = Depends(get_current_admin)):
    """获取存储统计信息"""
    return storage_manager.get_stats()


@router.get("/storage/files")
def list_storage_files(
    prefix: str = Query("", description="目录前缀"),
    file_type: str = Query("", description="文件类型筛选(uploads/cleaning/models等)"),
    user_id: int = Query(0, description="按用户ID筛选"),
    keyword: str = Query("", description="文件名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """列出存储中的文件，支持按类型、用户筛选和文件名模糊搜索"""
    type_mapping = {
        "uploads": "原始数据",
        "cleaning": "清洗结果",
        "feature_engineering": "特征工程",
        "models": "ML模型",
        "ml": "预测结果",
        "reports": "分析报告",
        "data_mining": "数据挖掘",
        "trash": "回收站",
    }

    all_files = storage_manager.list_files("")

    # 按类型筛选
    if file_type:
        if file_type == "other":
            classified_paths = list(type_mapping.keys())
            all_files = [f for f in all_files if not any(f.get("path", "").startswith(p) for p in classified_paths)]
        elif file_type == "ai":
            all_files = [f for f in all_files if f.get("path", "").startswith("ai")]
        elif file_type == "ml":
            all_files = [f for f in all_files if f.get("path", "").startswith("ml")]
        else:
            all_files = [f for f in all_files if f.get("path", "").startswith(file_type)]

    # 如果指定了类型，转换为前缀（ai 和 ml 类型特殊处理）
    if file_type and file_type != "other" and not prefix:
        if file_type in ("ai", "ml"):
            pass
        else:
            prefix = file_type

    # 按用户筛选（文件路径中包含 user_{id}）；未指定用户时按前缀过滤
    if user_id:
        user_prefix = f"user_{user_id}"
        all_files = [f for f in all_files if user_prefix in f.get("path", "")]
    elif prefix:
        all_files = [f for f in all_files if f.get("path", "").startswith(prefix)]

    # 文件名模糊搜索
    if keyword:
        keyword_lower = keyword.lower()
        all_files = [f for f in all_files if keyword_lower in f.get("name", "").lower()]

    # 修正文件大小：list_objects 可能返回 size=0，用 stat_object 获取真实大小
    for f in all_files:
        if not f.get("size") or f.get("size") == 0:
            try:
                minio_s = storage_manager._minio_storage
                stat = minio_s.client.stat_object(minio_s.bucket, f["path"])
                f["size"] = stat.size
                if not f.get("modified_time") and stat.last_modified:
                    f["modified_time"] = stat.last_modified.isoformat()
            except Exception:
                pass

    # 按修改时间倒序排序，最新的文件在最上面
    all_files.sort(key=lambda x: x.get("modified_time", ""), reverse=True)

    total = len(all_files)
    # 在 Python 层对返回的 list 切片实现分页
    start = (page - 1) * page_size
    end = start + page_size
    paginated_files = all_files[start:end]

    return {"files": paginated_files, "total": total, "page": page, "page_size": page_size}


@router.get("/storage/stats-by-type")
def get_storage_stats_by_type(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """按数据类型分类统计存储（合并 MinIO 和数据库数据）"""
    # 分类映射：MinIO 真实路径前缀 → 中文标签（与用户端数据管理 Tab 对应）
    type_mapping = {
        "uploads": "原始数据",
        "cleaning": "数据清洗产物",
        "data_mining": "数据挖掘产物",
        "feature_engineering": "特征工程产物",
        "models": "ML模型",
        "ml": "预测结果",
        "reports": "分析报告",
        "trash": "回收站",
    }

    all_files = storage_manager.list_files("")

    # 按路径前缀分类统计（反映 MinIO 真实存储情况）
    type_stats = {}
    for prefix, label in type_mapping.items():
        # 各分类从 MinIO 统计
        type_files = [f for f in all_files if f.get("path", "").startswith(prefix)]
        type_stats[prefix] = {
            "label": label,
            "count": len(type_files),
            "total_size": sum(f.get("size", 0) for f in type_files)
        }

    # 其他未分类文件
    classified_paths = set(type_mapping.keys())
    other_files = []
    for f in all_files:
        path = f.get("path", "")
        if not any(path.startswith(p) for p in classified_paths):
            other_files.append(f)
    type_stats["other"] = {
        "label": "其他",
        "count": len(other_files),
        "total_size": sum(f.get("size", 0) for f in other_files)
    }

    return {"type_stats": type_stats}


@router.delete("/storage/files")
def delete_storage_file(
    file_path: str = Query(..., description="文件路径"),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """删除存储中的单个文件(文件路径作为query参数传递,避免斜杠导致的路由匹配问题)

    与批量删除行为保持一致:
    - 删除 MinIO 文件
    - 同步删除数据库中关联的 Dataset 记录和 TaskRecord 记录
    - 对 ML 模型文件:级联删除测试集 CSV 文件
    - 对 ML 测试集文件:返回关联模型警告,需用户确认 force=true 才删除
    """
    from app.models import Dataset, TaskRecord
    from app.api.ml import cascade_delete_ml_testset, find_ml_model_by_testset_path

    # 测试集文件保护:删除前检查是否关联 ML 模型
    if 'testset' in file_path:
        related_models = find_ml_model_by_testset_path(db, file_path)
        if related_models:
            model_names = [m.name for m in related_models]
            raise HTTPException(
                status_code=409,
                detail=f"该文件是 ML 测试集,关联模型: {', '.join(model_names)}。删除后该模型将无法进行测试集评估。如确认删除,请使用批量删除接口或先删除关联模型。"
            )

    # 查找关联的 Dataset 记录(删除前先查,用于级联清理测试集)
    related_datasets = db.query(Dataset).filter(Dataset.file_path == file_path).all()
    for ds in related_datasets:
        if ds.artifact_type == "ml_model":
            cascade_delete_ml_testset(ds)

    # 删除 MinIO 文件
    success = storage_manager.delete(file_path)
    if not success:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 同步删除关联的 Dataset 和 TaskRecord 记录(与批量删除行为一致)
    deleted_dataset_count = 0
    for ds in related_datasets:
        db.query(TaskRecord).filter(TaskRecord.dataset_id == ds.id).delete()
        db.delete(ds)
        deleted_dataset_count += 1
    db.commit()

    return {
        "message": f"文件 {file_path} 已删除",
        "deleted_dataset_count": deleted_dataset_count
    }


@router.post("/storage/files/batch-delete")
def batch_delete_storage_files(
    body: dict,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """批量删除存储中的文件
    同时删除 MinIO 文件和数据库中关联的所有数据集记录（包括已删除/已清空的）
    """
    file_paths = body.get("file_paths", [])
    if not file_paths:
        raise HTTPException(status_code=400, detail="文件路径列表不能为空")

    from app.models import Dataset, TaskRecord
    deleted_files = []
    failed_files = []
    deleted_datasets = []

    for file_path in file_paths:
        try:
            # ML 测试集文件保护:检查是否关联 ML 模型
            # 测试集文件没有 Dataset 记录,需要遍历 pkl 反查
            if 'testset' in file_path:
                from app.api.ml import find_ml_model_by_testset_path
                related_models = find_ml_model_by_testset_path(db, file_path)
                if related_models:
                    # 批量删除中遇到关联模型的测试集,跳过并记录失败
                    model_names = [m.name for m in related_models]
                    failed_files.append({
                        "path": file_path,
                        "reason": f"ML 测试集关联模型 {', '.join(model_names)},请先删除关联模型"
                    })
                    continue

            # 删除前先查找关联的 Dataset 记录,用于级联清理 ML 测试集
            related_datasets = db.query(Dataset).filter(Dataset.file_path == file_path).all()
            for ds in related_datasets:
                if ds.artifact_type == "ml_model":
                    from app.api.ml import cascade_delete_ml_testset
                    cascade_delete_ml_testset(ds)

            # 删除 MinIO 中的文件
            success = storage_manager.delete(file_path)
            if success:
                deleted_files.append(file_path)
            else:
                failed_files.append({"path": file_path, "reason": "文件不存在或删除失败"})
                continue

            # 删除数据库中关联的所有数据集记录（不管什么状态，物理删除）
            for ds in related_datasets:
                # 删除关联的任务记录
                db.query(TaskRecord).filter(TaskRecord.dataset_id == ds.id).delete()
                deleted_datasets.append(ds.id)
                db.delete(ds)

        except Exception as e:
            failed_files.append({"path": file_path, "reason": str(e)})

    db.commit()

    return {
        "message": f"成功删除 {len(deleted_files)} 个项目，{len(deleted_datasets)} 条数据集记录",
        "deleted_count": len(deleted_files),
        "deleted_dataset_count": len(deleted_datasets),
        "failed_count": len(failed_files),
        "failed_files": failed_files
    }


@router.get("/storage/files/download/{file_path:path}")
def download_storage_file(
    file_path: str,
    current_admin: User = Depends(get_current_admin)
):
    """下载存储中的文件（支持路径中包含斜杠）"""
    return _build_download_response(file_path)


def _build_download_response(file_path: str) -> StreamingResponse:
    """构造文件下载响应的公共逻辑：校验存在性、读取内容并设置下载头"""
    if not storage_manager.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    content = storage_manager.read(file_path)
    if isinstance(content, str):
        content = content.encode('utf-8')

    filename = file_path.split('/')[-1]
    # filename* 支持中文与特殊字符（与用户端下载规范一致，见 datasets.py _download_name）
    quoted = quote(filename)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}
    )


@router.get("/database/tables")
def list_database_tables(current_admin: User = Depends(get_current_admin)):
    """列出数据库表（含统计信息）"""
    from app.utils.db import engine
    tables = []
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        
        with engine.connect().execution_options(timeout=30) as conn:
            for table_name in table_names:
                columns = inspector.get_columns(table_name)
                column_info = []
                for col in columns:
                    column_info.append({
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col["nullable"],
                        "default": col["default"]
                    })

                row_count_query = text(f"SELECT COUNT(*) FROM {table_name}")
                row_count = conn.execute(row_count_query).scalar()

                size_query = text(f"SELECT pg_total_relation_size(:table_name)")
                table_size = conn.execute(size_query, {"table_name": table_name}).scalar()

                indexes = inspector.get_indexes(table_name)
                index_info = []
                for idx in indexes:
                    index_info.append({
                        "name": idx.get("name", ""),
                        "column_names": idx.get("column_names", []),
                        "unique": idx.get("unique", False)
                    })

                tables.append({
                    "name": table_name,
                    "columns": column_info,
                    "indexes": index_info,
                    "row_count": int(row_count) if row_count else 0,
                    "table_size": int(table_size) if table_size else 0,
                    "index_count": len(indexes),
                    "column_count": len(column_info)
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {e}")
    
    return {"tables": tables}


def _get_valid_table_names():
    """获取当前数据库中所有合法表名（白名单）"""
    from app.utils.db import engine
    inspector = inspect(engine)
    return inspector.get_table_names()


@router.get("/database/tables/{table_name}/data")
def get_table_data(
    table_name: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str = Query(None, description="搜索关键词"),
    current_admin: User = Depends(get_current_admin)
):
    """获取表数据预览（参数化查询，表名白名单验证，支持搜索）"""
    from app.utils.db import engine

    valid_tables = _get_valid_table_names()
    if table_name not in valid_tables:
        raise HTTPException(status_code=400, detail=f"表 '{table_name}' 不存在或不允许访问")

    try:
        import pandas as pd
        import numpy as np
        from sqlalchemy import text

        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        text_columns = [col["name"] for col in columns if any(t in str(col["type"]).lower() for t in ("text", "varchar", "char", "string"))]

        base_query = f"SELECT * FROM {table_name}"
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        params = {"limit": limit, "offset": offset}

        if search and search.strip():
            search_term = search.strip().replace("%", "\\%").replace("_", "\\_")
            like_patterns = [f"{col} ILIKE :search_{i}" for i, col in enumerate(text_columns)]
            if like_patterns:
                where_clause = " WHERE " + " OR ".join(like_patterns)
                base_query += where_clause
                count_query += where_clause
                for i, col in enumerate(text_columns):
                    params[f"search_{i}"] = f"%{search_term}%"

        query = text(f"{base_query} LIMIT :limit OFFSET :offset")
        with engine.connect().execution_options(timeout=30) as conn:
            df = pd.read_sql(query, conn, params=params)
            total_query = text(count_query)
            total = conn.execute(total_query, {k: v for k, v in params.items() if k not in ["limit", "offset"]}).scalar()

        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

        return {
            "columns": df.columns.tolist(),
            "data": df.to_dict('records'),
            "total": int(total) if total else 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@router.get("/database/tables/{table_name}/export")
def export_table_data(
    table_name: str,
    search: str = Query(None, description="搜索关键词"),
    current_admin: User = Depends(get_current_admin)
):
    """导出表数据为 CSV"""
    from app.utils.db import engine

    valid_tables = _get_valid_table_names()
    if table_name not in valid_tables:
        raise HTTPException(status_code=400, detail=f"表 '{table_name}' 不存在或不允许访问")

    try:
        import pandas as pd
        import numpy as np
        from sqlalchemy import text

        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        text_columns = [col["name"] for col in columns if any(t in str(col["type"]).lower() for t in ("text", "varchar", "char", "string"))]

        base_query = f"SELECT * FROM {table_name}"
        params = {}

        if search and search.strip():
            search_term = search.strip().replace("%", "\\%").replace("_", "\\_")
            like_patterns = [f"{col} ILIKE :search_{i}" for i, col in enumerate(text_columns)]
            if like_patterns:
                base_query += " WHERE " + " OR ".join(like_patterns)
                for i, col in enumerate(text_columns):
                    params[f"search_{i}"] = f"%{search_term}%"

        with engine.connect().execution_options(timeout=60) as conn:
            df = pd.read_sql(text(base_query), conn, params=params)

        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

        import csv
        import io
        output = io.StringIO()
        df.to_csv(output, index=False, quoting=csv.QUOTE_NONNUMERIC)
        content = output.getvalue().encode('utf-8-sig')

        timestamp = datetime.now(SHANGHAI_TZ).strftime('%Y%m%d_%H%M%S')
        filename = f"{table_name}_{timestamp}.csv"

        # 中文/空格表名需 URL 编码，否则浏览器下载文件名乱码
        from urllib.parse import quote as _quote
        encoded_name = _quote(filename)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")


def _pg_dump_docker(db_url) -> bytes:
    """使用 Docker 容器内 pg_dump 执行备份（本机未安装 PostgreSQL 客户端时降级）

    PostgreSQL 运行于 Docker 容器 data-insight-postgres，容器内自带 pg_dump。
    通过 docker CLI（subprocess）执行，不依赖 docker SDK 包，兼容任意 Python 环境。
    返回完整 SQL 备份内容。
    """
    container_name = "data-insight-postgres"
    cmd = [
        "docker", "exec", container_name, "pg_dump",
        "-U", db_url.username or "postgres",
        "-d", db_url.database or "postgres", "-F", "p",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180)
    except FileNotFoundError:
        raise RuntimeError("docker 命令不可用，无法通过容器执行备份")
    except subprocess.TimeoutExpired:
        raise RuntimeError("容器内 pg_dump 执行超时（180秒）")
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "ignore") if isinstance(result.stderr, bytes) else str(result.stderr)
        raise RuntimeError(f"容器内 pg_dump 执行失败: {err[:500]}")
    content = result.stdout
    if not content:
        raise RuntimeError("容器内 pg_dump 输出为空，备份可能未完成")
    return content


@router.get("/database/backup")
def backup_database(current_admin: User = Depends(get_current_admin)):
    """数据库备份（生成 SQL 文件下载）

    优先使用本机 pg_dump（需安装 PostgreSQL 客户端工具）；
    本机未安装时自动降级为执行 Docker 容器 data-insight-postgres 内的 pg_dump。
    """
    from app.config import settings
    from sqlalchemy import make_url
    import tempfile

    try:
        timestamp = datetime.now(SHANGHAI_TZ).strftime('%Y%m%d_%H%M%S')
        filename = f"database_backup_{timestamp}.sql"

        # 从 DATABASE_URL 解析连接参数
        db_url = make_url(settings.DATABASE_URL)
        host = db_url.host or "localhost"
        port = db_url.port or 5432
        user = db_url.username or "postgres"
        password = db_url.password or ""
        dbname = db_url.database or "postgres"

        content = None
        try:
            # 方式一：本机 pg_dump
            env = os.environ.copy()
            env['PGPASSWORD'] = password
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as f:
                temp_path = f.name
            try:
                cmd = [
                    'pg_dump', '-h', host, '-p', str(port),
                    '-U', user, '-d', dbname, '-F', 'p', '-f', temp_path
                ]
                result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    raise HTTPException(status_code=500, detail=f"备份失败: {result.stderr[:500]}")
                with open(temp_path, 'rb') as f:
                    content = f.read()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        except FileNotFoundError:
            # 方式二：本机无 pg_dump → 降级为 Docker 容器内 pg_dump
            content = _pg_dump_docker(db_url)

        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/sql",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="备份超时（120秒）")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"备份失败: {e}")


class SqlQueryRequest(BaseModel):
    query: str


@router.post("/database/query")
def execute_query(
    request: SqlQueryRequest,
    current_admin: User = Depends(get_current_admin)
):
    """执行只读 SQL 查询（带超时控制）"""
    query = request.query
    if not query.strip().upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="仅支持 SELECT 查询")

    from app.utils.db import engine

    try:
        import pandas as pd
        import numpy as np
        from sqlalchemy import text

        with engine.connect().execution_options(timeout=30) as conn:
            df = pd.read_sql(text(query), conn)

        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

        return {
            "columns": df.columns.tolist(),
            "data": df.to_dict('records'),
            "row_count": len(df)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@router.get("/tasks/stats")
def get_task_stats(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取任务统计信息（含队列实时数、今日概况、成功率、平均耗时）"""
    # 自愈清理僵尸任务（running + 无 Celery 任务 + 超 60 分钟）
    _auto_heal_zombie_tasks(db)
    # created_at 存 UTC naive（上海时间 = UTC + 8h）。"今日"按上海时区零点折算回 UTC 起点，
    # 避免上海 00:00-08:00 的新增任务漏计（与 _daily_trend 的 +interval '8 hours' 口径一致）
    now_shanghai = datetime.utcnow() + timedelta(hours=8)
    today_start = now_shanghai.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)

    # 队列实时数（任务管理顶部监控卡）
    running_count = db.query(func.count(TaskRecord.id)).filter(TaskRecord.status == "running").scalar() or 0
    pending_count = db.query(func.count(TaskRecord.id)).filter(TaskRecord.status == "pending").scalar() or 0

    # 今日概况
    today_total = db.query(func.count(TaskRecord.id)).filter(TaskRecord.created_at >= today_start).scalar() or 0
    today_success = db.query(func.count(TaskRecord.id)).filter(
        TaskRecord.created_at >= today_start, TaskRecord.status == "success"
    ).scalar() or 0
    today_failed = db.query(func.count(TaskRecord.id)).filter(
        TaskRecord.created_at >= today_start, TaskRecord.status == "failed"
    ).scalar() or 0

    # 平均耗时（仅统计已结束且记录执行时间的任务）
    avg_time = db.query(func.avg(TaskRecord.execution_time)).filter(
        TaskRecord.execution_time.isnot(None),
        TaskRecord.status.in_(["success", "failed"])
    ).scalar()

    # 全量成功率
    total_done = db.query(func.count(TaskRecord.id)).filter(
        TaskRecord.status.in_(["success", "failed"])
    ).scalar() or 0
    total_success = db.query(func.count(TaskRecord.id)).filter(TaskRecord.status == "success").scalar() or 0
    success_rate = round(total_success / total_done * 100, 1) if total_done else None

    return {
        "async_available": task_manager.is_async_available(),
        "mode": "celery" if task_manager.is_async_available() else "sync",
        "stats": task_manager.get_stats() if hasattr(task_manager, 'get_stats') else {},
        "running_count": running_count,
        "pending_count": pending_count,
        "today_total": today_total,
        "today_success": today_success,
        "today_failed": today_failed,
        "success_rate": success_rate,
        "avg_execution_time_ms": round(avg_time) if avg_time else None,
    }


@router.get("/clickhouse/status")
def get_clickhouse_status(current_admin: User = Depends(get_current_admin)):
    """获取 ClickHouse 状态"""
    if not settings.CLICKHOUSE_ENABLED:
        return {"status": "offline", "message": "ClickHouse 未启用"}
    
    try:
        import requests
        response = requests.get(f"http://{settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT}/ping")
        if response.text.strip() == "Ok.":
            return {"status": "online", "message": "ClickHouse 连接正常"}
        else:
            return {"status": "error", "message": f"ClickHouse 响应异常: {response.text}"}
    except Exception as e:
        return {"status": "offline", "message": f"ClickHouse 连接失败: {e}"}


@router.get("/clickhouse/databases")
def list_clickhouse_databases(current_admin: User = Depends(get_current_admin)):
    """列出 ClickHouse 数据库"""
    if not settings.CLICKHOUSE_ENABLED:
        raise HTTPException(status_code=400, detail="ClickHouse 未启用")
    
    try:
        import requests
        query = "SHOW DATABASES"
        url = f"http://{settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT}/"
        auth = (settings.CLICKHOUSE_USER, settings.CLICKHOUSE_PASSWORD)
        response = requests.post(url, data=query, auth=auth)
        if response.status_code == 200:
            databases = [line.strip() for line in response.text.strip().split('\n')]
            return {"databases": databases}
        else:
            raise HTTPException(status_code=500, detail=f"查询失败: {response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse 操作失败: {e}")


@router.get("/clickhouse/tables")
def list_clickhouse_tables(
    database: str = Query("default", description="数据库名"),
    current_admin: User = Depends(get_current_admin)
):
    """列出 ClickHouse 表"""
    if not settings.CLICKHOUSE_ENABLED:
        raise HTTPException(status_code=400, detail="ClickHouse 未启用")
    
    try:
        import requests
        query = f"SHOW TABLES FROM {database}"
        url = f"http://{settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT}/"
        auth = (settings.CLICKHOUSE_USER, settings.CLICKHOUSE_PASSWORD)
        response = requests.post(url, data=query, auth=auth)
        if response.status_code == 200:
            tables = [line.strip() for line in response.text.strip().split('\n')]
            return {"tables": tables, "database": database}
        else:
            raise HTTPException(status_code=500, detail=f"查询失败: {response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse 操作失败: {e}")


@router.post("/clickhouse/query")
def execute_clickhouse_query(
    query: str = Body(..., embed=True, description="ClickHouse 查询语句（仅支持 SELECT）"),
    current_admin: User = Depends(get_current_admin)
):
    """执行 ClickHouse 查询"""
    if not settings.CLICKHOUSE_ENABLED:
        raise HTTPException(status_code=400, detail="ClickHouse 未启用")
    
    if not query.strip().upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="仅支持 SELECT 查询")
    
    try:
        import requests
        # default_format=TSVWithNames: 首行为列名（含中文列名/别名），否则默认 TSV 无列名头、首行数据会被误当列名
        url = f"http://{settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT}/?default_format=TSVWithNames"
        auth = (settings.CLICKHOUSE_USER, settings.CLICKHOUSE_PASSWORD)
        response = requests.post(url, data=query, auth=auth)
        if response.status_code == 200:
            lines = response.text.strip().split('\n')
            if not lines:
                return {"columns": [], "data": [], "row_count": 0}
            
            columns = lines[0].strip().split('\t')
            data = []
            for line in lines[1:]:
                if not line.strip():
                    continue
                values = line.strip().split('\t')
                row = dict(zip(columns, values))
                data.append(row)
            
            return {"columns": columns, "data": data, "row_count": len(data)}
        else:
            raise HTTPException(status_code=500, detail=f"查询失败: {response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse 操作失败: {e}")


# ==================== ClickHouse 同步管理 API（批次D）====================

# registry status → 中文标签
_CH_SYNC_STATUS_MAP = {
    "synced": "已同步",
    "failed": "同步失败",
    "syncing": "同步中",
}


@router.get("/clickhouse/sync-status")
def get_clickhouse_sync_status(db: Session = Depends(get_db),
                               current_admin: User = Depends(get_current_admin)):
    """数据集 ClickHouse 同步状态列表（registry + 阈值/可用性汇总）"""
    enabled = clickhouse_service.is_enabled()
    available = clickhouse_service.is_available() if enabled else False
    min_rows = int(settings.CLICKHOUSE_MIN_ROWS)
    regs = clickhouse_service.registry_list() if enabled else []
    items = []
    for reg in regs:
        status = str(reg.get("status") or "unknown")
        row_count = int(reg.get("row_count") or 0)
        try:
            columns = json.loads(reg.get("columns_json") or "{}")
            col_count = len(columns) if isinstance(columns, dict) else 0
        except (ValueError, TypeError):
            col_count = 0
        items.append({
            "dataset_id": int(reg.get("dataset_id") or 0),
            "dataset_name": reg.get("dataset_name") or "",
            "table_name": reg.get("table_name") or "",
            "row_count": row_count,
            "column_count": col_count,
            "status": status,
            "status_label": _CH_SYNC_STATUS_MAP.get(status, status),
            "meets_threshold": row_count >= min_rows,
            "data_version": int(reg.get("data_version") or 0),
            "synced_at": reg.get("synced_at"),
            "last_error": (reg.get("last_error") or "")[:200],
        })
    synced = sum(1 for r in items if r["status"] == "synced")
    failed = sum(1 for r in items if r["status"] == "failed")
    return {
        "enabled": enabled,
        "available": available,
        "min_rows": min_rows,
        "total": len(items),
        "synced": synced,
        "failed": failed,
        "items": items,
    }


@router.post("/clickhouse/sync/{dataset_id}")
def sync_clickhouse_dataset(dataset_id: int, db: Session = Depends(get_db),
                            current_admin: User = Depends(get_current_admin)):
    """手动重建单个数据集的 ClickHouse 同步（异步执行，状态可在 sync-status 查询）"""
    if not (settings.CLICKHOUSE_SYNC_ENABLED and clickhouse_service.is_enabled()):
        raise HTTPException(status_code=400, detail="ClickHouse 同步未启用")
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id, Dataset.status == "active"
    ).first()
    if not dataset:
        raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}")
    if str(dataset.artifact_type or "") not in ("raw_data", "analysis_data"):
        raise HTTPException(status_code=400,
                            detail=f"仅原始数据可同步（当前类型: {dataset.artifact_type}）")
    try:
        from app.services.clickhouse_service import trigger_sync
        trigger_sync(dataset_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步触发失败: {e}")
    return {"status": "triggered", "dataset_id": dataset_id, "message": "同步任务已触发，稍后可在同步状态页查看结果"}


@router.post("/clickhouse/cleanup/{dataset_id}")
def cleanup_clickhouse_dataset(dataset_id: int, db: Session = Depends(get_db),
                               current_admin: User = Depends(get_current_admin)):
    """清理单个数据集的 ClickHouse 副本（副本表 + 注册记录），数据本身不受影响"""
    existed = clickhouse_service.registry_get(dataset_id) is not None
    clickhouse_service.drop_dataset(dataset_id)
    return {"status": "cleaned", "dataset_id": dataset_id,
            "had_copy": existed, "message": "副本已清理（数据源文件不受影响）"}


@router.post("/clickhouse/cleanup-all")
def cleanup_all_clickhouse(db: Session = Depends(get_db),
                           current_admin: User = Depends(get_current_admin)):
    """清理全部 ClickHouse 数据集副本（副本表 + 注册记录）"""
    regs = clickhouse_service.registry_list()
    count = 0
    for reg in regs:
        clickhouse_service.drop_dataset(int(reg.get("dataset_id") or 0))
        count += 1
    return {"status": "cleaned", "count": count, "message": f"已清理 {count} 个数据集副本"}


@router.get("/clickhouse/storage-stats")
def get_clickhouse_storage_stats(current_admin: User = Depends(get_current_admin)):
    """ClickHouse 副本存储占用统计"""
    return clickhouse_service.storage_stats()


# ==================== 业务数据查询 API ====================

# module_source 到中文任务类型的映射表
_MODULE_SOURCE_TO_TASK_TYPE = {
    "upload": "数据上传",
    "cleaning": "数据清洗",
    "ml": "机器学习",
    "ai": "AI分析",
    "feature_engineering": "特征工程",
    "data_mining": "数据挖掘",
    "data_analysis": "数据分析",
    "dataset": "数据治理",
    "pipeline": "联动分析",
    "batch_predict": "机器学习",
}

# task_type → 中文标签（任务管理列表/详情/统计共用）
_ADMIN_TASK_TYPE_MAP = {
    "upload": "数据上传",
    "dataset": "数据治理",
    "cleaning": "数据清洗",
    "ml": "机器学习",
    "ml_training": "模型训练",
    "feature_engineering": "特征工程",
    "feature_engineering_select": "特征选择",
    "feature_engineering_construct": "特征构造",
    "feature_engineering_encode": "特征编码",
    "feature_engineering_scale": "特征缩放",
    "feature_engineering_reduce": "特征降维",
    "ai": "AI分析",
    "data_mining": "数据挖掘",
    "data_analysis": "数据分析",
    "user_admin": "账号管理",
}

# status → 中文标签
_ADMIN_TASK_STATUS_MAP = {
    "pending": "等待中",
    "running": "执行中",
    "success": "成功",
    "failed": "失败",
    "cancelled": "已取消",
    "warning": "警告",
    "error": "错误",
}


def _auto_heal_zombie_tasks(db: Session) -> int:
    """自愈清理僵尸任务（2026-08-15 新增）

    判定条件：status=running 且 celery_task_id 为 NULL 且创建超过 60 分钟。
    - celery_task_id 为 NULL 说明从未提交 Celery（同步执行路径），无法反查任务状态
    - 超过 60 分钟远超 Celery 30 分钟硬超时（CELERY_TASK_TIME_LIMIT=1800s），
      真实执行中的任务不可能存活这么久，必然是进程中断/会话异常遗留的僵尸记录

    处置：统一置为 cancelled 并在 result_summary 标注 admin_cancel（admin="system"），
    避免污染失败统计，同时保留记录供追溯。
    """
    import json as _json
    from sqlalchemy import text as _text

    cutoff = datetime.utcnow() - timedelta(minutes=60)
    mark = _json.dumps({
        "admin_cancel": {
            "admin": "system",
            "at": datetime.utcnow().isoformat(),
            "note": "系统自动清理：运行超时且无 Celery 任务的僵尸任务",
        }
    }, ensure_ascii=False)
    result = db.execute(
        _text(
            "UPDATE task_records SET status='cancelled', completed_at=:now, "
            "result_summary = CASE "
            "  WHEN result_summary IS NULL THEN CAST(:mark AS jsonb) "
            "  WHEN CAST(result_summary AS jsonb) = CAST('{}' AS jsonb) THEN CAST(:mark AS jsonb) "
            "  ELSE CAST(result_summary AS jsonb) || CAST(:mark AS jsonb) END "
            "WHERE status='running' AND celery_task_id IS NULL "
            "AND created_at < :cutoff"
        ),
        {"now": datetime.utcnow(), "mark": mark, "cutoff": cutoff},
    )
    db.commit()
    return result.rowcount or 0


@router.get("/business/datasets")
def list_business_datasets(
    user_id: int = Query(None, description="用户ID筛选"),
    module_source: str = Query(None, description="来源模块筛选"),
    status: str = Query(None, description="状态筛选"),
    keyword: str = Query("", description="文件名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """查询所有用户的数据集业务记录（联表 users 表获取 username）"""
    # 查询 Dataset 表
    # 自动检测 corrupted 状态：当查询 corrupted 时，先修复文件不存在但状态未标记的记录
    if status == "corrupted":
        check_query = db.query(Dataset).filter(
            or_(Dataset.status == "active", Dataset.status == None),
            Dataset.file_path.isnot(None)
        )
        if user_id is not None:
            check_query = check_query.filter(Dataset.user_id == user_id)
        corrupted_candidates = check_query.limit(1000).all()
        # 一次性拉取 MinIO 现有对象路径集合，避免逐条 stat_object 网络请求导致超时
        existing_paths = {f.get("path") for f in storage_manager.list_files("")}
        fixed_count = 0
        for ds in corrupted_candidates:
            if ds.file_path and ds.file_path not in existing_paths:
                ds.status = "corrupted"
                fixed_count += 1
        if fixed_count > 0:
            db.commit()

    ds_query = db.query(Dataset, User.username).outerjoin(User, Dataset.user_id == User.id)

    if user_id is not None:
        ds_query = ds_query.filter(Dataset.user_id == user_id)
    if module_source:
        if module_source == "ml":
            ds_query = ds_query.filter(Dataset.module_source.in_(["ml", "batch_predict"]))
        else:
            ds_query = ds_query.filter(Dataset.module_source == module_source)
    if keyword:
        ds_query = ds_query.filter(Dataset.name.ilike(f"%{keyword}%"))
    # 状态筛选：默认查活跃+回收站数据（active/deleted），让数据列表能看到用户回收站数据
    # 已清空（purged）和已损坏（corrupted）有专门的Tab展示，默认不纳入数据列表
    if status:
        ds_query = ds_query.filter(Dataset.status == status)
    else:
        ds_query = ds_query.filter(Dataset.status.in_(["active", "deleted"]))

    ds_total = ds_query.count()
    ds_rows = (
        ds_query.order_by(Dataset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    datasets = []
    for ds, username in ds_rows:
        datasets.append({
            "id": ds.id,
            "name": ds.name,
            "user_id": ds.user_id,
            "username": username,
            "module_source": ds.module_source,
            "module_label": ds.module_label,
            "artifact_type": ds.artifact_type,
            "algorithm": ds.algorithm,
            "row_count": ds.row_count,
            "file_size": ds.file_size,
            "status": ds.status,
            "color": dataset_color(ds.id),
            "file_path": ds.file_path,
            "parent_id": ds.parent_id,
            "root_dataset_id": ds.root_dataset_id,
            "source_type": ds.source_type,
            "connection_id": ds.connection_id,
            "table_name": ds.table_name,
            "created_at": _format_shanghai(ds.created_at) if ds.created_at else None,
            "deleted_at": _format_shanghai(ds.deleted_at) if ds.deleted_at else None,
        })

    return {"datasets": datasets, "total": ds_total, "page": page, "page_size": page_size}


@router.post("/business/datasets/{dataset_id}/restore")
def restore_purged_dataset(
    dataset_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """将 purged 状态的数据集恢复到用户回收站（状态变为 deleted）"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.status != "purged":
        raise HTTPException(status_code=400, detail="只有 purged 状态的数据集才能恢复")
    # 文件必须仍存在，否则用户端恢复时会读取失败
    if dataset.file_path and not storage_manager.exists(dataset.file_path):
        raise HTTPException(status_code=400, detail=f"数据集文件已不存在，无法恢复（{dataset.file_path}）")

    dataset.status = "deleted"
    dataset.deleted_at = None
    db.commit()

    # 管理员操作留痕（记录到所属用户的操作历史，便于用户侧追溯）
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=dataset.user_id, dataset_id=dataset_id,
        params={
            "operation": "admin_restore",
            "dataset_name": dataset.name,
            "dataset_id": dataset_id,
            "admin": current_admin.username,
            "note": "管理员从已清空(业务回收站)恢复到用户回收站",
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={"affected_count": 1}, execution_time=0)
    # 清理用户列表缓存，避免用户端最长 5 分钟看不到恢复结果
    clear_user_dataset_cache(dataset.user_id)

    return {"message": f"数据集 {dataset.name} 已恢复到用户回收站"}


@router.delete("/business/datasets/{dataset_id}/permanent-delete")
def admin_permanent_delete_dataset(
    dataset_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端永久删除数据集（物理删除，不可恢复）

    对于 ML 模型记录,会级联删除保存在 pkl 内部的测试集 CSV 文件,
    避免 MinIO 中产生孤儿测试集文件。
    """
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    deleted_name = dataset.name
    deleted_artifact_type = dataset.artifact_type
    deleted_user_id = dataset.user_id

    # ML 模型记录:先级联删除测试集文件,再删模型 pkl
    if dataset.artifact_type == "ml_model":
        from app.api.ml import cascade_delete_ml_testset
        cascade_delete_ml_testset(dataset)

    if dataset.file_path and storage_manager.exists(dataset.file_path):
        try:
            storage_manager.delete(dataset.file_path)
        except Exception as e:
            print(f"删除文件失败: {e}")

    db.delete(dataset)
    db.commit()

    # 管理员操作留痕（记录到所属用户的操作历史，便于审计）
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=deleted_user_id, dataset_id=dataset_id,
        params={
            "operation": "admin_permanent_delete",
            "dataset_name": deleted_name,
            "dataset_id": dataset_id,
            "artifact_type": deleted_artifact_type,
            "admin": current_admin.username,
            "note": "管理员永久删除（物理删除，不可恢复）",
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={"affected_count": 1}, execution_time=0)
    # 清理用户列表缓存，避免用户端残留已删除记录
    clear_user_dataset_cache(deleted_user_id)

    return {"message": f"数据集 {deleted_name} 已永久删除"}


@router.get("/business/stats")
def get_business_stats(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """数据库业务统计：按用户/模块/状态分组"""
    # 按用户分组：统计记录数和总占用空间（outerjoin 兼容无用户的数据集）
    by_user_rows = (
        db.query(
            Dataset.user_id,
            User.username,
            func.count(Dataset.id).label("count"),
            func.coalesce(func.sum(Dataset.file_size), 0).label("total_size"),
        )
        .outerjoin(User, Dataset.user_id == User.id)
        .group_by(Dataset.user_id, User.username)
        .all()
    )
    by_user = [
        {
            "user_id": row.user_id,
            "username": row.username,
            "count": row.count,
            "total_size": int(row.total_size) if row.total_size else 0,
        }
        for row in by_user_rows
    ]

    # 按模块分组：统计各模块产物数和总大小（含活跃+回收站数据，与数据列表口径一致）
    # 已清空（purged）和已损坏（corrupted）有专门Tab，不纳入分类统计卡片
    by_module_rows = (
        db.query(
            Dataset.module_source,
            func.count(Dataset.id).label("count"),
            func.coalesce(func.sum(Dataset.file_size), 0).label("total_size"),
        )
        .filter(Dataset.status.in_(["active", "deleted"]))
        .group_by(Dataset.module_source)
        .all()
    )
    
    # 将查询结果转为字典
    by_module_dict = {}
    for row in by_module_rows:
        by_module_dict[row.module_source] = {
            "module_source": row.module_source,
            "count": row.count,
            "total_size": int(row.total_size) if row.total_size else 0
        }
    
    # 合并 batch_predict 到 ml 模块
    if "batch_predict" in by_module_dict:
        if "ml" in by_module_dict:
            by_module_dict["ml"]["count"] += by_module_dict["batch_predict"]["count"]
            by_module_dict["ml"]["total_size"] += by_module_dict["batch_predict"]["total_size"]
        else:
            by_module_dict["ml"] = by_module_dict["batch_predict"].copy()
            by_module_dict["ml"]["module_source"] = "ml"
        del by_module_dict["batch_predict"]
    
    by_module = list(by_module_dict.values())

    # 按状态分组：统计各状态记录数
    by_status_rows = (
        db.query(
            Dataset.status,
            func.count(Dataset.id).label("count"),
        )
        .group_by(Dataset.status)
        .all()
    )
    
    # 将查询结果转为字典
    by_status_dict = {}
    for row in by_status_rows:
        by_status_dict[row.status] = {"status": row.status, "count": row.count}
    
    by_status = list(by_status_dict.values())

    # 回收站统计：统计用户软删除的数据（status=deleted），与用户端回收站 Tab 对应
    trash_row = db.query(
        func.count(Dataset.id).label("count"),
        func.coalesce(func.sum(Dataset.file_size), 0).label("total_size"),
    ).filter(Dataset.status == "deleted").first()

    return {
        "by_user": by_user,
        "by_module": by_module,
        "by_status": by_status,
        "trash_count": trash_row.count if trash_row else 0,
        "trash_size": trash_row.total_size if trash_row else 0,
    }


def _build_task_detail(task_type, params, result):
    """根据任务类型和参数构建用户友好的中文操作描述"""
    if task_type == "upload":
        filename = params.get("filename", "未知文件")
        row_count = result.get("row_count", 0)
        file_size = result.get("file_size", 0)
        size_str = _format_file_size(file_size)
        return f"上传文件 {filename}，共 {row_count} 行，大小 {size_str}"

    elif task_type == "dataset":
        # 数据治理操作：根据 operation 显示具体操作
        op = params.get("operation", "")
        op_label_map = {
            "soft_delete": "软删除",
            "batch_delete": "批量删除",
            "permanent_delete": "永久删除",
            "restore": "恢复数据",
            "clear_trash": "清空回收站",
            "clear_all": "清空所有",
            "edit_meta": "编辑元数据",
            "import_to_module": "跨模块导入",
            # 管理端操作留痕
            "admin_restore": "管理员恢复",
            "admin_permanent_delete": "管理员永久删除",
            "admin_delete_datasource": "管理员删除数据源",
        }
        op_label = op_label_map.get(op, op or "数据治理")
        dataset_name = params.get("dataset_name", "")
        if dataset_name:
            return f"{op_label} {dataset_name}"
        target_count = params.get("target_count")
        if target_count:
            return f"{op_label}（{target_count} 项）"
        return f"{op_label}"

    elif task_type == "cleaning":
        dataset_name = params.get("dataset_name", "未知数据集")
        method = params.get("method", "未知方法")
        new_name = result.get("new_dataset_name", "")
        detail = f"对 {dataset_name} 执行清洗（{method}）"
        if new_name:
            detail += f"，生成 {new_name}"
        return detail

    elif task_type == "ml_training":
        # 模型训练（独立 task_type）
        dataset_name = params.get("dataset_name", "未知数据集")
        algorithm = params.get("algorithm", "未知算法")
        accuracy = result.get("accuracy")
        detail = f"对 {dataset_name} 训练模型（{algorithm}）"
        if accuracy is not None:
            detail += f"，准确率 {accuracy}"
        return detail

    elif task_type == "ml":
        dataset_name = params.get("dataset_name", "未知数据集")
        algorithm = params.get("algorithm", "未知算法")
        accuracy = result.get("accuracy")
        detail = f"对 {dataset_name} 训练模型（{algorithm}）"
        if accuracy is not None:
            detail += f"，准确率 {accuracy}"
        return detail

    elif task_type in ("feature_engineering", "feature_engineering_select",
                       "feature_engineering_construct", "feature_engineering_encode",
                       "feature_engineering_scale", "feature_engineering_reduce"):
        # 特征工程：统一处理母类型和 5 个子类型
        dataset_name = params.get("dataset_name", "未知数据集")
        # 子类型中文映射
        fe_label_map = {
            "feature_engineering": "特征工程",
            "feature_engineering_select": "特征选择",
            "feature_engineering_construct": "特征构造",
            "feature_engineering_encode": "特征编码",
            "feature_engineering_scale": "特征缩放",
            "feature_engineering_reduce": "特征降维",
        }
        fe_label = fe_label_map.get(task_type, "特征工程")
        new_name = result.get("new_dataset_name", "")
        detail = f"对 {dataset_name} 执行{fe_label}"
        if new_name:
            detail += f"，生成 {new_name}"
        return detail

    elif task_type == "ai":
        dataset_name = params.get("dataset_name", "未知数据集")
        module = params.get("module", "AI分析")
        return f"对 {dataset_name} 执行 {module}"

    elif task_type == "data_mining":
        dataset_name = params.get("dataset_name", "未知数据集")
        method = params.get("method", "数据挖掘")
        return f"对 {dataset_name} 执行数据挖掘（{method}）"

    elif task_type == "data_analysis":
        dataset_name = params.get("dataset_name", "未知数据集")
        analysis_type = params.get("analysis_type", "数据分析")
        return f"对 {dataset_name} 执行数据分析（{analysis_type}）"

    elif task_type == "user_admin":
        # 管理员账号操作：根据 operation 显示具体操作与操作管理员
        op_label_map = {
            "admin_user_status": "管理员变更账号状态",
            "admin_reset_password": "管理员重置密码",
            "admin_unlock": "管理员解锁账号",
        }
        op_label = op_label_map.get(params.get("operation", ""), "账号管理操作")
        admin = params.get("admin", "")
        return f"{op_label}（操作管理员：{admin}）" if admin else op_label

    return f"执行 {task_type} 操作"


def _format_file_size(size_bytes):
    """格式化文件大小"""
    if not size_bytes:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


@router.get("/business/tasks")
def list_business_tasks(
    task_type: str = Query(None, description="任务类型筛选(upload/cleaning/ml/ml_training/feature_engineering_select等/ai/data_mining/data_analysis/user_admin)"),
    task_type_prefix: str = Query(None, description="任务类型前缀筛选(如 feature_engineering 匹配 5 个子类型)，与 task_type 二选一"),
    user_id: int = Query(None, description="用户ID筛选"),
    username: str = Query(None, description="按用户名模糊搜索"),
    status: str = Query(None, description="状态筛选(pending/running/success/failed/cancelled)"),
    failure_category: str = Query(None, description="失败分类筛选(param_error/data_error/system_error/timeout/network_error/unknown)"),
    date_from: datetime = Query(None, description="开始时间(含)，按创建时间过滤"),
    date_to: datetime = Query(None, description="结束时间(含)，按创建时间过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """查询业务任务历史（基于 task_records 表）"""
    # 自愈清理僵尸任务（running + 无 Celery 任务 + 超 60 分钟）
    _auto_heal_zombie_tasks(db)
    query = db.query(TaskRecord, User.username).outerjoin(
        User, TaskRecord.user_id == User.id
    )

    if task_type:
        query = query.filter(TaskRecord.task_type == task_type)
    if task_type_prefix:
        query = query.filter(TaskRecord.task_type.like(f"{task_type_prefix}_%"))
    if user_id is not None:
        query = query.filter(TaskRecord.user_id == user_id)
    if username:
        query = query.filter(User.username.ilike(f"%{username}%"))
    if status:
        query = query.filter(TaskRecord.status == status)
    if failure_category:
        query = query.filter(TaskRecord.failure_category == failure_category)
    if date_from:
        query = query.filter(TaskRecord.created_at >= date_from)
    if date_to:
        query = query.filter(TaskRecord.created_at <= date_to)

    total = query.count()
    rows = (
        query.order_by(TaskRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    tasks = []
    for record, username in rows:
        # 构建操作详情中文描述
        params = record.params or {}
        result = record.result_summary or {}
        detail = _build_task_detail(record.task_type, params, result)

        # 管理员取消/重试标注（2026-08-15：管理端取消/重试只标注原任务记录，不新建独立记录）
        if result.get("admin_cancel"):
            detail = f"【管理员取消】{detail}"

        tasks.append({
            "id": record.id,
            "task_type": _ADMIN_TASK_TYPE_MAP.get(record.task_type, record.task_type),
            "task_type_raw": record.task_type,
            "detail": detail,
            "user_id": record.user_id,
            "username": username,
            "status": _ADMIN_TASK_STATUS_MAP.get(record.status, record.status),
            "status_raw": record.status,
            "execution_time_ms": record.execution_time,
            "error_message": record.error_message,
            "failure_category": record.failure_category,
            "failure_category_label": get_failure_category_label(record.failure_category),
            "is_remote": bool(params.get("is_remote", False)),
            "dataset_id": record.dataset_id,
            "has_progress": bool(result.get("progress_history")),
            "created_at": _format_shanghai(record.created_at) if record.created_at else None,
            "completed_at": _format_shanghai(record.completed_at) if record.completed_at else None,
        })

    return {"tasks": tasks, "total": total, "page": page, "page_size": page_size}


@router.get("/business/task-stats")
def get_business_task_stats(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """任务统计：按任务类型统计、按用户统计、按日统计（基于 task_records 表）"""
    from sqlalchemy import func

    # 按任务类型统计
    by_module_rows = (
        db.query(TaskRecord.task_type, func.count(TaskRecord.id))
        .group_by(TaskRecord.task_type)
        .all()
    )
    by_module = [
        {"task_type": _ADMIN_TASK_TYPE_MAP.get(tt, tt), "count": cnt}
        for tt, cnt in by_module_rows
    ]

    # 按用户统计
    by_user_rows = (
        db.query(TaskRecord.user_id, User.username, func.count(TaskRecord.id))
        .outerjoin(User, TaskRecord.user_id == User.id)
        .group_by(TaskRecord.user_id, User.username)
        .all()
    )
    by_user = [
        {"user_id": uid, "username": uname or f"用户{uid}", "count": cnt}
        for uid, uname, cnt in by_user_rows
    ]

    # 按日统计（最近30天，含成功/失败数供成功率趋势）
    # created_at 为 UTC naive：筛选起点按 UTC 折算（上海钟面 -8h），分组按上海日期
    from datetime import datetime as _dt, timedelta as _td
    now_sh = _dt.now(SHANGHAI_TZ).replace(tzinfo=None)
    thirty_days_ago = now_sh - _td(days=29) - _td(hours=8)
    by_date_rows = db.execute(text("""
        SELECT to_char(created_at + interval '8 hours', 'YYYY-MM-DD') AS dk,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'success') AS success,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed
        FROM task_records WHERE created_at >= :s GROUP BY dk ORDER BY dk
    """), {"s": thirty_days_ago.strftime("%Y-%m-%d %H:%M:%S")}).fetchall()
    by_date_map = {r[0]: {"total": r[1] or 0, "success": r[2] or 0, "failed": r[3] or 0} for r in by_date_rows}
    by_date = []
    for i in range(29, -1, -1):
        d = (now_sh - _td(days=i)).strftime("%Y-%m-%d")
        rec = by_date_map.get(d, {"total": 0, "success": 0, "failed": 0})
        rate = round(rec["success"] / rec["total"] * 100, 1) if rec["total"] else None
        by_date.append({
            "date": d, "count": rec["total"],
            "success_count": rec["success"], "failed_count": rec["failed"],
            "success_rate": rate,
        })

    # 按状态统计（状态分布：pending/running/success/failed/cancelled）
    by_status_rows = (
        db.query(TaskRecord.status, func.count(TaskRecord.id))
        .group_by(TaskRecord.status)
        .all()
    )
    by_status = [
        {"status": _ADMIN_TASK_STATUS_MAP.get(s, s or "未知"), "status_raw": s, "count": cnt}
        for s, cnt in by_status_rows
    ]

    # 按模块统计失败数（失败 TOP 依据）
    by_module_failed_rows = (
        db.query(TaskRecord.task_type, func.count(TaskRecord.id))
        .filter(TaskRecord.status == "failed")
        .group_by(TaskRecord.task_type)
        .order_by(func.count(TaskRecord.id).desc())
        .all()
    )
    by_module_failed = [
        {"task_type": _ADMIN_TASK_TYPE_MAP.get(tt, tt), "count": cnt}
        for tt, cnt in by_module_failed_rows
    ]

    return {
        "by_module": by_module,
        "by_user": by_user,
        "by_date": by_date,
        "by_status": by_status,
        "by_module_failed": by_module_failed,
    }


@router.get("/tasks/{record_id}")
def get_admin_task_detail(
    record_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端任务详情（含 params/result_summary/error_message 完整信息，供详情抽屉展示）"""
    row = (
        db.query(TaskRecord, User.username)
        .outerjoin(User, TaskRecord.user_id == User.id)
        .filter(TaskRecord.id == record_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="任务记录不存在")
    record, username = row
    params = record.params or {}
    result = record.result_summary or {}

    return {
        "id": record.id,
        "task_type": _ADMIN_TASK_TYPE_MAP.get(record.task_type, record.task_type),
        "task_type_raw": record.task_type,
        "user_id": record.user_id,
        "username": username,
        "dataset_id": record.dataset_id,
        "status": _ADMIN_TASK_STATUS_MAP.get(record.status, record.status),
        "status_raw": record.status,
        "failure_category": record.failure_category,
        "failure_category_label": get_failure_category_label(record.failure_category),
        "error_message": record.error_message,
        "execution_time_ms": record.execution_time,
        "celery_task_id": record.celery_task_id,
        "params": params,
        "result_summary": result,
        "is_remote": bool(params.get("is_remote", False)),
        "created_at": _format_shanghai(record.created_at) if record.created_at else None,
        "completed_at": _format_shanghai(record.completed_at) if record.completed_at else None,
    }


# ===== 管理端任务干预（取消/重试，2026-08-15 新增）=====
# 与用户端接口（/api/datasets/tasks/{id}/cancel、/retry）不同：
# - 绕过 user_id 归属校验，管理员可操作任意用户的任务
# - 只在原任务记录上标注（admin_cancel / retry_history.operator=admin），不新建独立记录，避免审计重复与统计污染
# - 用户端操作历史可看到"【管理员取消】"前缀与重试来源


class AdminCancelTaskRequest(BaseModel):
    """管理员取消任务请求体"""
    note: str = ""


@router.post("/tasks/{record_id}/cancel")
def admin_cancel_task(
    record_id: int,
    body: AdminCancelTaskRequest | None = None,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端取消异步任务（pending/running 可取消，绕过用户归属校验）"""
    record = db.query(TaskRecord).filter(TaskRecord.id == record_id).first()
    if not record:
        return {"status": "error", "message": "任务记录不存在"}
    if record.status not in ("pending", "running"):
        return {"status": "error", "message": f"仅等待中/执行中的任务可取消，当前状态: {record.status}"}

    # 通过 celery_task_id 取消 Celery 任务
    if record.celery_task_id:
        result = task_manager.cancel_task(record.celery_task_id)
        if result.get("status") == "error":
            return {"status": "error", "message": result.get("message", "取消失败")}

    # 更新状态并在原任务记录上标注管理员取消
    note = (body.note if body else "").strip()
    record.status = "cancelled"
    record.completed_at = datetime.utcnow()
    summary = record.result_summary if isinstance(record.result_summary, dict) else {}
    summary["admin_cancel"] = {
        "admin": current_admin.username,
        "at": datetime.utcnow().isoformat(),
        "note": note or "管理员取消任务",
    }
    record.result_summary = summary
    db.commit()

    return {"status": "success", "message": "任务已取消（管理员操作）", "record_id": record_id}


@router.post("/tasks/{record_id}/retry")
def admin_retry_task(
    record_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端重试失败任务（仅 failed 可重试，绕过用户归属校验，复用用户额度容量检查）"""
    record = db.query(TaskRecord).filter(TaskRecord.id == record_id).first()
    if not record:
        return {"status": "error", "message": "任务记录不存在"}
    if record.status != "failed":
        return {"status": "error", "message": f"仅失败任务可重试，当前状态: {record.status}"}

    # 检查失败分类是否可重试（param_error/data_error 不可重试）
    if record.failure_category and not is_retryable_failure(record.failure_category):
        return {
            "status": "error",
            "message": f"失败原因「{get_failure_category_label(record.failure_category)}」不可重试，请修改参数或处理数据后重新执行"
        }

    # 容量检查（按任务所属用户的队列额度）
    can_run_now, queue_msg = check_task_queue_capacity(
        db, user_id=record.user_id, exclude_task_id=None
    )

    # 重置记录状态，retry_history 记录管理员重试来源
    record.status = "pending"
    record.error_message = None
    record.failure_category = None
    record.completed_at = None
    record.celery_task_id = None
    existing_summary = record.result_summary if isinstance(record.result_summary, dict) else {}
    retry_history = existing_summary.get("retry_history", [])
    retry_history.append({
        "previous_status": "failed",
        "previous_error": existing_summary.get("error", ""),
        "retry_time": datetime.utcnow().isoformat(),
        "operator": "admin",
        "operator_name": current_admin.username,
    })
    record.result_summary = {"retry_history": retry_history}
    db.commit()

    # running 已满则保持 pending，由调度器自动激活
    if not can_run_now:
        return {
            "status": "pending",
            "task_record_id": record_id,
            "message": f"任务已加入等待队列（管理员重试），{queue_msg}"
        }

    # 立即提交 Celery 执行
    result = task_manager.retry_task(str(record_id), db)
    if result.get("status") == "error":
        record.status = "failed"
        db.commit()
        return {"status": "error", "message": result.get("message", "重试失败")}

    new_celery_id = result.get("task_id", "")
    if new_celery_id:
        record.celery_task_id = new_celery_id
        record.status = "running"
        db.commit()

    return {
        "status": "queued",
        "task_id": new_celery_id,
        "task_record_id": record_id,
        "message": "任务已重新提交并开始执行（管理员重试）"
    }


# ===== 数据概览 =====

@router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """获取数据概览（用户/数据集/存储/任务 + 今日维度 + 错误概览）"""
    from datetime import datetime as _dt, timezone as _tz

    # created_at 经 psycopg2 存储为 UTC naive（上海时间 = UTC + 8h）。
    # "今日"按上海时区零点折算回 UTC 起点，避免上海 00:00-08:00 的数据漏计
    now_shanghai = _dt.now(_tz.utc) + timedelta(hours=8)
    today_start = now_shanghai.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    today_start_str = today_start.strftime("%Y-%m-%d %H:%M:%S")

    # 总用户数 / 总数据集数（不含已删除）/ 总任务数
    total_users = db.query(User).count()
    total_datasets = db.query(Dataset).filter(Dataset.status == "active").count()
    total_tasks = db.query(TaskRecord).count()

    # 今日新增用户 / 今日任务数 / 今日活跃用户（今天有任务记录的用户）
    today_new_users = db.query(User).filter(User.created_at >= today_start_str).count()
    today_tasks = db.query(TaskRecord).filter(TaskRecord.created_at >= today_start_str).count()
    active_users_today = db.query(TaskRecord.user_id).filter(
        TaskRecord.created_at >= today_start_str
    ).distinct().count()

    # 任务成功率（全部）
    success_tasks = db.query(TaskRecord).filter(TaskRecord.status == "success").count()
    task_success_rate = round(success_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0

    # 总存储量（MinIO stats 聚合，避免全量枚举文件）
    total_storage_bytes = 0
    try:
        stats = storage_manager.get_stats()
        total_storage_bytes = int(
            stats.get("total_size_bytes") or (stats.get("total_size_mb") or 0) * 1024 * 1024
        )
    except Exception:
        pass

    # 今日错误（log_records 入库 ERROR）
    errors_today = db.execute(text(
        "SELECT COUNT(*) FROM log_records WHERE level = 'ERROR' AND created_at >= :s"
    ), {"s": today_start_str}).scalar() or 0

    # 近 30 天增长趋势（created_at 存 UTC naive，按上海时区分组后供增长趋势图展示）
    trends = {
        "users": _daily_trend(db, "users", extra_where="role != 'admin'"),
        "datasets": _daily_trend(db, "datasets", extra_where="status = 'active'"),
        "storage": _daily_trend(db, "datasets", extra_where="status = 'active'",
                                agg_expr="COALESCE(SUM(file_size), 0)", agg_alias="value"),
        "tasks": _daily_trend(db, "task_records"),
        "ai_tokens": _daily_trend(db, "ai_usage_log",
                                  agg_expr="COALESCE(SUM(total_tokens), 0)", agg_alias="value"),
    }

    return {
        "total_users": total_users,
        "total_datasets": total_datasets,
        "total_storage_bytes": total_storage_bytes,
        "total_tasks": total_tasks,
        "active_users_today": active_users_today,
        "today_new_users": today_new_users,
        "today_tasks": today_tasks,
        "task_success_rate": task_success_rate,
        "errors_today": errors_today,
        "trends": trends,
    }


# ===== AI 用量统计（2026-08-15 新增） =====

@router.get("/ai-usage/stats")
def get_ai_usage_stats(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """AI 用量统计：汇总 / 按模块 / 按用户 / 近 30 天趋势

    数据源 ai_usage_log（记录每次 AI 调用的 token 消耗）；
    按用户统计需联 ai_conversations 取 user_id。
    """
    from datetime import datetime as _dt, timedelta as _td

    # 汇总
    s = db.execute(text("""
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM ai_usage_log
    """)).fetchone()
    total_calls = s[0] or 0
    summary = {
        "total_calls": total_calls,
        "prompt_tokens": s[1] or 0,
        "completion_tokens": s[2] or 0,
        "total_tokens": s[3] or 0,
        "avg_tokens_per_call": round((s[3] or 0) / total_calls, 1) if total_calls else 0,
    }

    # 按模块统计
    by_module = db.execute(text("""
        SELECT module_type, COUNT(*) AS calls,
               COALESCE(SUM(total_tokens), 0) AS tokens,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens
        FROM ai_usage_log GROUP BY module_type ORDER BY tokens DESC
    """)).fetchall()

    # 按用户统计（ai_usage_log 无 user_id，联 ai_conversations 取）
    by_user = db.execute(text("""
        SELECT COALESCE(c.user_id, 0) AS user_id,
               COALESCE(u.username, '未知用户') AS username,
               COUNT(*) AS calls, COALESCE(SUM(l.total_tokens), 0) AS tokens
        FROM ai_usage_log l
        LEFT JOIN ai_conversations c ON c.id = l.conversation_id
        LEFT JOIN users u ON u.id = c.user_id
        GROUP BY c.user_id, u.username ORDER BY tokens DESC
    """)).fetchall()

    # 近 30 天趋势（created_at 为 UTC naive：筛选起点按 UTC 折算，分组按上海日期）
    now_sh = _dt.now(SHANGHAI_TZ).replace(tzinfo=None)
    start = now_sh - _td(days=29) - _td(hours=8)
    trend_rows = db.execute(text("""
        SELECT to_char(created_at + interval '8 hours', 'YYYY-MM-DD') AS dk,
               COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM ai_usage_log WHERE created_at >= :s GROUP BY dk ORDER BY dk
    """), {"s": start.strftime("%Y-%m-%d %H:%M:%S")}).fetchall()
    by_day = {r[0]: {"calls": r[1] or 0, "tokens": r[2] or 0} for r in trend_rows}
    trend = []
    for i in range(29, -1, -1):
        d = (now_sh - _td(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": d[5:], **by_day.get(d, {"calls": 0, "tokens": 0})})

    return {
        "summary": summary,
        "by_module": [
            {"module_type": r[0] or "unknown", "calls": r[1] or 0, "tokens": r[2] or 0,
             "prompt_tokens": r[3] or 0, "completion_tokens": r[4] or 0}
            for r in by_module
        ],
        "by_user": [
            {"user_id": r[0], "username": r[1], "calls": r[2] or 0, "tokens": r[3] or 0}
            for r in by_user
        ],
        "trend": trend,
    }


# ===== 数据大屏聚合（2026-08-15 新增） =====

def _daily_trend(db: Session, table: str, date_expr: str = "created_at + interval '8 hours'", extra_where: str = "",
                 agg_expr: str = "COUNT(*)", agg_alias: str = "value", days: int = 29) -> list:
    """按天聚合通用辅助：返回近 N 天 [{date, value}]（0 填充）

    date_expr 为分组/筛选的时间表达式。数据库 created_at 为 UTC naive，
    默认 +8h 转上海钟面后同时作用于筛选与分组，使标签与前端一致（修复时区错位）。
    """
    from datetime import datetime as _dt, timedelta as _td
    now_sh = _dt.now(SHANGHAI_TZ).replace(tzinfo=None)
    start = now_sh - _td(days=days)
    where = f"WHERE {date_expr} >= :s"
    if extra_where:
        where += f" AND {extra_where}"
    rows = db.execute(text(
        f"SELECT to_char({date_expr}, 'YYYY-MM-DD') AS dk, {agg_expr} AS val "
        f"FROM {table} {where} GROUP BY dk ORDER BY dk"
    ), {"s": start.strftime("%Y-%m-%d %H:%M:%S")}).fetchall()
    by_day = {r[0]: r[1] or 0 for r in rows}
    result = []
    for i in range(days, -1, -1):
        d = (now_sh - _td(days=i)).strftime("%Y-%m-%d")
        result.append({"date": d[5:], "value": by_day.get(d, 0)})
    return result


@router.get("/dashboard")
def get_dashboard_data(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """数据大屏聚合接口：核心 KPI + 近 30 天趋势 + 分布 + 实时动态（一次请求渲染整屏）"""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    # ===== KPI（与 /overview 口径一致） =====
    today_start = _dt.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_str = today_start.strftime("%Y-%m-%d %H:%M:%S")
    total_users = db.query(User).count()
    total_datasets = db.query(Dataset).filter(Dataset.status == "active").count()
    total_tasks = db.query(TaskRecord).count()
    today_new_users = db.query(User).filter(User.created_at >= today_start_str).count()
    today_tasks = db.query(TaskRecord).filter(TaskRecord.created_at >= today_start_str).count()
    active_users_today = db.query(TaskRecord.user_id).filter(
        TaskRecord.created_at >= today_start_str
    ).distinct().count()
    success_tasks = db.query(TaskRecord).filter(TaskRecord.status == "success").count()
    task_success_rate = round(success_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0
    total_storage_bytes = 0
    try:
        stats = storage_manager.get_stats()
        total_storage_bytes = int(
            stats.get("total_size_bytes") or (stats.get("total_size_mb") or 0) * 1024 * 1024
        )
    except Exception:
        pass
    errors_today = db.execute(text(
        "SELECT COUNT(*) FROM log_records WHERE level = 'ERROR' AND created_at >= :s"
    ), {"s": today_start_str}).scalar() or 0
    ai_total = db.execute(text(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM ai_usage_log"
    )).scalar() or 0

    kpis = {
        "total_users": total_users, "today_new_users": today_new_users,
        "total_datasets": total_datasets, "total_storage_bytes": total_storage_bytes,
        "total_tasks": total_tasks, "task_success_rate": task_success_rate,
        "today_tasks": today_tasks, "active_users_today": active_users_today,
        "errors_today": errors_today, "total_ai_tokens": ai_total,
    }

    # ===== 近 30 天趋势（created_at 均为上海时区钟面时间，直接按天分组） =====
    trends = {
        "users": _daily_trend(db, "users", extra_where="role != 'admin'"),
        "datasets": _daily_trend(db, "datasets", extra_where="status = 'active'"),
        "storage": _daily_trend(db, "datasets", extra_where="status = 'active'",
                                agg_expr="COALESCE(SUM(file_size), 0)", agg_alias="value"),
        "tasks": _daily_trend(db, "task_records"),
        "ai_tokens": _daily_trend(db, "ai_usage_log",
                                  agg_expr="COALESCE(SUM(total_tokens), 0)", agg_alias="value"),
        # log_records 存 UTC，需 +8h 转上海时区标签（date_expr 同时作用于筛选与分组）
        "errors": _daily_trend(db, "log_records", date_expr="created_at + interval '8 hours'",
                               agg_expr="COUNT(*) FILTER (WHERE level = 'ERROR')", agg_alias="value"),
    }

    # ===== 分布 =====
    distributions = {
        # 数据集按模块（module_source 直接映射为中文，图例/饼图显示友好）
        "dataset_by_module": [
            {"name": _MODULE_SOURCE_TO_TASK_TYPE.get(r[0], r[0] or "其他"), "value": r[1] or 0}
            for r in db.execute(text(
                "SELECT module_source, COUNT(*) FROM datasets WHERE status = 'active' "
                "GROUP BY module_source ORDER BY COUNT(*) DESC"
            )).fetchall()
        ],
        # 任务按状态
        "task_by_status": [
            {"name": _ADMIN_TASK_STATUS_MAP.get(r[0] or "unknown", r[0] or "未知"), "value": r[1] or 0}
            for r in db.execute(text(
                "SELECT status, COUNT(*) FROM task_records GROUP BY status"
            )).fetchall()
        ],
        # AI 用量按模块
        "ai_by_module": [
            {"name": r[0] or "unknown", "value": r[1] or 0}
            for r in db.execute(text(
                "SELECT module_type, COALESCE(SUM(total_tokens), 0) FROM ai_usage_log "
                "GROUP BY module_type ORDER BY SUM(total_tokens) DESC"
            )).fetchall()
        ],
        # 数据集按产物类型
        "dataset_by_artifact": [
            {"name": r[0] or "其他", "value": r[1] or 0}
            for r in db.execute(text(
                "SELECT artifact_type, COUNT(*) FROM datasets WHERE status = 'active' "
                "GROUP BY artifact_type ORDER BY COUNT(*) DESC"
            )).fetchall()
        ],
    }

    # ===== 实时动态 =====
    recent_tasks = db.execute(text(
        "SELECT t.id, t.task_type, t.status, t.error_message, t.created_at, u.username "
        "FROM task_records t LEFT JOIN users u ON u.id = t.user_id "
        "ORDER BY t.created_at DESC LIMIT 8"
    )).fetchall()
    recent_errors = db.execute(text(
        "SELECT level, module, message, created_at FROM log_records "
        "WHERE level = 'ERROR' ORDER BY created_at DESC LIMIT 8"
    )).fetchall()

    def _fmt_sh(dt_val):
        """统一格式化为 'YYYY-MM-DD HH:MM:SS'（去掉 ISO 的 T 与时区后缀，供前端直接 slice 显示）"""
        if not dt_val:
            return None
        iso = _format_shanghai(dt_val)
        return iso[:19].replace("T", " ") if iso else None

    realtime = {
        "recent_tasks": [
            {
                "id": r[0], "task_type": _ADMIN_TASK_TYPE_MAP.get(r[1], r[1]),
                "status": _ADMIN_TASK_STATUS_MAP.get(r[2], r[2]),
                "status_raw": r[2], "error_message": r[3], "username": r[5],
                "created_at": _fmt_sh(r[4]),
            }
            for r in recent_tasks
        ],
        "recent_errors": [
            {"level": r[0], "module": r[1], "message": r[2], "created_at": _fmt_sh(r[3])}
            for r in recent_errors
        ],
    }

    return {"kpis": kpis, "trends": trends, "distributions": distributions, "realtime": realtime}


# ===== 运行日志管理 =====

# 日志模块映射（task 已移除：任务执行信息由 TaskRecord 表记录）
LOG_MODULES = {
    "api": "api.log",
    "error": "error.log",
    "system": "system.log",
}

_LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (INFO|WARNING|ERROR|DEBUG)\s*\| (.*)$")


def _parse_log_line(line: str):
    """结构化解析一行日志，返回 {time, level, message}；无法解析返回 None"""
    m = _LOG_LINE_RE.match(line.strip())
    if not m:
        return None
    return {"time": m.group(1), "level": m.group(2), "message": m.group(3)}


def _collect_log_files(module: str = "", file: str = ""):
    """收集要读取的日志文件列表，返回 [(module, filename), ...]

    - file 指定时只读该文件（可含轮转文件，如 api.log.2026-08-14）
    - module 指定时读该模块当前文件 + 全部轮转文件
    - 都不指定时读全部模块当前文件 + 全部轮转文件
    """
    if file:
        base = file.split(".")[0]
        mod = base if base in LOG_MODULES else "system"
        return [(mod, file)]
    if module and module in LOG_MODULES:
        base = LOG_MODULES[module]
        files = [base] + sorted(
            f for f in os.listdir(LOG_DIR)
            if f.startswith(base + ".") and os.path.isfile(os.path.join(LOG_DIR, f))
        )
        return [(module, f) for f in files]
    result = []
    for mod, base in LOG_MODULES.items():
        files = [base] + sorted(
            f for f in os.listdir(LOG_DIR)
            if f.startswith(base + ".") and os.path.isfile(os.path.join(LOG_DIR, f))
        )
        result.extend((mod, f) for f in files)
    return result


def _query_log_records(level="", module="", date="", keyword="", file="", since=""):
    """读取并过滤日志，返回结构化记录列表（已按时间倒序）

    级别/日期均为解析后精确匹配（不再子串匹配）；since 用于增量刷新（只返回 time > since 的行）。
    """
    records = []
    for mod_name, filename in _collect_log_files(module, file):
        log_path = os.path.join(LOG_DIR, filename)
        if not os.path.exists(log_path):
            continue
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parsed = _parse_log_line(line)
                    if not parsed:
                        continue
                    if level and parsed["level"] != level:
                        continue
                    if date and not parsed["time"].startswith(date):
                        continue
                    if since and parsed["time"] <= since:
                        continue
                    if keyword and keyword.lower() not in parsed["message"].lower():
                        continue
                    records.append({
                        "time": parsed["time"],
                        "level": parsed["level"],
                        "module": mod_name,
                        "message": parsed["message"],
                    })
        except Exception:
            continue
    records.sort(key=lambda r: r["time"], reverse=True)
    return records


@router.get("/logs")
def list_logs(
    level: str = "",
    module: str = "",
    date: str = "",
    keyword: str = "",
    file: str = "",
    since: str = "",
    page: int = 1,
    page_size: int = 50,
    current_admin: User = Depends(get_current_admin)
):
    """读取后端日志（2026-08-15 重构：结构化解析 + 精确过滤 + 支持轮转文件/增量）"""
    records = _query_log_records(level, module, date, keyword, file, since)
    total = len(records)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": records[start:start + page_size],
        "modules": list(LOG_MODULES.keys()),
        "levels": ["INFO", "WARNING", "ERROR"],
    }


@router.get("/logs/files")
def list_log_files(current_admin: User = Depends(get_current_admin)):
    """获取日志目录下全部日志文件（含轮转文件）"""
    result = []
    for mod, base in LOG_MODULES.items():
        files = [base] + sorted(
            f for f in os.listdir(LOG_DIR)
            if f.startswith(base + ".") and os.path.isfile(os.path.join(LOG_DIR, f))
        )
        for filename in files:
            file_path = os.path.join(LOG_DIR, filename)
            stat = os.stat(file_path)
            result.append({
                "module": mod,
                "filename": filename,
                "rotated": filename != base,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    result.sort(key=lambda x: (x["module"], x["filename"]))
    return {"files": result}


@router.get("/logs/summary")
def get_logs_summary(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """运行日志概览：今日 + 历史入库记录汇总 + 文件占用统计（供当日/历史 Tab 概览卡）"""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    # 历史累计（全部入库记录）
    errors_total = db.execute(text(
        "SELECT COUNT(*) FROM log_records WHERE level = 'ERROR'"
    )).scalar() or 0
    warnings_total = db.execute(text(
        "SELECT COUNT(*) FROM log_records WHERE level = 'WARNING'"
    )).scalar() or 0
    db_records_total = errors_total + warnings_total

    # 今日累计（created_at 存 UTC，今日零点按 UTC 计算）
    today_start = _dt.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_str = today_start.strftime("%Y-%m-%d %H:%M:%S")
    errors_today = db.execute(text(
        "SELECT COUNT(*) FROM log_records WHERE level = 'ERROR' AND created_at >= :s"
    ), {"s": today_start_str}).scalar() or 0
    warnings_today = db.execute(text(
        "SELECT COUNT(*) FROM log_records WHERE level = 'WARNING' AND created_at >= :s"
    ), {"s": today_start_str}).scalar() or 0

    # 文件占用统计（当前文件 + 轮转文件）
    file_stats = []
    total_file_bytes = 0
    for mod, base in LOG_MODULES.items():
        current_path = os.path.join(LOG_DIR, base)
        rotated = [
            f for f in os.listdir(LOG_DIR)
            if f.startswith(base + ".") and os.path.isfile(os.path.join(LOG_DIR, f))
        ]
        current_size = os.path.getsize(current_path) if os.path.exists(current_path) else 0
        rotated_size = sum(os.path.getsize(os.path.join(LOG_DIR, f)) for f in rotated)
        total_file_bytes += current_size + rotated_size
        file_stats.append({
            "module": mod,
            "current_size": current_size,
            "rotated_count": len(rotated),
            "rotated_size": rotated_size,
        })

    return {
        # 今日（当日 Tab）
        "today_records": errors_today + warnings_today,
        "errors_today": errors_today,
        "warnings_today": warnings_today,
        # 历史累计（历史 Tab）
        "total_records": db_records_total,
        "errors_total": errors_total,
        "warnings_total": warnings_total,
        "db_records_total": db_records_total,
        "file_stats": file_stats,
        "total_file_bytes": total_file_bytes,
    }


@router.get("/logs/trend")
def get_logs_trend(
    time_range: str = Query("24h", alias="range", description="24h 按小时 / 7d 按天聚合（从 log_records 表）"),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """错误/警告趋势（2026-08-15 新增：基于 log_records 入库记录）"""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    # created_at 存 UTC；按上海时区（+8h）聚合出标签，与用户直观时间一致
    utc_now = _dt.now(_tz.utc)
    sh_now = utc_now + _td(hours=8)

    if time_range == "7d":
        start = utc_now - _td(days=6)
        rows = db.execute(text("""
            SELECT to_char(created_at + interval '8 hours', 'MM-DD') AS dk,
                   COUNT(*) FILTER (WHERE level = 'ERROR') AS errs,
                   COUNT(*) FILTER (WHERE level = 'WARNING') AS warns
            FROM log_records WHERE created_at >= :s GROUP BY dk
        """), {"s": start.strftime("%Y-%m-%d %H:%M:%S")}).fetchall()
        by_day = {r[0]: {"errors": r[1] or 0, "warnings": r[2] or 0} for r in rows}
        trend = []
        for i in range(6, -1, -1):
            d = (sh_now - _td(days=i)).strftime("%m-%d")
            trend.append({"time": d, **by_day.get(d, {"errors": 0, "warnings": 0})})
    else:  # 24h 按小时
        start = utc_now - _td(hours=23)
        rows = db.execute(text("""
            SELECT to_char(created_at + interval '8 hours', 'HH24:00') AS hk,
                   COUNT(*) FILTER (WHERE level = 'ERROR') AS errs,
                   COUNT(*) FILTER (WHERE level = 'WARNING') AS warns
            FROM log_records WHERE created_at >= :s GROUP BY hk
        """), {"s": start.strftime("%Y-%m-%d %H:%M:%S")}).fetchall()
        by_hour = {r[0]: {"errors": r[1] or 0, "warnings": r[2] or 0} for r in rows}
        trend = []
        for i in range(23, -1, -1):
            h = (sh_now - _td(hours=i)).strftime("%H:00")
            trend.append({"time": h, **by_hour.get(h, {"errors": 0, "warnings": 0})})

    return {"trend": trend, "range": time_range}


@router.get("/logs/export")
def export_logs(
    level: str = "",
    module: str = "",
    date: str = "",
    keyword: str = "",
    file: str = "",
    current_admin: User = Depends(get_current_admin)
):
    """导出筛选后的日志为 txt（流式返回）"""
    records = _query_log_records(level, module, date, keyword, file, "")
    lines = [f"{r['time']} | {r['level']:<8} | [{r['module']}] {r['message']}" for r in records]
    content = "\n".join(lines)
    filename = f"logs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return StreamingResponse(
        iter([content]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ===== 用户管理 =====

@router.get("/users")
def list_users(
    search: str = Query("", description="按用户名或邮箱搜索"),
    status: str = Query("", description="状态筛选: active/disabled/locked，空=全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """获取用户列表（含数据统计与账号状态）"""
    query = db.query(User).filter(User.role != "admin")

    if search:
        like = f"%{search}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))

    if status == "active":
        query = query.filter(User.is_active.is_(True))
    elif status == "disabled":
        query = query.filter(User.is_active.is_(False))
    elif status == "locked":
        query = query.filter(User.locked_until > datetime.utcnow())

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    result = []
    for user in users:
        # 统计每个用户的数据集数量和总存储大小
        datasets = db.query(Dataset).filter(
            Dataset.user_id == user.id,
            Dataset.status == "active"
        ).all()

        dataset_count = len(datasets)
        total_storage = sum(d.file_size or 0 for d in datasets)

        # 统计任务记录数
        task_count = db.query(TaskRecord).filter(TaskRecord.user_id == user.id).count()

        result.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "is_active": bool(user.is_active),
            "failed_login_count": user.failed_login_count or 0,
            "locked_until": _format_shanghai(user.locked_until) if user.locked_until else None,
            "is_locked": bool(user.locked_until and user.locked_until > datetime.utcnow()),
            "created_at": _format_shanghai(user.created_at) if user.created_at else None,
            "last_login_at": _format_shanghai(user.last_login_at) if user.last_login_at else None,
            "last_login_ip": user.last_login_ip,
            "dataset_count": dataset_count,
            "total_storage_bytes": total_storage,
            "task_count": task_count
        })

    return {"users": result, "total": total, "page": page, "page_size": page_size}


@router.get("/users/stats")
def get_users_stats(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin)
):
    """获取用户数据统计"""
    from datetime import datetime, timedelta

    # 总用户数（不含管理员）
    total_users = db.query(User).filter(User.role != "admin").count()

    # 今日活跃用户：今天有登录记录或今天有任务记录的用户
    # （修正口径：纯登录未执行任务的用户也应计入活跃）
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    active_today = db.query(User.id).filter(
        or_(
            User.last_login_at >= today_start,
            User.id.in_(
                db.query(TaskRecord.user_id).filter(TaskRecord.created_at >= today_start)
            )
        )
    ).count()

    # 被禁用账号数
    disabled_users = db.query(User).filter(
        User.role != "admin", User.is_active.is_(False)
    ).count()

    # 处于锁定状态的账号数
    locked_users = db.query(User).filter(
        User.role != "admin", User.locked_until > datetime.utcnow()
    ).count()

    # 总数据集数
    total_datasets = db.query(Dataset).filter(Dataset.status == "active").count()

    # 总存储量（从数据集表累加 file_size）
    from sqlalchemy import func
    storage_result = db.query(func.sum(Dataset.file_size)).filter(
        Dataset.status == "active"
    ).scalar()
    total_storage = storage_result or 0

    # 近 30 天注册趋势（created_at 为 UTC naive：筛选起点按 UTC 折算，分组按上海日期）
    from datetime import datetime as _dt, timedelta as _td
    now_sh = _dt.now(SHANGHAI_TZ).replace(tzinfo=None)
    thirty_days_ago = now_sh - _td(days=29) - _td(hours=8)
    reg_rows = db.execute(text(
        "SELECT to_char(created_at + interval '8 hours', 'YYYY-MM-DD') AS dk, COUNT(*) AS cnt "
        "FROM users WHERE role != 'admin' AND created_at >= :s GROUP BY dk ORDER BY dk"
    ), {"s": thirty_days_ago.strftime("%Y-%m-%d %H:%M:%S")}).fetchall()
    reg_by_day = {r[0]: r[1] or 0 for r in reg_rows}
    registration_trend = []
    for i in range(29, -1, -1):
        d = (now_sh - _td(days=i)).strftime("%Y-%m-%d")
        registration_trend.append({"date": d[5:], "value": reg_by_day.get(d, 0)})

    return {
        "total_users": total_users,
        "active_today": active_today,
        "disabled_users": disabled_users,
        "locked_users": locked_users,
        "total_datasets": total_datasets,
        "total_storage_bytes": total_storage,
        "registration_trend": registration_trend,
    }


class UserStatusUpdate(BaseModel):
    """禁用/启用用户账号请求体"""
    is_active: bool


class ResetPasswordRequest(BaseModel):
    """重置用户密码请求体（new_password 为空时自动生成随机密码）"""
    new_password: str | None = None


def _generate_random_password(length: int = 10) -> str:
    """生成随机登录密码（字母+数字）"""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _admin_user_operation_record(db: Session, user: User, operation: str, note: str,
                                 admin: User, result_summary: dict = None) -> None:
    """管理员账号操作统一留痕（写入被操作用户的 task_records，供用户端审计追溯）"""
    task_record = create_task_record(
        db=db, task_type="user_admin", user_id=user.id,
        params={
            "operation": operation,
            "username": user.username,
            "user_id": user.id,
            "admin": admin.username,
            "note": note,
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary=result_summary or {"affected_count": 1},
                       execution_time=0)


@router.put("/users/{user_id}/status")
def update_user_status(
    user_id: int,
    body: UserStatusUpdate,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """禁用/启用用户账号（管理员账号不可被禁用）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="不能操作管理员账号")
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="不能操作当前登录的管理员账号")

    user.is_active = body.is_active
    # 启用时重置失败计数与锁定状态，让账号立即恢复正常
    if body.is_active:
        user.failed_login_count = 0
        user.locked_until = None
    db.commit()

    # 管理员操作留痕
    _admin_user_operation_record(
        db, user, operation="admin_user_status",
        note="管理员启用账号" if body.is_active else "管理员禁用账号",
        admin=current_admin,
        result_summary={"affected_count": 1, "is_active": body.is_active}
    )
    return {"success": True, "is_active": body.is_active}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    body: ResetPasswordRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """重置用户密码（管理员指定或自动生成），并清除登录锁定状态"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="不能操作管理员账号")

    new_password = (body.new_password or "").strip() or _generate_random_password()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")

    user.hashed_password = get_password_hash(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()

    # 管理员操作留痕（不写入密码明文，避免在操作历史中泄露）
    _admin_user_operation_record(
        db, user, operation="admin_reset_password",
        note="管理员重置登录密码", admin=current_admin,
        result_summary={"affected_count": 1}
    )
    return {"success": True, "new_password": new_password}


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """手动解锁账号（清除失败计数与锁定状态）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="不能操作管理员账号")

    user.failed_login_count = 0
    user.locked_until = None
    db.commit()

    # 管理员操作留痕
    _admin_user_operation_record(
        db, user, operation="admin_unlock",
        note="管理员解锁账号", admin=current_admin,
        result_summary={"affected_count": 1}
    )
    return {"success": True}


# ===== 用户申请（联系管理员）管理 =====

# 申请分类 → 中文标签（与前端 ContactAdmin.vue 功能卡片一致）
SUPPORT_CATEGORY_LABELS = {
    "restore_dataset": "恢复数据集",
    "unlock": "解锁账户",
    "error_report": "错误上报",
}

# 申请状态 → 中文标签
SUPPORT_STATUS_LABELS = {
    "pending": "待处理",
    "done": "已处理",
}


def _support_message_dict(msg: SupportMessage) -> dict:
    """将申请记录转为返回字典"""
    content = msg.content or {}
    # 内容摘要：恢复数据集显示数据集名称，错误上报显示描述前 60 字
    summary = ""
    if msg.category == "restore_dataset":
        summary = content.get("dataset_name", "")
    elif msg.category == "error_report":
        summary = (content.get("description") or "")[:60]

    return {
        "id": msg.id,
        "category": msg.category,
        "category_label": SUPPORT_CATEGORY_LABELS.get(msg.category, msg.category),
        "username": msg.username or "",
        "contact": msg.contact or "",
        "content": content,
        "content_summary": summary,
        "attachment_path": msg.attachment_path,
        "attachment_name": msg.attachment_name,
        "client_ip": msg.client_ip,
        "status": msg.status,
        "status_label": SUPPORT_STATUS_LABELS.get(msg.status, msg.status),
        "admin_note": msg.admin_note or "",
        "admin_id": msg.admin_id,
        "created_at": _format_shanghai(msg.created_at) if msg.created_at else None,
        "processed_at": _format_shanghai(msg.processed_at) if msg.processed_at else None,
    }


@router.get("/users/messages")
def list_support_messages(
    category: str = Query("", description="分类筛选: restore_dataset/unlock/error_report，空=全部"),
    status: str = Query("", description="状态筛选: pending/done，空=全部"),
    keyword: str = Query("", description="按申请人/内容关键字搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取用户申请列表（联系管理员提交）"""
    query = db.query(SupportMessage)

    if category:
        query = query.filter(SupportMessage.category == category)
    if status:
        query = query.filter(SupportMessage.status == status)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            SupportMessage.username.ilike(like),
            SupportMessage.contact.ilike(like),
        ))

    total = query.count()
    rows = (
        query.order_by(SupportMessage.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "messages": [_support_message_dict(m) for m in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/users/messages/{message_id}")
def get_support_message(
    message_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取单条申请详情"""
    msg = db.query(SupportMessage).filter(SupportMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="申请不存在")
    return _support_message_dict(msg)


class ProcessSupportMessageRequest(BaseModel):
    """处理申请请求体"""
    admin_note: str = ""


@router.post("/users/messages/{message_id}/process")
def process_support_message(
    message_id: int,
    body: ProcessSupportMessageRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """标记申请为已处理（解锁/恢复等一键操作由前端调用现有接口执行）"""
    msg = db.query(SupportMessage).filter(SupportMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="申请不存在")
    if msg.status == "done":
        raise HTTPException(status_code=400, detail="该申请已处理，请勿重复操作")

    msg.status = "done"
    msg.admin_note = (body.admin_note or "").strip()[:500]
    msg.admin_id = current_admin.id
    msg.processed_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    return {"success": True, "message": "申请已标记为已处理", "message_id": msg.id}


@router.delete("/users/messages/{message_id}")
def delete_support_message(
    message_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """删除申请记录（同步删除 MinIO 附件）"""
    msg = db.query(SupportMessage).filter(SupportMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="申请不存在")

    # 同步删除截图附件（失败不影响申请删除）
    if msg.attachment_path:
        storage_manager.delete(msg.attachment_path)

    db.delete(msg)
    db.commit()
    return {"success": True, "message": "申请已删除"}


@router.get("/cache/hit-rate")
def get_cache_hit_rate(
    time_range: str = Query("24h", alias="range", description="时间范围: 24h(按小时)/7d(按天)/30d(按天)"),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取应用级缓存命中率趋势（支持 24h/7d/30d 历史）

    2026-08-15 重写：
    - 实时值：cache_manager 进程内埋点（data-insight:* 键的 hits/misses）
    - 历史趋势：cache_stats_hourly 表（TaskScheduler 每分钟落库），24h 按小时、7d/30d 按天聚合
    """
    # ===== 实时值（进程内） =====
    hits = cache_manager._hits
    misses = cache_manager._misses
    total = hits + misses
    # 样本不足时命中率返回 None（前端显示"-"，避免 1 次命中=100% 的误导）
    hit_rate = round(hits / total * 100, 2) if total >= MIN_HIT_RATE_SAMPLE else None

    # ===== 历史趋势（从库读取） =====
    from sqlalchemy import text as _text
    from datetime import timedelta as _td
    from collections import defaultdict

    now = datetime.now()
    trend = []

    if time_range in ("7d", "30d"):
        days = 7 if time_range == "7d" else 30
        start_hour = (now - _td(days=days - 1)).strftime("%Y%m%d") + "00"
        rows = db.execute(_text("""
            SELECT hour, SUM(hits) AS hits, SUM(misses) AS misses,
                   MAX(total_keys) AS total_keys, MAX(memory_bytes) AS memory_bytes
            FROM cache_stats_hourly WHERE hour >= :start
            GROUP BY hour ORDER BY hour
        """), {"start": start_hour}).fetchall()
        # 按天聚合
        daily = defaultdict(lambda: {"hits": 0, "misses": 0, "keys": 0, "mem": 0})
        for r in rows:
            day = r[0][:8]  # YYYYMMDD
            daily[day]["hits"] += r[1] or 0
            daily[day]["misses"] += r[2] or 0
            daily[day]["keys"] = max(daily[day]["keys"], r[3] or 0)
            daily[day]["mem"] = max(daily[day]["mem"], r[4] or 0)
        for i in range(days - 1, -1, -1):
            day = (now - _td(days=i)).strftime("%Y%m%d")
            rec = daily.get(day, {"hits": 0, "misses": 0, "keys": 0, "mem": 0})
            d_total = rec["hits"] + rec["misses"]
            trend.append({
                "hour": (now - _td(days=i)).strftime("%m-%d"),
                "hit_rate": round(rec["hits"] / d_total * 100, 2) if d_total > 0 else 0,
                "hits": rec["hits"],
                "misses": rec["misses"],
                "total_keys": rec["keys"],
                "memory_bytes": rec["mem"],
            })
    else:  # 24h 按小时
        start_hour = (now - _td(hours=23)).strftime("%Y%m%d%H")
        rows = db.execute(_text("""
            SELECT hour, hits, misses, total_keys, memory_bytes
            FROM cache_stats_hourly WHERE hour >= :start ORDER BY hour
        """), {"start": start_hour}).fetchall()
        hourly = {r[0]: r for r in rows}
        for i in range(23, -1, -1):
            ts = now - _td(hours=i)
            hk = ts.strftime("%Y%m%d%H")
            r = hourly.get(hk)
            if r:
                h_hits, h_misses = r[1] or 0, r[2] or 0
                h_total = h_hits + h_misses
                trend.append({
                    "hour": ts.strftime("%H:00"),
                    "hit_rate": round(h_hits / h_total * 100, 2) if h_total > 0 else 0,
                    "hits": h_hits,
                    "misses": h_misses,
                    "total_keys": r[3] or 0,
                    "memory_bytes": r[4] or 0,
                })
            else:
                trend.append({
                    "hour": ts.strftime("%H:00"),
                    "hit_rate": 0, "hits": 0, "misses": 0,
                    "total_keys": 0, "memory_bytes": 0,
                })

    # ===== 汇总统计（按时间范围，供历史统计 Tab 汇总卡） =====
    start_hour_s = start_hour  # 前面分支已计算 start_hour
    sum_row = db.execute(_text("""
        SELECT COALESCE(SUM(hits), 0), COALESCE(SUM(misses), 0),
               COALESCE(MAX(total_keys), 0), COALESCE(MIN(hour), '')
        FROM cache_stats_hourly WHERE hour >= :start
    """), {"start": start_hour_s}).fetchone()
    sum_hits, sum_misses = sum_row[0] or 0, sum_row[1] or 0
    sum_total = sum_hits + sum_misses
    data_start = sum_row[3] or ""
    if data_start:
        # "YYYYMMDDHH" → "MM-DD HH:00"
        data_start = f"{data_start[4:6]}-{data_start[6:8]} {data_start[8:10]}:00"
    summary = {
        "total_requests": sum_total,
        "avg_hit_rate": round(sum_hits / sum_total * 100, 1) if sum_total >= MIN_HIT_RATE_SAMPLE else None,
        "peak_keys": sum_row[2] or 0,
        "data_start": data_start,
    }

    return {
        "current": {
            "hit_rate": hit_rate,
            "total_hits": hits,
            "total_misses": misses,
            "total_requests": total,
        },
        "trend": trend,
        "summary": summary,
        "range": time_range,
        "source": "app",
    }


@router.delete("/cache/history")
def delete_cache_history(
    start: str = Query(None, description="起始小时(YYYYMMDDHH)，可选；传了则按小时范围删除"),
    end: str = Query(None, description="结束小时(YYYYMMDDHH)，可选"),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """删除历史缓存统计（cache_stats_hourly 表）

    不传 start/end 时清空全部历史记录；
    传了则删除 [start, end] 小时范围内的记录（字符串比较，hour 为 YYYYMMDDHH）。
    """
    from sqlalchemy import text as _text

    if start and end:
        deleted = db.execute(_text(
            "DELETE FROM cache_stats_hourly WHERE hour >= :s AND hour <= :e"
        ), {"s": start, "e": end}).rowcount
        scope = f"{start} ~ {end}"
    else:
        deleted = db.execute(_text("DELETE FROM cache_stats_hourly")).rowcount
        scope = "全部"

    db.commit()
    return {"message": f"已删除 {deleted} 条历史缓存统计记录（{scope}）", "deleted": deleted, "scope": scope}


# ====== 数据源连接管理（管理端） ======

@router.get("/datasource-connections")
def admin_list_datasource_connections(
    user_id: int = Query(None, description="按用户ID筛选"),
    keyword: str = Query("", description="名称/主机/数据库模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端：查看所有用户的数据源连接（密码脱敏，仅返回掩码）"""
    query = db.query(DataSourceConnection, User.username).outerjoin(
        User, DataSourceConnection.user_id == User.id
    )
    if user_id is not None:
        query = query.filter(DataSourceConnection.user_id == user_id)
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(or_(
            DataSourceConnection.name.ilike(kw),
            DataSourceConnection.host.ilike(kw),
            DataSourceConnection.database.ilike(kw),
            DataSourceConnection.username.ilike(kw),
        ))
    total = query.count()
    rows = (
        query.order_by(DataSourceConnection.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for conn, username in rows:
        result.append({
            "id": conn.id,
            "name": conn.name,
            "db_type": conn.db_type,
            "host": conn.host,
            "port": conn.port,
            "database": conn.database,
            "username": conn.username,
            "extra_params": conn.extra_params,
            "password_display": "******",
            "user_id": conn.user_id,
            "owner_username": username,
            "ref_count": db.query(Dataset).filter(Dataset.connection_id == conn.id).count(),
            "created_at": _format_shanghai(conn.created_at) if conn.created_at else None,
        })
    return {"connections": result, "total": total, "page": page, "page_size": page_size}


@router.post("/datasource-connections/{conn_id}/test")
def admin_test_datasource_connection(
    conn_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端：测试指定数据源连接的连通性（使用存储的加密密码）"""
    conn = db.query(DataSourceConnection).filter(DataSourceConnection.id == conn_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="数据源连接不存在")
    try:
        from app.api.data_sources import _build_db_url, _test_connection_internal, TestConnectionRequest
        password = decrypt_password(conn.password_encrypted)
        req = TestConnectionRequest(
            db_type=conn.db_type, host=conn.host, port=conn.port,
            database=conn.database, username=conn.username,
            password=password, extra_params=conn.extra_params
        )
        return _test_connection_internal(req)
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}


@router.delete("/datasource-connections/{conn_id}")
def admin_delete_datasource_connection(
    conn_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """管理端：删除数据源连接（有活跃数据集引用时拒绝，返回引用列表）

    与用户端删除逻辑对齐：工作副本可再生产，删除连接时一并软删；
    活跃引用（active）拒绝删除；已删除/回收站引用的 connection_id 置空。
    """
    conn = db.query(DataSourceConnection).filter(DataSourceConnection.id == conn_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="数据源连接不存在")

    from app.models import shanghai_now
    ref_datasets = db.query(Dataset).filter(Dataset.connection_id == conn_id).all()
    # 工作副本是可再生的中间产物，删除连接时一并软删，不阻止连接删除
    for d in ref_datasets:
        if d.artifact_type == "feature_workcopy":
            d.status = "deleted"
            d.deleted_at = shanghai_now()
    normal_refs = [d for d in ref_datasets if d.artifact_type != "feature_workcopy"]
    active_refs = [d for d in normal_refs if d.status == "active"]
    deleted_refs = [d for d in normal_refs if d.status != "active"]

    if active_refs:
        ref_names = [d.name for d in active_refs[:5]]
        suffix = "..." if len(active_refs) > 5 else ""
        raise HTTPException(
            status_code=400,
            detail=f"该连接被 {len(active_refs)} 个活跃数据集引用（{', '.join(ref_names)}{suffix}），"
                   f"请先从各模块中删除这些数据集后再删除连接"
        )

    # 清理已删除/回收站的数据集的连接引用
    for ds in deleted_refs:
        ds.connection_id = None

    deleted_name = conn.name
    deleted_user_id = conn.user_id
    db.delete(conn)
    db.commit()

    # 管理端操作留痕（记录到所属用户的操作历史）
    task_record = create_task_record(
        db=db, task_type="dataset", user_id=deleted_user_id,
        params={
            "operation": "admin_delete_datasource",
            "datasource_name": deleted_name,
            "admin": current_admin.username,
            "note": "管理员删除数据源连接",
        }
    )
    update_task_record(db=db, record_id=task_record.id, status="success",
                       result_summary={"affected_count": 1}, execution_time=0)
    clear_user_dataset_cache(deleted_user_id)

    return {"success": True, "message": f"数据源连接「{deleted_name}」已删除"}