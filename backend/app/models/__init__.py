"""ORM 模型 - 统一导出"""
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, JSON, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    avatar = Column(String(500))
    # Phase 5 管理后台权限：is_admin=1 可访问对话日志/设置（也可通过 .env ADMIN_USERNAMES 配置）
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    knowledge_bases = relationship("KnowledgeBase", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    owned_orgs = relationship("Organization", back_populates="owner", cascade="all, delete-orphan")
    org_memberships = relationship("OrgMember", back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    owner_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    owner = relationship("User", back_populates="owned_orgs")
    members = relationship("OrgMember", back_populates="organization", cascade="all, delete-orphan")
    knowledge_bases = relationship("KnowledgeBase", back_populates="organization")


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uk_org_user"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    org_id = Column(BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), default="member")  # admin / member
    joined_at = Column(DateTime, server_default=func.now())

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="org_memberships")


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id = Column(BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    document_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="knowledge_bases")
    organization = relationship("Organization", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20))
    file_size = Column(BigInteger)
    chunk_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="SET NULL"))
    # 飞书 IM 会话隔离（Phase 4）：open_id=飞书用户，chat_id=飞书 open_chat_id（群/单聊）
    open_id = Column(String(64), index=True)
    chat_id = Column(String(64), index=True)
    title = Column(String(255))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON)
    # Agent 工具调用记录：[{tool, arguments, result_summary}]（Phase 3 使用）
    tool_calls = Column(JSON)
    token_count = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")
