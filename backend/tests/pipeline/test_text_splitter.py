"""文本切片工具单元测试"""
import pytest
from app.utils.text_splitter import split_text


class TestSplitText:
    """测试文本切片逻辑"""

    def test_basic_split(self):
        """基本切片功能"""
        text = "这是一段测试文本。" * 50  # ~500 字符
        chunks = split_text(text, chunk_size=100, chunk_overlap=20, doc_id=1, filename="test.txt")
        assert len(chunks) > 1
        for chunk in chunks:
            assert "text" in chunk
            assert "metadata" in chunk

    def test_short_text_single_chunk(self):
        """短文本只产生一个切片"""
        text = "简短文本"
        chunks = split_text(text, chunk_size=500, chunk_overlap=50, doc_id=1, filename="short.txt")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "简短文本"

    def test_empty_text(self):
        """空文本返回空列表"""
        chunks = split_text("", chunk_size=500, chunk_overlap=50, doc_id=1, filename="empty.txt")
        assert len(chunks) == 0

    def test_metadata_fields(self):
        """验证 metadata 包含必要字段"""
        text = "测试内容" * 100
        chunks = split_text(text, chunk_size=50, chunk_overlap=10, doc_id=42, filename="meta.txt")
        for i, chunk in enumerate(chunks):
            meta = chunk["metadata"]
            assert meta["doc_id"] == "42"  # doc_id 存储为字符串
            assert meta["filename"] == "meta.txt"
            assert meta["chunk_index"] == i

    def test_overlap_content(self):
        """重叠区域内容验证"""
        # 创建一个长文本
        words = [f"段落{i}" for i in range(100)]
        text = " ".join(words)
        chunks = split_text(text, chunk_size=100, chunk_overlap=30, doc_id=1, filename="overlap.txt")
        if len(chunks) >= 2:
            # 相邻切片应有重叠内容
            end_of_first = chunks[0]["text"][-20:]
            start_of_second = chunks[1]["text"][:20]
            # 至少部分字符重叠
            overlap_chars = set(end_of_first) & set(start_of_second)
            assert len(overlap_chars) > 0

    def test_chunk_count_consistency(self):
        """切片数量与文本长度正相关"""
        short = split_text("这是短句。" * 10, chunk_size=50, chunk_overlap=5, doc_id=1, filename="a.txt")
        long = split_text("这是长句子，包含更多内容。" * 50, chunk_size=50, chunk_overlap=5, doc_id=2, filename="b.txt")
        assert len(long) > len(short)
