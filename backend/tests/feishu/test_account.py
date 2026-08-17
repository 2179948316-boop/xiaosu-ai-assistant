"""飞书账号绑定测试：指令识别、密码验证、绑定/解绑全流程"""
import json
import sys
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services import feishu_bot  # noqa: E402
# 拆分后 monkeypatch 需要指向源码模块（而非 shim）
from app.services.feishu import account as _account  # noqa: E402


class TestParseAccountCommand:
    def test_bind_account(self):
        assert feishu_bot.parse_account_command("绑定账号：13800000001") == ("bind", "13800000001")

    def test_bind_account_no_separator(self):
        assert feishu_bot.parse_account_command("绑定账号13800000001") == ("bind", "13800000001")

    def test_show_me(self):
        assert feishu_bot.parse_account_command("我的账号") == ("me", "")
        assert feishu_bot.parse_account_command("当前账号") == ("me", "")

    def test_list_kbs(self):
        assert feishu_bot.parse_account_command("我的知识库") == ("list_kb", "")
        assert feishu_bot.parse_account_command("有哪些知识库") == ("list_kb", "")

    def test_unbind(self):
        assert feishu_bot.parse_account_command("解除绑定") == ("unbind", "")

    def test_normal_message_not_command(self):
        assert feishu_bot.parse_account_command("今天考勤怎么样") is None
        assert feishu_bot.parse_account_command("绑定知识库：员工手册") is None


class _SeqResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _account_user(username="alice", password="pw123456", feishu_open_id=None):
    return SimpleNamespace(
        id=1, username=username,
        password_hash=feishu_bot.hash_password(password),
        feishu_open_id=feishu_open_id, is_admin=False,
    )


class _AccountDB:
    def __init__(self, *results):
        self._results = list(results)
        self.commits = 0

    async def execute(self, stmt):
        return _SeqResult(self._results.pop(0) if self._results else None)

    async def commit(self):
        self.commits += 1


class TestHandleAccountCommand:
    def _clear_pending(self):
        feishu_bot._ACCOUNT_PENDING.clear()

    async def test_start_bind_p2p(self):
        self._clear_pending()
        db = _AccountDB(_account_user())
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "绑定账号：alice", "p2p")
        assert "即将把" in json.loads(content)["text"]
        assert "ou_a" in feishu_bot._ACCOUNT_PENDING
        self._clear_pending()

    async def test_start_bind_group_rejected(self):
        self._clear_pending()
        msg_type, content = await feishu_bot.handle_account_command(
            AsyncMock(), "ou_a", "绑定账号：alice", "group")
        assert "私聊" in json.loads(content)["text"]
        assert "ou_a" not in feishu_bot._ACCOUNT_PENDING

    async def test_start_bind_unknown_user(self):
        self._clear_pending()
        msg_type, content = await feishu_bot.handle_account_command(
            _AccountDB(None), "ou_a", "绑定账号：ghost", "p2p")
        assert "不存在" in json.loads(content)["text"]

    async def test_verify_password_success(self):
        self._clear_pending()
        user = _account_user()
        db = _AccountDB(user, None)
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", time.time())
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "pw123456", "p2p")
        assert "验证通过" in json.loads(content)["text"]
        assert user.feishu_open_id == "ou_a"
        assert db.commits == 1
        assert "ou_a" not in feishu_bot._ACCOUNT_PENDING
        self._clear_pending()

    async def test_verify_password_wrong(self):
        self._clear_pending()
        user = _account_user()
        db = _AccountDB(user)
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", time.time())
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "wrong-pass", "p2p")
        assert "验证失败" in json.loads(content)["text"]
        assert user.feishu_open_id is None
        assert "ou_a" not in feishu_bot._ACCOUNT_PENDING
        self._clear_pending()

    async def test_verify_password_with_prefix_colon(self):
        self._clear_pending()
        user = _account_user()
        db = _AccountDB(user, None)
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", time.time())
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "密码：pw123456", "p2p")
        assert "验证通过" in json.loads(content)["text"]
        assert user.feishu_open_id == "ou_a"
        self._clear_pending()

    async def test_verify_password_with_prefix_space(self):
        self._clear_pending()
        user = _account_user()
        db = _AccountDB(user, None)
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", time.time())
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "密码 pw123456", "p2p")
        assert "验证通过" in json.loads(content)["text"]
        assert user.feishu_open_id == "ou_a"
        self._clear_pending()

    async def test_verify_cancel(self):
        self._clear_pending()
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", 0)
        msg_type, content = await feishu_bot.handle_account_command(AsyncMock(), "ou_a", "取消", "p2p")
        assert "已取消" in json.loads(content)["text"]
        assert "ou_a" not in feishu_bot._ACCOUNT_PENDING
        self._clear_pending()

    async def test_password_in_group_rejected(self):
        self._clear_pending()
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", 0)
        msg_type, content = await feishu_bot.handle_account_command(
            AsyncMock(), "ou_a", "pw123456", "group")
        assert "私聊" in json.loads(content)["text"]
        assert "ou_a" in feishu_bot._ACCOUNT_PENDING
        self._clear_pending()

    async def test_show_bound_account(self):
        db = _AccountDB(_account_user(feishu_open_id="ou_a"))
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "我的账号", "p2p")
        assert "alice" in json.loads(content)["text"]

    async def test_show_unbound_account(self):
        msg_type, content = await feishu_bot.handle_account_command(
            _AccountDB(None), "ou_a", "我的账号", "p2p")
        assert "未绑定" in json.loads(content)["text"]

    async def test_list_kbs(self, monkeypatch):
        monkeypatch.setattr(
            _account, "list_visible_kbs",
            AsyncMock(return_value=[
                SimpleNamespace(name="员工手册", id=5, document_count=4, org_id=None),
                SimpleNamespace(name="test", id=6, document_count=3, org_id=2),
            ]),
        )
        db = _AccountDB(_account_user(feishu_open_id="ou_a"))
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "我的知识库", "p2p")
        text = json.loads(content)["text"]
        assert "员工手册" in text and "ID=5" in text and "组织" in text

    async def test_unbind(self):
        user = _account_user(feishu_open_id="ou_a")
        db = _AccountDB(user)
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "解除绑定", "p2p")
        assert "已解除" in json.loads(content)["text"]
        assert user.feishu_open_id is None
        assert db.commits == 1

    async def test_normal_message_not_handled(self):
        self._clear_pending()
        assert await feishu_bot.handle_account_command(
            AsyncMock(), "ou_a", "今天考勤怎么样", "p2p") is None