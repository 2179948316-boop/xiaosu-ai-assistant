"""文本切片工具"""
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing import List, Dict


def split_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    doc_id: int = 0,
    filename: str = "",
) -> List[Dict]:
    """
    将文本切分为多个 chunk，每个 chunk 附带元数据。
    chunk_size=500 字符适合 1.5B 小模型的上下文窗口。
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " "],
        length_function=len,
    )

    raw_chunks = splitter.split_text(text)

    chunks = []
    for i, chunk_text in enumerate(raw_chunks):
        if chunk_text.strip():
            chunks.append({
                "text": chunk_text.strip(),
                "metadata": {
                    "doc_id": str(doc_id),
                    "filename": filename,
                    "chunk_index": i,
                    "total_chunks": len(raw_chunks),
                }
            })

    return chunks
