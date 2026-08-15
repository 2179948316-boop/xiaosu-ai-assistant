"""RAG 服务 - 编排检索增强生成的核心流程（混合检索 + 重排序）"""
import json
import logging
from typing import AsyncGenerator, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.models import Message
from app.services.embedding_service import get_embedding
from app.services import vector_service
from app.services.bm25_service import bm25_search
from app.services.reranker_service import reciprocal_rank_fusion
from app.services.cross_encoder_reranker import rerank_by_cross_encoder
from app.services.cache_service import get_cached_answer, set_cached_answer
from app.services.llm_service import chat_stream

settings = get_settings()
logger = logging.getLogger(__name__)

# 系统提示词
SYSTEM_PROMPT = """你是一个企业知识库问答助手。请基于以下检索到的参考资料来回答用户的问题。

要求：
1. 如果参考资料中有相关信息，请基于资料准确回答，并注明信息来源
2. 如果参考资料中没有相关信息，请明确告知用户"根据现有知识库未找到相关信息"
3. 回答要简洁清晰，使用中文
4. 不要编造不在参考资料中的内容"""


def build_context_prompt(sources: List[Dict]) -> str:
    """将检索到的片段组合为上下文"""
    if not sources:
        return "未检索到相关参考资料。"

    context_parts = []
    for i, source in enumerate(sources, 1):
        filename = source.get("metadata", {}).get("filename", "未知文档")
        text = source["text"]
        score = source.get("score", 0)
        method = source.get("retrieval_method", "hybrid")
        context_parts.append(
            f"[资料{i}] 来源: {filename} (相关度: {score}, 检索方式: {method})\n{text}"
        )

    return "\n\n---\n\n".join(context_parts)


async def rag_chat_stream(
    db: AsyncSession,
    conversation_id: int,
    kb_id: int,
    user_question: str,
) -> AsyncGenerator[str, None]:
    """
    RAG 流式问答完整流程（缓存 + 混合检索 + Cross-Encoder 重排序）:
    0. Redis 缓存检查（命中则直接返回）
    1. 向量化用户问题
    2. 多路召回: 向量检索 top-20 + BM25 检索 top-10
    3. RRF 融合多路结果 top-20
    4. Cross-Encoder 精排 top-3
    5. 构建增强 Prompt
    6. 流式调用 LLM
    7. 保存对话记录 + 写入缓存
    """
    # 0. Redis 缓存检查
    try:
        cached = await get_cached_answer(user_question, kb_id)
        if cached:
            # 发送缓存的来源信息
            if cached.get("sources"):
                yield _sse_event({"type": "sources", "sources": cached["sources"]})
            # 分块输出缓存答案，模拟流式体验
            answer = cached["answer"]
            chunk_size = 4
            for i in range(0, len(answer), chunk_size):
                yield _sse_event({"type": "chunk", "content": answer[i:i+chunk_size]})
            # 保存缓存回复到对话历史
            try:
                assistant_msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    sources=[{
                        "filename": s.get("filename", "未知"),
                        "score": s.get("score", 0),
                        "text_preview": s.get("text_preview", ""),
                    } for s in cached.get("sources", [])] or None,
                )
                db.add(assistant_msg)
                await db.commit()
            except Exception as save_err:
                logger.error(f"保存缓存回复失败: {save_err}")
            yield _sse_event({"type": "done", "content": answer, "cached": True})
            return
    except Exception as e:
        logger.warning(f"缓存检查异常，继续正常流程: {e}")

    # 1. 向量化用户问题
    try:
        query_embedding = await get_embedding(user_question)
    except Exception as e:
        logger.error(f"Embedding 服务异常: {e}")
        yield _sse_event({"type": "error", "content": f"Embedding 服务异常: {str(e)}"})
        return

    # 2. 多路召回
    # 2a. 向量检索 - 召回 top-20 候选（宽松阈值，用于后续精排）
    dense_results = await vector_service.search_similar_dense_extended(
        kb_id=kb_id,
        query_embedding=query_embedding,
        top_k=20,
        min_score=0.1,
    )
    logger.info(f"向量检索召回 {len(dense_results)} 条")

    # 2b. BM25 关键词检索 - 召回 top-10
    bm25_results = await bm25_search(kb_id=kb_id, query=user_question, top_k=10)
    logger.info(f"BM25 检索召回 {len(bm25_results)} 条")

    # 3. RRF 融合多路结果 top-20
    result_lists = [r for r in [dense_results, bm25_results] if r]
    if result_lists:
        fused_results = reciprocal_rank_fusion(result_lists, k=60, top_k=20)
    else:
        fused_results = []
    logger.info(f"RRF 融合后 {len(fused_results)} 条")

    # 4. Cross-Encoder 精排 top-3
    if fused_results:
        sources = await rerank_by_cross_encoder(
            query=user_question,
            candidates=fused_results,
            top_k=3,
        )
    else:
        sources = []
    logger.info(f"Cross-Encoder 精排后 {len(sources)} 条")

    # 5. 发送来源信息
    if sources:
        source_info = [
            {
                "filename": s["metadata"].get("filename", "未知"),
                "chunk_index": s["metadata"].get("chunk_index", 0),
                "score": s["score"],
                "text_preview": s["text"][:100],
                "retrieval_method": s.get("retrieval_method", "hybrid"),
            }
            for s in sources
        ]
        yield _sse_event({"type": "sources", "sources": source_info})

    # 6. 获取对话历史（最近 6 条消息，控制 token 用量）
    history = await _get_conversation_history(db, conversation_id, limit=6)

    # 7. 构建消息列表
    context = build_context_prompt(sources)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"参考资料：\n{context}"},
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_question})

    # 8. 流式生成回答（try/finally 确保即使连接中断也能保存回复）
    full_response = ""
    stream_error = None
    try:
        async for token in chat_stream(messages):
            full_response += token
            yield _sse_event({"type": "chunk", "content": token})
    except Exception as e:
        logger.error(f"LLM 生成异常: {e}")
        stream_error = e
        yield _sse_event({"type": "error", "content": f"LLM 生成异常: {str(e)}"})
    finally:
        # 无论流式输出是否正常完成，只要有内容就保存到数据库
        if full_response:
            try:
                assistant_msg = Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_response,
                    sources=[{
                        "filename": s["metadata"].get("filename", "未知"),
                        "score": s["score"],
                        "text_preview": s["text"][:200],
                    } for s in sources] if sources else None,
                )
                db.add(assistant_msg)
                await db.commit()
                logger.info(f"助手回复已保存 (conversation_id={conversation_id}, {len(full_response)} chars)")
            except Exception as save_err:
                logger.error(f"保存助手消息失败: {save_err}")

    if stream_error:
        return

    # 写入 Redis 缓存
    if full_response and sources:
        try:
            cache_sources = [{
                "filename": s["metadata"].get("filename", "未知"),
                "chunk_index": s["metadata"].get("chunk_index", 0),
                "score": s["score"],
                "text_preview": s["text"][:100],
                "retrieval_method": s.get("retrieval_method", "hybrid"),
            } for s in sources]
            await set_cached_answer(user_question, kb_id, full_response, cache_sources)
        except Exception as cache_err:
            logger.warning(f"缓存写入失败: {cache_err}")

    yield _sse_event({"type": "done", "content": full_response})


async def _get_conversation_history(db: AsyncSession, conversation_id: int, limit: int = 6) -> List[Dict]:
    """获取对话历史，返回最近 N 条消息"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()  # 恢复时间顺序

    return [{"role": m.role, "content": m.content} for m in messages]


def _sse_event(data: dict) -> str:
    """构造 SSE 格式事件数据"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
