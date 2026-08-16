"""应用配置模块"""
from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # 应用配置
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_NAME: str = "小苏 - 公司内部 AI 助手"

    # 数据库配置
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "123456"
    DB_NAME: str = "rag_knowledge_base"

    # JWT 配置
    SECRET_KEY: str = "rag-knowledge-base-secret-key-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Ollama 配置（本地模式）
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "deepseek-r1:1.5b"
    EMBEDDING_MODEL: str = "nomic-embed-text"

    # LLM 提供商选择: "ollama" 或 "openai"
    LLM_PROVIDER: str = "ollama"

    # OpenAI 兼容 API 配置（适用于 MiniMax/DeepSeek/SiliconFlow/OpenAI 等）
    OPENAI_BASE_URL: str = "https://api.minimax.chat/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_LLM_MODEL: str = "MiniMax-Text-01"
    OPENAI_EMBEDDING_MODEL: str = ""  # 留空则 Embedding 仍用 Ollama

    # Embedding 提供商选择: "ollama" 或 "openai"（独立于 LLM_PROVIDER）
    EMBEDDING_PROVIDER: str = "ollama"

    # Chroma 配置
    CHROMA_PERSIST_DIR: str = "../data/chroma_db"
    CHROMA_COLLECTION_NAME: str = "knowledge_chunks"

    # Redis 缓存配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600          # 缓存 TTL（秒），默认 1 小时
    REDIS_CACHE_ENABLED: bool = True     # 缓存总开关

    # RAG 问答配置
    # 拒答硬阈值：精排后 top1 相关度低于该值时不调用 LLM，直接返回拒答文案
    # 所有检索路径的相关度均已归一化到 0-1（Cross-Encoder 输出经 sigmoid 归一）
    REFUSAL_SCORE_THRESHOLD: float = 0.35

    # Agent 工具调用配置
    AGENT_MAX_ROUNDS: int = 5            # 工具调用循环最大轮数
    AGENT_HISTORY_LIMIT: int = 6         # 多轮记忆：回填给 LLM 的最近消息条数
    MOCK_API_BASE: str = "http://127.0.0.1:8000"  # mock 数据服务（工具执行器内部调用）

    # 飞书机器人配置（Phase 4）
    FEISHU_APP_ID: str = ""              # 飞书开放平台应用 App ID
    FEISHU_APP_SECRET: str = ""          # 飞书开放平台应用 App Secret
    FEISHU_ENCRYPT_KEY: str = ""         # 事件订阅 Encrypt Key（长连接模式可留空）
    FEISHU_VERIFICATION_TOKEN: str = ""  # 事件订阅 Verification Token（长连接模式可留空）
    FEISHU_DEFAULT_KB_ID: int = 0        # 机器人默认查询的知识库 ID（0=自动选第一个）
    BOT_IDEMPOTENCY_TTL: int = 300       # 消息幂等去重窗口（秒）

    # 管理后台配置（Phase 5）
    # 逗号分隔的额外管理员用户名（配合 users.is_admin 字段；两者满足其一即管理员）
    ADMIN_USERNAMES: str = ""
    # 设置页可切换的 LLM 模型白名单（逗号分隔）
    LLM_MODEL_WHITELIST: str = "deepseek-r1:1.5b,MiniMax-Text-01"
    # 机器人心跳文件（相对 backend 目录），由 bot_service 定时写入，管理后台读取判断在线
    BOT_HEARTBEAT_FILE: str = "../data/bot_heartbeat.json"

    # 文件上传配置
    UPLOAD_DIR: str = "../data/uploads"
    MAX_FILE_SIZE_MB: int = 50

    @property
    def DATABASE_URL(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        return f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 容忍 .env 中的额外变量（如 Docker 注入的 REDIS_HOST）


@lru_cache()
def get_settings() -> Settings:
    return Settings()
