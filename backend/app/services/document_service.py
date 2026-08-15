"""文档服务 - 处理文档上传、解析、切片的完整流程"""
import os
import shutil
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import UploadFile
from typing import List

from app.config import get_settings
from app.models import Document, KnowledgeBase
from app.utils.file_parser import parse_file, get_file_type
from app.utils.text_splitter import split_text
from app.services.embedding_service import get_embeddings
from app.services import vector_service
from app.services import bm25_service

settings = get_settings()
logger = logging.getLogger(__name__)


async def process_document_upload(
    db: AsyncSession,
    file: UploadFile,
    kb_id: int,
    user_id: int,
) -> Document:
    """
    完整的文档处理流程:
    0. 增量更新：同名文档先删旧版本（向量 + 记录），再按新文档处理
    1. 保存文件到磁盘
    2. 创建文档记录
    3. 解析文件内容
    4. 文本切片
    5. 向量化
    6. 存入 Chroma
    7. 更新文档状态和知识库统计
    """
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "uploads", str(kb_id))
    os.makedirs(upload_dir, exist_ok=True)

    file_type = get_file_type(file.filename)
    file_path = os.path.join(upload_dir, file.filename)

    # 0. 增量更新：同知识库下同名文档视为版本替换
    #    先删除旧文档的向量与数据库记录（磁盘文件由下方写入直接覆盖），
    #    保证重复上传同名文件时索引只保留最新版本
    existing_result = await db.execute(
        select(Document).where(
            Document.kb_id == kb_id,
            Document.filename == file.filename,
        )
    )
    old_docs = list(existing_result.scalars().all())
    for old_doc in old_docs:
        await vector_service.delete_document_chunks(kb_id, old_doc.id)
        await db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == kb_id)
            .values(document_count=KnowledgeBase.document_count - 1)
        )
        await db.delete(old_doc)
    if old_docs:
        await db.commit()
        logger.info(f"增量更新：替换同名文档 '{file.filename}' (kb_id={kb_id}, 旧版本 {[d.id for d in old_docs]})")

    # 1. 保存文件
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 2. 创建文档记录
    doc = Document(
        kb_id=kb_id,
        user_id=user_id,
        filename=file.filename,
        file_type=file_type,
        file_size=len(content),
        status="processing",
    )
    db.add(doc)
    await db.flush()  # 获取 doc.id

    try:
        # 3. 解析文件
        text = parse_file(file_path, file_type)
        if not text.strip():
            doc.status = "failed"
            await db.commit()
            raise ValueError("文件内容为空，无法解析")

        # 4. 文本切片
        chunks = split_text(text, chunk_size=500, chunk_overlap=50, doc_id=doc.id, filename=file.filename)

        if not chunks:
            doc.status = "failed"
            await db.commit()
            raise ValueError("文本切片后无有效内容")

        # 5. 批量向量化
        texts = [c["text"] for c in chunks]
        embeddings = await get_embeddings(texts)

        # 6. 存入 Chroma
        await vector_service.add_chunks(kb_id, doc.id, chunks, embeddings)

        # 7. 更新状态
        doc.chunk_count = len(chunks)
        doc.status = "completed"

        # 更新知识库文档计数
        await db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == kb_id)
            .values(document_count=KnowledgeBase.document_count + 1)
        )

        await db.commit()
        await db.refresh(doc)

        # 刷新 BM25 索引（文档变更后重建）
        try:
            await bm25_service.build_bm25_index(kb_id)
        except Exception:
            pass  # BM25 索引构建失败不影响上传结果

        # 失效 Redis 缓存（知识库内容已变更）
        try:
            from app.services.cache_service import invalidate_kb_cache
            await invalidate_kb_cache(kb_id)
        except Exception:
            pass

        return doc

    except Exception as e:
        doc.status = "failed"
        await db.commit()
        raise e


async def delete_document(db: AsyncSession, doc_id: int, user_id: int = None):
    """删除文档：移除向量 + 文件 + 数据库记录（权限由路由层校验）"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError("文档不存在")

    kb_id = doc.kb_id

    # 删除 Chroma 向量
    await vector_service.delete_document_chunks(kb_id, doc_id)

    # 更新知识库文档计数
    await db.execute(
        update(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id)
        .values(document_count=KnowledgeBase.document_count - 1)
    )

    # 删除数据库记录
    await db.delete(doc)
    await db.commit()

    # 刷新 BM25 索引（文档删除后重建）
    bm25_service.invalidate_cache(kb_id)
    try:
        await bm25_service.build_bm25_index(kb_id)
    except Exception:
        pass

    # 失效 Redis 缓存
    try:
        from app.services.cache_service import invalidate_kb_cache
        await invalidate_kb_cache(kb_id)
    except Exception:
        pass


async def get_documents_by_kb(db: AsyncSession, kb_id: int, user_id: int) -> List[Document]:
    """获取知识库下的所有文档"""
    result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb_id, Document.user_id == user_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())
