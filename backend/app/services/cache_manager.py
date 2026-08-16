"""
缓存管理层
支持 Redis 缓存，Redis 不可用时使用内存 LRU 缓存
"""
import json
import time
from typing import Optional, Any, Dict
from collections import OrderedDict
from app.config import settings

# 命中率最低样本量：总请求数低于该值时，命中率视为小样本失真（如 1 次命中=100%），返回 None 由前端显示"-"
MIN_HIT_RATE_SAMPLE = 10


class MemoryCache:
    """内存 LRU 缓存（Redis 不可用时使用）"""

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
        self._ttl: Dict[str, float] = {}  # 记录过期时间

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key not in self._cache:
            return None

        # 检查是否过期
        if key in self._ttl and time.time() > self._ttl[key]:
            self.delete(key)
            return None

        # 移到末尾（最近使用）
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key: str, value: Any, ttl: int = 3600):
        """设置缓存值"""
        # 如果缓存已满，移除最旧的
        if len(self._cache) >= self._max_size and key not in self._cache:
            self._cache.popitem(last=False)

        self._cache[key] = value
        if ttl > 0:
            self._ttl[key] = time.time() + ttl
        else:
            self._ttl.pop(key, None)

    def delete(self, key: str):
        """删除缓存"""
        self._cache.pop(key, None)
        self._ttl.pop(key, None)

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._ttl.clear()


class CacheManager:
    """
    缓存管理器
    优先使用 Redis，不可用时使用内存缓存
    """

    def __init__(self):
        self._redis = None
        self._memory = MemoryCache()
        self._redis_available = False
        # 应用级命中埋点（2026-08-15 新增：统计 data-insight:* 键的命中/未命中，
        # 替代误导性的 Redis 全实例 keyspace 统计）
        self._hits = 0
        self._misses = 0
        # 按小时采样的命中历史：{ "%Y%m%d%H": {"hits": n, "misses": n} }
        self._hit_history: Dict[str, Dict[str, int]] = {}

        if settings.REDIS_ENABLED:
            self._init_redis()

    def _init_redis(self):
        """初始化 Redis 连接"""
        try:
            import redis
            self._redis = redis.from_url(settings.REDIS_URL)
            # 测试连接
            self._redis.ping()
            self._redis_available = True
            print("✅ Redis 缓存已启用")
        except Exception as e:
            print(f"⚠️ Redis 连接失败，使用内存缓存: {e}")
            self._redis_available = False

    def _make_key(self, key: str) -> str:
        """生成带前缀的键"""
        return f"data-insight:{key}"

    def get(self, key: str) -> Optional[Any]:
        """获取缓存（含应用级命中/未命中埋点）"""
        cache_key = self._make_key(key)

        # 优先尝试 Redis
        if self._redis_available:
            try:
                value = self._redis.get(cache_key)
                if value:
                    self._record_hit()
                    return json.loads(value)
            except Exception:
                self._redis_available = False
                pass

        # 降级到内存缓存
        value = self._memory.get(cache_key)
        if value is not None:
            self._record_hit()
        else:
            self._record_miss()
        return value

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存"""
        if ttl is None:
            ttl = settings.REDIS_TTL

        cache_key = self._make_key(key)
        serialized = json.dumps(value, default=str)

        # 优先写入 Redis
        if self._redis_available:
            try:
                self._redis.setex(cache_key, ttl, serialized)
                return
            except Exception:
                self._redis_available = False
                pass

        # 降级到内存缓存
        self._memory.set(cache_key, value, ttl)

    def delete(self, key: str):
        """删除缓存"""
        cache_key = self._make_key(key)

        if self._redis_available:
            try:
                self._redis.delete(cache_key)
            except Exception:
                self._redis_available = False
                pass

        self._memory.delete(cache_key)

    def delete_pattern(self, pattern: str):
        """按前缀/模式删除缓存（支持通配符 *）"""
        cache_pattern = self._make_key(pattern)

        if self._redis_available:
            try:
                for key in self._redis.scan_iter(match=cache_pattern):
                    self._redis.delete(key)
            except Exception:
                self._redis_available = False
                pass

        for key in list(self._memory._cache.keys()):
            if key.startswith(cache_pattern.replace('*', '')):
                self._memory.delete(key)

    def clear(self):
        """清空缓存"""
        if self._redis_available:
            try:
                # 只清除带前缀的键
                for key in self._redis.scan_iter(match="data-insight:*"):
                    self._redis.delete(key)
            except Exception:
                pass

        self._memory.clear()

    def _record_hit(self):
        """记录一次命中（进程内采样，按小时归档）"""
        self._hits += 1
        self._hit_history.setdefault(self._hour_key(), {"hits": 0, "misses": 0})["hits"] += 1

    def _record_miss(self):
        """记录一次未命中"""
        self._misses += 1
        self._hit_history.setdefault(self._hour_key(), {"hits": 0, "misses": 0})["misses"] += 1

    @staticmethod
    def _hour_key() -> str:
        """当前小时键（本地时间），用于按小时归档命中历史"""
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d%H")

    def _estimate_memory_bytes(self) -> int:
        """估算内存缓存占用字节数（序列化后长度求和）"""
        total = 0
        for value in self._memory._cache.values():
            try:
                total += len(json.dumps(value, default=str))
            except Exception:
                total += 64
        return total

    def persist_hourly(self, db) -> int:
        """将进程内小时命中归档持久化到数据库（2026-08-15 新增）

        对 _hit_history 中每个小时执行 upsert（hour 唯一键），
        同时把当前 total_keys/memory_bytes 快照写入当前小时行。
        由后台线程（TaskScheduler）每分钟调用，服务重启不丢失历史。
        返回本次写入的小时数。
        """
        from datetime import datetime
        from sqlalchemy import text

        current_hour = datetime.now().strftime("%Y%m%d%H")
        written = 0
        try:
            # 进程重启后恢复基线：当前小时在库中已有记录时，以库中累计值作为进程内埋点起点，
            # 避免覆盖清零丢失重启前同小时已累计的命中统计
            if current_hour not in self._hit_history:
                row = db.execute(text(
                    "SELECT hits, misses FROM cache_stats_hourly WHERE hour = :h"
                ), {"h": current_hour}).fetchone()
                if row:
                    self._hit_history[current_hour] = {"hits": row[0] or 0, "misses": row[1] or 0}

            stats = self.get_stats()
            total_keys = stats.get("total_keys", 0)
            memory_bytes = stats.get("memory_bytes", 0)

            for hour_key, rec in list(self._hit_history.items()):
                hits = rec["hits"]
                misses = rec["misses"]
                total = hits + misses
                rate = round(hits / total * 100) if total > 0 else 0
                db.execute(text("""
                    INSERT INTO cache_stats_hourly
                        (hour, hits, misses, hit_rate, total_keys, memory_bytes, updated_at)
                    VALUES (:hour, :hits, :misses, :rate, :total_keys, :mem, now())
                    ON CONFLICT (hour) DO UPDATE SET
                        hits = EXCLUDED.hits,
                        misses = EXCLUDED.misses,
                        hit_rate = EXCLUDED.hit_rate,
                        total_keys = EXCLUDED.total_keys,
                        memory_bytes = EXCLUDED.memory_bytes,
                        updated_at = now()
                """), {
                    "hour": hour_key, "hits": hits, "misses": misses,
                    "rate": rate, "total_keys": total_keys, "mem": memory_bytes,
                })
                written += 1

            # 当前小时即使无请求也记录一条快照（total_keys/memory_bytes 持续追踪）
            if current_hour not in self._hit_history:
                db.execute(text("""
                    INSERT INTO cache_stats_hourly
                        (hour, hits, misses, hit_rate, total_keys, memory_bytes, updated_at)
                    VALUES (:hour, 0, 0, 0, :total_keys, :mem, now())
                    ON CONFLICT (hour) DO UPDATE SET
                        total_keys = EXCLUDED.total_keys,
                        memory_bytes = EXCLUDED.memory_bytes,
                        updated_at = now()
                """), {"hour": current_hour, "total_keys": total_keys, "mem": memory_bytes})
                written += 1

            db.commit()
        except Exception:
            # 落库失败不影响缓存读写（记录但静默，避免后台线程反复报错）
            try:
                db.rollback()
            except Exception:
                pass
        return written

    def get_stats(self) -> Dict[str, Any]:
        """缓存统计（2026-08-15 增强：应用真实键数/内存占用/应用级命中埋点）"""
        redis_dbsize = 0
        total_keys = 0
        memory_bytes = 0

        if self._redis_available:
            try:
                redis_dbsize = self._redis.dbsize()
                # 应用真实键数：仅统计 data-insight:* 前缀键（scan 迭代避免 keys 阻塞）
                total_keys = sum(1 for _ in self._redis.scan_iter(match="data-insight:*", count=500))
                info = self._redis.info("memory")
                memory_bytes = info.get("used_memory", 0)
            except Exception:
                self._redis_available = False

        mem_keys = len(self._memory._cache)
        if not self._redis_available:
            total_keys = mem_keys
            memory_bytes = self._estimate_memory_bytes()

        # 样本不足时命中率返回 None（前端显示"-"，避免 1 次命中=100% 的误导）
        _total_req = self._hits + self._misses
        _hit_rate = round(self._hits / _total_req * 100, 2) if _total_req >= MIN_HIT_RATE_SAMPLE else None

        return {
            "redis_enabled": settings.REDIS_ENABLED,
            "redis_available": self._redis_available,
            # 兼容旧字段：内存缓存键数
            "memory_cache_size": mem_keys,
            # 新增：应用真实键总数（Redis 下为 data-insight:* 键数，内存下为内存缓存键数）
            "total_keys": total_keys,
            # 新增：内存占用字节（Redis 下为实例 used_memory，内存下为估算值）
            "memory_bytes": memory_bytes,
            # 新增：应用级命中埋点
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": _hit_rate,
            # Redis 实例总键数（含其他应用，仅供参考）
            "redis_dbsize": redis_dbsize,
        }


# 全局缓存实例
cache_manager = CacheManager()
