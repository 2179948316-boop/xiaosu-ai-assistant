"""飞书账号绑定（Phase 5.6）- open_id ↔ Web 账号关联

提供账号绑定指令识别、密码验证、账号查询/解绑，以及当前账号可见知识库列表。
"""
import json
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User, KnowledgeBase, OrgMember
from app.routers.auth import hash_password, verify_password

from . import utils as feishu_utils

settings = get_settings()
logger = logging.getLogger(__name__)

# 等待密码验证：open_id -> (username, ts)；进程内内存态 + 5 分钟超时
_ACCOUNT_PENDING: Dict[str, Tuple[str, float]] = {}
_ACCOUNT_PENDING_TTL = 300

_ACCOUNT_COMMAND_PATTERNS: Dict[str, str] = {
    "bind": r"^绑定账号[：:为]?\s*(\S+)$",
    "me": r"^(?:我的账号|当前账号|绑定账号是什么)$",
    "list_kb": r"^(?:我的知识库|有哪些知识库|查看知识库|知识库列表)$",
    "unbind": r"^解除(?:账号)?绑定$",
}


def parse_account_command(question: str) -> Optional[Tuple[str, str]]:
    """识别账号绑定指令，返回 (kind, arg)；非指令返回 None。"""
    if not question:
        return None
    q = question.strip()
    for kind, pattern in _ACCOUNT_COMMAND_PATTERNS.items():
        m = re.match(pattern, q)
        if m:
            return kind, (m.group(1).strip() if m.groups() else "")
    return None


async def resolve_bound_user(db: AsyncSession, open_id: str) -> Optional[User]:
    """通过 feishu_open_id 找到当前飞书身份关联的 Web 账号；未绑定返回 None。"""
    if not open_id:
        return None
    result = await db.execute(select(User).where(User.feishu_open_id == open_id))
    return result.scalar_one_or_none()


async def list_visible_kbs(db: AsyncSession, user: User) -> List[KnowledgeBase]:
    """账号可见知识库：个人库 + 所属组织库，按创建倒序。"""
    org_result = await db.execute(
        select(OrgMember.org_id).where(OrgMember.user_id == user.id)
    )
    org_ids = [row[0] for row in org_result.all()]

    personal = (KnowledgeBase.org_id.is_(None)) & (KnowledgeBase.user_id == user.id)
    if org_ids:
        where = or_(personal, KnowledgeBase.org_id.in_(org_ids))
    else:
        where = personal

    result = await db.execute(
        select(KnowledgeBase).where(where).order_by(KnowledgeBase.id.desc())
    )
    return list(result.scalars().all())


async def handle_account_command(
    db: AsyncSession,
    open_id: str,
    question: str,
    chat_type: str = "p2p",
) -> Optional[Tuple[str, str]]:
    """处理账号绑定指令（含密码验证态）；非指令返回 None。"""
    cmd = parse_account_command(question)
    pending = _ACCOUNT_PENDING.get(open_id)

    # ---- 验证态：下一条非指令消息视为密码（或「取消」） ----
    if pending is not None:
        if chat_type != "p2p":
            return feishu_utils.build_text_reply("密码验证只能在私聊中进行，请在私聊里完成绑定。")
        if (question or "").strip() == "取消":
            _ACCOUNT_PENDING.pop(open_id, None)
            return feishu_utils.build_text_reply("已取消绑定，没有做任何修改。")
        if cmd is not None and cmd[0] != "bind":
            return feishu_utils.build_text_reply("请先输入该账号的登录密码完成验证，或回复「取消」。")
        username, ts = pending
        if time.time() - ts > _ACCOUNT_PENDING_TTL:
            _ACCOUNT_PENDING.pop(open_id, None)
            return feishu_utils.build_text_reply("验证超时，请重新发送「绑定账号：用户名」。")
        return await _verify_account_password(db, open_id, question, username)

    if cmd is None:
        return None

    kind, arg = cmd
    if kind == "bind":
        return await _start_account_bind(db, open_id, arg, chat_type)
    if kind == "me":
        return await _show_bound_account(db, open_id)
    if kind == "list_kb":
        return await _list_account_kbs(db, open_id)
    if kind == "unbind":
        return await _unbind_account(db, open_id)
    return None


async def _start_account_bind(
    db: AsyncSession,
    open_id: str,
    username: str,
    chat_type: str,
) -> Tuple[str, str]:
    """发起绑定：校验账号存在（避免输密码后才发现打错），进入密码验证态。"""
    if chat_type != "p2p":
        return feishu_utils.build_text_reply("为了密码安全，请在与小苏的私聊中完成账号绑定。")
    if not username:
        return feishu_utils.build_text_reply("格式：绑定账号：用户名（手机号）")
    result = await db.execute(select(User).where(User.username == username))
    if not result.scalar_one_or_none():
        return feishu_utils.build_text_reply(f"账号「{username}」不存在，请先在 Web 端注册。")
    _ACCOUNT_PENDING[open_id] = (username, time.time())
    return feishu_utils.build_text_reply(
        f"即将把当前飞书身份绑定到账号「{username}」。\n"
        f"请直接回复该账号的登录密码完成验证（密码仅用于本次验证，不会保存）。\n"
        f"注意：直接发密码即可，不要加「密码：」之类的前缀。\n"
        f"回复「取消」可中止。"
    )


async def _verify_account_password(
    db: AsyncSession,
    open_id: str,
    password: str,
    username: str,
) -> Tuple[str, str]:
    """验证密码并写入 feishu_open_id 关联（换绑时清掉旧账号的关联）。"""
    _ACCOUNT_PENDING.pop(open_id, None)

    password = re.sub(r"^\s*密码\s*[：:，,、]?\s*", "", (password or "").strip())

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        logger.warning(f"飞书账号绑定失败: open_id={open_id} username={username} 密码错误")
        return feishu_utils.build_text_reply(
            "验证失败：账号不存在或密码错误，已取消绑定。\n请重新发送「绑定账号：用户名」。"
        )

    old = await db.execute(select(User).where(User.feishu_open_id == open_id))
    old_user = old.scalar_one_or_none()
    if old_user and old_user.id != user.id:
        old_user.feishu_open_id = None

    user.feishu_open_id = open_id
    await db.commit()
    logger.info(f"飞书账号绑定成功: open_id={open_id} → username={username} (id={user.id})")
    return feishu_utils.build_text_reply(
        f"验证通过，已绑定账号「{username}」。\n"
        "之后本会话的知识库检索将按你的账号范围进行（个人库 + 所在组织库）。\n"
        "可用指令：\n· 我的知识库\n· 绑定知识库：<名称或ID>\n· 当前知识库"
    )


async def _show_bound_account(db: AsyncSession, open_id: str) -> Tuple[str, str]:
    """查询当前 open_id 关联的 Web 账号。"""
    user = await resolve_bound_user(db, open_id)
    if not user:
        return feishu_utils.build_text_reply(
            "当前未绑定 Web 账号。\n发送「绑定账号：用户名」并输入密码验证后，"
            "检索将按你的知识库范围进行（同名知识库也不会混淆）。"
        )
    return feishu_utils.build_text_reply(f"当前绑定账号：{user.username}（管理员：{'是' if user.is_admin else '否'}）")


async def _list_account_kbs(db: AsyncSession, open_id: str) -> Tuple[str, str]:
    """列出当前账号可见的知识库。"""
    user = await resolve_bound_user(db, open_id)
    if not user:
        return feishu_utils.build_text_reply(
            "当前未绑定 Web 账号，无法列出知识库。\n先发送「绑定账号：用户名」完成验证绑定。"
        )
    kbs = await list_visible_kbs(db, user)
    if not kbs:
        return feishu_utils.build_text_reply(
            f"账号「{user.username}」下还没有知识库，请先在 Web 端创建并上传文档。"
        )
    lines = [f"账号「{user.username}」的知识库："]
    for kb in kbs:
        scope = "组织" if kb.org_id else "个人"
        lines.append(f"· {kb.name}（ID={kb.id}，{kb.document_count} 篇，{scope}）")
    lines.append("发「绑定知识库：<名称或ID>」即可让本会话使用该库。")
    return feishu_utils.build_text_reply("\n".join(lines))


async def _unbind_account(db: AsyncSession, open_id: str) -> Tuple[str, str]:
    """解除 open_id ↔ 账号关联。"""
    user = await resolve_bound_user(db, open_id)
    if not user:
        return feishu_utils.build_text_reply("当前未绑定账号。")
    user.feishu_open_id = None
    await db.commit()
    logger.info(f"飞书账号解除绑定: open_id={open_id} username={user.username}")
    return feishu_utils.build_text_reply(f"已解除与账号「{user.username}」的绑定。")