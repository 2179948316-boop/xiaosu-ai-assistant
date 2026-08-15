"""Redis 缓存服务 - 高频问答结果缓存

缓存策略：
- 缓存键: rag_cache:{sha256(kb_id + normalized_question)}
- 缓存值: JSON {"answer": str, "sources": list}
- TTL: 可配置（默认 1 小时）
- 降级: Redis 不可用时所有操作静默返回 None/False，走完整 RAG 流程
- 失效: 文档上传/删除时通过 kb_index 二级索引批量清除
"""
import hashlib
import json
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

_redis_client = None
_redis_available: Optional[bool] = None


async def _get_redis():
    """惰性初始化 async Redis 连接，失败时静默降级。"""
    global _redis_client, _redis_available

    if _redis_available is False:
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        settings = get_settings()

        if not settings.REDIS_CACHE_ENABLED:
            _redis_available = False
            return None

        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await _redis_client.ping()
        _redis_available = True
        logger.info(f"Redis 缓存连接成功: {settings.REDIS_URL}")
        return _redis_client

    except Exception as e:
        logger.warning(f"Redis 连接失败，缓存功能降级: {e}")
        _redis_available = False
        _redis_client = None
        return None


def _make_cache_key(question: str, kb_id: int) -> str:
    """生成确定性缓存键（大小写不敏感、去空格）"""
    normalized = question.strip().lower()
    raw = f"kb:{kb_id}:q:{normalized}"
    return f"rag_cache:{hashlib.sha256(raw.encode()).hexdigest()}"


async def get_cached_answer(question: str, kb_id: int) -> Optional[Dict]:
    """
    查询缓存答案。
    返回 {"answer": str, "sources": list} 或 None（缓存未命中 / Redis 异常）。
    """
    client = await _get_redis()
    if client is None:
        return None

    try:
        key = _make_cache_key(question, kb_id)
        data = await client.get(key)
        if data:
            logger.info(f"缓存命中: question={question[:30]}...")
            return json.loads(data)
        return None
    except Exception as e:
        logger.warning(f"Redis GET 失败: {e}")
        return None


async def set_cached_answer(
    question: str,
    kb_id: int,
    answer: str,
    sources: List[Dict],
    ttl: Optional[int] = None,
) -> bool:
    """写入缓存。成功返回 True，失败返回 False。"""
    client = await _get_redis()
    if client is None:
        return False

    try:
        from app.config import get_settings
        settings = get_settings()
        ttl = ttl or settings.REDIS_CACHE_TTL

        key = _make_cache_key(question, kb_id)
        value = json.dumps({
            "answer": answer,
            "sources": sources,
        }, ensure_ascii=False)

        await client.set(key, value, ex=ttl)
        # 二级索引：记录此 key 属于哪个 kb_id，便于批量失效
        await client.sadd(f"kb_index:{kb_id}", key)
        logger.info(f"缓存写入: question={question[:30]}..., TTL={ttl}s")
        return True
    except Exception as e:
        logger.warning(f"Redis SET 失败: {e}")
        return False


async def invalidate_kb_cache(kb_id: int) -> int:
    """
    失效指定知识库的所有缓存。
    在文档上传/删除时调用。返回删除的 key 数量。
    """
    client = await _get_redis()
    if client is None:
        return 0

    try:
        index_key = f"kb_index:{kb_id}"
        cache_keys = await client.smembers(index_key)
        deleted = 0
        if cache_keys:
            pipe = client.pipeline()
            for key in cache_keys:
                pipe.delete(key)
            pipe.delete(index_key)
            results = await pipe.execute()
            deleted = sum(results[:-1])  # 最后一个是删 index_key 的结果
        logger.info(f"缓存失效: kb_id={kb_id}, 删除 {deleted} 条缓存")
        return deleted
    except Exception as e:
        logger.warning(f"Redis 缓存失效操作失败: {e}")
        return 0


async def get_cache_stats() -> Dict:
    """返回缓存状态，供健康检查使用。"""
    client = await _get_redis()
    if client is None:
        return {"status": "unavailable", "keys": 0}

    try:
        dbsize = await client.dbsize()
        return {
            "status": "connected",
            "total_keys": dbsize,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}
