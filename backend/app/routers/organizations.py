"""组织管理路由 - 创建组织、邀请成员、成员管理"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models import User, Organization, OrgMember
from app.schemas import OrgCreate, OrgResponse, OrgMemberAdd, OrgMemberResponse
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/organizations", tags=["组织管理"])


async def _get_org_or_404(db: AsyncSession, org_id: int) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="组织不存在")
    return org


async def _check_admin(db: AsyncSession, org_id: int, user_id: int):
    """校验当前用户是否为组织 admin"""
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
            OrgMember.role == "admin",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="需要管理员权限")


async def _check_member(db: AsyncSession, org_id: int, user_id: int):
    """校验当前用户是否为组织成员"""
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="非组织成员")


@router.post("", response_model=OrgResponse)
async def create_organization(
    data: OrgCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建组织，创建者自动成为 admin"""
    org = Organization(
        name=data.name,
        description=data.description,
        owner_id=user.id,
    )
    db.add(org)
    await db.flush()

    # 创建者自动加入为 admin
    member = OrgMember(org_id=org.id, user_id=user.id, role="admin")
    db.add(member)
    await db.flush()
    await db.refresh(org)

    return OrgResponse(
        id=org.id,
        name=org.name,
        description=org.description,
        owner_id=org.owner_id,
        member_count=1,
        created_at=org.created_at,
    )


@router.get("", response_model=List[OrgResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前用户所属的所有组织"""
    # 子查询：用户加入的所有 org_id
    subq = select(OrgMember.org_id).where(OrgMember.user_id == user.id).scalar_subquery()
    result = await db.execute(
        select(Organization).where(Organization.id.in_(subq)).order_by(Organization.created_at.desc())
    )
    orgs = list(result.scalars().all())

    # 批量查询成员数
    responses = []
    for org in orgs:
        count_result = await db.execute(
            select(func.count()).select_from(OrgMember).where(OrgMember.org_id == org.id)
        )
        member_count = count_result.scalar() or 0
        responses.append(OrgResponse(
            id=org.id,
            name=org.name,
            description=org.description,
            owner_id=org.owner_id,
            member_count=member_count,
            created_at=org.created_at,
        ))
    return responses


@router.get("/{org_id}/members", response_model=List[OrgMemberResponse])
async def list_members(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取组织成员列表"""
    await _check_member(db, org_id, user.id)

    result = await db.execute(
        select(OrgMember, User.username)
        .join(User, OrgMember.user_id == User.id)
        .where(OrgMember.org_id == org_id)
        .order_by(OrgMember.joined_at.asc())
    )
    rows = result.all()
    return [
        OrgMemberResponse(
            id=member.id,
            user_id=member.user_id,
            username=username,
            role=member.role,
            joined_at=member.joined_at,
        )
        for member, username in rows
    ]


@router.post("/{org_id}/members", response_model=OrgMemberResponse)
async def add_member(
    org_id: int,
    data: OrgMemberAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """邀请成员加入组织（仅 admin）"""
    await _check_admin(db, org_id, user.id)

    # 查找目标用户
    result = await db.execute(select(User).where(User.username == data.username))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail=f"用户 '{data.username}' 不存在")

    # 检查是否已是成员
    existing = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == target_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该用户已是组织成员")

    member = OrgMember(org_id=org_id, user_id=target_user.id, role=data.role)
    db.add(member)
    await db.flush()
    await db.refresh(member)

    return OrgMemberResponse(
        id=member.id,
        user_id=target_user.id,
        username=target_user.username,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.delete("/{org_id}/members/{member_user_id}")
async def remove_member(
    org_id: int,
    member_user_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """移除组织成员（仅 admin，不能移除自己）"""
    await _check_admin(db, org_id, user.id)

    if member_user_id == user.id:
        raise HTTPException(status_code=400, detail="不能移除自己，请转让管理员后再退出")

    result = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == member_user_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="该用户不是组织成员")

    await db.delete(member)
    await db.commit()
    return {"message": "成员已移除"}


@router.delete("/{org_id}")
async def delete_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除组织（仅 owner）"""
    org = await _get_org_or_404(db, org_id)
    if org.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有创建者可以删除组织")

    await db.delete(org)
    await db.commit()
    return {"message": "组织已删除"}
