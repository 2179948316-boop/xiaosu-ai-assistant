"""Chroma 向量存储服务"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Dict, Optional
from app.config import get_settings
import os

settings = get_settings()

# 初始化 Chroma 客户端（持久化存储）
_persist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "chroma_db")
os.makedirs(_persist_dir, exist_ok=True)

_chroma_client = chromadb.PersistentClient(
    path=_persist_dir,
    settings=ChromaSettings(anonymized_telemetry=False),
)


def get_or_create_collection(kb_id: int):
    """获取或创建知识库对应的 collection"""
    collection_name = f"kb_{kb_id}"
    return _chroma_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )


async def add_chunks(kb_id: int, doc_id: int, chunks: List[Dict], embeddings: List[List[float]]):
    """将文档切片和向量添加到 Chroma"""
    collection = get_or_create_collection(kb_id)

    ids = [f"doc{doc_id}_chunk{c['metadata']['chunk_index']}" for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


async def search_similar(
    kb_id: int,
    query_embedding: List[float],
    top_k: int = 5,
    min_score: float = 0.3,
) -> List[Dict]:
    """
    在知识库中搜索相似片段（纯向量检索）。
    返回按相关度排序的结果列表。
    """
    collection = get_or_create_collection(kb_id)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"][0]:
        return []

    matched = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        similarity = 1 - distance  # cosine distance -> similarity

        if similarity >= min_score:
            matched.append({
                "id": doc_id,
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "score": round(similarity, 4),
                "retrieval_method": "dense",
            })

    return matched


async def search_similar_dense_extended(
    kb_id: int,
    query_embedding: List[float],
    top_k: int = 15,
    min_score: float = 0.1,
) -> List[Dict]:
    """
    扩展向量检索 - 召回更多候选用于后续重排序。
    top_k 默认为 15，min_score 降低到 0.1 以获取更多候选。
    """
    return await search_similar(kb_id, query_embedding, top_k=top_k, min_score=min_score)


async def get_all_documents(kb_id: int) -> List[Dict]:
    """获取知识库中的所有文档（用于构建 BM25 索引）"""
    collection = get_or_create_collection(kb_id)
    try:
        all_data = collection.get(include=["documents", "metadatas"])
        if not all_data or not all_data["ids"]:
            return []
        return [
            {
                "id": doc_id,
                "text": all_data["documents"][i],
                "metadata": all_data["metadatas"][i] if all_data["metadatas"] else {},
            }
            for i, doc_id in enumerate(all_data["ids"])
        ]
    except Exception:
        return []


async def delete_document_chunks(kb_id: int, doc_id: int):
    """删除文档对应的所有向量"""
    collection = get_or_create_collection(kb_id)
    # 通过 metadata 过滤删除
    try:
        collection.delete(where={"doc_id": str(doc_id)})
    except Exception:
        # 如果 collection 为空或删除失败，忽略
        pass


def delete_collection(kb_id: int):
    """删除整个知识库的 collection"""
    try:
        _chroma_client.delete_collection(f"kb_{kb_id}")
    except Exception:
        pass
