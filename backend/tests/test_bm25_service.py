"""BM25 服务单元测试 - 分词与检索逻辑"""
import pytest
from app.services.bm25_service import tokenize, BM25Index


class TestTokenize:
    """测试中英文混合分词"""

    def test_chinese_basic(self):
        result = tokenize("企业信息管理系统")
        assert len(result) > 0
        # 应该分出有意义的词
        assert any("企业" in w or "信息" in w or "管理" in w or "系统" in w for w in result)

    def test_english_basic(self):
        result = tokenize("knowledge base system")
        assert "knowledge" in result
        assert "base" in result
        assert "system" in result

    def test_mixed_chinese_english(self):
        result = tokenize("使用Python进行数据分析")
        assert len(result) > 0
        # 应包含英文关键词
        assert any("python" in w for w in result)

    def test_stopwords_filtered(self):
        result = tokenize("这是一个很好的系统")
        # 停用词 "这", "是", "一个" 应被过滤
        assert "这" not in result
        assert "是" not in result

    def test_empty_string(self):
        result = tokenize("")
        assert result == []

    def test_only_stopwords(self):
        result = tokenize("的了是在不有")
        assert len(result) == 0

    def test_case_insensitive(self):
        result1 = tokenize("Python Programming")
        result2 = tokenize("python programming")
        assert result1 == result2

    def test_short_words_filtered(self):
        result = tokenize("a b c test")
        # 单字符词应被过滤
        assert all(len(w) > 1 for w in result)


class TestBM25Index:
    """测试 BM25 索引构建和检索"""

    def _build_sample_index(self, kb_id=1):
        documents = [
            {"id": "doc1", "text": "企业信息安全管理制度包括访问控制和数据加密", "metadata": {"filename": "安全制度.docx"}},
            {"id": "doc2", "text": "员工考勤管理规定上下班打卡迟到早退处理办法", "metadata": {"filename": "考勤制度.docx"}},
            {"id": "doc3", "text": "CloudFlow产品支持微服务架构和容器化部署", "metadata": {"filename": "产品文档.docx"}},
            {"id": "doc4", "text": "公司年度财务报表显示营收增长百分之二十", "metadata": {"filename": "财务报告.docx"}},
        ]
        index = BM25Index()
        index.build(kb_id, documents)
        return index

    def test_build_index(self):
        index = self._build_sample_index()
        assert index.is_built is True
        assert index._kb_id == 1

    def test_build_empty_documents(self):
        index = BM25Index()
        index.build(1, [])
        assert index.is_built is False

    def test_search_relevant_result(self):
        index = self._build_sample_index()
        results = index.search("信息安全访问控制", top_k=2)
        assert len(results) > 0
        # 安全制度文档应该排在前面
        assert results[0]["id"] == "doc1"

    def test_search_employee_attendance(self):
        index = self._build_sample_index()
        results = index.search("员工考勤打卡迟到", top_k=2)
        assert len(results) > 0
        assert results[0]["id"] == "doc2"

    def test_search_product_docs(self):
        index = self._build_sample_index()
        results = index.search("微服务容器化部署", top_k=2)
        assert len(results) > 0
        assert results[0]["id"] == "doc3"

    def test_search_no_results(self):
        index = self._build_sample_index()
        results = index.search("完全无关的随机内容xyz", top_k=5)
        # 可能返回低分结果或空
        assert isinstance(results, list)

    def test_search_empty_query(self):
        index = self._build_sample_index()
        results = index.search("", top_k=5)
        assert results == []

    def test_search_unbuilt_index(self):
        index = BM25Index()
        results = index.search("test query", top_k=5)
        assert results == []

    def test_score_normalization(self):
        index = self._build_sample_index()
        results = index.search("企业管理制度", top_k=5)
        for r in results:
            assert 0 <= r["score"] <= 1.0

    def test_result_fields(self):
        index = self._build_sample_index()
        results = index.search("员工管理", top_k=2)
        for r in results:
            assert "id" in r
            assert "text" in r
            assert "metadata" in r
            assert "score" in r
            assert r["retrieval_method"] == "bm25"
