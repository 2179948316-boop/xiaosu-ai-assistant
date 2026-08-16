"""飞书机器人服务单元测试（离线：不依赖真实飞书连接 / 数据库 / LLM）

覆盖：消息解析（去 @）、回复构造（text/post 富文本）、幂等去重、
SSE 事件解析、Agent 结果收集、知识库绑定指令解析与检索优先级。
"""
import json
import sys
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import feishu_bot  # noqa: E402


class _FakeMention:
    def __init__(self, key, name="小苏", mid=None):
        self.key = key
        self.name = name
        self.id = mid


class TestExtractQuestion:
    def test_strips_bot_mention(self):
        content = json.dumps({"text": "@_user_1 今天考勤怎么样"}, ensure_ascii=False)
        mentions = [_FakeMention("@_user_1")]
        assert feishu_bot.extract_question(content, mentions) == "今天考勤怎么样"

    def test_plain_p2p_no_mentions(self):
        content = json.dumps({"text": "帮我查下订单"}, ensure_ascii=False)
        assert feishu_bot.extract_question(content, None) == "帮我查下订单"

    def test_multiple_mentions(self):
        content = json.dumps({"text": "@_user_1 @_user_2 谁迟到了"}, ensure_ascii=False)
        mentions = [_FakeMention("@_user_1"), _FakeMention("@_user_2")]
        assert feishu_bot.extract_question(content, mentions) == "谁迟到了"

    def test_invalid_json_returns_raw(self):
        assert feishu_bot.extract_question("纯文本问题", None) == "纯文本问题"

    def test_empty_text(self):
        content = json.dumps({"text": "@_user_1"}, ensure_ascii=False)
        assert feishu_bot.extract_question(content, [_FakeMention("@_user_1")]) == ""


class TestBuildReply:
    def test_text_reply(self):
        msg_type, content = feishu_bot.build_text_reply("你好")
        assert msg_type == "text"
        assert json.loads(content) == {"text": "你好"}

    def test_post_reply_with_sources(self):
        sources = [{
            "filename": "考勤制度.md",
            "score": 0.92,
            "text_preview": "请假需提前一天申请……",
        }]
        msg_type, content = feishu_bot.build_post_reply("答案正文", sources)
        assert msg_type == "post"
        post = json.loads(content)
        assert "zh_cn" in post
        paragraphs = post["zh_cn"]["content"]
        # 首段是答案正文
        assert paragraphs[0][0]["text"] == "答案正文"
        # 包含来源文件名与相关度百分比
        flat = json.dumps(post, ensure_ascii=False)
        assert "考勤制度.md" in flat
        assert "92%" in flat
        assert "请假需提前一天申请" in flat

    def test_post_reply_multiline_answer(self):
        msg_type, content = feishu_bot.build_post_reply("第一行\n第二行", [])
        post = json.loads(content)
        paragraphs = post["zh_cn"]["content"]
        # 多行答案被拆成多段
        assert paragraphs[0][0]["text"] == "第一行"
        assert paragraphs[1][0]["text"] == "第二行"

    def test_post_reply_caps_sources_at_3(self):
        sources = [
            {"filename": f"f{i}.md", "score": 0.5, "text_preview": "x"} for i in range(5)
        ]
        _, content = feishu_bot.build_post_reply("答案", sources)
        flat = content
        assert "f0.md" in flat and "f2.md" in flat
        assert "f3.md" not in flat  # 超过 3 条被截断


class TestParseSSE:
    def test_valid(self):
        data = feishu_bot._parse_sse('data: {"type": "done", "content": "hi"}')
        assert data == {"type": "done", "content": "hi"}

    def test_non_data_line(self):
        assert feishu_bot._parse_sse("event: message") is None

    def test_invalid_json(self):
        assert feishu_bot._parse_sse("data: {bad json") is None


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_memory_fallback_dedup(self):
        """Redis 不可用时用内存集合去重：首次 False，重复 True"""
        feishu_bot._MEM_SEEN.clear()
        with patch.object(feishu_bot, "_get_redis", new=AsyncMock(return_value=None)):
            assert await feishu_bot.is_duplicate("msg-A") is False
            assert await feishu_bot.is_duplicate("msg-A") is True
            assert await feishu_bot.is_duplicate("msg-B") is False
        feishu_bot._MEM_SEEN.clear()

    @pytest.mark.asyncio
    async def test_redis_setnx_dedup(self):
        """Redis SETNX：set 返回 True=首次（非重复），None=已存在（重复）"""
        mock_redis = AsyncMock()
        mock_redis.set.side_effect = [True, None]
        with patch.object(feishu_bot, "_get_redis", new=AsyncMock(return_value=mock_redis)):
            assert await feishu_bot.is_duplicate("msg-X") is False
            assert await feishu_bot.is_duplicate("msg-X") is True
        # 确认使用了 nx + ex 参数
        mock_redis.set.assert_called_with(
            "bot_msg_seen:msg-X", "1", nx=True, ex=feishu_bot.settings.BOT_IDEMPOTENCY_TTL
        )

    @pytest.mark.asyncio
    async def test_empty_message_id_not_dedup(self):
        assert await feishu_bot.is_duplicate("") is False


class TestRunAgentAndCollect:
    @pytest.mark.asyncio
    async def test_collects_done_and_sources(self):
        async def fake_stream(db, conversation_id, kb_id, question):
            yield 'data: {"type": "tools", "tool": {"name": "get_current_time"}}\n\n'
            yield 'data: {"type": "chunk", "content": "部分"}\n\n'
            yield 'data: {"type": "sources", "sources": [{"filename": "a.md", "score": 0.9}]}\n\n'
            yield 'data: {"type": "done", "content": "最终回答"}\n\n'

        with patch.object(feishu_bot, "agent_chat_stream", new=fake_stream):
            content, sources = await feishu_bot.run_agent_and_collect(
                AsyncMock(), 1, 1, "问题"
            )
        assert content == "最终回答"
        assert sources == [{"filename": "a.md", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_error_event_becomes_fallback(self):
        async def fake_stream(db, conversation_id, kb_id, question):
            yield 'data: {"type": "error", "content": "系统暂时无法查询"}\n\n'

        with patch.object(feishu_bot, "agent_chat_stream", new=fake_stream):
            content, sources = await feishu_bot.run_agent_and_collect(
                AsyncMock(), 1, 1, "问题"
            )
        assert content == "系统暂时无法查询"
        assert sources == []


class TestBotMentioned:
    def test_no_mentions(self):
        assert feishu_bot.bot_mentioned(None, "ou_bot") is False

    def test_matching_bot(self):
        assert feishu_bot.bot_mentioned([_FakeMention("@_user_1", mid="ou_bot")], "ou_bot") is True

    def test_other_user_mentioned(self):
        assert feishu_bot.bot_mentioned([_FakeMention("@_user_1", mid="ou_other")], "ou_bot") is False


class TestParseBindingCommand:
    """知识库绑定/查询指令识别（Phase 5.5）"""

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


class _SeqResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _SeqDB:
    """按调用顺序返回预置结果的假 AsyncSession（一次 execute 弹出一个结果）"""

    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, stmt):
        return _SeqResult(self._results.pop(0) if self._results else None)


class TestResolveKbId:
    """检索优先级：群绑定 > 个人绑定 > FEISHU_DEFAULT_KB_ID > 第一个知识库"""

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
        """绑定账号后：无显式绑定 → 回退该账号可见的最新知识库（不会误连别人的库）"""
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 0)
        monkeypatch.setattr(
            feishu_bot, "list_visible_kbs",
            AsyncMock(return_value=[SimpleNamespace(id=6), SimpleNamespace(id=3)]),
        )
        user = SimpleNamespace(id=9)
        db = _SeqDB(None)  # 1 次：open_id 绑定查询
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a", user=user) == 6

    @pytest.mark.asyncio
    async def test_user_no_kb_falls_to_global_first(self, monkeypatch):
        """账号下没有库 → 仍回退全局第一个知识库"""
        monkeypatch.setattr(feishu_bot.settings, "FEISHU_DEFAULT_KB_ID", 0)
        monkeypatch.setattr(feishu_bot, "list_visible_kbs", AsyncMock(return_value=[]))
        user = SimpleNamespace(id=9)
        db = _SeqDB(None, SimpleNamespace(id=7))  # open 检查 + 全局第一个
        assert await feishu_bot.resolve_kb_id(db, open_id="ou_a", user=user) == 7


class TestHandleBindingCommand:
    async def test_query_current_binding(self, monkeypatch):
        kb = SimpleNamespace(name="考勤库", document_count=4, user_id=1)

        class DB:
            async def execute(self, stmt):
                return _SeqResult(None)  # 未绑定账号

            async def get(self, model, pk):
                return kb

        monkeypatch.setattr(feishu_bot, "resolve_kb_id", AsyncMock(return_value=5))
        msg_type, content = await feishu_bot.handle_binding_command(DB(), "ou_a", "oc_b", "当前知识库")
        assert msg_type == "text"
        text = json.loads(content)["text"]
        assert "考勤库" in text and "ID=5" in text and "4 篇" in text

    async def test_bind_by_name(self, monkeypatch):
        kb = SimpleNamespace(id=5, name="员工手册", document_count=4)
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)  # 已绑定账号

        monkeypatch.setattr(feishu_bot, "_find_kbs_by_name", AsyncMock(return_value=[kb]))
        monkeypatch.setattr(feishu_bot, "set_binding", AsyncMock(return_value="群 oc_b"))
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：员工手册")
        text = json.loads(content)["text"]
        assert "员工手册" in text and "群 oc_b" in text

    async def test_bind_by_id(self, monkeypatch):
        kb = SimpleNamespace(id=5, name="员工手册", document_count=4)
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(feishu_bot, "_find_kb_by_id", AsyncMock(return_value=kb))
        monkeypatch.setattr(feishu_bot, "set_binding", AsyncMock(return_value="群 oc_b"))
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：5")
        assert "员工手册" in json.loads(content)["text"]

    async def test_bind_not_found(self, monkeypatch):
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(feishu_bot, "_find_kbs_by_name", AsyncMock(return_value=[]))
        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：不存在的库")
        assert "没找到" in json.loads(content)["text"]

    async def test_bind_requires_account_first(self):
        class DB:
            async def execute(self, stmt):
                return _SeqResult(None)  # 未绑定账号

        msg_type, content = await feishu_bot.handle_binding_command(
            DB(), "ou_a", "oc_b", "绑定知识库：员工手册")
        assert "绑定账号" in json.loads(content)["text"]

    async def test_bind_multiple_candidates(self, monkeypatch):
        user = SimpleNamespace(id=1, username="alice")

        class DB:
            async def execute(self, stmt):
                return _SeqResult(user)

        monkeypatch.setattr(
            feishu_bot, "_find_kbs_by_name",
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


class TestParseAccountCommand:
    """账号绑定指令识别（Phase 5.6）"""

    def test_bind_account(self):
        assert feishu_bot.parse_account_command("绑定账号：18806276625") == ("bind", "18806276625")

    def test_bind_account_no_separator(self):
        assert feishu_bot.parse_account_command("绑定账号18806276625") == ("bind", "18806276625")

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


def _account_user(username="alice", password="pw123456", feishu_open_id=None):
    return SimpleNamespace(
        id=1, username=username,
        password_hash=feishu_bot.hash_password(password),
        feishu_open_id=feishu_open_id, is_admin=False,
    )


class _AccountDB:
    """账号绑定测试用假 db：execute 按序弹结果 + 记录 commit"""

    def __init__(self, *results):
        self._results = list(results)
        self.commits = 0

    async def execute(self, stmt):
        return _SeqResult(self._results.pop(0) if self._results else None)

    async def commit(self):
        self.commits += 1


class TestHandleAccountCommand:
    """账号绑定全流程：发起 → 密码验证 → 绑定生效 / 失败清理 / 私聊限制"""

    def _clear_pending(self):
        feishu_bot._ACCOUNT_PENDING.clear()

    async def test_start_bind_p2p(self):
        self._clear_pending()
        db = _AccountDB(_account_user())
        msg_type, content = await feishu_bot.handle_account_command(
            db, "ou_a", "绑定账号：alice", "p2p")
        assert "即将把" in json.loads(content)["text"]
        assert "ou_a" in feishu_bot._ACCOUNT_PENDING  # 进入验证态
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
        """正确密码 → 绑定成功：feishu_open_id 写入 + commit"""
        self._clear_pending()
        user = _account_user()
        db = _AccountDB(user, None)  # 第二次 execute：旧关联查询 → 无
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", time.time())
        msg_type, content = await feishu_bot.handle_account_command(db, "ou_a", "pw123456", "p2p")
        assert "验证通过" in json.loads(content)["text"]
        assert user.feishu_open_id == "ou_a"
        assert db.commits == 1
        assert "ou_a" not in feishu_bot._ACCOUNT_PENDING  # 验证态已退出
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

    async def test_verify_cancel(self):
        self._clear_pending()
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", 0)
        msg_type, content = await feishu_bot.handle_account_command(
            AsyncMock(), "ou_a", "取消", "p2p")
        assert "已取消" in json.loads(content)["text"]
        assert "ou_a" not in feishu_bot._ACCOUNT_PENDING
        self._clear_pending()

    async def test_password_in_group_rejected(self):
        """验证态中群聊消息不会当成密码（密码不暴露到群里）"""
        self._clear_pending()
        feishu_bot._ACCOUNT_PENDING["ou_a"] = ("alice", 0)
        msg_type, content = await feishu_bot.handle_account_command(
            AsyncMock(), "ou_a", "pw123456", "group")
        assert "私聊" in json.loads(content)["text"]
        assert "ou_a" in feishu_bot._ACCOUNT_PENDING  # 验证态保留，可回私聊继续
        self._clear_pending()

    async def test_show_bound_account(self):
        db = _AccountDB(_account_user(feishu_open_id="ou_a"))
        msg_type, content = await feishu_bot.handle_account_command(
            db, "ou_a", "我的账号", "p2p")
        assert "alice" in json.loads(content)["text"]

    async def test_show_unbound_account(self):
        msg_type, content = await feishu_bot.handle_account_command(
            _AccountDB(None), "ou_a", "我的账号", "p2p")
        assert "未绑定" in json.loads(content)["text"]

    async def test_list_kbs(self, monkeypatch):
        monkeypatch.setattr(
            feishu_bot, "list_visible_kbs",
            AsyncMock(return_value=[
                SimpleNamespace(name="员工手册", id=5, document_count=4, org_id=None),
                SimpleNamespace(name="test", id=6, document_count=3, org_id=2),
            ]),
        )
        db = _AccountDB(_account_user(feishu_open_id="ou_a"))
        msg_type, content = await feishu_bot.handle_account_command(
            db, "ou_a", "我的知识库", "p2p")
        text = json.loads(content)["text"]
        assert "员工手册" in text and "ID=5" in text and "组织" in text

    async def test_unbind(self):
        user = _account_user(feishu_open_id="ou_a")
        db = _AccountDB(user)
        msg_type, content = await feishu_bot.handle_account_command(
            db, "ou_a", "解除绑定", "p2p")
        assert "已解除" in json.loads(content)["text"]
        assert user.feishu_open_id is None
        assert db.commits == 1

    async def test_normal_message_not_handled(self):
        self._clear_pending()
        assert await feishu_bot.handle_account_command(
            AsyncMock(), "ou_a", "今天考勤怎么样", "p2p") is None


class TestFindKbsByNameInScope:
    """账号可见范围内的名称匹配：精确优先，模糊候选截断"""

    async def test_exact_name_first(self, monkeypatch):
        monkeypatch.setattr(
            feishu_bot, "list_visible_kbs",
            AsyncMock(return_value=[
                SimpleNamespace(name="test", id=4),
                SimpleNamespace(name="test-kb", id=1),
            ]),
        )
        found = await feishu_bot._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "test")
        assert [kb.id for kb in found] == [4]

    async def test_fuzzy_match(self, monkeypatch):
        monkeypatch.setattr(
            feishu_bot, "list_visible_kbs",
            AsyncMock(return_value=[
                SimpleNamespace(name="考勤制度", id=1),
                SimpleNamespace(name="考勤手册", id=2),
                SimpleNamespace(name="薪酬制度", id=3),
            ]),
        )
        found = await feishu_bot._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "考勤")
        assert [kb.id for kb in found] == [1, 2]

    async def test_no_match(self, monkeypatch):
        monkeypatch.setattr(feishu_bot, "list_visible_kbs", AsyncMock(return_value=[]))
        found = await feishu_bot._find_kbs_by_name(
            AsyncMock(), SimpleNamespace(id=1), "不存在")
        assert found == []

    async def test_fuzzy_capped_at_5(self, monkeypatch):
        monkeypatch.setattr(
            feishu_bot, "list_visible_kbs",
            AsyncMock(return_value=[SimpleNamespace(name=f"x{i}", id=i) for i in range(8)]),
        )
        found = await feishu_bot._find_kbs_by_name(AsyncMock(), SimpleNamespace(id=1), "x")
        assert len(found) == 5
