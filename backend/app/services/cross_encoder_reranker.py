"""Cross-Encoder Reranker 服务 - 基于交叉编码器的精排

使用 sentence-transformers 的 CrossEncoder 模型对 (query, document) 对进行联合编码，
比 Bi-Encoder 的余弦相似度更准确地衡量相关性。

模型: BAAI/bge-reranker-v2-m3 (支持中文，~1.1GB)
降级链: bge-reranker-v2-m3 → bge-reranker-base → Bi-Encoder
"""
import logging
import asyncio
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 模块级单例
_reranker = None
_reranker_model_name: Optional[str] = None
_load_failed: bool = False


def _load_cross_encoder(model_name: str = "BAAI/bge-reranker-v2-m3"):
    """
    惰性加载 Cross-Encoder 模型（首次调用时下载）。
    失败时自动降级到 bge-reranker-base，再失败则标记 _load_failed。
    """
    global _reranker, _reranker_model_name, _load_failed

    if _load_failed:
        return None
    if _reranker is not None:
        return _reranker

    try:
        import os
        # 将 HuggingFace 缓存指向 E 盘（避免占用 C 盘空间）
        e_drive_cache = r"E:\.cache\huggingface"
        os.makedirs(e_drive_cache, exist_ok=True)
        os.environ["HF_HOME"] = e_drive_cache
        os.environ["HF_HUB_CACHE"] = os.path.join(e_drive_cache, "hub")
        # Windows 不支持符号链接（需开发者模式），强制使用文件拷贝
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        # 如果未设置 HF_ENDPOINT，使用国内镜像
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            logger.info("使用 HuggingFace 国内镜像: https://hf-mirror.com")

        from sentence_transformers import CrossEncoder

        # 优先从本地缓存加载（不联网检查更新）
        try:
            _reranker = CrossEncoder(model_name, local_files_only=True)
            _reranker_model_name = model_name
            logger.info(f"Cross-Encoder 从本地缓存加载成功: {model_name}")
            return _reranker
        except Exception:
            logger.info("本地缓存未找到模型，尝试在线下载...")

        _reranker = CrossEncoder(model_name)
        _reranker_model_name = model_name
        logger.info(f"Cross-Encoder 模型下载并加载成功: {model_name}")
        return _reranker
    except Exception as e:
        logger.warning(f"Cross-Encoder {model_name} 加载失败: {e}")
        if model_name != "BAAI/bge-reranker-base":
            logger.info("尝试回退到 BAAI/bge-reranker-base ...")
            return _load_cross_encoder("BAAI/bge-reranker-base")
        _load_failed = True
        logger.error("所有 Cross-Encoder 模型均加载失败，将使用 Bi-Encoder 降级")
        return None


async def rerank_by_cross_encoder(
    query: str,
    candidates: List[Dict],
    top_k: int = 3,
) -> List[Dict]:
    """
    Cross-Encoder 重排序。

    对每个 (query, candidate_text) 对进行联合编码，得到精确的相关性分数，
    按分数降序排列后返回 top_k 个结果。

    如果 Cross-Encoder 不可用或推理失败，自动降级为 Bi-Encoder。
    """
    if not candidates:
        return []
    if len(candidates) <= top_k:
        return candidates

    model = _load_cross_encoder()

    if model is None:
        logger.warning("Cross-Encoder 不可用，降级为 Bi-Encoder 重排序")
        from app.services.reranker_service import rerank_by_embedding
        return await rerank_by_embedding(query, candidates, top_k)

    try:
        # 构建 (query, doc) 对
        pairs = [[query, c["text"]] for c in candidates]

        # 在线程池中执行同步推理，避免阻塞 async 事件循环
        scores = await asyncio.to_thread(model.predict, pairs)

        # Cross-Encoder 输出为原始 logits（无界），用 sigmoid 归一化到 0-1，
        # 与向量检索/BM25 的相关度语义保持一致，也便于与拒答阈值比较
        import math
        normalized = [1.0 / (1.0 + math.exp(-float(s))) for s in scores]

        # 附加分数并排序
        scored = []
        for i, candidate in enumerate(candidates):
            scored.append({
                **candidate,
                "rerank_score": round(normalized[i], 4),
                "original_score": candidate.get("score", 0),
            })

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 取 top_k，用 rerank_score 覆盖 score
        result = []
        for item in scored[:top_k]:
            item["score"] = item["rerank_score"]
            item["retrieval_method"] = item.get("retrieval_method", "hybrid")
            result.append(item)

        return result

    except Exception as e:
        logger.error(f"Cross-Encoder 推理失败: {e}，降级为 Bi-Encoder")
        from app.services.reranker_service import rerank_by_embedding
        return await rerank_by_embedding(query, candidates, top_k)


def is_cross_encoder_loaded() -> bool:
    """健康检查：Cross-Encoder 模型是否已加载"""
    return _reranker is not None


def get_model_name() -> Optional[str]:
    """返回当前加载的模型名称"""
    return _reranker_model_name
