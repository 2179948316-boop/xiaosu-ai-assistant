"""文档管理路由"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List
from sqlalchemy import select

from app.database import get_db
from app.models import User, Document
from app.schemas import DocumentResponse
from app.routers.auth import get_current_user
from app.routers.knowledge import check_kb_access
from app.services.document_service import process_document_upload, delete_document, get_documents_by_kb
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/documents", tags=["文档管理"])


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
