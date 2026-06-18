"""
Redis缓存操作
提供Redis缓存功能，用于缓存查询结果和会话数据
"""
import json
from typing import Any, Optional, Dict
from datetime import timedelta

from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("redis_cache")


class RedisCache:
    """Redis缓存操作类"""
    
    def __init__(self):
        config = ConfigManager()
        self.config = config.redis_config
        self._client = None
        self.default_ttl = self.config["ttl"]
        
    def connect(self):
        """连接Redis服务器"""
        try:
            import redis
            try:
                self._client = redis.Redis(
                    host=self.config["host"],
                    port=self.config["port"],
                    password=self.config["password"],
                    db=self.config["db"],
                    decode_responses=True,
                    protocol=2,  # RESP2 兼容旧版 Redis
                )
            except TypeError:
                # redis-py < 5.0 不支持 protocol 参数
                self._client = redis.Redis(
                    host=self.config["host"],
                    port=self.config["port"],
                    password=self.config["password"],
                    db=self.config["db"],
                    decode_responses=True,
                )
            self._client.ping()
            logger.info(f"已连接到Redis: {self.config['host']}:{self.config['port']}")
        except ImportError:
            logger.warning("redis未安装，使用内存缓存模式")
            self._client = None
        except Exception as e:
            logger.error(f"连接Redis失败: {e}")
            raise
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        try:
            if self._client is None:
                return None
            value = self._client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"获取缓存失败: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存值"""
        try:
            if self._client is None:
                return
            ttl = ttl or self.default_ttl
            self._client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            logger.error(f"设置缓存失败: {e}")
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            if self._client is None:
                return False
            return bool(self._client.delete(key))
        except Exception as e:
            logger.error(f"删除缓存失败: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """检查key是否存在"""
        try:
            if self._client is None:
                return False
            return bool(self._client.exists(key))
        except Exception as e:
            logger.error(f"检查缓存存在失败: {e}")
            return False
    
    def set_hash(self, name: str, key: str, value: Any, ttl: int = None):
        """设置hash字段"""
        try:
            if self._client is None:
                return
            self._client.hset(name, key, json.dumps(value, ensure_ascii=False))
            if ttl:
                self._client.expire(name, ttl)
        except Exception as e:
            logger.error(f"设置hash缓存失败: {e}")
    
    def get_hash(self, name: str, key: str = None) -> Any:
        """获取hash字段"""
        try:
            if self._client is None:
                return None
            if key:
                value = self._client.hget(name, key)
                return json.loads(value) if value else None
            else:
                return self._client.hgetall(name)
        except Exception as e:
            logger.error(f"获取hash缓存失败: {e}")
            return None
    
    # 便捷方法 - 缓存查询结果
    def cache_query_result(self, query: str, result: Dict, ttl: int = None):
        """缓存查询结果"""
        import hashlib
        key = f"query_cache:{hashlib.md5(query.encode()).hexdigest()}"
        self.set(key, result, ttl)
    
    def get_cached_query(self, query: str) -> Optional[Dict]:
        """获取缓存的查询结果"""
        import hashlib
        key = f"query_cache:{hashlib.md5(query.encode()).hexdigest()}"
        return self.get(key)
    
    # 便捷方法 - 会话管理
    def save_conversation(self, conversation_id: str, messages: list, ttl: int = None):
        """保存会话"""
        key = f"conversation:{conversation_id}"
        self.set(key, messages, ttl)
    
    def get_conversation(self, conversation_id: str) -> Optional[list]:
        """获取会话"""
        key = f"conversation:{conversation_id}"
        return self.get(key)


# 模块级单例
_redis_cache: Optional[RedisCache] = None


def get_redis_cache() -> Optional[RedisCache]:
    """获取 RedisCache 单例，首次调用自动初始化（失败返回 None）"""
    global _redis_cache
    if _redis_cache is None:
        try:
            _redis_cache = RedisCache()
            _redis_cache.connect()
        except Exception:
            logger.warning("Redis 不可用，缓存功能关闭")
            _redis_cache = RedisCache()
            _redis_cache._client = None
    return _redis_cache if _redis_cache._client is not None else None
