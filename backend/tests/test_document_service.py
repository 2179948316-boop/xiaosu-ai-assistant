"""文档服务测试：增量更新（同名文档版本替换）为核心场景（任务 6.2）"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import document_service


class _FakeScalars:
    """模拟 execute 结果：.scalars().all() 返回预置文档列表"""

    def __init__(self, docs):
        self._docs = docs

    def scalars(self):
        return self

    def all(self):
        return self._docs


def _make_file(filename="员工手册.md", content=b"hello world"):
    f = SimpleNamespace(filename=filename)
    f.read = AsyncMock(return_value=content)
    return f


def _fake_db(*execute_results):
    db = AsyncMock()
    db.execute.side_effect = list(execute_results)
    return db


def _chunks():
    return [{"text": "hello", "doc_id": 99, "filename": "员工手册.md"}]


@pytest.fixture(autouse=True)
def _patch_pipeline(monkeypatch):
    """统一 mock 掉 解析/切片/向量化/Chroma/BM25 等外部依赖"""
    monkeypatch.setattr(document_service, "parse_file", lambda path, ft: "模拟文档内容")
    monkeypatch.setattr(document_service, "split_text", lambda *a, **k: _chunks())
    monkeypatch.setattr(document_service, "get_embeddings", AsyncMock(return_value=[[0.1] * 8]))
    monkeypatch.setattr(
        document_service.vector_service, "add_chunks", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        document_service.vector_service, "delete_document_chunks", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        document_service.bm25_service, "build_bm25_index", AsyncMock(return_value=None)
    )


class TestIncrementalUpload:
    """同名文档重复上传 → 旧版本被替换（向量删除 + 记录删除 + 计数先减后加）"""

    @pytest.mark.asyncio
    async def test_same_name_replaces_old(self):
        old_doc = SimpleNamespace(id=1, kb_id=5, filename="员工手册.md")
        db = _fake_db(
            _FakeScalars([old_doc]),  # 1. 同名检查：命中旧文档
            AsyncMock(),              # 2. update KB document_count -1
            AsyncMock(),              # 3. update KB document_count +1
        )
        file = _make_file()

        doc = await document_service.process_document_upload(db, file, kb_id=5, user_id=3)

        # 旧文档被删：向量 + 记录
        document_service.vector_service.delete_document_chunks.assert_awaited_once_with(5, 1)
        assert old_doc in [c.args[0] for c in db.delete.call_args_list]
        # 新文档创建完成
        assert doc.filename == "员工手册.md"
        assert doc.status == "completed"
        assert doc.kb_id == 5
        # 计数先减后加（净 0）
        kb_updates = [c.args[0] for c in db.execute.call_args_list]
        assert len(kb_updates) == 3  # select + 减 + 加
        assert db.commit.await_count >= 2

    @pytest.mark.asyncio
    async def test_new_name_no_delete(self):
        """无同名文档 → 不触发任何删除，直接建新文档"""
        db = _fake_db(
            _FakeScalars([]),  # 1. 同名检查：未命中
            AsyncMock(),       # 2. update KB document_count +1
        )
        file = _make_file()

        doc = await document_service.process_document_upload(db, file, kb_id=5, user_id=3)

        document_service.vector_service.delete_document_chunks.assert_not_awaited()
        assert db.delete.await_count == 0
        assert doc.status == "completed"
        assert doc.filename == "员工手册.md"

    @pytest.mark.asyncio
    async def test_empty_content_fails(self):
        """空文件内容 → 标记 failed 并抛错（错误分支兜底）"""
        monkeypatch_marker = None
        db = _fake_db(
            _FakeScalars([]),
            AsyncMock(),
        )
        file = _make_file()

        with patch.object(
            document_service, "parse_file", lambda path, ft: "   "
        ):
            with pytest.raises(ValueError, match="文件内容为空"):
                await document_service.process_document_upload(db, file, kb_id=5, user_id=3)
        # 状态落库为 failed
        failed_add = db.add.call_args.args[0]
        assert failed_add.status == "failed"
