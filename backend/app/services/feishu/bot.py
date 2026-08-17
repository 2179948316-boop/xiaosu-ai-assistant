"""飞书机器人主编排 - 用户/KB 解析 + 消息处理主流程

依赖 feishu 子包中各模块：account（账号绑定）、binding（KB 绑定/会话）、utils（工具）。
"""
import json
import logging
import secrets
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User, Conversation, Message, KnowledgeBase, ImKbBinding
from app.routers.auth import hash_password

from . import utils as feishu_utils
from . import account as feishu_account
from . import binding as feishu_binding

settings = get_settings()
logger = logging.getLogger(__name__)


async def ensure_feishu_user(db: AsyncSession, open_id: str) -> int:
    """为飞书用户懒建一个本地 User（不可登录），返回 user_id。"""
    username = f"fs_{open_id}"[:50]
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user:
        return user.id
    user = User(
        username=username,
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
    user: Optional[User] = None,
):
    """确定机器人使用的知识库（三级绑定 + 账号兜底 + 全局兜底）。"""
    # 1. 群/会话绑定
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
        logger.warning(f"FEISHU_DEFAULT_KB_ID={settings.FEISHU_DEFAULT_KB_ID} 不存在，继续回退")

    # 3. 账号兜底
    if user is not None:
        user_kbs = await feishu_account.list_visible_kbs(db, user)
        if user_kbs:
            return user_kbs[0].id

    # 4. 全局第一个知识库
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id.asc()).limit(1))
    kb = result.scalar_one_or_none()
    return kb.id if kb else None


async def process_question(
    db: AsyncSession,
    open_id: str,
    chat_id: str,
    question: str,
    chat_type: str = "p2p",
) -> Tuple[str, str]:
    """完整处理一条消息：账号指令 → KB 绑定指令 → 会话隔离 → 保存用户消息 → Agent → 构造回复。"""
    # Phase 5.6：账号绑定指令
    account_reply = await feishu_account.handle_account_command(db, open_id, question, chat_type)
    if account_reply is not None:
        return account_reply

    # Phase 5.5：知识库绑定指令
    binding_reply = await feishu_binding.handle_binding_command(db, open_id, chat_id, question)
    if binding_reply is not None:
        return binding_reply

    # 按绑定解析知识库
    user = await feishu_account.resolve_bound_user(db, open_id)
    kb_id = await resolve_kb_id(db, open_id, chat_id, user)
    if kb_id is None:
        return feishu_utils.build_text_reply("还没有可用的知识库，请先在 Web 后台创建并上传文档。")

    user_id = await ensure_feishu_user(db, open_id)
    conversation_id = await feishu_binding.get_or_create_conversation(
        db, user_id, open_id, chat_id, kb_id, title=question
    )

    # 保存用户消息
    db.add(Message(conversation_id=conversation_id, role="user", content=question))
    await db.commit()

    # 独立 session 跑 Agent 管线
    from app.database import async_session_factory
    async with async_session_factory() as agent_db:
        content, sources = await feishu_utils.run_agent_and_collect(
            agent_db, conversation_id, kb_id, question
        )

    if not content:
        content = feishu_utils.FALLBACK_TEXT
    if sources:
        return feishu_utils.build_post_reply(content, sources)
    return feishu_utils.build_text_reply(content)