"""文件解析工具单元测试"""
import os
import pytest
from app.utils.file_parser import get_file_type, parse_file


class TestGetFileType:
    """测试文件类型识别"""

    def test_pdf(self):
        assert get_file_type("report.pdf") == "pdf"

    def test_docx(self):
        assert get_file_type("文档.docx") == "docx"

    def test_html(self):
        assert get_file_type("page.html") == "html"

    def test_htm(self):
        assert get_file_type("page.htm") == "htm"

    def test_txt(self):
        assert get_file_type("notes.txt") == "txt"

    def test_uppercase(self):
        assert get_file_type("DOC.PDF") == "pdf"

    def test_no_extension(self):
        assert get_file_type("README") == ""

    def test_chinese_filename(self):
        assert get_file_type("员工手册.docx") == "docx"

    def test_multiple_dots(self):
        assert get_file_type("report.v2.final.pdf") == "pdf"


class TestParseFile:
    """测试文件解析 (使用测试文档)"""

    @pytest.fixture
    def test_docs_dir(self):
        """测试文档目录"""
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "test_docs")

    def test_parse_txt(self, test_docs_dir):
        txt_file = os.path.join(test_docs_dir, "常见问题FAQ.txt")
        if os.path.exists(txt_file):
            text = parse_file(txt_file, "txt")
            assert len(text) > 0
            assert isinstance(text, str)

    def test_parse_html(self, test_docs_dir):
        html_file = os.path.join(test_docs_dir, "信息安全管理制度.html")
        if os.path.exists(html_file):
            text = parse_file(html_file, "html")
            assert len(text) > 0
            # HTML 中的 script/style 应被移除
            assert "<script" not in text.lower()
            assert "<style" not in text.lower()

    def test_parse_docx(self, test_docs_dir):
        docx_file = os.path.join(test_docs_dir, "员工手册.docx")
        if os.path.exists(docx_file):
            text = parse_file(docx_file, "docx")
            assert len(text) > 0

    def test_unsupported_type(self):
        with pytest.raises(ValueError, match="不支持的文件类型"):
            parse_file("fake.xyz", "xyz")
