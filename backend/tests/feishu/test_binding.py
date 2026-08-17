"""飞书知识库绑定测试：指令解析、检索优先级、绑定处理全流程"""
import json
import sys
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services import feishu_bot  # noqa: E402
# 拆分后 monkeypatch 需要指向源码模块（而非 shim）
from app.services.feishu import account as _account  # noqa: E402
from app.services.feishu import binding as _binding  # noqa: E402
from app.services.feishu import bot as _bot  # noqa: E402


class _SeqResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _SeqDB:
    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, stmt):
        return _SeqResult(self._results.pop(0) if self._results else None)


class TestParseBindingCommand:
    def test_bind_with_colon(self):
        assert feishu_bot.parse_binding_command("绑定知识库：员工手册") == "员工手册"

    def test_switch_without_separator(self):
        assert feishu_bot.parse_binding_command("切换知识库员工手册") == "员工手册"

    def test_use_kb(self):
        assert feishu_bot.parse_binding_command("使用考勤库") == "考勤库"

    def test_set_with_wei(self):
        assert feishu_bot.parse_binding_command("设置为员工手册库") == "员工手册库"

    def test_query_current(self):
        assert feishu_bot.parse_binding_command("当前知识库") == ""

    def test_query_now_binding(self):
        assert feishu_bot.parse_binding_command("现在绑定的是哪个库？") == ""

    def test_normal_question_not_command(self):
        assert feishu_bot.parse_binding_command("今天考勤怎么样") is None

    def test_bare_bind_not_command(self):
        assert feishu_bot.parse_binding_command("绑定") is None

    def test_empty_or_none(self):
        assert feishu_bot.parse_binding_command("") is None
        assert feishu_bot.parse_binding_command(None) is None


class TestResolveKbId:
    @pytest.mark.asyncio
    async def test_chat_binding_wins(self):
        db = _SeqDB(SimpleNamespace(kb_id=2))
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a", chat_id="oc_b") == 2

    @pytest.mark.asyncio
    async def test_open_binding_when_no_chat_binding(self):
        db = _SeqDB(None, SimpleNamespace(kb_id=3))
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a", chat_id="oc_b") == 3

    @pytest.mark.asyncio
    async def test_default_kb_id(self, monkeypatch):
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 9)
        db = _SeqDB(None, SimpleNamespace(id=9))
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a") == 9

    @pytest.mark.asyncio
    async def test_fallback_first_kb(self, monkeypatch):
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 0)
        db = _SeqDB(None, SimpleNamespace(id=7))
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a") == 7

    @pytest.mark.asyncio
    async def test_no_kb_anywhere_returns_none(self, monkeypatch):
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 0)
        db = _SeqDB(None, None)
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a") is None

    @pytest.mark.asyncio
    async def test_bound_user_latest_kb_fallback(self, monkeypatch):
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 0)
        monkeypatch.setattr(
            _account, "list_visible_kbs",
            AsyncMock(return_value=[SimpleNamespace(id=6), SimpleNamespace(id=3)]),
        )
        user = SimpleNamespace(id=9)
        db = _SeqDB(None)
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a", user=user) == 6

    @pytest.mark.asyncio
    async def test_user_no_kb_falls_to_global_first(self, monkeypatch):
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 0)
        monkeypatch.setattr(_account, "list_visible_kbs", AsyncMock(return_value=[]))
        user = SimpleNamespace(id=9)
        db = _SeqDB(None, SimpleNamespace(id=7))
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a", user=user) == 7


class TestHandleBindingCommand:
    async def test_query_current_binding(self, monkeypatch):
        kb = SimpleNamespace(name="考勤库", document_count=4, user_id=1)

        class DB:
            async def execute(self, stmt):
                return _SeqResult(None)

            async def get(self, model, pk):
                return kb

        monkeypatch.setattr(_binding, "_resolve_kb_id_only", AsyncMock(return_value=5))
        msg_type, content = await feishu_bot.handle_binding_command(DB(), "ou_a", "oc_b", "当前知识库")
        assert msg_type == "text"
        text = json.loads(content)["text"]
        assert "考勤库" in text and "ID=5" in text and "4 篇" in text

    async def test_bind_by_name(self, monkeypatch):
        kb = SimpleNamespace(id=5, name="员工手册", document_count=4)
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(_binding, "_find_kbs_by_name", AsyncMock(return_value=[kb]))
        monkeypatch.setattr(_binding, "set_binding", AsyncMock(return_value="群 oc_b"))
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：员工手册")
        assert "员工手册" in json.loads(content)["text"]

    async def test_bind_by_id(self, monkeypatch):
        kb = SimpleNamespace(id=5, name="员工手册", document_count=4)
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(_binding, "_find_kb_by_id", AsyncMock(return_value=kb))
        monkeypatch.setattr(_binding, "set_binding", AsyncMock(return_value="群 oc_b"))
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：5")
        assert "员工手册" in json.loads(content)["text"]

    async def test_bind_not_found(self, monkeypatch):
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(_binding, "_find_kbs_by_name", AsyncMock(return_value=[]))
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：不存在的库")
        assert "没找到" in json.loads(content)["text"]

    async def test_bind_requires_account_first(self):
        class DB:
            async def execute(self, stmt):
                return _SeqResult(None)

        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：员工手册")
        assert "绑定账号" in json.loads(content)["text"]

    async def test_bind_multiple_candidates(self, monkeypatch):
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(
            _binding, "_find_kbs_by_name",
            AsyncMock(return_value=[
                SimpleNamespace(id=3, name="test", document_count=2),
                SimpleNamespace(id=4, name="test", document_count=1),
            ]),
        )
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：test")
        text = json.loads(content)["text"]
        assert "匹配到多个" in text and "ID=3" in text and "ID=4" in text

    async def test_normal_question_not_handled(self):
        assert await feishu_bot.handle_binding_command(
            AsyncMock(), "ou_a", "oc_b", "今天考勤怎么样") is None


class TestFindKbsByNameInScope:
    async def test_exact_name_first(self, monkeypatch):
        monkeypatch.setattr(
            _account, "list_visible_kbs",
            AsyncMock(return_value=[
                SimpleNamespace(name="test", id=4),
                SimpleNamespace(name="test-kb", id=1),
            ]),
        )
        found = await _binding._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "test")
        assert [kb.id for kb in found] == [4]

    async def test_fuzzy_match(self, monkeypatch):
        monkeypatch.setattr(
            _account, "list_visible_kbs",
            AsyncMock(return_value=[
                SimpleNamespace(name="考勤制度", id=1),
                SimpleNamespace(name="考勤手册", id=2),
                SimpleNamespace(name="薪酬制度", id=3),
            ]),
        )
        found = await _binding._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "考勤")
        assert [kb.id for kb in found] == [1, 2]

    async def test_no_match(self, monkeypatch):
        monkeypatch.setattr(_account, "list_visible_kbs", AsyncMock(return_value=[]))
        found = await _binding._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "不存在")
        assert found == []

    async def test_fuzzy_capped_at_5(self, monkeypatch):
        monkeypatch.setattr(
            _account, "list_visible_kbs",
            AsyncMock(return_value=[SimpleNamespace(name=f"x{i}", id=i) for i in range(8)]),
        )
        found = await _binding._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "x")
        assert len(found) == 5