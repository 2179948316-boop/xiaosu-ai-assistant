"""Embedding 服务 - 支持 Ollama（本地）和 OpenAI 兼容 API（云端）双模式

通过 .env 中 EMBEDDING_PROVIDER 切换：
  - "ollama"：调用本地 Ollama（默认，768 维）
  - "openai"：调用 OpenAI 兼容 API

⚠️ 切换 Embedding 模型后，必须重建知识库向量（维度不同，旧向量不兼容）
"""
import httpx
import logging
from typing import List
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _is_openai_mode() -> bool:
    return settings.EMBEDDING_PROVIDER == "openai"


def _get_headers() -> dict:
    if _is_openai_mode():
        return {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
    return {}


def _get_embedding_model() -> str:
    if _is_openai_mode() and settings.OPENAI_EMBEDDING_MODEL:
        return settings.OPENAI_EMBEDDING_MODEL
    return settings.EMBEDDING_MODEL


async def get_embedding(text: str, embed_type: str = "query") -> List[float]:
    """获取单个文本的 embedding 向量（embed_type: query/db，MiniMax 需要区分）"""
    if _is_openai_mode():
        results = await _openai_embeddings([text], embed_type=embed_type)
        return results[0]
    else:
        return await _ollama_get_embedding(text)


async def get_embeddings(texts: List[str], embed_type: str = "db") -> List[List[float]]:
    """批量获取文本的 embedding 向量（embed_type: db/query，MiniMax 需要区分）"""
    if not texts:
        return []
    if _is_openai_mode():
        return await _openai_embeddings(texts, embed_type=embed_type)
    else:
        return await _ollama_get_embeddings(texts)


# ==================== Ollama 模式 ====================

async def _ollama_get_embedding(text: str) -> List[float]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={
                "model": settings.EMBEDDING_MODEL,
                "input": text,
            }
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]


async def _ollama_get_embeddings(texts: List[str]) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={
                "model": settings.EMBEDDING_MODEL,
                "input": texts,
            }
        )
        response.raise_for_status()
        return response.json()["embeddings"]


# ==================== OpenAI 兼容模式 ====================

def _is_minimax_embedding() -> bool:
    """判断是否为 MiniMax embedding 模型（API 格式与 OpenAI 不兼容）"""
    model = _get_embedding_model()
    return "embo" in model.lower()


async def _openai_embeddings(texts: List[str], embed_type: str = "db") -> List[List[float]]:
    """OpenAI 兼容 API 批量 embedding（自动适配 MiniMax 格式）"""
    model = _get_embedding_model()
    url = f"{settings.OPENAI_BASE_URL}/embeddings"
    headers = _get_headers()

    if _is_minimax_embedding():
        # MiniMax 格式: {"model": "embo-01", "texts": [...], "type": "db"/"query"}
        # 响应: {"vectors": [[...], ...], "base_resp": {"status_code": 0}}
        payload = {"model": model, "texts": texts, "type": embed_type}
    else:
        # 标准 OpenAI 格式
        payload = {"model": model, "input": texts}

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        if _is_minimax_embedding():
            # MiniMax 响应: {"vectors": [[...], ...]}
            vectors = data.get("vectors")
            if vectors is None:
                raise RuntimeError(f"MiniMax embedding 返回异常: {data.get('base_resp', {})}")
            return vectors
        else:
            # OpenAI 格式: {"data": [{"embedding": [...], "index": 0}, ...]}
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]
