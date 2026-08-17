"""LLM 服务 - 支持 MiniMax 和 DeepSeek 云端 API 双模式

通过 .env 中 LLM_PROVIDER 切换：
  - "minimax"：调用 MiniMax API（默认）
  - "deepseek"：调用 DeepSeek API
"""
import httpx
import json
import logging
from typing import AsyncGenerator, List, Dict
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _get_llm_config() -> dict:
    """根据 LLM_PROVIDER 返回对应提供商的配置"""
    if settings.LLM_PROVIDER == "deepseek":
        return {
            "base_url": settings.DEEPSEEK_BASE_URL,
            "api_key": settings.DEEPSEEK_API_KEY,
            "model": settings.DEEPSEEK_LLM_MODEL,
        }
    # minimax（默认）
    return {
        "base_url": settings.MINIMAX_BASE_URL,
        "api_key": settings.MINIMAX_API_KEY,
        "model": settings.MINIMAX_LLM_MODEL,
    }


def _get_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _get_llm_model(model: str = None) -> str:
    if model:
        return model
    return _get_llm_config()["model"]


async def chat_stream(
    messages: List[Dict[str, str]],
    model: str = None,
) -> AsyncGenerator[str, None]:
    """流式对话生成。自动根据 LLM_PROVIDER 选择 MiniMax 或 DeepSeek。"""
    async for token in _openai_chat_stream(messages, model):
        yield token


async def chat_complete(messages: List[Dict[str, str]], model: str = None) -> str:
    """非流式调用，返回完整回复"""
    return await _openai_chat_complete(messages, model)


async def chat_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    model: str = None,
) -> Dict:
    """带工具的非流式调用（Agent 工具阶段使用）。"""
    return await _openai_chat_with_tools(messages, tools, model)


# ==================== OpenAI 兼容模式（同时适配 MiniMax / DeepSeek） ====================

async def _openai_chat_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    model: str = None,
) -> Dict:
    """OpenAI 兼容 API：choices[0].message.tool_calls，arguments 为 JSON 字符串"""
    config = _get_llm_config()
    model = _get_llm_model(model)
    url = f"{config['base_url']}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers=_get_headers(config["api_key"]),
        )
        response.raise_for_status()
        data = response.json()

    message = data["choices"][0]["message"]
    tool_calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            arguments = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        tool_calls.append({
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "arguments": arguments,
        })
    usage = data.get("usage") or {}
    return {
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        },
    }


async def _openai_chat_stream(
    messages: List[Dict[str, str]],
    model: str = None,
) -> AsyncGenerator[str, None]:
    """OpenAI 兼容 API 流式调用（SSE）"""
    config = _get_llm_config()
    model = _get_llm_model(model)
    url = f"{config['base_url']}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 4096,
    }
    headers = _get_headers(config["api_key"])

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
    config = _get_llm_config()
    model = _get_llm_model(model)
    url = f"{config['base_url']}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    headers = _get_headers(config["api_key"])

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
