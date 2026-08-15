"""Reranker 重排序服务 - 对粗召回结果进行精排"""
from typing import List, Dict
from app.services.embedding_service import get_embeddings


async def rerank_by_embedding(
    query: str,
    candidates: List[Dict],
    top_k: int = 5,
) -> List[Dict]:
    """
    基于 Embedding 的重排序（Bi-Encoder Reranker）。

    原理：对 query 和每个候选文档分别计算 embedding，
    然后用精确的余弦相似度重新排序。
    相比 Chroma 的 ANN 近似检索，这里用的是精确计算，排序更准确。

    参数:
        query: 用户查询
        candidates: 粗召回的候选文档列表（包含 text 字段）
        top_k: 返回的精排结果数量

    返回:
        按精排分数降序排列的 top_k 个结果
    """
    if not candidates:
        return []

    if len(candidates) <= top_k:
        # 候选数量 <= 需要的数量，无需重排
        return candidates

    # 将 query 和所有候选文档一起 embedding
    all_texts = [query] + [c["text"] for c in candidates]

    try:
        embeddings = await get_embeddings(all_texts)
    except Exception:
        # 如果 embedding 失败，降级为原始排序
        return candidates[:top_k]

    query_embedding = embeddings[0]
    doc_embeddings = embeddings[1:]

    # 计算精确余弦相似度
    import math

    def cosine_sim(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # 为每个候选文档计算精排分数
    reranked = []
    for i, candidate in enumerate(candidates):
        sim = cosine_sim(query_embedding, doc_embeddings[i])
        reranked.append({
            **candidate,
            "rerank_score": round(sim, 4),
            "original_score": candidate.get("score", 0),
        })

    # 按精排分数降序排列
    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)

    # 用 rerank_score 替换 score 字段
    result = []
    for item in reranked[:top_k]:
        item["score"] = item["rerank_score"]
        result.append(item)

    return result


def reciprocal_rank_fusion(
    result_lists: List[List[Dict]],
    k: int = 60,
    top_k: int = 10,
) -> List[Dict]:
    """
    Reciprocal Rank Fusion (RRF) - 多路召回结果融合算法。

    将来自不同检索方法（如向量检索、BM25）的结果按排名融合。
    RRF 公式: score(d) = Σ 1/(k + rank_i(d))

    参数:
        result_lists: 多路检索结果列表，每路结果按分数降序排列
        k: RRF 常数（默认60，控制排名衰减速度）
        top_k: 返回的融合结果数量

    返回:
        按 RRF 融合分数降序排列的结果
    """
    # doc_id -> {rrf_score, doc_data}
    doc_scores: Dict[str, Dict] = {}

    for result_list in result_lists:
        for rank, doc in enumerate(result_list):
            doc_id = doc.get("id", str(rank))
            rrf_score = 1.0 / (k + rank + 1)  # rank 从 0 开始

            if doc_id in doc_scores:
                doc_scores[doc_id]["rrf_score"] += rrf_score
                # 保留分数更高的那份数据
                if doc.get("score", 0) > doc_scores[doc_id]["score"]:
                    doc_scores[doc_id].update(doc)
            else:
                doc_scores[doc_id] = {**doc}
                doc_scores[doc_id]["rrf_score"] = rrf_score

            doc_scores[doc_id]["score"] = max(
                doc.get("score", 0),
                doc_scores[doc_id].get("score", 0),
            )

    # 按 RRF 分数降序排列
    sorted_docs = sorted(doc_scores.values(), key=lambda x: x["rrf_score"], reverse=True)

    # 归一化 RRF 分数到 0-1 范围
    if sorted_docs:
        max_rrf = sorted_docs[0]["rrf_score"]
        for doc in sorted_docs:
            doc["score"] = round(doc["rrf_score"] / max_rrf, 4)

    return sorted_docs[:top_k]
