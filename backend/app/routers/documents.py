"""文档管理路由"""
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import List
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models import User, Document, KnowledgeBase
from app.schemas import DocumentResponse
from app.routers.auth import get_current_user
from app.routers.knowledge import check_kb_access
from app.services.document_service import process_document_upload, delete_document, get_documents_by_kb
from app.retrieval import vector_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/documents", tags=["文档管理"])
settings = get_settings()


class BatchDeleteRequest(BaseModel):
    doc_ids: List[int]


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    上传文档到知识库。
    自动执行：解析 → 切片 → 向量化 → 存储
    支持格式：PDF, DOCX, HTML, TXT, Markdown
    同名文件重复上传将替换旧版本（增量更新）
    权限：知识库所有者或所属组织成员均可上传
    """
    # 校验知识库访问权限（个人/组织成员）
    await check_kb_access(db, kb_id, user.id)

    allowed_types = {"pdf", "docx", "html", "htm", "txt", "md", "markdown"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，支持: {', '.join(allowed_types)}")

    try:
        doc = await process_document_upload(db, file, kb_id, user.id)
        return doc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")


@router.get("/{kb_id}", response_model=List[DocumentResponse])
async def list_documents(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取知识库下的文档列表（组织成员可见所有文档）"""
    # 校验知识库访问权限
    await check_kb_access(db, kb_id, user.id)

    # 组织知识库：显示该 KB 下所有文档（不限 user_id）
    result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/{doc_id}")
async def remove_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除文档（同时删除向量数据和文件），需要知识库访问权限"""
    # 先找到文档所属的知识库
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 校验知识库访问权限
    await check_kb_access(db, doc.kb_id, user.id)

    try:
        await delete_document(db, doc_id, user.id)
        return {"message": "文档已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch-delete")
async def batch_remove_documents(
    req: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量删除文档（同时删除向量数据和文件）。"""
    if not req.doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids 不能为空")

    result = await db.execute(select(Document).where(Document.id.in_(req.doc_ids)))
    docs = list(result.scalars().all())

    if not docs:
        raise HTTPException(status_code=404, detail="未找到任何匹配的文档")

    # 校验所有文档属于同一个知识库，且有权限
    kb_ids = {doc.kb_id for doc in docs}
    if len(kb_ids) > 1:
        raise HTTPException(status_code=400, detail="批量删除的文档必须属于同一个知识库")
    await check_kb_access(db, next(iter(kb_ids)), user.id)

    success = 0
    errors = []
    for doc in docs:
        try:
            await delete_document(db, doc.id, user.id)
            success += 1
        except Exception as e:
            errors.append({"doc_id": doc.id, "filename": doc.filename, "error": str(e)})

    return {"message": f"成功删除 {success} 个文档", "success_count": success, "errors": errors}


@router.get("/{doc_id}/preview")
async def preview_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取文档全文预览（含 chunk 列表，用于前端高亮定位）。"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    await check_kb_access(db, doc.kb_id, user.id)

    # 读取缓存的解析文本
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "uploads", str(doc.kb_id))
    parsed_path = os.path.join(upload_dir, f"{doc.filename}.parsed.txt")
    if not os.path.exists(parsed_path):
        raise HTTPException(status_code=404, detail="文档预览暂不可用（请重新上传）")

    with open(parsed_path, "r", encoding="utf-8") as f:
        full_text = f.read()

    # 从 ChromaDB 获取该文档所有 chunks
    try:
        all_docs = await vector_service.get_all_documents(doc.kb_id)
        chunks = [
            {"chunk_index": int(d["metadata"].get("chunk_index", 0)), "text": d["text"]}
            for d in all_docs if d["metadata"].get("doc_id") == str(doc_id)
        ]
        chunks.sort(key=lambda c: c["chunk_index"])
    except Exception:
        chunks = []

    return {
        "filename": doc.filename,
        "full_text": full_text,
        "chunks": chunks,
    }
