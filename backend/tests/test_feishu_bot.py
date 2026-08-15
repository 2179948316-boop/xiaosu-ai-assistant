"""飞书机器人服务单元测试（离线：不依赖真实飞书连接 / 数据库 / LLM）

覆盖：消息解析（去 @）、回复构造（text/post 富文本）、幂等去重、
SSE 事件解析、Agent 结果收集。
"""
import json
import sys
import os
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
