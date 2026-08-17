"""RAGAS 适配器 - 基于 MiniMax/DeepSeek 云端 API

RAGAS 需要 LLM 和 Embeddings 适配器来计算 faithfulness / answer_relevancy 等指标。
这里复用 llm_service 和 embedding_service，不依赖本地 Ollama。

适配 RAGAS 0.4.x 接口：BaseRagasLLM + LangChain PromptValue/LLMResult
"""
import asyncio
from typing import List, Optional

from langchain_core.outputs import LLMResult, Generation
from langchain_core.prompt_values import PromptValue
from ragas.llms.base import BaseRagasLLM
from langchain_core.callbacks import Callbacks

from app.services.llm_service import chat_complete


class RagasLLM(BaseRagasLLM):
    """RAGAS LLM 适配器 - 使用 llm_service（MiniMax / DeepSeek）"""

    def __init__(self, model: str = None):
        self.model = model

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
        text = await chat_complete(
            [{"role": "user", "content": prompt_text}],
            model=self.model,
        )
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
        return await chat_complete(
            [{"role": "user", "content": prompt_text}],
            model=self.model,
        )


from ragas.embeddings.base import BaseRagasEmbeddings


class RagasEmbeddings(BaseRagasEmbeddings):
    """RAGAS Embeddings 适配器 - 使用 embedding_service（MiniMax）"""

    def __init__(self, model: str = None):
        self.model = model

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        from app.services.embedding_service import get_embeddings
        return await get_embeddings(texts, embed_type="db")

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
