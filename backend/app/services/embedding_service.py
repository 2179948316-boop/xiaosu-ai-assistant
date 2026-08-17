"""Embedding 服务 - 基于 MiniMax API（云端）

使用 MiniMax embo 系列模型生成文本向量。
"""
import httpx
import logging
from typing import List
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _get_embedding_config() -> dict:
    return {
        "base_url": settings.EMBEDDING_BASE_URL,
        "api_key": settings.EMBEDDING_API_KEY,
        "model": settings.EMBEDDING_MODEL,
    }


def _get_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def get_embedding(text: str, embed_type: str = "query") -> List[float]:
    """获取单个文本的 embedding 向量（embed_type: query/db，MiniMax 需要区分）"""
    results = await _get_embeddings([text], embed_type=embed_type)
    return results[0]


async def get_embeddings(texts: List[str], embed_type: str = "db") -> List[List[float]]:
    """批量获取文本的 embedding 向量（embed_type: db/query，MiniMax 需要区分）"""
    if not texts:
        return []
    return await _get_embeddings(texts, embed_type=embed_type)


async def _get_embeddings(texts: List[str], embed_type: str = "db") -> List[List[float]]:
    """调用 MiniMax Embedding API"""
    config = _get_embedding_config()
    url = f"{config['base_url']}/embeddings"
    headers = _get_headers(config["api_key"])

    # MiniMax 格式: {"model": "embo-01", "texts": [...], "type": "db"/"query"}
    # 响应: {"vectors": [[...], ...], "base_resp": {"status_code": 0}}
    payload = {
        "model": config["model"],
        "texts": texts,
        "type": embed_type,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    vectors = data.get("vectors")
    if vectors is None:
        raise RuntimeError(
            f"MiniMax embedding 返回异常: {data.get('base_resp', {})}"
        )
    return vectors
