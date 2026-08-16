"""数据库连接管理"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            # 如果 session 已经提交过（例如在 StreamingResponse 场景中），不再重复提交
            # 使用 is_active 检查 session 是否还处于活跃状态
            if session.is_active:
                await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def ensure_schema() -> None:
    """
    启动时保证数据库结构最新（兼容旧库升级）：
    1. create_all 幂等建表 —— 本地开发未执行 init.sql 时兜底
    2. create_all 不会 ALTER 已有表，缺少的列在此手动补齐
    """
    import logging
    from sqlalchemy import inspect, text
    # 延迟导入，避免循环引用（models 依赖 database.Base）
    from app import models  # noqa: F401  确保所有模型注册到 Base.metadata

    logger = logging.getLogger(__name__)

    async with engine.begin() as conn:
        # 1. 幂等建表
        await conn.run_sync(Base.metadata.create_all)

        # 2. 检查 messages.tool_calls 列（v1.1 新增）
        def _has_tool_calls(sync_conn) -> bool:
            columns = inspect(sync_conn).get_columns("messages")
            return any(c["name"] == "tool_calls" for c in columns)

        try:
            has_col = await conn.run_sync(_has_tool_calls)
            if not has_col:
                await conn.execute(
                    text("ALTER TABLE messages ADD COLUMN tool_calls JSON NULL")
                )
                logger.info("数据库迁移: messages 表新增 tool_calls 列")
        except Exception as e:
            # messages 表不存在等异常由 create_all 兜底，此处仅记录
            logger.warning(f"ensure_schema 补列检查跳过: {e}")

        # 3. 检查 conversations.open_id / chat_id 列（v1.2 飞书会话隔离新增）
        def _conversation_columns(sync_conn) -> set:
            return {c["name"] for c in inspect(sync_conn).get_columns("conversations")}

        try:
            conv_cols = await conn.run_sync(_conversation_columns)
            if "open_id" not in conv_cols:
                await conn.execute(
                    text("ALTER TABLE conversations ADD COLUMN open_id VARCHAR(64) NULL")
                )
                await conn.execute(text("CREATE INDEX ix_conversations_open_id ON conversations (open_id)"))
                logger.info("数据库迁移: conversations 表新增 open_id 列")
            if "chat_id" not in conv_cols:
                await conn.execute(
                    text("ALTER TABLE conversations ADD COLUMN chat_id VARCHAR(64) NULL")
                )
                await conn.execute(text("CREATE INDEX ix_conversations_chat_id ON conversations (chat_id)"))
                logger.info("数据库迁移: conversations 表新增 chat_id 列")
        except Exception as e:
            logger.warning(f"ensure_schema conversations 补列检查跳过: {e}")

        # 4. 检查 users.is_admin 列（v1.3 管理后台权限新增）
        def _user_columns(sync_conn) -> set:
            return {c["name"] for c in inspect(sync_conn).get_columns("users")}

        try:
            user_cols = await conn.run_sync(_user_columns)
            if "is_admin" not in user_cols:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0")
                )
                logger.info("数据库迁移: users 表新增 is_admin 列")
        except Exception as e:
            logger.warning(f"ensure_schema users 补列检查跳过: {e}")

        # 5. 检查 messages.token_count 列（v1.3 管理后台 token 统计新增）
        def _message_columns(sync_conn) -> set:
            return {c["name"] for c in inspect(sync_conn).get_columns("messages")}

        try:
            msg_cols = await conn.run_sync(_message_columns)
            if "token_count" not in msg_cols:
                await conn.execute(
                    text("ALTER TABLE messages ADD COLUMN token_count INT NULL")
                )
                logger.info("数据库迁移: messages 表新增 token_count 列")
        except Exception as e:
            logger.warning(f"ensure_schema messages 补列检查跳过: {e}")
