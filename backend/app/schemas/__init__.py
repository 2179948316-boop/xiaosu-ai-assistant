"""Pydantic Schema 定义 - 统一导出"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


# ============ 用户相关 ============

class UserRegister(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    avatar: Optional[str] = None
    is_admin: bool = False
    created_at: datetime

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============ 组织相关 ============

class OrgCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None

class OrgResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    owner_id: int
    member_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True

class OrgMemberAdd(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    role: str = Field(default="member", pattern="^(admin|member)$")

class OrgMemberResponse(BaseModel):
    id: int
    user_id: int
    username: str
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


# ============ 知识库相关 ============

class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    org_id: Optional[int] = None  # 不传则为个人私有知识库

class KBResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    org_id: Optional[int] = None
    org_name: Optional[str] = None
    document_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ============ 文档相关 ============

class DocumentResponse(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: int = 0
    status: str = "pending"
    created_at: datetime

    class Config:
        from_attributes = True


# ============ 对话相关 ============

class ConversationCreate(BaseModel):
    kb_id: Optional[int] = None
    title: Optional[str] = None

class ConversationResponse(BaseModel):
    id: int
    kb_id: Optional[int] = None
    title: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    sources: Optional[list] = None
    tool_calls: Optional[list] = None
    token_count: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    kb_id: int
    message: str = Field(..., min_length=1, max_length=2000)

class ChatStreamResponse(BaseModel):
    type: str  # "chunk" | "sources" | "done" | "error"
    content: Optional[str] = None
    sources: Optional[list] = None
    conversation_id: Optional[int] = None
    message_id: Optional[int] = None
