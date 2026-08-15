"""知识库管理路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_
from typing import List

from app.database import get_db
from app.models import User, KnowledgeBase, OrgMember, Organization
from app.schemas import KBCreate, KBResponse
from app.routers.auth import get_current_user
from app.services import vector_service

router = APIRouter(prefix="/api/knowledge-bases", tags=["知识库"])


# ============ 权限辅助函数（供 documents / chat 路由复用） ============

async def get_user_org_ids(db: AsyncSession, user_id: int) -> List[int]:
    """获取用户所属的所有组织 ID"""
    result = await db.execute(
        select(OrgMember.org_id).where(OrgMember.user_id == user_id)
    )
    return [row[0] for row in result.all()]


async def check_kb_access(db: AsyncSession, kb_id: int, user_id: int) -> KnowledgeBase:
    """
    校验用户是否有权访问该知识库（读取级别）。
    - 个人知识库：user_id 匹配
    - 组织知识库：用户是该组织成员
    返回 KnowledgeBase 对象，无权限则抛 404。
    """
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 个人知识库
    if kb.org_id is None:
        if kb.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问该知识库")
        return kb

    # 组织知识库：检查成员资格
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == kb.org_id,
            OrgMember.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="无权访问该知识库，您不是该组织成员")
    return kb


async def check_kb_admin(db: AsyncSession, kb: KnowledgeBase, user_id: int) -> None:
    """
    校验用户是否有知识库管理权限（写入/删除级别）。
    - 个人知识库：必须是创建者
    - 组织知识库：必须是组织 admin
    """
    if kb.org_id is None:
        if kb.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权管理该知识库")
        return

    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == kb.org_id,
            OrgMember.user_id == user_id,
            OrgMember.role == "admin",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="需要组织管理员权限")


# ============ 路由 ============

@router.get("", response_model=List[KBResponse])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前用户可见的知识库列表（个人 + 所属组织）"""
    org_ids = await get_user_org_ids(db, user.id)

    # 个人知识库 + 组织知识库
    conditions = [
        KnowledgeBase.org_id.is_(None),
        KnowledgeBase.user_id == user.id,
    ]
    if org_ids:
        conditions.append(KnowledgeBase.org_id.in_(org_ids))

    # 使用 or_ 组合：(个人) OR (在用户所属组织中)
    personal_cond = (KnowledgeBase.org_id.is_(None)) & (KnowledgeBase.user_id == user.id)
    if org_ids:
        org_cond = KnowledgeBase.org_id.in_(org_ids)
        where_clause = or_(personal_cond, org_cond)
    else:
        where_clause = personal_cond

    result = await db.execute(
        select(KnowledgeBase)
        .where(where_clause)
        .order_by(KnowledgeBase.created_at.desc())
    )
    kbs = list(result.scalars().all())

    # 批量获取组织名称
    org_name_map = {}
    kb_org_ids = {kb.org_id for kb in kbs if kb.org_id}
    if kb_org_ids:
        org_result = await db.execute(
            select(Organization).where(Organization.id.in_(kb_org_ids))
        )
        org_name_map = {org.id: org.name for org in org_result.scalars().all()}

    # 构造响应（附带 org_name）
    responses = []
    for kb in kbs:
        resp = KBResponse(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            org_id=kb.org_id,
            org_name=org_name_map.get(kb.org_id) if kb.org_id else None,
            document_count=kb.document_count,
            created_at=kb.created_at,
        )
        responses.append(resp)
    return responses


@router.post("", response_model=KBResponse)
async def create_knowledge_base(
    data: KBCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建知识库（可选绑定组织，需要组织管理员权限）"""
    org_id = data.org_id

    if org_id:
        # 验证用户是该组织的 admin
        result = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == user.id,
                OrgMember.role == "admin",
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="需要组织管理员权限才能创建组织知识库")

    kb = KnowledgeBase(
        user_id=user.id,
        org_id=org_id,
        name=data.name,
        description=data.description,
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)

    # 获取组织名称
    org_name = None
    if org_id:
        org_result = await db.execute(
            select(Organization.name).where(Organization.id == org_id)
        )
        org_name = org_result.scalar_one_or_none()

    return KBResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        org_id=kb.org_id,
        org_name=org_name,
        document_count=kb.document_count,
        created_at=kb.created_at,
    )


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除知识库及其所有向量数据（需要管理权限）"""
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 权限校验：个人→创建者，组织→admin
    await check_kb_admin(db, kb, user.id)

    # 删除 Chroma collection
    vector_service.delete_collection(kb_id)

    await db.delete(kb)
    await db.commit()
    return {"message": "知识库已删除"}
