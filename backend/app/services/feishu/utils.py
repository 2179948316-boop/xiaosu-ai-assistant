"""飞书机器人工具函数 - 幂等防重放、消息解析、回复构造、Agent 结果收集"""
import json
import logging
from typing import Dict, List, Optional, Tuple

from app.config import get_settings
from app.services.cache_service import _get_redis
from app.services.agent_service import agent_chat_stream

settings = get_settings()
logger = logging.getLogger(__name__)

# Redis 不可用时的内存幂等兜底（进程内，重启即清空，可接受）
_MEM_SEEN: set = set()
_MEM_SEEN_CAP = 5000

FALLBACK_TEXT = "抱歉，小苏暂时开小差了，请稍后再试。"


# ============ 幂等防重放 ============

async def is_duplicate(message_id: str) -> bool:
    """按 message_id 判断是否重复事件（飞书可能重放）。首次出现返回 False 并记录。"""
    if not message_id:
        return False
    key = f"bot_msg_seen:{message_id}"
    redis = await _get_redis()
    if redis is not None:
        try:
            ok = await redis.set(key, "1", nx=True, ex=settings.BOT_IDEMPOTENCY_TTL)
            return not bool(ok)
        except Exception as e:
            logger.warning(f"幂等 Redis 写入失败，降级内存去重: {e}")
    # 内存兜底
    if message_id in _MEM_SEEN:
        return True
    if len(_MEM_SEEN) >= _MEM_SEEN_CAP:
        _MEM_SEEN.clear()
    _MEM_SEEN.add(message_id)
    return False


# ============ 消息解析 ============

def extract_question(content: str, mentions: Optional[List] = None) -> str:
    """从飞书 text 消息内容提取纯问题文本（去掉 @机器人 占位符）。"""
    try:
        text = json.loads(content).get("text", "")
    except (json.JSONDecodeError, TypeError):
        text = content or ""
    if mentions:
        for m in mentions:
            key = getattr(m, "key", None)
            if key:
                text = text.replace(key, "")
    return text.strip()


def bot_mentioned(mentions: Optional[List], bot_open_id: Optional[str]) -> bool:
    """群聊中判断是否 @ 了机器人（单聊恒为 True）。"""
    if not mentions:
        return False
    for m in mentions:
        mid = getattr(m, "id", None)
        if bot_open_id and mid and (mid == bot_open_id or bot_open_id in str(mid)):
            return True
    return bot_open_id is None


# ============ Agent 调用与回复构造 ============

def _parse_sse(event: str) -> Optional[Dict]:
    """解析 agent_chat_stream 产出的 'data: {...}' 事件。"""
    if not event.startswith("data: "):
        return None
    try:
        return json.loads(event[len("data: "):])
    except json.JSONDecodeError:
        return None


async def run_agent_and_collect(
    db,
    conversation_id: int,
    kb_id: int,
    question: str,
) -> Tuple[str, List[Dict]]:
    """消费 agent_chat_stream，收集最终回答与引用来源（忽略中间 chunk/tools）。"""
    final_content = ""
    sources: List[Dict] = []
    async for event in agent_chat_stream(db, conversation_id, kb_id, question):
        data = _parse_sse(event)
        if not data:
            continue
        etype = data.get("type")
        if etype == "done":
            final_content = data.get("content", "")
        elif etype == "sources":
            sources = data.get("sources", [])
        elif etype == "error":
            final_content = data.get("content", FALLBACK_TEXT)
    return final_content, sources


def build_text_reply(content: str) -> Tuple[str, str]:
    """纯文本回复（无引用来源）。返回 (msg_type, content_json)。"""
    return "text", json.dumps({"text": content}, ensure_ascii=False)


def build_post_reply(content: str, sources: List[Dict]) -> Tuple[str, str]:
    """post 富文本回复：正文 + 参考来源（文件名/片段/相关度）。返回 (msg_type, content_json)。"""
    paragraphs: List[List[Dict]] = []
    for line in (content or "").split("\n"):
        paragraphs.append([{"tag": "text", "text": line}])
    if sources:
        paragraphs.append([{"tag": "text", "text": "——————————"}])
        paragraphs.append([{"tag": "text", "text": "📎 参考来源"}])
        for s in sources[:3]:
            score = s.get("score", 0)
            try:
                score_pct = f"{float(score) * 100:.0f}%"
            except (TypeError, ValueError):
                score_pct = "-"
            paragraphs.append([
                {"tag": "text", "text": f"· {s.get('filename', '未知')}（相关度 {score_pct}）"},
            ])
            preview = (s.get("text_preview") or "").strip()
            if preview:
                paragraphs.append([{"tag": "text", "text": f"    {preview[:100]}"}])
    post = {"zh_cn": {"title": "小苏", "content": paragraphs}}
    return "post", json.dumps(post, ensure_ascii=False)