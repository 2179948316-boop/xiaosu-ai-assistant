"""LLM 服务 - 支持 Ollama（本地）和 OpenAI 兼容 API（云端）双模式

通过 .env 中 LLM_PROVIDER 切换：
  - "ollama"：调用本地 Ollama（默认）
  - "openai"：调用 OpenAI 兼容 API（MiniMax / DeepSeek / SiliconFlow / OpenAI 等）
"""
import httpx
import json
import logging
from typing import AsyncGenerator, List, Dict
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _is_openai_mode() -> bool:
    return settings.LLM_PROVIDER == "openai"


def _get_headers() -> Dict[str, str]:
    """根据模式返回请求头"""
    if _is_openai_mode():
        return {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
    return {}


def _get_llm_model(model: str = None) -> str:
    """根据模式返回模型名"""
    if model:
        return model
    if _is_openai_mode():
        return settings.OPENAI_LLM_MODEL
    return settings.LLM_MODEL


async def chat_stream(
    messages: List[Dict[str, str]],
    model: str = None,
) -> AsyncGenerator[str, None]:
    """
    流式对话生成。自动根据 LLM_PROVIDER 选择 Ollama 或 OpenAI 兼容 API。
    """
    if _is_openai_mode():
        async for token in _openai_chat_stream(messages, model):
            yield token
    else:
        async for token in _ollama_chat_stream(messages, model):
            yield token


async def chat_complete(messages: List[Dict[str, str]], model: str = None) -> str:
    """非流式调用，返回完整回复"""
    if _is_openai_mode():
        return await _openai_chat_complete(messages, model)
    else:
        return await _ollama_chat_complete(messages, model)


# ==================== Ollama 模式 ====================

async def _ollama_chat_stream(
    messages: List[Dict[str, str]],
    model: str = None,
) -> AsyncGenerator[str, None]:
    model = _get_llm_model(model)
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_ctx": 4096,
        }
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        token = data["message"]["content"]
                        if token:
                            yield token
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue


async def _ollama_chat_complete(messages: List[Dict[str, str]], model: str = None) -> str:
    model = _get_llm_model(model)
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_ctx": 4096,
                }
            }
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


# ==================== OpenAI 兼容模式 ====================

async def _openai_chat_stream(
    messages: List[Dict[str, str]],
    model: str = None,
) -> AsyncGenerator[str, None]:
    """OpenAI 兼容 API 流式调用（SSE）"""
    model = _get_llm_model(model)
    url = f"{settings.OPENAI_BASE_URL}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 4096,
    }
    headers = _get_headers()

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST", url, json=payload, headers=headers,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()  # 去掉 "data: " 前缀
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue


async def _openai_chat_complete(messages: List[Dict[str, str]], model: str = None) -> str:
    """OpenAI 兼容 API 非流式调用"""
    model = _get_llm_model(model)
    url = f"{settings.OPENAI_BASE_URL}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    headers = _get_headers()

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
