"""小苏 - 公司内部 AI 助手后端入口"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import traceback
import os

from app.config import get_settings
from app.log_config import setup_logging
from app.routers import auth, knowledge, documents, chat, organizations

settings = get_settings()

# 初始化日志：console + logs/app.log
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保数据目录存在
    base_dir = os.path.dirname(os.path.dirname(__file__))
    os.makedirs(os.path.join(base_dir, "data", "uploads"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "data", "chroma_db"), exist_ok=True)

    # 确保数据库结构最新（建表 + 旧库补列），失败不阻断启动
    try:
        from app.database import ensure_schema
        await ensure_schema()
    except Exception as e:
        print(f"⚠️ 数据库结构检查失败（应用继续启动）: {e}")

    print(f"🚀 {settings.APP_NAME} 启动成功")
    print(f"📡 Ollama: {settings.OLLAMA_BASE_URL}")
    print(f"🤖 LLM: {settings.LLM_MODEL}")
    print(f"📐 Embedding: {settings.EMBEDDING_MODEL}")
    print(f"💾 Redis: {settings.REDIS_URL} (cache={'on' if settings.REDIS_CACHE_ENABLED else 'off'})")
    print(f"🔄 Reranker: Cross-Encoder (bge-reranker-v2-m3, 首次使用时自动加载)")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="公司内部 AI 助手小苏 - RAG 知识库 + Agent 工具调用",
    lifespan=lifespan,
)

# CORS - 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175", "http://localhost:5177", "http://localhost:3000", "http://127.0.0.1:5173", "http://127.0.0.1:5175", "http://127.0.0.1:5177"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理 - 打印详细错误方便调试
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {str(exc)}"},
    )

# 注册路由
app.include_router(auth.router)
app.include_router(knowledge.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(organizations.router)


@app.get("/api/health")
async def health_check():
    from app.services.cache_service import get_cache_stats
    from app.services import cross_encoder_reranker as _ce_mod
    cache_stats = await get_cache_stats()
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "cache": cache_stats,
        "reranker": {
            "type": "cross_encoder" if _ce_mod.is_cross_encoder_loaded() else "bi_encoder",
            "model": _ce_mod.get_model_name() or "pending (loaded on first request)",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
