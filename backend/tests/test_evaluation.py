"""评估系统单元测试"""
import pytest
import sys
import os
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestTestsetGeneration:
    """测试数据集生成逻辑"""

    @pytest.mark.asyncio
    async def test_generate_questions_for_chunk(self):
        """正常生成问题"""
        from evaluation.generate_testset import generate_questions_for_chunk
        with patch("evaluation.generate_testset.chat_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "什么是信息安全？\n新员工入职流程是什么？"
            questions = await generate_questions_for_chunk(
                "信息安全是指保护信息免受未经授权的访问...", num_questions=2
            )
            assert len(questions) == 2
            assert "信息安全" in questions[0]

    @pytest.mark.asyncio
    async def test_generate_questions_handles_empty_response(self):
        """LLM 返回空字符串时返回空列表"""
        from evaluation.generate_testset import generate_questions_for_chunk
        with patch("evaluation.generate_testset.chat_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ""
            questions = await generate_questions_for_chunk("短文本", num_questions=2)
            assert questions == []

    @pytest.mark.asyncio
    async def test_generate_questions_handles_llm_error(self):
        """LLM 异常时返回空列表"""
        from evaluation.generate_testset import generate_questions_for_chunk
        with patch("evaluation.generate_testset.chat_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Ollama down")
            questions = await generate_questions_for_chunk("some text", num_questions=2)
            assert questions == []

    @pytest.mark.asyncio
    async def test_generate_questions_limits_count(self):
        """生成的问题数不超过 num_questions"""
        from evaluation.generate_testset import generate_questions_for_chunk
        with patch("evaluation.generate_testset.chat_complete", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "第一个重要的问题是什么？\n第二个关键问题是什么呢？\n第三个核心问题是啥？\n第四个补充问题内容？\n第五个额外的问题内容？"
            questions = await generate_questions_for_chunk("长文本内容...", num_questions=3)
            assert len(questions) == 3


class TestDatasetFormat:
    """验证数据集格式"""

    def test_dataset_entry_has_required_fields(self):
        """测试集条目包含所有必需字段"""
        sample = {
            "question": "什么是信息安全？",
            "ground_truth": "信息安全是指保护信息...",
            "contexts": ["信息安全是指保护信息..."],
            "source_id": "doc1_chunk0",
            "source_file": "security.pdf",
        }
        required_fields = ["question", "ground_truth", "contexts"]
        for field in required_fields:
            assert field in sample, f"Missing required field: {field}"
        assert isinstance(sample["contexts"], list)
        assert len(sample["contexts"]) > 0


class TestRagasAdapters:
    """RAGAS 适配器测试"""

    def test_ollama_llm_init(self):
        """OllamaLLM 初始化不报错"""
        from evaluation.ragas_adapters import OllamaLLM
        llm = OllamaLLM()
        assert llm.model is not None
        assert llm.base_url is not None

    def test_ollama_embeddings_init(self):
        """OllamaEmbeddings 初始化不报错"""
        from evaluation.ragas_adapters import OllamaEmbeddings
        emb = OllamaEmbeddings()
        assert emb.model is not None
        assert emb.base_url is not None

    @pytest.mark.asyncio
    async def test_ollama_llm_agenerate(self):
        """OllamaLLM 异步生成调用"""
        from evaluation.ragas_adapters import OllamaLLM
        llm = OllamaLLM()
        with patch("httpx.AsyncClient") as mock_client_cls:
            from unittest.mock import MagicMock
            mock_response = MagicMock()
            mock_response.json.return_value = {"message": {"content": "回答"}}
            mock_response.raise_for_status = lambda: None
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await llm.agenerate("测试问题")
            assert result == "回答"
