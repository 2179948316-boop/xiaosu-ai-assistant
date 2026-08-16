"""认证路由 - 注册/登录/JWT"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer

from app.database import get_db
from app.config import get_settings
from app.models import User
from app.schemas import UserRegister, UserLogin, UserResponse, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["认证"])
settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """JWT Token 解析，获取当前用户"""
    credentials_exception = HTTPException(status_code=401, detail="无效的认证凭据")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


def is_admin_user(user: User) -> bool:
    """管理员判定（Phase 5）：users.is_admin 字段 或 .env ADMIN_USERNAMES 白名单，满足其一即可"""
    if getattr(user, "is_admin", False):
        return True
    admins = [u.strip() for u in (settings.ADMIN_USERNAMES or "").split(",") if u.strip()]
    return user.username in admins


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """管理后台接口依赖：非管理员直接 403"""
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.post("/register", response_model=UserResponse)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    # 检查用户名是否已存在
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT Token"""
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )
