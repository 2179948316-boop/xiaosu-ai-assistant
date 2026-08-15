"""重建知识库向量数据 + 运行 RAGAS 评估的完整流程"""
import asyncio
import sys
import os
import logging

# 设置路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def rebuild_kb():
    """从 test_docs 重建 KB #2 的向量数据"""
    import pymysql
    from app.utils.file_parser import parse_file, get_file_type
    from app.utils.text_splitter import split_text
    from app.services.embedding_service import get_embeddings
    from app.retrieval import vector_service

    kb_id = 2
    user_id = 1
    test_docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_docs")

    # 获取 KB #2 的文档列表（MySQL 中已有记录）
    conn = pymysql.connect(host="localhost", port=3306, user="root", password="123456", database="rag_knowledge_base")
    cur = conn.cursor()
    cur.execute("SELECT id, filename, file_type, chunk_count FROM documents WHERE kb_id=%s", (kb_id,))
    db_docs = cur.fetchall()
    conn.close()

    print(f"MySQL 中 KB #{kb_id} 有 {len(db_docs)} 个文档")

    # 映射 test_docs 文件名到 MySQL 记录
    test_files = os.listdir(test_docs_dir)
    print(f"test_docs/ 中有 {len(test_files)} 个文件: {test_files}")

    total_chunks = 0
    for doc_id, filename, file_type, expected_chunks in db_docs:
        # 找到对应的测试文件
        file_path = os.path.join(test_docs_dir, filename)
        if not os.path.exists(file_path):
            # 尝试模糊匹配
            matches = [f for f in test_files if filename.startswith(f.split('.')[0][:4]) or f.startswith(filename.split('.')[0][:4])]
            if matches:
                file_path = os.path.join(test_docs_dir, matches[0])
            else:
                print(f"  [SKIP] 找不到文件: {filename}")
                continue

        print(f"  处理 [{doc_id}] {filename}...")

        # 解析文件
        text = parse_file(file_path, file_type)
        if not text.strip():
            print(f"    [WARN] 文件内容为空")
            continue

        # 文本切片
        chunks = split_text(text, chunk_size=500, chunk_overlap=50, doc_id=doc_id, filename=filename)
        if not chunks:
            print(f"    [WARN] 切片后无有效内容")
            continue

        # 向量化
        print(f"    切片数: {len(chunks)}, 正在向量化...")
        texts = [c["text"] for c in chunks]
        embeddings = await get_embeddings(texts)

        # 存入 Chroma
        await vector_service.add_chunks(kb_id, doc_id, chunks, embeddings)
        total_chunks += len(chunks)
        print(f"    [OK] {len(chunks)} 个向量已存入 Chroma")

    print(f"\n重建完成: 共 {total_chunks} 个向量")

    # 验证
    docs = await vector_service.get_all_documents(kb_id)
    print(f"验证: Chroma 中有 {len(docs)} 个文档片段")
    return len(docs) > 0


async def run_generate_testset(kb_id=2, num_samples=10):
    """生成测试集"""
    from evaluation.generate_testset import generate_test_dataset
    print(f"\n{'='*60}")
    print(f"生成测试集 (kb_id={kb_id}, num_samples={num_samples})")
    print(f"{'='*60}")
    await generate_test_dataset(
        kb_id=kb_id,
        num_samples=num_samples,
        questions_per_chunk=2,
        output_path="evaluation/results/test_dataset.json",
    )


async def run_eval(kb_id=2, max_questions=8):
    """运行评估"""
    from evaluation.run_evaluation import run_evaluation
    print(f"\n{'='*60}")
    print(f"运行 RAGAS 评估 (kb_id={kb_id}, max_questions={max_questions})")
    print(f"{'='*60}")
    await run_evaluation(
        kb_id=kb_id,
        test_dataset_path="evaluation/results/test_dataset.json",
        output_path="evaluation/results/eval_results.json",
        max_questions=max_questions,
    )


async def main():
    print("=" * 60)
    print("RAG 评估完整流程")
    print("=" * 60)

    # Step 1: 重建向量
    print("\n[Step 1] 重建 ChromaDB 向量数据...")
    ok = await rebuild_kb()
    if not ok:
        print("[FAIL] 向量重建失败")
        return

    # Step 2: 生成测试集
    print("\n[Step 2] 生成测试集...")
    await run_generate_testset(kb_id=2, num_samples=10)

    # Step 3: 运行评估
    print("\n[Step 3] 运行 RAGAS 评估...")
    await run_eval(kb_id=2, max_questions=8)

    print("\n全部完成!")


if __name__ == "__main__":
    asyncio.run(main())
