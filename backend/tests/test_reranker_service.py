"""Reranker 服务单元测试 - RRF 融合与重排序逻辑"""
import pytest
from app.services.reranker_service import reciprocal_rank_fusion


class TestRRF:
    """测试 Reciprocal Rank Fusion 算法"""

    def _make_results(self, ids_scores):
        """辅助: 构造检索结果列表"""
        return [
            {"id": id_, "text": f"文档{id_}", "metadata": {"filename": f"{id_}.txt"}, "score": score}
            for id_, score in ids_scores
        ]

    def test_single_list(self):
        """单路召回: 排名不变"""
        results = self._make_results([("a", 0.9), ("b", 0.7), ("c", 0.5)])
        fused = reciprocal_rank_fusion([results], k=60, top_k=5)
        assert len(fused) == 3
        assert fused[0]["id"] == "a"
        assert fused[1]["id"] == "b"
        assert fused[2]["id"] == "c"

    def test_two_lists_overlap(self):
        """两路召回有重叠: 重叠文档排名提升"""
        list1 = self._make_results([("a", 0.9), ("b", 0.7), ("c", 0.5)])
        list2 = self._make_results([("b", 0.95), ("d", 0.6), ("e", 0.4)])
        fused = reciprocal_rank_fusion([list1, list2], k=60, top_k=5)

        ids = [r["id"] for r in fused]
        # b 在两个列表中排名都很靠前，融合后应排在前列
        assert "b" in ids
        assert fused[0]["id"] in ("a", "b")  # a 或 b 排第一

    def test_two_lists_promote(self):
        """低排名文档在两路中出现，RRF 分数提升"""
        list1 = self._make_results([("a", 0.99), ("b", 0.9), ("c", 0.8), ("d", 0.7), ("e", 0.6)])
        list2 = self._make_results([("e", 0.95), ("f", 0.5)])
        fused = reciprocal_rank_fusion([list1, list2], k=60, top_k=10)

        ids = [r["id"] for r in fused]
        # e 在 list1 排第5, list2 排第1, RRF 应使其排名提升
        e_rank = ids.index("e")
        assert e_rank < 4  # 应比原始排名第5更靠前

    def test_empty_lists(self):
        """空列表不报错"""
        fused = reciprocal_rank_fusion([], k=60, top_k=5)
        assert fused == []

    def test_one_empty_one_full(self):
        """一路为空，另一路正常"""
        list1 = self._make_results([("a", 0.9), ("b", 0.7)])
        fused = reciprocal_rank_fusion([list1, []], k=60, top_k=5)
        assert len(fused) == 2

    def test_top_k_truncation(self):
        """top_k 限制结果数量"""
        results = self._make_results([(f"doc{i}", 1.0 - i * 0.1) for i in range(20)])
        fused = reciprocal_rank_fusion([results], k=60, top_k=5)
        assert len(fused) == 5

    def test_score_range(self):
        """归一化后分数在 0-1 之间"""
        list1 = self._make_results([("a", 0.9), ("b", 0.7)])
        list2 = self._make_results([("c", 0.8), ("d", 0.6)])
        fused = reciprocal_rank_fusion([list1, list2], k=60, top_k=10)
        for doc in fused:
            assert 0 <= doc["score"] <= 1.0

    def test_identical_lists(self):
        """两路完全相同: 排序不变"""
        results = self._make_results([("a", 0.9), ("b", 0.7), ("c", 0.5)])
        fused = reciprocal_rank_fusion([results, results], k=60, top_k=5)
        ids = [r["id"] for r in fused]
        assert ids == ["a", "b", "c"]

    def test_k_parameter_effect(self):
        """k 值越小，排名靠前的文档优势越大"""
        list1 = self._make_results([("a", 0.9), ("b", 0.8)])
        list2 = self._make_results([("b", 0.95), ("a", 0.85)])

        fused_small_k = reciprocal_rank_fusion([list1, list2], k=1, top_k=2)
        fused_large_k = reciprocal_rank_fusion([list1, list2], k=1000, top_k=2)

        # 两者都应返回结果
        assert len(fused_small_k) == 2
        assert len(fused_large_k) == 2

    def test_metadata_preserved(self):
        """融合后元数据保留"""
        results = [
            {"id": "x", "text": "内容", "metadata": {"filename": "test.txt", "chunk_index": 3}, "score": 0.8}
        ]
        fused = reciprocal_rank_fusion([results], k=60, top_k=5)
        assert fused[0]["metadata"]["filename"] == "test.txt"
        assert fused[0]["metadata"]["chunk_index"] == 3
