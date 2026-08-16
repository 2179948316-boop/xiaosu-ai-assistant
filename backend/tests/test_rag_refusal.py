"""RAG 拒答硬阈值测试（任务 6.1）：mock LLM，验证分数低于阈值时直接拒答、不调 LLM"""
import json
import pytest
from unittest.mock import AsyncMock

from app.retrieval import rag_service

REFUSAL_TEXT = "文档里没找到相关内容，换个问法试试。也可以让管理员补充相关文档后再问我。"


def _low_score_source(score=0.1):
    return [{
        "score": score,
        "metadata": {"filename": "员工手册.md", "chunk_index": 0},
        "id": "chunk_1",
        "text": "年假规则：入职满一年享受 5 天年假。",
    }]


async def _collect_events(*args, **kwargs):
    return [
        json.loads(e.removeprefix("data: ").strip())
        for e in [x async for x in rag_service.rag_chat_stream(*args, **kwargs)]
    ]


class TestRefusalThreshold:
    """top1 分数 < REFUSAL_SCORE_THRESHOLD(0.35) → 拒答且不调用 LLM"""

    @pytest.mark.asyncio
    async def test_low_score_refuses_without_llm(self, monkeypatch):
        monkeypatch.setattr(rag_service, "get_cached_answer", AsyncMock(return_value=None))
        monkeypatch.setattr(
            rag_service, "retrieve_context", AsyncMock(return_value=_low_score_source(0.1))
        )
        llm_called = False

        async def _forbidden_llm(*args, **kwargs):
            nonlocal llm_called
            llm_called = True
            raise AssertionError("拒答路径不应调用 LLM")
            yield  # pragma: no cover

        monkeypatch.setattr(rag_service, "chat_stream", _forbidden_llm)
        db = AsyncMock()

        events = await _collect_events(db, conversation_id=1, kb_id=2, user_question="员工年假几天？")

        assert llm_called is False
        chunks = [e["content"] for e in events if e["type"] == "chunk"]
        assert chunks == [REFUSAL_TEXT]
        done = [e for e in events if e["type"] == "done"]
        assert len(done) == 1
        assert done[0]["refused"] is True
        assert done[0]["content"] == REFUSAL_TEXT

    @pytest.mark.asyncio
    async def test_high_score_calls_llm(self, monkeypatch):
        """分数达标 → 正常走 LLM 流式回答"""
        monkeypatch.setattr(rag_service, "get_cached_answer", AsyncMock(return_value=None))
        monkeypatch.setattr(
            rag_service, "retrieve_context", AsyncMock(return_value=_low_score_source(0.8))
        )

        async def _fake_llm_stream(messages):
            for token in ["年假是", "5天。"]:
                yield token

        monkeypatch.setattr(rag_service, "chat_stream", _fake_llm_stream)

        class _EmptyScalars:
            def scalars(self):
                return self

            def all(self):
                return []

        db = AsyncMock()
        db.execute.return_value = _EmptyScalars()

        events = await _collect_events(db, conversation_id=1, kb_id=2, user_question="员工年假几天？")

        chunks = [e["content"] for e in events if e["type"] == "chunk"]
        assert "".join(chunks) == "年假是5天。"
        # 来源事件正常下发
        sources = [e for e in events if e["type"] == "sources"]
        assert len(sources) == 1
        assert sources[0]["sources"][0]["filename"] == "员工手册.md"
        assert not any(e.get("refused") for e in events)

    @pytest.mark.asyncio
    async def test_retrieval_error_degrades(self, monkeypatch):
        """检索管线异常 → 返回 error 事件，不崩溃"""
        monkeypatch.setattr(rag_service, "get_cached_answer", AsyncMock(return_value=None))
        monkeypatch.setattr(
            rag_service, "retrieve_context", AsyncMock(side_effect=RuntimeError("chroma down"))
        )
        db = AsyncMock()

        events = await _collect_events(db, conversation_id=1, kb_id=2, user_question="考勤规则？")

        errors = [e for e in events if e["type"] == "error"]
        assert len(errors) == 1
        assert "检索失败" in errors[0]["content"]
