"""自动生成 RAG 评估测试集 - 从 Chroma 知识库文档中生成 QA 对

用法:
    cd backend
    python -m evaluation.generate_testset --kb_id 2 --num_samples 20

输出:
    evaluation/test_dataset.json
"""
import argparse
import asyncio
import json
import random
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services import vector_service
from app.services.llm_service import chat_complete

logger = logging.getLogger(__name__)

QUESTION_GENERATION_PROMPT = """基于以下文档内容，请生成 {num_questions} 个具体的中文问题。
这些问题应该能够根据提供的内容来回答。每个问题单独一行，不要编号，不要加序号。

文档内容：
{context}

请生成 {num_questions} 个问题："""


async def generate_questions_for_chunk(
    chunk_text: str,
    num_questions: int = 2,
) -> list:
    """用 LLM 为文档片段生成问题"""
    prompt = QUESTION_GENERATION_PROMPT.format(
        context=chunk_text, num_questions=num_questions
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await chat_complete(messages)
        questions = [
            line.strip() for line in response.strip().split("\n")
            if line.strip() and len(line.strip()) > 5
        ]
        return questions[:num_questions]
    except Exception as e:
        logger.error(f"问题生成失败: {e}")
        return []


async def generate_test_dataset(
    kb_id: int,
    num_samples: int = 20,
    questions_per_chunk: int = 2,
    output_path: str = "evaluation/test_dataset.json",
):
    """
    自动生成测试数据集:
    1. 从 Chroma 获取知识库文档片段
    2. 随机采样 num_samples 个片段
    3. 为每个片段用 LLM 生成问题
    4. 保存为 JSON
    """
    # 1. 获取文档
    docs = await vector_service.get_all_documents(kb_id)
    if not docs:
        print(f"知识库 {kb_id} 中没有文档")
        return

    print(f"知识库 {kb_id} 共有 {len(docs)} 个文档片段")

    # 2. 过滤 + 采样
    eligible = [d for d in docs if len(d["text"]) > 50]
    samples = random.sample(eligible, min(num_samples, len(eligible)))
    print(f"采样 {len(samples)} 个片段用于生成测试集")

    # 3. 生成 QA 对
    dataset = []
    for i, sample in enumerate(samples):
        print(f"  生成中 [{i+1}/{len(samples)}]...")
        questions = await generate_questions_for_chunk(
            sample["text"], num_questions=questions_per_chunk
        )
        for q in questions:
            dataset.append({
                "question": q,
                "ground_truth": sample["text"],
                "contexts": [sample["text"]],
                "source_id": sample["id"],
                "source_file": sample.get("metadata", {}).get("filename", "unknown"),
            })

    # 4. 保存
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"测试集已保存: {output_path} ({len(dataset)} 个 QA 对)")
    return dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 RAG 评估测试集")
    parser.add_argument("--kb_id", type=int, required=True, help="知识库 ID")
    parser.add_argument("--num_samples", type=int, default=20, help="采样数量")
    parser.add_argument("--questions_per_chunk", type=int, default=2)
    parser.add_argument("--output", type=str, default="evaluation/test_dataset.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(generate_test_dataset(
        kb_id=args.kb_id,
        num_samples=args.num_samples,
        questions_per_chunk=args.questions_per_chunk,
        output_path=args.output,
    ))
