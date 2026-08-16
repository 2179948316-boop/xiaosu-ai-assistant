"""管理后台路由单元测试（离线：不依赖真实数据库 / 飞书 / LLM）

覆盖：管理员判定、403 权限、对话日志查询与统计、机器人心跳状态、
LLM 模型切换（白名单校验 + .env 写入）、飞书知识库绑定管理。
"""
import json
import sys
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers import admin  # noqa: E402
from app.routers.auth import get_current_admin, is_admin_user  # noqa: E402


def _user(username="alice", is_admin=False):
    return SimpleNamespace(username=username, is_admin=is_admin)


class TestIsAdminUser:
    def test_is_admin_field(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "ADMIN_USERNAMES", "")
        assert is_admin_user(_user(is_admin=True)) is True

    def test_whitelist_username(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "ADMIN_USERNAMES", "boss,alice")
        assert is_admin_user(_user(username="alice")) is True

    def test_whitelist_with_spaces(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "ADMIN_USERNAMES", "boss, alice ,  test")
        assert is_admin_user(_user(username="test")) is True

    def test_plain_user_not_admin(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "ADMIN_USERNAMES", "boss")
        assert is_admin_user(_user(username="alice")) is False


class TestGetCurrentAdmin:
    async def test_admin_ok(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "ADMIN_USERNAMES", "")
        user = await get_current_admin(_user(is_admin=True))
        assert user.username == "alice"

    async def test_non_admin_forbidden(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "ADMIN_USERNAMES", "boss")
        with pytest.raises(HTTPException) as exc:
            await get_current_admin(_user(username="alice"))
        assert exc.value.status_code == 403


class TestHeartbeat:
    def _write(self, path, ts):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pid": 123, "ts": ts}, f)

    def test_fresh_heartbeat_connected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(admin.settings, "BOT_HEARTBEAT_FILE", str(tmp_path / "hb.json"))
        self._write(tmp_path / "hb.json", datetime.now().isoformat())
        info = admin._read_bot_heartbeat()
        assert info["connected"] is True
        assert info["pid"] == 123

    def test_stale_heartbeat_offline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(admin.settings, "BOT_HEARTBEAT_FILE", str(tmp_path / "hb.json"))
        old = (datetime.now() - timedelta(minutes=5)).isoformat()
        self._write(tmp_path / "hb.json", old)
        assert admin._read_bot_heartbeat()["connected"] is False

    def test_missing_heartbeat_offline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(admin.settings, "BOT_HEARTBEAT_FILE", str(tmp_path / "nope.json"))
        info = admin._read_bot_heartbeat()
        assert info["connected"] is False and info["pid"] is None


class TestSettingsUpdate:
    def test_reject_non_whitelist_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(admin.settings, "LLM_MODEL_WHITELIST", "deepseek-r1:1.5b")
        with pytest.raises(HTTPException) as exc:
            asyncio_run(admin.update_admin_settings(admin.SettingsUpdate(llm_model="gpt-4")))
        assert exc.value.status_code == 400

    def test_write_existing_key(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("LLM_MODEL=old-model\nFEISHU_APP_ID=x\n", encoding="utf-8")
        monkeypatch.setattr(admin, "_ENV_FILE", str(env_file))
        monkeypatch.setattr(admin.settings, "LLM_MODEL_WHITELIST", "deepseek-r1:1.5b,MiniMax-Text-01")
        asyncio_run(admin.update_admin_settings(
            admin.SettingsUpdate(llm_model="deepseek-r1:1.5b"), _user("boss", is_admin=True)))
        content = env_file.read_text(encoding="utf-8")
        assert "LLM_MODEL=deepseek-r1:1.5b\n" in content
        assert "FEISHU_APP_ID=x" in content  # 其他键不受影响

    def test_append_missing_key(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("FEISHU_APP_ID=x\n", encoding="utf-8")
        monkeypatch.setattr(admin, "_ENV_FILE", str(env_file))
        monkeypatch.setattr(admin.settings, "LLM_MODEL_WHITELIST", "MiniMax-Text-01")
        asyncio_run(admin.update_admin_settings(
            admin.SettingsUpdate(llm_model="MiniMax-Text-01"), _user("boss", is_admin=True)))
        content = env_file.read_text(encoding="utf-8")
        # 写入的键取决于当前 provider（openai → OPENAI_LLM_MODEL，ollama → LLM_MODEL）
        target_key = "OPENAI_LLM_MODEL" if admin.settings.LLM_PROVIDER == "openai" else "LLM_MODEL"
        assert f"{target_key}=MiniMax-Text-01\n" in content
        assert "FEISHU_APP_ID=x" in content  # 其他键不受影响


class TestAdminLogs:
    """用假数据库验证查询过滤与统计聚合逻辑"""

    def _conv(self, cid, username, updated_at, open_id=None):
        return SimpleNamespace(
            id=cid, title=f"对话{cid}", username=username,
            open_id=open_id, created_at=updated_at, updated_at=updated_at,
        )

    async def test_logs_pagination_and_stats(self, monkeypatch):
        convs = [self._conv(1, "alice", datetime(2026, 8, 1, 10, 0, 0))]
        rows = [(c, c.username, "最近回答内容") for c in convs]
        stats = [(1, 3, 120, 2)]  # conv_id, msg_count, total_tokens, tool_count

        fake_db = _FakeDB(total=1, rows=rows, stats=stats)
        resp = await admin.admin_logs(db=fake_db, admin=_user("boss", is_admin=True))
        assert resp.total == 1
        item = resp.items[0]
        assert item.username == "alice"
        assert item.message_count == 3
        assert item.total_tokens == 120
        assert item.tool_call_count == 2
        assert item.last_answer == "最近回答内容"
        assert item.source == "web"

    async def test_im_conversation_source(self, monkeypatch):
        convs = [self._conv(2, "fs_x", datetime(2026, 8, 2, 9, 0, 0), open_id="ou_abc")]
        rows = [(c, c.username, None) for c in convs]
        fake_db = _FakeDB(total=1, rows=rows, stats=[])
        resp = await admin.admin_logs(db=fake_db, admin=_user("boss", is_admin=True))
        assert resp.items[0].source == "im"
        assert resp.items[0].open_id == "ou_abc"


class TestAdminBindings:
    """飞书知识库绑定管理（Phase 5.5）：列表 / upsert / 删除"""

    def _binding(self, bid=1, open_id="ou_a", chat_id=None, kb_id=5):
        return SimpleNamespace(
            id=bid, open_id=open_id, chat_id=chat_id, kb_id=kb_id,
            created_at=datetime(2026, 8, 10, 9, 0, 0),
            updated_at=datetime(2026, 8, 10, 9, 0, 0),
        )

    def _kb(self, kid=5, name="员工手册", document_count=4):
        return SimpleNamespace(id=kid, name=name, document_count=document_count)

    def test_scope_label(self):
        assert admin._binding_scope_label(None, "oc_b") == "群 oc_b"
        assert admin._binding_scope_label("ou_a", None) == "用户 ou_a"
        assert admin._binding_scope_label("ou_a", "oc_b") == "单聊 ou_a + 群 oc_b"

    async def test_list_bindings_joins_kb_name(self):
        binding, kb = self._binding(), self._kb()

        class _DB:
            def __init__(self):
                self.calls = 0

            async def execute(self, stmt):
                self.calls += 1
                if self.calls == 1:
                    return _FakeResult([binding])
                return _FakeResult([kb])

        resp = await admin.list_admin_bindings(db=_DB(), admin=_user("boss", is_admin=True))
        item = resp[0]
        assert item["scope_label"] == "用户 ou_a"
        assert item["kb_name"] == "员工手册"
        assert item["document_count"] == 4

    async def test_create_binding_ok(self, monkeypatch):
        mock_set = AsyncMock(return_value="用户 ou_a")
        monkeypatch.setattr(admin, "set_binding", mock_set)
        kb, binding = self._kb(), self._binding()

        class _DB:
            def __init__(self):
                self.results = [kb, binding]

            async def execute(self, stmt):
                return _FakeResult([self.results.pop(0)])

        db = _DB()
        resp = await admin.create_admin_binding(
            admin.BindingCreate(open_id="ou_a", kb_id=5),
            db=db,
            admin=_user("boss", is_admin=True),
        )
        assert resp["kb_name"] == "员工手册"
        assert resp["scope_label"] == "用户 ou_a"
        mock_set.assert_awaited_once_with(db, "ou_a", None, 5)

    async def test_create_binding_requires_scope(self):
        with pytest.raises(HTTPException) as exc:
            await admin.create_admin_binding(
                admin.BindingCreate(kb_id=5), db=AsyncMock(), admin=_user("boss", is_admin=True))
        assert exc.value.status_code == 400

    async def test_create_binding_kb_not_found(self):
        class _DB:
            async def execute(self, stmt):
                return _FakeResult([])

        with pytest.raises(HTTPException) as exc:
            await admin.create_admin_binding(
                admin.BindingCreate(chat_id="oc_b", kb_id=999),
                db=_DB(),
                admin=_user("boss", is_admin=True),
            )
        assert exc.value.status_code == 404

    async def test_delete_binding(self):
        binding = self._binding()

        class _DB:
            def __init__(self):
                self.deleted = []
                self.committed = 0

            async def execute(self, stmt):
                return _FakeResult([binding])

            async def delete(self, obj):
                self.deleted.append(obj)

            async def commit(self):
                self.committed += 1

        db = _DB()
        resp = await admin.delete_admin_binding(1, db=db, admin=_user("boss", is_admin=True))
        assert "已解除" in resp["message"]
        assert len(db.deleted) == 1 and db.committed == 1

    async def test_delete_missing_binding_404(self):
        class _DB:
            async def execute(self, stmt):
                return _FakeResult([])

        with pytest.raises(HTTPException) as exc:
            await admin.delete_admin_binding(99, db=_DB(), admin=_user("boss", is_admin=True))
        assert exc.value.status_code == 404


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar(self):
        return self._rows[0] if isinstance(self._rows, (list, tuple)) and self._rows else 0

    def scalar_one_or_none(self):
        if isinstance(self._rows, (list, tuple)) and self._rows:
            return self._rows[0]
        return None

    def scalar_one(self):
        return self._rows[0] if isinstance(self._rows, (list, tuple)) else self._rows

    def scalars(self):
        return SimpleNamespace(all=lambda: [r for r in self._rows])

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    """按调用顺序返回预设结果的假 AsyncSession"""

    def __init__(self, total, rows, stats):
        self._total = total
        self._rows = rows
        self._stats = stats
        self._exec_calls = 0

    async def execute(self, stmt):
        self._exec_calls += 1
        if self._exec_calls == 1:
            return _FakeResult([self._total])
        if self._exec_calls == 2:
            return _FakeResult(self._rows)
        return _FakeResult(self._stats)

    async def get(self, model, pk):
        return None


def asyncio_run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)
