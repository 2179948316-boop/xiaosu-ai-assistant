"""BM25 关键词检索服务 - 基于稀疏向量的精确匹配"""
import re
import jieba
from rank_bm25 import BM25Okapi
from typing import List, Dict, Optional
from app.retrieval import vector_service


# 中文停用词表（精简版）
_STOPWORDS = set("的了是在不有和人这中大为上个国我以要他时来用们生到作地于出会也对子可下自之年过发后能都多然没日等起还发已成事只作当想看文无开手十用主行方又如前所本见经头面起公同工己电小数高因提定已变部机给长院正明原将设应全制各管期市表化先次品美该此什从被它最让那名取世什间保系已正清形去质进该正很新最现利什即且被原正很最".split())


def tokenize(text: str) -> List[str]:
    """中英文混合分词"""
    # 使用 jieba 进行中文分词
    words = jieba.lcut(text.lower())
    # 过滤停用词和短词
    return [w.strip() for w in words if w.strip() and len(w.strip()) > 1 and w.strip() not in _STOPWORDS]


class BM25Index:
    """BM25 索引，内存中构建和检索"""

    def __init__(self):
        self._index: Optional[BM25Okapi] = None
        self._documents: List[Dict] = []
        self._kb_id: Optional[int] = None

    @property
    def is_built(self) -> bool:
        return self._index is not None and len(self._documents) > 0

    def build(self, kb_id: int, documents: List[Dict]):
        """
        从文档列表构建 BM25 索引。
        documents: [{"id": str, "text": str, "metadata": dict}, ...]
        """
        if not documents:
            self._index = None
            self._documents = []
            self._kb_id = kb_id
            return

        self._kb_id = kb_id
        self._documents = documents

        # 对每个文档进行分词
        tokenized_corpus = [tokenize(doc["text"]) for doc in documents]
        self._index = BM25Okapi(tokenized_corpus)

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        BM25 检索，返回按分数降序排列的结果。
        """
        if not self.is_built:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = self._index.get_scores(query_tokens)

        # 获取 top_k 结果
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        max_score = max(scores) if max(scores) > 0 else 1.0

        for idx in top_indices:
            if scores[idx] <= 0:
                break
            doc = self._documents[idx]
            results.append({
                "id": doc["id"],
                "text": doc["text"],
                "metadata": doc.get("metadata", {}),
                "score": round(scores[idx] / max_score, 4),  # 归一化到 0-1
                "retrieval_method": "bm25",
            })

        return results


# 全局索引缓存 (kb_id -> BM25Index)
_bm25_cache: Dict[int, BM25Index] = {}


async def build_bm25_index(kb_id: int):
    """
    从 Chroma 加载知识库的所有文档，构建 BM25 索引。
    在文档上传/删除后调用以刷新索引。
    """
    collection = vector_service.get_or_create_collection(kb_id)

    try:
        # 获取 collection 中的所有文档
        all_data = collection.get(include=["documents", "metadatas"])
    except Exception:
        all_data = None

    if not all_data or not all_data["ids"]:
        _bm25_cache[kb_id] = BM25Index()
        _bm25_cache[kb_id].build(kb_id, [])
        return

    documents = []
    for i, doc_id in enumerate(all_data["ids"]):
        documents.append({
            "id": doc_id,
            "text": all_data["documents"][i],
            "metadata": all_data["metadatas"][i] if all_data["metadatas"] else {},
        })

    index = BM25Index()
    index.build(kb_id, documents)
    _bm25_cache[kb_id] = index


def get_bm25_index(kb_id: int) -> Optional[BM25Index]:
    """获取知识库的 BM25 索引"""
    return _bm25_cache.get(kb_id)


async def bm25_search(kb_id: int, query: str, top_k: int = 10) -> List[Dict]:
    """BM25 检索入口"""
    index = _bm25_cache.get(kb_id)
    if not index or not index.is_built:
        # 尝试自动构建
        await build_bm25_index(kb_id)
        index = _bm25_cache.get(kb_id)

    if not index:
        return []

    return index.search(query, top_k=top_k)


def invalidate_cache(kb_id: int):
    """清除知识库的 BM25 缓存（文档变更后调用）"""
    _bm25_cache.pop(kb_id, None)
