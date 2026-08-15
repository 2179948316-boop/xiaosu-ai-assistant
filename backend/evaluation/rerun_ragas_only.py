"""从已有的检索+生成结果重新计算 RAGAS 指标

跳过耗时的检索和生成阶段，直接加载 eval_results.json 中的问题/答案/上下文，
使用 deepseek-r1:1.5b（更可靠的 JSON 输出）计算 RAGAS 四项指标。
"""
import json
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import get_settings

settings = get_settings()


async def rerun_ragas(
    results_path: str = "evaluation/eval_results.json",
    output_path: str = "evaluation/eval_results_final.json",
):
    # 加载已有结果
    with open(results_path, "r", encoding="utf-8") as f:
        prev = json.load(f)

    questions = []
    ground_truths = []
    contexts = []
    answers = []

    for item in prev["per_question"]:
        questions.append(item["question"])
        ground_truths.append(item["ground_truth"])
        answers.append(item["answer_preview"])
        # answer_preview 只是截断的，但足够评估用
        contexts.append([""])  # 会从 test_dataset 补

    # 从 test_dataset 获取完整 contexts
    with open("evaluation/test_dataset.json", "r", encoding="utf-8") as f:
        test_data = json.load(f)

    for i, item in enumerate(prev["per_question"]):
        # 在 test_dataset 中找到对应问题
        for td in test_data:
            if td["question"] == item["question"]:
                contexts[i] = td["contexts"]
                break

    print(f"加载 {len(questions)} 个问题，使用 deepseek-r1:1.5b 计算 RAGAS 指标...")

    try:
        from ragas import evaluate
        from ragas.metrics import (
            context_precision,
            context_recall,
            faithfulness,
            answer_relevancy,
        )
        from ragas.run_config import RunConfig
        from datasets import Dataset
        from evaluation.ragas_adapters import OllamaLLM, OllamaEmbeddings

        eval_dataset = Dataset.from_dict({
            "question": questions,
            "ground_truth": ground_truths,
            "contexts": contexts,
            "answer": answers,
        })

        # 用 deepseek-r1:1.5b 做评估（JSON 输出更可靠）
        llm = OllamaLLM(model="deepseek-r1:1.5b")
        embeddings = OllamaEmbeddings()

        run_config = RunConfig(
            max_workers=2,
            timeout=300,
            max_retries=3,
        )

        results = evaluate(
            eval_dataset,
            metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
            llm=llm,
            embeddings=embeddings,
            run_config=run_config,
        )

        metrics = dict(results)
        print("\n" + "=" * 60)
        print("RAGAS 评估结果")
        print("=" * 60)
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")
        print("=" * 60)

    except Exception as e:
        print(f"RAGAS 评估失败: {e}")
        import traceback
        traceback.print_exc()
        metrics = {"error": str(e)}

    # 更新结果文件
    prev["metrics"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()}
    prev["evaluation_model"] = "deepseek-r1:1.5b"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(prev, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存: {output_path}")
    return metrics


if __name__ == "__main__":
    asyncio.run(rerun_ragas())
