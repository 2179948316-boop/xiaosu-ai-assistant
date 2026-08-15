"""RAGAS 适配器 - 将 Ollama 接入 RAGAS 评估框架

RAGAS 需要 LLM 和 Embeddings 适配器来计算 faithfulness / answer_relevancy 等指标。
这里通过 httpx 直接调用 Ollama API，无需引入 LangChain。

适配 RAGAS 0.4.x 接口：BaseRagasLLM + LangChain PromptValue/LLMResult
"""
import httpx
import asyncio
from typing import List, Optional

from langchain_core.outputs import LLMResult, Generation
from langchain_core.prompt_values import PromptValue
from ragas.llms.base import BaseRagasLLM
from langchain_core.callbacks import Callbacks

from app.config import get_settings

settings = get_settings()


class OllamaLLM(BaseRagasLLM):
    """RAGAS LLM 适配器 - Ollama (兼容 0.4.x)"""

    def __init__(self, model: str = None, base_url: str = None):
        self.model = model or settings.LLM_MODEL
        self.base_url = base_url or settings.OLLAMA_BASE_URL

    async def agenerate_text(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float = 0.01,
        stop: Optional[List[str]] = None,
        callbacks: Callbacks = None,
    ) -> LLMResult:
        """异步生成文本 - RAGAS 核心调用入口"""
        prompt_text = prompt.to_string()
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt_text}],
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": 4096,
                        **({"stop": stop} if stop else {}),
                    },
                    **({"think": False} if "deepseek" in self.model or "qwen3" in self.model else {}),
                },
            )
            response.raise_for_status()
            text = response.json()["message"]["content"]

        generations = [[Generation(text=text)]]
        return LLMResult(generations=generations)

    def generate_text(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float = 0.01,
        stop: Optional[List[str]] = None,
        callbacks: Callbacks = None,
    ) -> LLMResult:
        """同步生成文本"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.agenerate_text(prompt, n, temperature, stop, callbacks)
            )
        finally:
            loop.close()

    async def generate(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float = 0.01,
        stop: Optional[List[str]] = None,
        callbacks: Callbacks = None,
    ) -> LLMResult:
        """异步 generate - RAGAS 内部 await 调用此方法"""
        return await self.agenerate_text(prompt, n, temperature, stop, callbacks)

    def is_finished(self, response: LLMResult) -> bool:
        """RAGAS 0.4.x 抽象方法 - 判断 LLM 响应是否完成"""
        if response and response.generations:
            return all(
                gen.generation_info.get("finished", True)
                for gen_list in response.generations
                for gen in gen_list
                if gen.generation_info
            )
        return True

    # 兼容旧接口（generate_testset.py 中使用了 agenerate）
    async def agenerate(self, prompt, **kwargs) -> str:
        prompt_text = str(prompt)
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt_text}],
                    "stream": False,
                    "options": {"temperature": 0.0, "num_ctx": 4096},
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]


from ragas.embeddings.base import BaseRagasEmbeddings


class OllamaEmbeddings(BaseRagasEmbeddings):
    """RAGAS Embeddings 适配器 - Ollama"""

    def __init__(self, model: str = None, base_url: str = None):
        self.model = model or settings.EMBEDDING_MODEL
        self.base_url = base_url or settings.OLLAMA_BASE_URL

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            return response.json()["embeddings"]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.aembed_documents(texts))
        finally:
            loop.close()

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    async def aembed_query(self, text: str) -> List[float]:
        results = await self.aembed_documents([text])
        return results[0]
