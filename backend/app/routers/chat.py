"""聊天与对话管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from typing import List
from datetime import datetime

from app.database import get_db, async_session_factory
from app.models import User, Conversation, Message
from app.schemas import (
    ChatRequest, ConversationCreate, ConversationResponse, MessageResponse
)
from app.routers.auth import get_current_user
from app.routers.knowledge import check_kb_access
from app.services.agent_service import agent_chat_stream

router = APIRouter(tags=["聊天"])


# ============ 对话管理 ============

@router.get("/api/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前用户的对话列表"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("/api/conversations", response_model=ConversationResponse)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建新对话"""
    conv = Conversation(
        user_id=user.id,
        kb_id=data.kb_id,
        title=data.title or "新对话",
    )
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return conv


@router.get("/api/conversations/{conv_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取对话的消息列表"""
    # 验证对话归属
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="对话不存在")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars().all())


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除对话及其所有消息"""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user.id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    await db.delete(conv)
    await db.commit()
    return {"message": "对话已删除"}


# ============ RAG 聊天（流式） ============

@router.post("/api/chat")
async def chat(
    data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Agent 问答接口（SSE 流式）。
    支持工具调用：员工信息 / 考勤 / 订单 / 当前时间 / 知识库检索，
    模型自主决定工具组合，最终回答流式返回。
    事件类型：conversation / tools / sources / chunk / done / error
    """
    # 校验知识库访问权限（个人/组织成员）
    await check_kb_access(db, data.kb_id, user.id)

    conversation_id = data.conversation_id

    # 如果没有 conversation_id，创建新对话
    if not conversation_id:
        conv = Conversation(
            user_id=user.id,
            kb_id=data.kb_id,
            title=data.message[:50],
        )
        db.add(conv)
        await db.flush()
        await db.refresh(conv)
        conversation_id = conv.id

    # 保存用户消息
    user_msg = Message(
        conversation_id=conversation_id,
        role="user",
        content=data.message,
    )
    db.add(user_msg)
    await db.flush()

    # 更新对话时间（使用 func.now() 确保触发更新）
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=func.now())
    )

    # 立即 commit，确保对话记录在 SSE 流开始前已入库
    # 这样用户点击"新建对话"时能立即看到之前的对话
    await db.commit()

    # SSE 生成器 - 使用独立 session 处理 RAG 流和助手消息保存
    async def event_generator():
        import json
        # 先发 conversation_id
        yield f"data: {json.dumps({'type': 'conversation', 'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

        # 创建独立的 db session 供 Agent 管线使用
        async with async_session_factory() as agent_db:
            try:
                async for event in agent_chat_stream(agent_db, conversation_id, data.kb_id, data.message):
                    yield event
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
            finally:
                await agent_db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
