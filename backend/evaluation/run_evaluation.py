"""RAGAS 评估脚本 - 计算 RAG 系统的核心指标

用法:
    cd backend
    python -m evaluation.run_evaluation --kb_id 2

输出:
    evaluation/results/eval_results.json

指标:
    - context_precision: 检索到的上下文与答案的精确度
    - context_recall:    检索到的上下文对标准答案的覆盖度
    - faithfulness:      生成答案对检索上下文的忠实度
    - answer_relevancy:  生成答案与问题的相关性
"""
import argparse
import asyncio
import json
import logging
import sys
import os
import time
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import get_settings
from app.services.embedding_service import get_embedding
from app.retrieval import vector_service
from app.retrieval.bm25_service import bm25_search
from app.retrieval.reranker_service import reciprocal_rank_fusion
from app.retrieval.cross_encoder_reranker import rerank_by_cross_encoder
from app.services.llm_service import chat_complete
from app.retrieval.rag_service import SYSTEM_PROMPT, build_context_prompt

logger = logging.getLogger(__name__)
settings = get_settings()


async def retrieve_for_question(
    kb_id: int,
    question: str,
    dense_top_k: int = 20,
    bm25_top_k: int = 10,
    rerank_top_k: int = 3,
) -> List[Dict]:
    """对单个问题执行完整检索管线"""
    query_embedding = await get_embedding(question)

    dense_results = await vector_service.search_similar_dense_extended(
        kb_id=kb_id, query_embedding=query_embedding,
        top_k=dense_top_k, min_score=0.1,
    )
    bm25_results = await bm25_search(kb_id=kb_id, query=question, top_k=bm25_top_k)

    result_lists = [r for r in [dense_results, bm25_results] if r]
    fused = reciprocal_rank_fusion(result_lists, k=60, top_k=20) if result_lists else []

    if fused:
        sources = await rerank_by_cross_encoder(question, fused, top_k=rerank_top_k)
    else:
        sources = []

    return sources


async def generate_answer(sources: List[Dict], question: str) -> str:
    """基于检索结果生成 LLM 回答"""
    context = build_context_prompt(sources)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"参考资料：\n{context}"},
        {"role": "user", "content": question},
    ]
    return await chat_complete(messages)


async def run_evaluation(
    kb_id: int,
    test_dataset_path: str = "evaluation/results/test_dataset.json",
    output_path: str = "evaluation/results/eval_results.json",
    max_questions: int = None,
):
    """
    执行完整 RAGAS 评估:
    1. 加载测试集
    2. 对每个问题运行检索+生成
    3. 计算 RAGAS 指标
    4. 输出报告
    """
    # 1. 加载测试集
    with open(test_dataset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)

    if max_questions:
        test_data = test_data[:max_questions]

    print(f"评估数据集: {len(test_data)} 个问题, kb_id={kb_id}")

    # 2. 运行检索+生成
    questions = []
    ground_truths = []
    retrieved_contexts = []
    generated_answers = []

    for i, item in enumerate(test_data):
        print(f"  评估 [{i+1}/{len(test_data)}]: {item['question'][:50]}...")
        start = time.time()

        sources = await retrieve_for_question(kb_id, item["question"])
        contexts = [s["text"] for s in sources] if sources else [""]

        answer = await generate_answer(sources, item["question"])

        elapsed = time.time() - start
        print(f"    检索到 {len(sources)} 条, 耗时 {elapsed:.1f}s")

        questions.append(item["question"])
        ground_truths.append(item["ground_truth"])
        retrieved_contexts.append(contexts)
        generated_answers.append(answer)

    # 3. 计算 RAGAS 指标
    print("\n计算 RAGAS 指标...")
    metrics = {}

    try:
        from ragas import evaluate
        from ragas.metrics import (
            context_precision,
            context_recall,
            faithfulness,
            answer_relevancy,
        )
        from datasets import Dataset
        from evaluation.ragas_adapters import RagasLLM, RagasEmbeddings

        eval_dataset = Dataset.from_dict({
            "question": questions,
            "ground_truth": ground_truths,
            "contexts": retrieved_contexts,
            "answer": generated_answers,
        })

        from ragas.run_config import RunConfig

        run_config = RunConfig(
            max_workers=2,
            timeout=300,
            max_retries=2,
        )

        results = evaluate(
            eval_dataset,
            metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
            llm=RagasLLM(),
            embeddings=RagasEmbeddings(),
            run_config=run_config,
        )

        metrics = {}
        try:
            df = results.to_pandas()
            for col in df.columns:
                if col in ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]:
                    metrics[col] = float(df[col].mean())
        except Exception:
            try:
                for name in ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]:
                    if hasattr(results, name):
                        metrics[name] = float(getattr(results, name))
            except Exception:
                if hasattr(results, '_scores_dict'):
                    metrics = {k: float(v) for k, v in results._scores_dict.items()}

    except ImportError as e:
        logger.error(f"RAGAS 未安装: {e}。请运行 pip install ragas datasets")
        metrics = {"error": f"ragas not installed: {e}"}
    except Exception as e:
        logger.error(f"RAGAS 评估失败: {e}")
        metrics = {"error": str(e)}

    # 4. 构建报告
    report = {
        "kb_id": kb_id,
        "num_questions": len(questions),
        "metrics": {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
        "per_question": [
            {
                "question": q,
                "ground_truth": gt[:200],
                "retrieved_count": len(ctx),
                "answer_preview": a[:200],
            }
            for q, gt, ctx, a in zip(questions, ground_truths, retrieved_contexts, generated_answers)
        ],
    }

    # 保存报告
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print("\n" + "=" * 60)
    print("RAG 评估报告")
    print("=" * 60)
    print(f"知识库 ID: {kb_id}")
    print(f"评估问题数: {len(questions)}")
    print("-" * 40)
    if "error" not in metrics:
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    else:
        print(f"  评估失败: {metrics['error']}")
    print("=" * 60)
    print(f"详细报告已保存: {output_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 系统 RAGAS 评估")
    parser.add_argument("--kb_id", type=int, required=True)
    parser.add_argument("--testset", type=str, default="evaluation/results/test_dataset.json")
    parser.add_argument("--output", type=str, default="evaluation/results/eval_results.json")
    parser.add_argument("--max_questions", type=int, default=None, help="限制评估问题数")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_evaluation(
        kb_id=args.kb_id,
        test_dataset_path=args.testset,
        output_path=args.output,
        max_questions=args.max_questions,
    ))
