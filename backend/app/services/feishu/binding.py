"""飞书知识库绑定（Phase 5.5）+ 会话管理

知识库绑定指令解析、按名/按 ID 查找、绑定关系写入；
会话隔离核心函数：同一 (open_id, chat_id) 复用同一 Conversation。
"""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User, Conversation, KnowledgeBase, ImKbBinding

from . import utils as feishu_utils
from . import account as feishu_account

settings = get_settings()
logger = logging.getLogger(__name__)

# 绑定/切换类指令模式
_BIND_PATTERNS = [
    r"^(?:绑定|切换|设置)(?:知识库)?[：:为]?\s*(.+)$",
    r"^使用(?:知识库)?[：:为]?\s*(.+)$",
    r"^(?:当前|现在)(?:用的|绑定的|绑定的是)?(?:是什么|是哪个|哪个)?(?:知识库|库)[？?]?$",
]


def parse_binding_command(question: str) -> Optional[str]:
    """识别飞书知识库绑定指令。

    - "绑定知识库：员工手册" / "切换知识库员工手册" → 返回库名
    - "当前知识库" / "现在绑定的是哪个库" → 返回 ""（查询当前绑定）
    - 普通问题 → 返回 None
    """
    if not question:
        return None
    for pat in _BIND_PATTERNS:
        m = re.match(pat, question.strip())
        if m:
            groups = m.groups()
            return groups[0].strip() if groups else ""
    return None


async def _find_kb_by_id(db: AsyncSession, user: User, kb_id: int) -> Optional[KnowledgeBase]:
    """在账号可见范围内按 ID 精确查找知识库。"""
    for kb in await feishu_account.list_visible_kbs(db, user):
        if kb.id == kb_id:
            return kb
    return None


async def _find_kbs_by_name(db: AsyncSession, user: User, name: str) -> List[KnowledgeBase]:
    """在账号可见范围内按名称匹配：精确名优先；否则模糊匹配（最多 5 个候选）。"""
    kbs = await feishu_account.list_visible_kbs(db, user)
    exact = [kb for kb in kbs if kb.name == name]
    if exact:
        return exact[:1]
    return [kb for kb in kbs if name in kb.name][:5]


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
) -> Optional[Tuple[str, str]]:
    """处理知识库绑定指令，返回 (msg_type, content_json)；非指令返回 None。"""
    command = parse_binding_command(question)
    if command is None:
        return None

    # 查询当前绑定
    if command == "":
        user = await feishu_account.resolve_bound_user(db, open_id)
        kb_id = await _resolve_kb_id_only(db, open_id, chat_id, user)
        if kb_id is None:
            return feishu_utils.build_text_reply("当前没有可用知识库，请先在 Web 后台创建。")
        kb = await db.get(KnowledgeBase, kb_id)
        name = kb.name if kb else f"#{kb_id}"
        doc_count = kb.document_count if kb else 0
        owner = ""
        if kb and user is not None and kb.user_id != user.id:
            owner = f"，属其他账号(#{kb.user_id})"
        return feishu_utils.build_text_reply(
            f"当前绑定的知识库是「{name}」（ID={kb_id}，文档 {doc_count} 篇{owner}）"
        )

    # 绑定/切换：先确认账号身份，再在该账号可见范围内匹配
    user = await feishu_account.resolve_bound_user(db, open_id)
    if user is None:
        return feishu_utils.build_text_reply(
            "绑定知识库前需要先绑定 Web 账号（同名库才不会混淆）：\n"
            "发送「绑定账号：用户名」并按提示输入密码验证。"
        )

    if command.isdigit():
        kb = await _find_kb_by_id(db, user, int(command))
        if kb is None:
            return feishu_utils.build_text_reply(
                f"账号「{user.username}」下没有 ID={command} 的知识库。发「我的知识库」查看全部。"
            )
    else:
        kbs = await _find_kbs_by_name(db, user, command)
        if not kbs:
            return feishu_utils.build_text_reply(
                f"账号「{user.username}」下没找到名为「{command}」的知识库。\n"
                "发「我的知识库」查看该账号的全部知识库。"
            )
        if len(kbs) > 1:
            lines = [f"「{command}」匹配到多个知识库，请回复「绑定知识库：<ID>」精确指定："]
            for kb in kbs:
                lines.append(f"· {kb.name}（ID={kb.id}，{kb.document_count} 篇）")
            return feishu_utils.build_text_reply("\n".join(lines))
        kb = kbs[0]

    scope = await set_binding(db, open_id, chat_id, kb.id)
    return feishu_utils.build_text_reply(
        f"已为{scope}绑定知识库「{kb.name}」（ID={kb.id}，文档 {kb.document_count} 篇）。"
        f"\n接下来在这个会话里提问都会检索这个库。"
    )


async def _resolve_kb_id_only(
    db: AsyncSession,
    open_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    user: Optional[User] = None,
) -> Optional[int]:
    """内部：仅用于查询当前绑定的最短路径（无账号兜底）。"""
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
    if settings.FEISHU_DEFAULT_KB_ID:
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == settings.FEISHU_DEFAULT_KB_ID)
        )
        if result.scalar_one_or_none():
            return settings.FEISHU_DEFAULT_KB_ID
    return None


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