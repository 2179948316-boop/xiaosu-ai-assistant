"""Agent 编排服务 - 工具调用循环 + 最终流式回答

流程：
  1. 工具阶段（非流式）：LLM(带工具) → 解析 tool_calls → 执行工具 → 结果回填
     再调 LLM，循环最多 AGENT_MAX_ROUNDS 轮（模型自主决定何时停止）
  2. 模型产出最终文本后，分块输出模拟流式（保证与最终内容一致，
     避免二次生成造成内容漂移；工具阶段必须非流式以保证 tool_calls 解析可靠）
  3. 工具调用轨迹保存到 Message.tool_calls，search_kb 引用来源保存到 Message.sources
  4. 兜底：LLM 调用失败重试 1 次；循环超轮数给出兜底文案
"""
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Message
from app.services.agent_tools import TOOL_SCHEMAS, execute_tool
from app.services.llm_service import chat_with_tools

settings = get_settings()
logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """你是公司内部 AI 助手"小苏"，可以调用工具查询真实数据来回答用户问题。

可用工具：
- get_employee_info: 员工信息（部门/级别/薪资/入职日期）
- get_attendance: 考勤记录（status: normal=正常, late=迟到, leave=请假, absent=缺勤；overtime_hours>0 表示加班）
- get_orders: 订单记录（status: paid=已支付, refunded=已退款）
- get_current_time: 当前日期时间（北京时间）
- search_kb: 检索公司知识库文档

规则：
1. 先判断问题类型再选工具；员工/考勤/订单/时间类问题用对应工具，不要用 search_kb 代替
2. 用户提到"今天/现在/上周/最近/本月"等相对时间时，必须先调用 get_current_time
   确认当前日期，再据此推算具体日期范围；禁止凭空猜测日期
3. 员工编号从用户描述或知识库中获取；无法确定时请用户补充编号
4. search_kb 返回的 top1_score 是相关度（0-1）。若 found=False 或 top1_score < 0.35，
   说明知识库没有相关内容，请明确告知用户"根据现有知识库未找到相关信息"，不要编造
5. 只能基于工具返回的数据回答，不得编造；涉及统计时基于数据自行计算并给出结论
6. 回答使用中文，简洁清晰，必要时给出关键数字和日期"""


def _sse_event(data: dict) -> str:
    """构造 SSE 格式事件数据"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _to_source_info(s: Dict) -> Dict:
    """search_kb 来源 → 前端 sources 事件 / Message.sources 结构"""
    return {
        "filename": s.get("filename", "未知"),
        "chunk_id": s.get("chunk_id", ""),
        "chunk_index": s.get("chunk_index", 0),
        "score": s.get("score", 0),
        "text_preview": (s.get("text", "") or "")[:150],
        "retrieval_method": "agent_search_kb",
    }


async def _save_assistant_message(
    db: AsyncSession,
    conversation_id: int,
    content: str,
    tool_trace: List[Dict],
    kbs_sources: List[Dict],
    token_count: Optional[int] = None,
) -> None:
    """保存助手消息（含工具轨迹、引用来源与 token 用量），失败不影响响应"""
    try:
        db.add(Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            tool_calls=tool_trace if tool_trace else None,
            sources=[_to_source_info(s) for s in kbs_sources] if kbs_sources else None,
            token_count=token_count if token_count else None,
        ))
        await db.commit()
        logger.info(
            f"Agent 回复已保存 (conversation_id={conversation_id}, "
            f"tools={len(tool_trace)}, sources={len(kbs_sources)}, tokens={token_count})"
        )
    except Exception as save_err:
        logger.error(f"保存 Agent 助手消息失败: {save_err}")


async def agent_chat_stream(
    db: AsyncSession,
    conversation_id: int,
    kb_id: int,
    user_question: str,
) -> AsyncGenerator[str, None]:
    """Agent 工具调用 + 最终流式回答的完整流程"""
    messages: List[Dict] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_question},
    ]
    tool_trace: List[Dict] = []   # 工具调用轨迹（入库 + 前端展示）
    kbs_sources: List[Dict] = []  # search_kb 命中的引用来源

    # ============ 工具阶段（非流式循环） ============
    final_content = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    for round_idx in range(settings.AGENT_MAX_ROUNDS):
        resp = None
        try:
            resp = await chat_with_tools(messages, tools=TOOL_SCHEMAS)
        except Exception as e:
            # 兜底 1：LLM 调用异常，重试 1 次
            logger.error(f"Agent 第 {round_idx + 1} 轮 LLM 调用失败: {e}")
            try:
                resp = await chat_with_tools(messages, tools=TOOL_SCHEMAS)
            except Exception as retry_err:
                logger.error(f"Agent LLM 重试仍失败: {retry_err}")
                yield _sse_event({"type": "error", "content": "系统暂时无法查询，请稍后再试。"})
                return

        # 累计 token 用量（管理后台统计；Ollama/OpenAI 模式均已归一为 usage 字段）
        usage = resp.get("usage") or {}
        total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
        total_completion_tokens += int(usage.get("completion_tokens") or 0)

        tool_calls = resp.get("tool_calls") or []
        if not tool_calls:
            final_content = resp.get("content") or ""
            break

        # 回填 assistant 的 tool_calls 消息（含原始参数），供后续轮次继续
        messages.append({
            "role": "assistant",
            "content": resp.get("content") or "",
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        })

        # 逐个执行工具并回填结果
        for tc in tool_calls:
            try:
                result = await execute_tool(tc["name"], tc["arguments"], kb_id)
            except Exception as exec_err:
                # 兜底 2：工具执行异常 → 错误信息回填给模型，由模型决定重试或说明
                logger.error(f"工具执行异常 {tc['name']}: {exec_err}")
                result = json.dumps({"error": f"工具执行异常: {exec_err}"}, ensure_ascii=False)

            trace_entry: Dict = {"name": tc["name"], "arguments": tc["arguments"]}
            try:
                result_data = json.loads(result)
                if tc["name"] == "search_kb" and result_data.get("found"):
                    kbs_sources.extend(result_data.get("sources", []))
                trace_entry["result"] = result_data
            except (json.JSONDecodeError, TypeError):
                trace_entry["result"] = result
            tool_trace.append(trace_entry)

            # SSE 推送工具调用轨迹（前端显示工具指示器）
            yield _sse_event({
                "type": "tools",
                "tool": {"name": tc["name"], "arguments": tc["arguments"]},
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
    else:
        # 兜底 3：循环超轮数
        final_content = "我尝试了多次仍未能完成这个查询，可能系统暂时不可用，请稍后再试。"

    final_content = final_content or "抱歉，我没有理解你的问题，请换个方式描述。"

    # 保存消息（工具轨迹 + 引用来源 + token 用量）
    total_tokens = total_prompt_tokens + total_completion_tokens
    await _save_assistant_message(
        db, conversation_id, final_content, tool_trace, kbs_sources,
        token_count=total_tokens or None,
    )

    # ============ 最终回答阶段（分块输出，模拟流式） ============
    if kbs_sources:
        yield _sse_event({
            "type": "sources",
            "sources": [_to_source_info(s) for s in kbs_sources],
        })

    chunk_size = 8
    for i in range(0, len(final_content), chunk_size):
        yield _sse_event({"type": "chunk", "content": final_content[i:i + chunk_size]})

    yield _sse_event({"type": "done", "content": final_content})
