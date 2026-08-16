"""管理后台路由（Phase 5）- 对话日志 + 系统设置 + 飞书知识库绑定（仅管理员）

权限：get_current_admin 依赖 = users.is_admin 字段 或 .env ADMIN_USERNAMES 白名单。
功能：
  - GET /api/admin/logs         全用户对话列表（分页 + 用户/时间筛选 + 统计）
  - GET /api/admin/logs/{id}    单对话完整消息（内容 / tool_calls / token_count / 来源）
  - GET /api/admin/settings     系统设置（LLM 模型白名单 + 飞书/机器人心跳状态）
  - POST /api/admin/settings    切换 LLM 模型（白名单校验后写入 .env，重启仍生效）
  - GET/POST/DELETE /api/admin/bindings   飞书知识库绑定管理（按群 chat_id / 按人 open_id）
"""
import json
import logging
import os
from datetime import datetime, time as dtime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User, Conversation, Message, ImKbBinding, KnowledgeBase
from app.routers.auth import get_current_admin
from app.services.feishu_bot import set_binding

router = APIRouter(prefix="/api/admin", tags=["管理后台"])
settings = get_settings()
logger = logging.getLogger(__name__)

# backend/.env 绝对路径（本文件位于 backend/app/routers/）
_ENV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".env",
)

# 心跳文件新鲜度阈值（秒）：bot 每 15s 写一次，超过 90s 未更新视为离线
_HEARTBEAT_FRESH_SECONDS = 90


def _resolve_path(p: str) -> str:
    """相对路径基于 backend 目录解析"""
    if os.path.isabs(p):
        return p
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_dir, p)


# ============ 对话日志 ============


class LogConversationItem(BaseModel):
    id: int
    title: Optional[str] = None
    username: str
    source: str = "web"                      # "web" | "im"（飞书）
    open_id: Optional[str] = None
    message_count: int = 0
    total_tokens: int = 0
    tool_call_count: int = 0
    last_answer: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class LogListResponse(BaseModel):
    items: List[LogConversationItem]
    total: int
    page: int
    page_size: int


@router.get("/logs", response_model=LogListResponse)
async def admin_logs(
    username: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """全用户对话列表：按用户/时间筛选，含消息数、token 总量、工具调用数与最近回答"""
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page>=1, 1<=page_size<=100")
    conditions = []
    if username:
        conditions.append(User.username.like(f"%{username}%"))
    if start:
        try:
            conditions.append(Conversation.updated_at >= datetime.combine(
                datetime.strptime(start, "%Y-%m-%d").date(), dtime.min))
        except ValueError:
            raise HTTPException(status_code=400, detail="start 格式应为 YYYY-MM-DD")
    if end:
        try:
            conditions.append(Conversation.updated_at <= datetime.combine(
                datetime.strptime(end, "%Y-%m-%d").date(), dtime.max))
        except ValueError:
            raise HTTPException(status_code=400, detail="end 格式应为 YYYY-MM-DD")

    # 每个对话最近一条 assistant 回答（相关子查询，供列表预览）
    last_answer_subq = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id, Message.role == "assistant")
        .order_by(Message.id.desc())
        .limit(1)
        .scalar_subquery()
    )

    base = select(Conversation, User.username, last_answer_subq.label("last_answer")).join(
        User, Conversation.user_id == User.id
    )
    if conditions:
        base = base.where(*conditions)

    # 总数
    total_result = await db.execute(
        select(func.count()).select_from(
            select(Conversation.id).join(User, Conversation.user_id == User.id)
            .where(*conditions).subquery()
        )
    )
    total = total_result.scalar() or 0

    # 当前页
    rows = await db.execute(
        base.order_by(Conversation.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    conv_rows = rows.all()

    # 批量统计：消息数 / token 总量 / 工具调用数
    conv_ids = [c.id for c, _, _ in conv_rows]
    stats: dict = {}
    if conv_ids:
        stat_rows = await db.execute(
            select(
                Message.conversation_id,
                func.count().label("msg_count"),
                func.coalesce(func.sum(Message.token_count), 0).label("total_tokens"),
                func.coalesce(func.sum(func.json_length(Message.tool_calls)), 0).label("tool_count"),
            )
            .where(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
        )
        stats = {cid: (m, t, tc) for cid, m, t, tc in stat_rows.all()}

    items = []
    for conv, username_str, last_answer in conv_rows:
        msg_count, total_tokens, tool_count = stats.get(conv.id, (0, 0, 0))
        items.append(LogConversationItem(
            id=conv.id,
            title=conv.title,
            username=username_str,
            source="im" if conv.open_id else "web",
            open_id=conv.open_id,
            message_count=msg_count,
            total_tokens=total_tokens,
            tool_call_count=tool_count,
            last_answer=(last_answer or "")[:200],
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        ))
    return LogListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/logs/{conv_id}")
async def admin_log_detail(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """单对话完整消息：role/content/tool_calls/token_count/sources（含来源标注）"""
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    user = await db.get(User, conv.user_id)
    msgs = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.id.asc())
    )
    return {
        "conversation": {
            "id": conv.id,
            "title": conv.title,
            "username": user.username if user else f"#{conv.user_id}",
            "source": "im" if conv.open_id else "web",
            "open_id": conv.open_id,
            "chat_id": conv.chat_id,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
        },
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "sources": m.sources,
                "tool_calls": m.tool_calls,
                "token_count": m.token_count,
                "created_at": m.created_at,
            }
            for m in msgs.scalars().all()
        ],
    }


# ============ 系统设置 ============


def _read_bot_heartbeat() -> dict:
    """读取机器人心跳文件，判断飞书长连接是否在线"""
    path = _resolve_path(settings.BOT_HEARTBEAT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data.get("ts", ""))
        fresh = (datetime.now() - ts).total_seconds() < _HEARTBEAT_FRESH_SECONDS
        return {"connected": fresh, "pid": data.get("pid"), "heartbeat_at": data.get("ts")}
    except Exception:
        return {"connected": False, "pid": None, "heartbeat_at": None}


class SettingsUpdate(BaseModel):
    llm_model: str


@router.get("/settings")
async def get_admin_settings(admin: User = Depends(get_current_admin)):
    """系统设置：当前模型 / 白名单 / 飞书机器人状态"""
    whitelist = [m.strip() for m in settings.LLM_MODEL_WHITELIST.split(",") if m.strip()]
    return {
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": (
            settings.OPENAI_LLM_MODEL if settings.LLM_PROVIDER == "openai" else settings.LLM_MODEL
        ),
        "model_whitelist": whitelist,
        "feishu": {
            "app_id": settings.FEISHU_APP_ID,
            "configured": bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET),
        },
        "bot": _read_bot_heartbeat(),
    }


@router.post("/settings")
async def update_admin_settings(
    data: SettingsUpdate,
    admin: User = Depends(get_current_admin),
):
    """切换 LLM 模型：白名单校验 → 写入 backend/.env（重启后依然生效）"""
    whitelist = [m.strip() for m in settings.LLM_MODEL_WHITELIST.split(",") if m.strip()]
    if data.llm_model not in whitelist:
        raise HTTPException(status_code=400, detail=f"模型不在白名单: {data.llm_model}")

    target_key = "OPENAI_LLM_MODEL" if settings.LLM_PROVIDER == "openai" else "LLM_MODEL"

    lines: List[str] = []
    if os.path.exists(_ENV_FILE):
        with open(_ENV_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{target_key}="):
            lines[i] = f"{target_key}={data.llm_model}\n"
            found = True
            break
    if not found:
        lines.append(f"{target_key}={data.llm_model}\n")
    with open(_ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # 刷新进程内配置缓存（下一次请求即生效）
    from app.config import get_settings as _gs
    _gs.cache_clear()
    logger.info(f"管理员 {admin.username} 切换 LLM 模型 → {data.llm_model}（写入 {target_key}）")
    return {"llm_model": data.llm_model, "key": target_key}


# ============ 飞书知识库绑定（Phase 5.5） ============


class BindingCreate(BaseModel):
    """新增/更新一条飞书绑定：open_id（按人）与 chat_id（按群）至少填一个"""
    open_id: Optional[str] = None
    chat_id: Optional[str] = None
    kb_id: int


def _binding_scope_label(open_id: Optional[str], chat_id: Optional[str]) -> str:
    """绑定对象的人类可读描述"""
    if open_id and chat_id:
        return f"单聊 {open_id} + 群 {chat_id}"
    if chat_id:
        return f"群 {chat_id}"
    return f"用户 {open_id}"


@router.get("/bindings")
async def list_admin_bindings(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """列出所有飞书知识库绑定（含知识库名 / 文档数）"""
    result = await db.execute(
        select(ImKbBinding).order_by(ImKbBinding.id.desc())
    )
    bindings = list(result.scalars().all())

    kb_ids = {b.kb_id for b in bindings}
    kb_map: dict = {}
    if kb_ids:
        kb_result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        )
        kb_map = {kb.id: kb for kb in kb_result.scalars().all()}

    return [
        {
            "id": b.id,
            "open_id": b.open_id,
            "chat_id": b.chat_id,
            "scope_label": _binding_scope_label(b.open_id, b.chat_id),
            "kb_id": b.kb_id,
            "kb_name": kb_map[b.kb_id].name if b.kb_id in kb_map else None,
            "document_count": (
                kb_map[b.kb_id].document_count if b.kb_id in kb_map else None
            ),
            "created_at": b.created_at,
            "updated_at": b.updated_at,
        }
        for b in bindings
    ]


@router.post("/bindings")
async def create_admin_binding(
    data: BindingCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """新增/更新一条绑定（upsert）：open_id 或 chat_id + 存在的 kb_id"""
    if not data.open_id and not data.chat_id:
        raise HTTPException(status_code=400, detail="open_id 与 chat_id 至少填一个")

    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == data.kb_id)
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {data.kb_id}")

    scope = await set_binding(db, data.open_id, data.chat_id, data.kb_id)
    logger.info(f"管理员 {admin.username} 后台设置绑定: {scope} → kb_id={data.kb_id}")

    # 返回最新绑定记录
    result = await db.execute(
        select(ImKbBinding).where(
            ImKbBinding.open_id == data.open_id,
            ImKbBinding.chat_id == data.chat_id,
        )
    )
    binding = result.scalar_one()
    return {
        "id": binding.id,
        "open_id": binding.open_id,
        "chat_id": binding.chat_id,
        "scope_label": _binding_scope_label(binding.open_id, binding.chat_id),
        "kb_id": binding.kb_id,
        "kb_name": kb.name,
        "document_count": kb.document_count,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


@router.delete("/bindings/{binding_id}")
async def delete_admin_binding(
    binding_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """删除一条绑定（解除后按优先级回退默认知识库）"""
    result = await db.execute(
        select(ImKbBinding).where(ImKbBinding.id == binding_id)
    )
    binding = result.scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=404, detail="绑定不存在")
    scope = _binding_scope_label(binding.open_id, binding.chat_id)
    await db.delete(binding)
    await db.commit()
    logger.info(f"管理员 {admin.username} 删除绑定: {scope}")
    return {"message": f"已解除绑定（{scope}）"}
