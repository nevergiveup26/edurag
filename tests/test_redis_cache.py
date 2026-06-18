"""database.redis_cache Redis缓存测试"""
import pytest
import json
from unittest.mock import MagicMock, patch


class TestRedisCacheInit:
    def test_default_config(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        assert cache._client is None
        assert cache.default_ttl is not None

    def test_default_ttl_from_config(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        assert isinstance(cache.default_ttl, int)
        assert cache.default_ttl > 0


class TestConnect:
    def test_connect_success(self):
        import sys
        mock_redis = MagicMock()
        mock_redis.Redis = MagicMock()
        mock_redis.Redis.return_value.ping = MagicMock()
        sys.modules["redis"] = mock_redis
        try:
            from database.redis_cache import RedisCache
            cache = RedisCache()
            cache.connect()
            assert cache._client is not None
        finally:
            sys.modules.pop("redis", None)

    def test_connect_import_error(self):
        import sys
        original_redis = sys.modules.get("redis")
        sys.modules["redis"] = None
        try:
            from database.redis_cache import RedisCache
            cache = RedisCache()
            cache.connect()
            assert cache._client is None
        finally:
            if original_redis:
                sys.modules["redis"] = original_redis
            else:
                sys.modules.pop("redis", None)

    def test_connect_exception_raises(self):
        import sys
        mock_redis = MagicMock()
        mock_redis.Redis = MagicMock(side_effect=Exception("connection refused"))
        sys.modules["redis"] = mock_redis
        try:
            from database.redis_cache import RedisCache
            cache = RedisCache()
            with pytest.raises(Exception, match="connection refused"):
                cache.connect()
        finally:
            sys.modules.pop("redis", None)

    def test_connect_typeerror_fallback(self):
        """redis-py < 5.0 不支持 protocol 参数时走 fallback"""
        import sys
        mock_redis = MagicMock()
        # 第一次调用抛 TypeError，第二次成功
        mock_redis.Redis = MagicMock(side_effect=[
            TypeError("unexpected keyword argument 'protocol'"),
            MagicMock(),
        ])
        mock_redis.Redis.return_value.ping = MagicMock()
        sys.modules["redis"] = mock_redis
        try:
            from database.redis_cache import RedisCache
            cache = RedisCache()
            cache.connect()
            assert cache._client is not None
        finally:
            sys.modules.pop("redis", None)


class TestGet:
    def test_no_client(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        assert cache.get("key") is None

    def test_get_miss(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.return_value = None
        assert cache.get("key") is None

    def test_get_hit(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.return_value = json.dumps({"val": 42})
        result = cache.get("key")
        assert result == {"val": 42}

    def test_get_exception_returns_none(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.side_effect = Exception("boom")
        assert cache.get("key") is None


class TestSet:
    def test_no_client(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache.set("key", "value")  # 不应抛异常

    def test_set_with_default_ttl(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache.default_ttl = 3600
        cache.set("key", {"data": 1})
        cache._client.setex.assert_called_once()
        args = cache._client.setex.call_args
        assert args[0][0] == "key"
        assert args[0][1] == 3600

    def test_set_with_custom_ttl(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache.set("key", "value", ttl=60)
        assert cache._client.setex.call_args[0][1] == 60

    def test_set_exception(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.setex.side_effect = Exception("boom")
        cache.set("key", "value")  # 不抛异常


class TestDelete:
    def test_no_client(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        assert cache.delete("key") is False

    def test_delete_success(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.delete.return_value = 1
        assert cache.delete("key") is True

    def test_delete_exception(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.delete.side_effect = Exception("boom")
        assert cache.delete("key") is False


class TestExists:
    def test_no_client(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        assert cache.exists("key") is False

    def test_exists_true(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.exists.return_value = 1
        assert cache.exists("key") is True

    def test_exists_false(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.exists.return_value = 0
        assert cache.exists("key") is False


class TestHashOps:
    def test_set_hash_no_client(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache.set_hash("h", "k", "v")  # 不抛异常

    def test_set_hash(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache.set_hash("h", "k", {"a": 1})
        cache._client.hset.assert_called_once()

    def test_set_hash_with_ttl(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache.set_hash("h", "k", "v", ttl=600)
        cache._client.expire.assert_called_once_with("h", 600)

    def test_get_hash_no_client(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        assert cache.get_hash("h", "k") is None

    def test_get_hash_specific_key(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.hget.return_value = json.dumps({"x": 1})
        result = cache.get_hash("h", "k")
        assert result == {"x": 1}

    def test_get_hash_all(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.hgetall.return_value = {"k1": "v1", "k2": "v2"}
        result = cache.get_hash("h")
        assert result == {"k1": "v1", "k2": "v2"}

    def test_get_hash_key_not_found(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.hget.return_value = None
        assert cache.get_hash("h", "k") is None


class TestQueryCache:
    def test_cache_query_result(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache.cache_query_result("什么是勾股定理", {"answer": "..."})
        cache._client.setex.assert_called_once()
        args = cache._client.setex.call_args
        assert args[0][0].startswith("query_cache:")

    def test_get_cached_query(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.return_value = json.dumps({"answer": "cached"})
        result = cache.get_cached_query("什么是勾股定理")
        assert result == {"answer": "cached"}

    def test_get_cached_query_miss(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.return_value = None
        assert cache.get_cached_query("query") is None


class TestConversationCache:
    def test_save_conversation(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache.save_conversation("conv_1", [{"role": "user", "content": "hi"}])
        args = cache._client.setex.call_args
        assert args[0][0] == "conversation:conv_1"

    def test_get_conversation(self):
        from database.redis_cache import RedisCache
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.return_value = json.dumps([{"role": "user", "content": "hi"}])
        result = cache.get_conversation("conv_1")
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestGetRedisCacheSingleton:
    def test_first_call_initializes(self):
        import sys
        from database import redis_cache as rc_mod

        mock_redis = MagicMock()
        mock_redis.Redis.return_value.ping = MagicMock()
        sys.modules["redis"] = mock_redis

        # 重置单例
        rc_mod._redis_cache = None
        try:
            result = rc_mod.get_redis_cache()
            assert result is not None
        finally:
            sys.modules.pop("redis", None)
            rc_mod._redis_cache = None

    def test_connect_failed_returns_none(self):
        import sys
        from database import redis_cache as rc_mod

        mock_redis = MagicMock()
        mock_redis.Redis = MagicMock(side_effect=Exception("no redis"))
        sys.modules["redis"] = mock_redis

        rc_mod._redis_cache = None
        try:
            result = rc_mod.get_redis_cache()
            assert result is None
        finally:
            sys.modules.pop("redis", None)
            rc_mod._redis_cache = None

    def test_import_error_returns_none(self):
        import sys
        from database import redis_cache as rc_mod

        # 注入假 redis 模块模拟 ImportError
        mock_redis = MagicMock()
        mock_redis.Redis = MagicMock(side_effect=ImportError("no redis installed"))
        sys.modules["redis"] = mock_redis

        rc_mod._redis_cache = None
        try:
            result = rc_mod.get_redis_cache()
            assert result is None
        finally:
            sys.modules.pop("redis", None)
            rc_mod._redis_cache = None
