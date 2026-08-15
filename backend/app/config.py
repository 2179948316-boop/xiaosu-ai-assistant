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
