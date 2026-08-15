"""完整 RAGAS 评估 - 检索+生成用 qwen3:4b，RAGAS 指标用 deepseek-r1:1.5b

用法:
    cd backend
    python -m evaluation.run_eval_split
"""
import asyncio
import json
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import get_settings
from app.services.embedding_service import get_embedding
from app.services import vector_service
from app.services.bm25_service import bm25_search
from app.services.reranker_service import reciprocal_rank_fusion
from app.services.cross_encoder_reranker import rerank_by_cross_encoder
from app.services.llm_service import chat_complete
from app.services.rag_service import SYSTEM_PROMPT, build_context_prompt

logger = logging.getLogger(__name__)
settings = get_settings()


async def retrieve_for_question(kb_id, question, dense_top_k=20, bm25_top_k=10, rerank_top_k=3):
    query_embedding = await get_embedding(question)
    dense_results = await vector_service.search_similar_dense_extended(
        kb_id=kb_id, query_embedding=query_embedding, top_k=dense_top_k, min_score=0.1,
    )
    bm25_results = await bm25_search(kb_id=kb_id, query=question, top_k=bm25_top_k)
    result_lists = [r for r in [dense_results, bm25_results] if r]
    fused = reciprocal_rank_fusion(result_lists, k=60, top_k=20) if result_lists else []
    if fused:
        sources = await rerank_by_cross_encoder(question, fused, top_k=rerank_top_k)
    else:
        sources = []
    return sources


async def generate_answer(sources, question):
    context = build_context_prompt(sources)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"参考资料：\n{context}"},
        {"role": "user", "content": question},
    ]
    return await chat_complete(messages)


async def main():
    kb_id = 2
    max_questions = 4
    output_path = "evaluation/eval_results_final.json"

    # 1. 加载测试集
    with open("evaluation/test_dataset.json", "r", encoding="utf-8") as f:
        test_data = json.load(f)
    test_data = test_data[:max_questions]

    print(f"评估数据集: {len(test_data)} 个问题, kb_id={kb_id}")

    # 2. 检索+生成（用 qwen3:4b，通过 LLM_MODEL 环境变量）
    questions, ground_truths, retrieved_contexts, generated_answers = [], [], [], []

    for i, item in enumerate(test_data):
        print(f"  [{i+1}/{len(test_data)}]: {item['question'][:50]}...")
        start = time.time()
        sources = await retrieve_for_question(kb_id, item["question"])
        contexts_list = [s["text"] for s in sources] if sources else [""]
        answer = await generate_answer(sources, item["question"])
        elapsed = time.time() - start
        print(f"    检索 {len(sources)} 条, 答案 {len(answer)} 字, 耗时 {elapsed:.1f}s")
        questions.append(item["question"])
        ground_truths.append(item["ground_truth"])
        retrieved_contexts.append(contexts_list)
        generated_answers.append(answer)

    # 3. RAGAS 评估（用 deepseek-r1:1.5b）
    print("\n计算 RAGAS 指标 (deepseek-r1:1.5b)...")
    metrics = {}

    try:
        from ragas import evaluate
        from ragas.metrics import context_precision, context_recall, faithfulness, answer_relevancy
        from ragas.run_config import RunConfig
        from datasets import Dataset
        from evaluation.ragas_adapters import OllamaLLM, OllamaEmbeddings

        eval_dataset = Dataset.from_dict({
            "question": questions,
            "ground_truth": ground_truths,
            "contexts": retrieved_contexts,
            "answer": generated_answers,
        })

        run_config = RunConfig(max_workers=2, timeout=300, max_retries=3)
        results = evaluate(
            eval_dataset,
            metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
            llm=OllamaLLM(model="deepseek-r1:1.5b"),
            embeddings=OllamaEmbeddings(),
            run_config=run_config,
        )
        # RAGAS 0.4.x 返回 EvaluationResult，不能直接 dict()
        # 尝试多种方式提取指标
        metrics = {}
        try:
            # 方式1: 从 DataFrame 提取
            df = results.to_pandas()
            print(f"RAGAS DataFrame 列: {list(df.columns)}")
            for col in df.columns:
                if col in ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]:
                    metrics[col] = float(df[col].mean())
        except Exception as e1:
            try:
                # 方式2: 直接属性
                for name in ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]:
                    if hasattr(results, name):
                        metrics[name] = float(getattr(results, name))
            except Exception as e2:
                # 方式3: scores_dict
                try:
                    if hasattr(results, '_scores_dict'):
                        metrics = {k: float(v) for k, v in results._scores_dict.items()}
                    elif hasattr(results, 'scores'):
                        metrics = {k: float(v) for k, v in results.scores.items()}
                except Exception as e3:
                    print(f"所有提取方式均失败: {e1}, {e2}, {e3}")
                    metrics = {"error": f"extraction failed: {e1}"}

    except Exception as e:
        print(f"RAGAS 评估失败: {e}")
        import traceback
        traceback.print_exc()
        metrics = {"error": str(e)}

    # 4. 报告
    report = {
        "kb_id": kb_id,
        "num_questions": len(questions),
        "generation_model": settings.LLM_MODEL,
        "evaluation_model": "deepseek-r1:1.5b",
        "metrics": {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
        "per_question": [
            {
                "question": q,
                "ground_truth": gt[:300],
                "retrieved_count": len(ctx),
                "answer": a,
            }
            for q, gt, ctx, a in zip(questions, ground_truths, retrieved_contexts, generated_answers)
        ],
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("RAG 评估报告")
    print("=" * 60)
    print(f"知识库 ID: {kb_id}")
    print(f"生成模型: {settings.LLM_MODEL}")
    print(f"评估模型: deepseek-r1:1.5b")
    print(f"评估问题数: {len(questions)}")
    print("-" * 40)
    if "error" not in metrics:
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    else:
        print(f"  评估失败: {metrics['error']}")
    print("=" * 60)
    print(f"详细报告: {output_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
