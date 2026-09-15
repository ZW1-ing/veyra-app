"""文档分块：中文优先按段落和标点切，再对超长块做滑动窗口切分。

为什么不是简单地每 500 字切一刀：中文的语义边界在句号和换行上，
按标点切能让每个块的语义更完整，检索出来的片段更像人能读的内容。
"""

import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])")


def _hard_wrap(text: str, size: int, overlap: int) -> list[str]:
    """没有任何标点可切时的兜底：滑动窗口。"""
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def _split_long_paragraph(paragraph: str, size: int, overlap: int) -> list[str]:
    if len(paragraph) <= size:
        return [paragraph]

    sentences = [s for s in _SENTENCE_SPLIT.split(paragraph) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_wrap(sentence, size, overlap))
            continue
        if len(current) + len(sentence) <= size:
            current += sentence
        else:
            chunks.append(current)
            # 保留上一块尾部作为重叠，避免答案正好落被切断的位置
            tail = current[-overlap:] if overlap > 0 else ""
            current = tail + sentence
    if current.strip():
        chunks.append(current)
    return chunks


def chunk_text(text: str, size: int = 500, overlap: int = 80) -> list[str]:
    """把长文本切成若干块，返回去空后的结果。"""
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    raw_chunks: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(normalized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        raw_chunks.extend(_split_long_paragraph(paragraph, size, overlap))

    return [c.strip() for c in raw_chunks if c.strip()]
