"""Redis 缓存服务单元测试"""
import pytest
import sys
import os
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCacheKey:
    """缓存键生成逻辑"""

    def test_deterministic(self):
        """相同输入生成相同 key"""
        from app.services.cache_service import _make_cache_key
        key1 = _make_cache_key("什么是RAG？", 1)
        key2 = _make_cache_key("什么是RAG？", 1)
        assert key1 == key2

    def test_case_insensitive(self):
        """大小写不敏感"""
        from app.services.cache_service import _make_cache_key
        key1 = _make_cache_key("What is RAG?", 1)
        key2 = _make_cache_key("what is rag?", 1)
        assert key1 == key2

    def test_different_kb_different_key(self):
        """不同知识库生成不同 key"""
        from app.services.cache_service import _make_cache_key
        key1 = _make_cache_key("test", 1)
        key2 = _make_cache_key("test", 2)
        assert key1 != key2

    def test_whitespace_normalized(self):
        """前后空格被归一化"""
        from app.services.cache_service import _make_cache_key
        key1 = _make_cache_key("  hello  ", 1)
        key2 = _make_cache_key("hello", 1)
        assert key1 == key2

    def test_key_prefix(self):
        """key 以 rag_cache: 开头"""
        from app.services.cache_service import _make_cache_key
        key = _make_cache_key("test", 1)
        assert key.startswith("rag_cache:")


class TestCacheOperations:
    """缓存读写操作"""

    @pytest.mark.asyncio
    async def test_get_returns_none_when_redis_down(self):
        """Redis 不可用时返回 None"""
        from app.services.cache_service import get_cached_answer
        with patch("app.services.cache_service._get_redis", new_callable=AsyncMock, return_value=None):
            result = await get_cached_answer("test", 1)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_cached_data(self):
        """正常返回缓存数据"""
        from app.services.cache_service import get_cached_answer
        mock_client = AsyncMock()
        mock_client.get.return_value = '{"answer": "缓存的回答", "sources": []}'
        with patch("app.services.cache_service._get_redis", new_callable=AsyncMock, return_value=mock_client):
            result = await get_cached_answer("test", 1)
            assert result is not None
            assert result["answer"] == "缓存的回答"

    @pytest.mark.asyncio
    async def test_set_handles_redis_failure(self):
        """Redis 不可用时 set 返回 False"""
        from app.services.cache_service import set_cached_answer
        with patch("app.services.cache_service._get_redis", new_callable=AsyncMock, return_value=None):
            result = await set_cached_answer("q", 1, "answer", [])
            assert result is False

    @pytest.mark.asyncio
    async def test_set_writes_to_redis(self):
        """正常写入缓存"""
        from app.services.cache_service import set_cached_answer
        mock_client = AsyncMock()
        mock_client.set.return_value = True
        mock_client.sadd.return_value = 1
        with patch("app.services.cache_service._get_redis", new_callable=AsyncMock, return_value=mock_client):
            with patch("app.config.get_settings") as mock_settings:
                mock_settings.return_value.REDIS_CACHE_TTL = 3600
                result = await set_cached_answer("q", 1, "answer", [])
                assert result is True
                mock_client.set.assert_called_once()
                mock_client.sadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_returns_zero_when_redis_down(self):
        """Redis 不可用时 invalidate 返回 0"""
        from app.services.cache_service import invalidate_kb_cache
        with patch("app.services.cache_service._get_redis", new_callable=AsyncMock, return_value=None):
            result = await invalidate_kb_cache(1)
            assert result == 0

    @pytest.mark.asyncio
    async def test_cache_stats_unavailable(self):
        """Redis 不可用时 stats 显示 unavailable"""
        from app.services.cache_service import get_cache_stats
        with patch("app.services.cache_service._get_redis", new_callable=AsyncMock, return_value=None):
            stats = await get_cache_stats()
            assert stats["status"] == "unavailable"
