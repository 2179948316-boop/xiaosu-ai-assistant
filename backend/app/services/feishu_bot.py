"""飞书机器人服务 - 消息接收 → Agent 编排 → 富文本回复

职责（Phase 4）：
  - 会话隔离：按 (open_id, chat_id) 维护独立 Conversation，A 的上下文不泄漏给 B
  - 幂等防重放：按 message_id 去重（Redis SETNX，降级内存集合）
  - 复用 agent_chat_stream 管线：消费 SSE 事件，取最终回答 + 引用来源
  - 回复格式：无来源用 text，有来源用 post 富文本（文件名 + 片段 + 相关度）

注意：本模块只包含与飞书 SDK 解耦的业务逻辑，lark-oapi 客户端与事件分发
在 bot_service.py 入口中装配，便于单元测试（不依赖真实飞书连接）。
"""
import json
import logging
import secrets
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User, Conversation, Message, KnowledgeBase, ImKbBinding
from app.routers.auth import hash_password
from app.services.agent_service import agent_chat_stream
from app.services.cache_service import _get_redis

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
            # SET NX EX：仅当 key 不存在时设置成功
            ok = await redis.set(key, "1", nx=True, ex=settings.BOT_IDEMPOTENCY_TTL)
            # ok=True 表示首次出现（非重复）；None/False 表示已存在（重复）
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


# ============ 用户 / 知识库 / 会话 ============

async def ensure_feishu_user(db: AsyncSession, open_id: str) -> int:
    """为飞书用户懒建一个本地 User（不可登录），返回 user_id。"""
    username = f"fs_{open_id}"[:50]
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user:
        return user.id
    user = User(
        username=username,
        # 随机密码哈希：该账号仅供飞书会话归属，不可用于 Web 登录
        password_hash=hash_password(secrets.token_urlsafe(24)),
    )
    db.add(user)
    await db.flush()
    logger.info(f"为飞书用户创建本地账号: {username} (id={user.id})")
    return user.id


async def resolve_kb_id(
    db: AsyncSession,
    open_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> Optional[int]:
    """确定机器人使用的知识库（Phase 5.5 绑定优先）。

    优先级：群绑定(chat_id) > 个人绑定(open_id) > FEISHU_DEFAULT_KB_ID > 第一个知识库。
    """
    # 1. 群/会话绑定（管理后台或飞书指令配置）
    if chat_id:
        result = await db.execute(
            select(ImKbBinding).where(ImKbBinding.chat_id == chat_id)
        )
        binding = result.scalar_one_or_none()
        if binding:
            return binding.kb_id
    if open_id:
        result = await db.execute(
            select(ImKbBinding).where(ImKbBinding.open_id == open_id)
        )
        binding = result.scalar_one_or_none()
        if binding:
            return binding.kb_id

    # 2. 全局默认
    if settings.FEISHU_DEFAULT_KB_ID:
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == settings.FEISHU_DEFAULT_KB_ID)
        )
        if result.scalar_one_or_none():
            return settings.FEISHU_DEFAULT_KB_ID
        logger.warning(f"FEISHU_DEFAULT_KB_ID={settings.FEISHU_DEFAULT_KB_ID} 不存在，回退第一个知识库")
    # 3. 兜底：第一个知识库
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id.asc()).limit(1))
    kb = result.scalar_one_or_none()
    return kb.id if kb else None


# ============ 知识库绑定指令（Phase 5.5） ============

# 绑定/切换类指令（捕获库名）；查询类指令无捕获组（返回空串）
_BIND_PATTERNS = [
    r"^(?:绑定|切换|设置)(?:知识库)?[：:为]?\s*(.+)$",
    r"^使用(?:知识库)?[：:为]?\s*(.+)$",
    r"^(?:当前|现在)(?:用的|绑定的|绑定的是)?(?:是什么|是哪个|哪个)?(?:知识库|库)[？?]?$",
]


def parse_binding_command(question: str) -> Optional[str]:
    """识别飞书知识库绑定指令。

    - "绑定知识库：员工手册" / "切换知识库员工手册" / "使用XX库" → 返回库名
    - "当前知识库" / "现在绑定的是哪个库" → 返回 ""（空串 = 查询当前绑定）
    - 普通问题 → 返回 None
    """
    import re as _re
    if not question:
        return None
    for pat in _BIND_PATTERNS:
        m = _re.match(pat, question.strip())
        if m:
            groups = m.groups()
            # 查询类指令无捕获组
            return groups[0].strip() if groups else ""
    return None


async def find_kb_by_name(db: AsyncSession, name: str) -> Optional[KnowledgeBase]:
    """按名称模糊查找知识库（取最新创建的），供绑定指令使用。"""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.name.contains(name))
        .order_by(KnowledgeBase.id.desc())
    )
    return result.scalars().first()


async def set_binding(
    db: AsyncSession,
    open_id: Optional[str],
    chat_id: Optional[str],
    kb_id: int,
) -> str:
    """写入/更新绑定关系，返回绑定对象描述。"""
    result = await db.execute(
        select(ImKbBinding).where(
            ImKbBinding.open_id == open_id,
            ImKbBinding.chat_id == chat_id,
        )
    )
    binding = result.scalar_one_or_none()
    if binding:
        binding.kb_id = kb_id
    else:
        db.add(ImKbBinding(open_id=open_id, chat_id=chat_id, kb_id=kb_id))
    await db.commit()
    scope = f"群 {chat_id}" if chat_id else f"用户 {open_id}"
    logger.info(f"知识库绑定已更新: {scope} → kb_id={kb_id}")
    return scope


async def handle_binding_command(
    db: AsyncSession,
    open_id: str,
    chat_id: str,
    question: str,
) -> Tuple[str, str]:
    """处理知识库绑定指令，返回 (msg_type, content_json)；非指令返回 None。"""
    command = parse_binding_command(question)
    if command is None:
        return None

    # 查询当前绑定
    if command == "":
        kb_id = await resolve_kb_id(db, open_id, chat_id)
        if kb_id is None:
            return build_text_reply("当前没有可用知识库，请先在 Web 后台创建。")
        kb = await db.get(KnowledgeBase, kb_id)
        name = kb.name if kb else f"#{kb_id}"
        doc_count = kb.document_count if kb else 0
        return build_text_reply(f"当前绑定的知识库是「{name}」（ID={kb_id}，文档 {doc_count} 篇）")

    # 绑定/切换：按名称查找
    kb = await find_kb_by_name(db, command)
    if kb is None:
        return build_text_reply(
            f"没找到名为「{command}」的知识库。可用指令：\n"
            "· 绑定知识库：<名称>\n· 当前知识库"
        )
    scope = await set_binding(db, open_id, chat_id, kb.id)
    return build_text_reply(
        f"已为{scope}绑定知识库「{kb.name}」（ID={kb.id}，文档 {kb.document_count} 篇）。"
        f"\n接下来在这个会话里提问都会检索这个库。"
    )


async def get_or_create_conversation(
    db: AsyncSession,
    user_id: int,
    open_id: str,
    chat_id: str,
    kb_id: int,
    title: str,
) -> int:
    """会话隔离核心：同一 (open_id, chat_id) 复用同一 Conversation。"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.open_id == open_id,
            Conversation.chat_id == chat_id,
        ).order_by(Conversation.updated_at.desc())
    )
    conv = result.scalars().first()
    if conv:
        # 若知识库变更则跟随最新
        if conv.kb_id != kb_id:
            conv.kb_id = kb_id
        return conv.id
    conv = Conversation(
        user_id=user_id,
        kb_id=kb_id,
        open_id=open_id,
        chat_id=chat_id,
        title=title[:50],
    )
    db.add(conv)
    await db.flush()
    logger.info(f"新建飞书会话 conversation_id={conv.id} (open_id={open_id}, chat_id={chat_id})")
    return conv.id


# ============ 消息解析 ============

def extract_question(content: str, mentions: Optional[List] = None) -> str:
    """从飞书 text 消息内容提取纯问题文本（去掉 @机器人 占位符）。

    飞书群消息 content 形如 {"text":"@_user_1 今天考勤怎么样"}，
    mentions 中每个元素的 key 即占位符（如 @_user_1）。
    """
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
        # mention.id 可能是 open_id 或带前缀；宽松匹配
        if bot_open_id and mid and (mid == bot_open_id or bot_open_id in str(mid)):
            return True
        # 无 bot_open_id 时，只要 @ 了任意对象也认为触发（保底）
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
    db: AsyncSession,
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
    # 正文按行拆分（post 中 \n 不渲染，需拆成多段）
    for line in (content or "").split("\n"):
        paragraphs.append([{"tag": "text", "text": line}])
    # 来源分隔与明细
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


# ============ 主编排 ============

async def process_question(
    db: AsyncSession,
    open_id: str,
    chat_id: str,
    question: str,
) -> Tuple[str, str]:
    """完整处理一条消息：绑定指令 → 会话隔离 → 保存用户消息 → Agent → 构造回复。

    返回 (msg_type, content_json)。任何异常向上抛，由调用方兜底。
    """
    # Phase 5.5：知识库绑定指令（"绑定知识库：xx" / "当前知识库"）直接回复，不走 Agent
    binding_reply = await handle_binding_command(db, open_id, chat_id, question)
    if binding_reply is not None:
        return binding_reply

    # 按绑定解析知识库（群绑定 > 个人绑定 > 默认 > 第一个）
    kb_id = await resolve_kb_id(db, open_id, chat_id)
    if kb_id is None:
        return build_text_reply("还没有可用的知识库，请先在 Web 后台创建并上传文档。")

    user_id = await ensure_feishu_user(db, open_id)
    conversation_id = await get_or_create_conversation(
        db, user_id, open_id, chat_id, kb_id, title=question
    )

    # 保存用户消息（与 Web 路由 chat.py 一致）
    db.add(Message(conversation_id=conversation_id, role="user", content=question))
    await db.commit()

    # 独立 session 跑 Agent 管线（其内部保存助手消息）
    from app.database import async_session_factory
    async with async_session_factory() as agent_db:
        content, sources = await run_agent_and_collect(
            agent_db, conversation_id, kb_id, question
        )

    if not content:
        content = FALLBACK_TEXT
    if sources:
        return build_post_reply(content, sources)
    return build_text_reply(content)
