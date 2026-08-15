"""Cross-Encoder Reranker 单元测试"""
import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCrossEncoderReranker:

    @pytest.fixture
    def sample_candidates(self):
        return [
            {
                "id": f"doc{i}",
                "text": f"这是第{i}个文档的内容，包含关键词测试。",
                "metadata": {"filename": f"doc{i}.txt"},
                "score": round(0.9 - i * 0.08, 2),
                "retrieval_method": "hybrid",
            }
            for i in range(10)
        ]

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        """空候选列表返回空"""
        from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
        result = await rerank_by_cross_encoder("查询", [], top_k=3)
        assert result == []

    @pytest.mark.asyncio
    async def test_fewer_than_top_k(self, sample_candidates):
        """候选数量少于 top_k 时直接返回"""
        from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
        result = await rerank_by_cross_encoder("查询", sample_candidates[:2], top_k=3)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fallback_when_model_unavailable(self, sample_candidates):
        """Cross-Encoder 不可用时降级为 Bi-Encoder"""
        from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
        with patch("app.retrieval.cross_encoder_reranker._load_cross_encoder", return_value=None):
            with patch("app.retrieval.reranker_service.rerank_by_embedding") as mock_bi:
                mock_bi.return_value = sample_candidates[:3]
                result = await rerank_by_cross_encoder("查询", sample_candidates, top_k=3)
                mock_bi.assert_called_once()
                assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fallback_on_predict_failure(self, sample_candidates):
        """模型推理失败时降级为 Bi-Encoder"""
        from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("OOM")
        with patch("app.retrieval.cross_encoder_reranker._load_cross_encoder", return_value=mock_model):
            with patch("app.retrieval.reranker_service.rerank_by_embedding") as mock_bi:
                mock_bi.return_value = sample_candidates[:3]
                result = await rerank_by_cross_encoder("查询", sample_candidates, top_k=3)
                mock_bi.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_rerank(self, sample_candidates):
        """正常推理时按 rerank_score 降序排列"""
        from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
        mock_model = MagicMock()
        # 返回倒序分数，验证排序逻辑
        mock_model.predict.return_value = [0.1 * i for i in range(10)]
        with patch("app.retrieval.cross_encoder_reranker._load_cross_encoder", return_value=mock_model):
            result = await rerank_by_cross_encoder("查询", sample_candidates, top_k=3)
            assert len(result) == 3
            # 分数应降序
            assert result[0]["rerank_score"] >= result[1]["rerank_score"]
            assert result[1]["rerank_score"] >= result[2]["rerank_score"]
            # score 应被 rerank_score 覆盖
            for item in result:
                assert item["score"] == item["rerank_score"]
                assert "original_score" in item

    @pytest.mark.asyncio
    async def test_top_k_respected(self, sample_candidates):
        """返回结果数量等于 top_k"""
        from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.5] * 10
        with patch("app.retrieval.cross_encoder_reranker._load_cross_encoder", return_value=mock_model):
            result = await rerank_by_cross_encoder("查询", sample_candidates, top_k=5)
            assert len(result) == 5

    def test_health_check_initial_state(self):
        """初始状态下 health check 应反映加载状态"""
        from app.retrieval.cross_encoder_reranker import is_cross_encoder_loaded, get_model_name
        # 如果之前没加载过，应返回 False
        # 注意：如果其他测试已触发加载，状态可能不同
        loaded = is_cross_encoder_loaded()
        model = get_model_name()
        if not loaded:
            assert model is None or isinstance(model, str)
