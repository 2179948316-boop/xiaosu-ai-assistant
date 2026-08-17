"""Agent 编排服务单元测试（Mock LLM，覆盖工具调用/降级/超轮数场景）"""
import json
import sys
import os
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _skip_agent_stream():
    """自动跳过 agent 真流式（不 Mock 的话会真实调用 LLM），回退分块输出。"""
    from app.services import agent_service
    agent_service._AGENT_SKIP_STREAM = True
    yield
    agent_service._AGENT_SKIP_STREAM = False


async def _collect_events(db, question="张伟今天考勤怎么样？"):
    """运行 agent_chat_stream 并收集解析后的事件列表"""
    from app.services.agent_service import agent_chat_stream
    events = []
    async for event in agent_chat_stream(db, 1, 1, question):
        events.append(json.loads(event[len("data: "):]))
    return events


class TestAgentDirectAnswer:
    """无工具调用：模型直接回答"""

    @pytest.mark.asyncio
    async def test_direct_answer(self):
        """不调用工具时直接输出最终回答，不产生 tools 事件"""
        from app.services import agent_service
        db = AsyncMock()

        async def fake_chat_with_tools(messages, tools=None, model=None):
            return {"content": "你好，我是小苏。", "tool_calls": []}

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools):
            events = await _collect_events(db, "你好")

        types = [e["type"] for e in events]
        assert types == ["chunk", "done"]
        # 内容完整（分块拼接还原）
        full = "".join(e["content"] for e in events if e["type"] == "chunk")
        assert full == "你好，我是小苏。"
        assert events[-1]["content"] == "你好，我是小苏。"
        # 消息入库（无工具轨迹）
        saved = db.add.call_args[0][0]
        assert saved.role == "assistant"
        assert saved.content == "你好，我是小苏。"
        assert saved.tool_calls is None
        assert saved.sources is None


class TestAgentToolCall:
    """工具调用循环"""

    @pytest.mark.asyncio
    async def test_single_tool_round(self):
        """一轮工具调用后产出最终回答：先 tools 事件，后 chunk/done"""
        from app.services import agent_service
        db = AsyncMock()
        calls = {"n": 0}

        async def fake_chat_with_tools(messages, tools=None, model=None):
            if calls["n"] == 0:
                calls["n"] += 1
                return {
                    "content": "",
                    "tool_calls": [{"id": "call_0", "name": "get_current_time", "arguments": {}}],
                }
            return {"content": "现在是 2026-08-15 10:00:00。", "tool_calls": []}

        async def fake_execute_tool(name, arguments, kb_id):
            return '{"current_time": "2026-08-15 10:00:00", "timezone": "Asia/Shanghai"}'

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools), \
             patch.object(agent_service, "execute_tool", new=fake_execute_tool):
            events = await _collect_events(db, "现在几点了？")

        types = [e["type"] for e in events]
        # 工具调用在前，最终回答分块输出（可能多个 chunk），done 收尾
        assert types[0] == "tools"
        assert types[-1] == "done"
        assert set(types) == {"tools", "chunk", "done"}
        assert events[0]["tool"]["name"] == "get_current_time"
        full = "".join(e["content"] for e in events if e["type"] == "chunk")
        assert "2026-08-15" in full
        # 消息入库：工具轨迹记录
        saved = db.add.call_args[0][0]
        assert saved.tool_calls is not None
        assert saved.tool_calls[0]["name"] == "get_current_time"
        assert saved.tool_calls[0]["result"]["current_time"] == "2026-08-15 10:00:00"

    @pytest.mark.asyncio
    async def test_multi_tool_same_round(self):
        """同一轮多个 tool_calls 逐个执行并按序发送 tools 事件"""
        from app.services import agent_service
        db = AsyncMock()
        calls = {"n": 0}

        async def fake_chat_with_tools(messages, tools=None, model=None):
            if calls["n"] == 0:
                calls["n"] += 1
                return {
                    "content": "",
                    "tool_calls": [
                        {"id": "call_0", "name": "get_employee_info", "arguments": {"emp_id": 1001}},
                        {"id": "call_1", "name": "get_attendance", "arguments": {"emp_id": 1001}},
                    ],
                }
            return {"content": "张伟在技术部。", "tool_calls": []}

        async def fake_execute_tool(name, arguments, kb_id):
            if name == "get_employee_info":
                return '{"emp_id": 1001, "name": "张伟", "department": "技术部"}'
            return '{"total": 1, "records": []}'

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools), \
             patch.object(agent_service, "execute_tool", new=fake_execute_tool):
            events = await _collect_events(db)

        tools = [e["tool"]["name"] for e in events if e["type"] == "tools"]
        assert tools == ["get_employee_info", "get_attendance"]
        # 工具消息已回填（2 条 role=tool 追加到 messages）
        saved = db.add.call_args[0][0]
        assert len(saved.tool_calls) == 2

    @pytest.mark.asyncio
    async def test_search_kb_sources_saved(self):
        """search_kb 命中时：sources 事件 + Message.sources 入库"""
        from app.services import agent_service
        db = AsyncMock()
        calls = {"n": 0}

        async def fake_chat_with_tools(messages, tools=None, model=None):
            if calls["n"] == 0:
                calls["n"] += 1
                return {
                    "content": "",
                    "tool_calls": [{"id": "call_0", "name": "search_kb", "arguments": {"query": "请假制度"}}],
                }
            return {"content": "根据知识库，请假需提前一天申请。", "tool_calls": []}

        async def fake_execute_tool(name, arguments, kb_id):
            return json.dumps({
                "found": True,
                "top1_score": 0.92,
                "sources": [{
                    "filename": "考勤制度.md",
                    "chunk_index": 3,
                    "chunk_id": "doc1_chunk3",
                    "score": 0.92,
                    "text": "请假需提前一天向直属上级申请，并填写请假单……",
                }],
            }, ensure_ascii=False)

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools), \
             patch.object(agent_service, "execute_tool", new=fake_execute_tool):
            events = await _collect_events(db)

        types = [e["type"] for e in events]
        assert "sources" in types
        sources_event = next(e for e in events if e["type"] == "sources")
        assert sources_event["sources"][0]["filename"] == "考勤制度.md"
        assert sources_event["sources"][0]["text_preview"].startswith("请假需提前一天")
        saved = db.add.call_args[0][0]
        assert saved.sources is not None
        assert saved.sources[0]["chunk_id"] == "doc1_chunk3"


class TestAgentDegradation:
    """降级兜底"""

    @pytest.mark.asyncio
    async def test_llm_error_retry_success(self):
        """LLM 首次异常 → 重试成功 → 正常回答"""
        from app.services import agent_service
        db = AsyncMock()
        call_n = {"n": 0}

        async def fake_chat_with_tools(messages, tools=None, model=None):
            call_n["n"] += 1
            if call_n["n"] == 1:
                raise TimeoutError("LLM timeout")
            return {"content": "重试成功。", "tool_calls": []}

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools):
            events = await _collect_events(db)

        assert call_n["n"] == 2
        types = [e["type"] for e in events]
        assert types == ["chunk", "done"]

    @pytest.mark.asyncio
    async def test_llm_error_retry_failed(self):
        """LLM 两次异常 → error 事件，不再继续"""
        from app.services import agent_service
        db = AsyncMock()

        async def fake_chat_with_tools(messages, tools=None, model=None):
            raise TimeoutError("LLM timeout")

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools):
            events = await _collect_events(db)

        assert events == [{"type": "error", "content": "系统暂时无法查询，请稍后再试。"}]
        # 不保存任何消息
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_rounds_fallback(self):
        """模型一直返回 tool_calls → 循环超 AGENT_MAX_ROUNDS 轮 → 兜底文案"""
        from app.services import agent_service
        db = AsyncMock()

        async def fake_chat_with_tools(messages, tools=None, model=None):
            return {
                "content": "",
                "tool_calls": [{"id": "call_0", "name": "get_current_time", "arguments": {}}],
            }

        async def fake_execute_tool(name, arguments, kb_id):
            return '{"current_time": "2026-08-15 10:00:00"}'

        max_rounds = 5
        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools), \
             patch.object(agent_service, "execute_tool", new=fake_execute_tool), \
             patch.object(agent_service.settings, "AGENT_MAX_ROUNDS", max_rounds):
            events = await _collect_events(db)

        # 每轮 1 个 tools 事件 + chunk + done
        tool_events = [e for e in events if e["type"] == "tools"]
        assert len(tool_events) == max_rounds
        full = "".join(e["content"] for e in events if e["type"] == "chunk")
        assert "多次" in full

    @pytest.mark.asyncio
    async def test_tool_execution_error_fallback_to_model(self):
        """工具执行异常 → 错误信息回填给模型（不中断循环），模型可正常收尾"""
        from app.services import agent_service
        db = AsyncMock()
        calls = {"n": 0}

        async def fake_chat_with_tools(messages, tools=None, model=None):
            if calls["n"] == 0:
                calls["n"] += 1
                return {
                    "content": "",
                    "tool_calls": [{"id": "call_0", "name": "get_employee_info", "arguments": {"emp_id": 9999}}],
                }
            return {"content": "抱歉，查不到该员工。", "tool_calls": []}

        async def fake_execute_tool(name, arguments, kb_id):
            raise ConnectionError("mock api down")

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools), \
             patch.object(agent_service, "execute_tool", new=fake_execute_tool):
            events = await _collect_events(db)

        types = [e["type"] for e in events]
        assert types[0] == "tools"
        assert types[-1] == "done"
        assert set(types) == {"tools", "chunk", "done"}
        saved = db.add.call_args[0][0]
        # 工具轨迹记录 result 为错误信息
        assert "error" in saved.tool_calls[0]["result"]


class TestToolExecutors:
    """真实工具执行器（无需网络的部分）"""

    @pytest.mark.asyncio
    async def test_get_current_time(self):
        from app.services.agent_tools import execute_tool
        result = await execute_tool("get_current_time", {}, 1)
        data = json.loads(result)
        assert "current_time" in data
        assert data["timezone"] == "Asia/Shanghai"

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        from app.services.agent_tools import execute_tool
        result = await execute_tool("not_exist", {}, 1)
        assert "未知工具" in result

    @pytest.mark.asyncio
    async def test_search_kb_missing_query(self):
        from app.services.agent_tools import execute_tool
        result = await execute_tool("search_kb", {}, 1)
        assert "缺少 query" in result


class TestAgentMultiTurnHistory:
    """多轮记忆：agent_chat_stream 应将历史回填给 LLM（排除刚保存的当前问题）"""

    @pytest.mark.asyncio
    async def test_history_injected_before_user_question(self):
        from app.services import agent_service

        class _Msg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        class _FakeScalars:
            def scalars(self):
                return self

            def all(self):
                # 模拟 _get_recent_history 的 DESC 查询结果（最新在前），内部 reverse() 后恢复时间序
                return [
                    _Msg("assistant", "你好小明，有什么可以帮你？"),
                    _Msg("user", "我叫小明"),
                ]

        db = AsyncMock()
        db.execute.return_value = _FakeScalars()
        captured = {}

        async def fake_chat_with_tools(messages, tools=None, model=None):
            captured["messages"] = [dict(m) for m in messages]
            return {"content": "在的，小明。", "tool_calls": []}

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools):
            events = await _collect_events(db, "还记得我叫什么吗？")

        roles = [m["role"] for m in captured["messages"]]
        # 首条 system，随后注入历史（user+assistant），当前问题在最后
        assert roles == ["system", "user", "assistant", "user"]
        assert captured["messages"][1]["content"] == "我叫小明"
        assert captured["messages"][2]["content"] == "你好小明，有什么可以帮你？"
        assert captured["messages"][3]["content"] == "还记得我叫什么吗？"
        # 最终回答正常产出
        full = "".join(e["content"] for e in events if e["type"] == "chunk")
        assert full == "在的，小明。"

    @pytest.mark.asyncio
    async def test_history_query_failure_falls_back_to_empty(self):
        """历史查询异常时降级为空历史，不阻断问答（同时覆盖 AsyncMock db 场景）"""
        from app.services import agent_service
        db = AsyncMock()
        # execute 返回不可迭代的 AsyncMock → list() 抛错 → 应降级为空历史
        db.execute.return_value = AsyncMock()

        async def fake_chat_with_tools(messages, tools=None, model=None):
            return {"content": "你好。", "tool_calls": []}

        with patch.object(agent_service, "chat_with_tools", new=fake_chat_with_tools):
            events = await _collect_events(db, "你好")

        full = "".join(e["content"] for e in events if e["type"] == "chunk")
        assert full == "你好。"
