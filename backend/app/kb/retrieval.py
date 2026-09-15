"""混合检索：TF-IDF 词法打分 + 向量相似度，返回带来源编号的片段。

三个关键设计：
1. 中文按「单字 + 二元组」切分，不需要分词词典，「知识库」能命中「知识」「识库」。
2. 用 IDF 给词加权：像「的」「怎么」这种到处出现的词权重接近下限，
   所以不会出现「任何问题都能匹配上任何文档」。
3. 归一化用「全部查询词的权重和」做分母，而不是用候选里的最高分。
   按最高分归一化会让最弱的一次命中也被放大成满分，是常见的隐形 bug。

除了打分，还要求命中覆盖率达标（min_coverage）：问量子计算时，
只有几个「的」字命中，覆盖率极低，直接判定为无关。
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .embedding import cosine_similarity

try:  # numpy 是可选的：没装时退回纯 Python，功能一样，只是慢一些
    import numpy as _np
except ImportError:  # pragma: no cover - 取决于环境
    _np = None

# 候选少于这个数时，转成 numpy 数组的开销反而更大，直接用 Python 循环
_NUMPY_THRESHOLD = 64


def cosine_scores_batch(
    query: Sequence[float], vectors: Sequence[Sequence[float]]
) -> list[float]:
    """批量余弦相似度。

    数据量小的时候逐条算；超过阈值就转成矩阵一次算完。
    这是「全量余弦」在几千块规模下依然够用的关键——
    真正的 ANN 索引（pgvector / faiss）要等到矩阵乘法都嫌慢时才值得引入。
    """
    if not vectors:
        return []
    if _np is None or len(vectors) < _NUMPY_THRESHOLD:
        return [max(0.0, cosine_similarity(query, v)) for v in vectors]

    matrix = _np.asarray(vectors, dtype=_np.float32)
    vector = _np.asarray(query, dtype=_np.float32)
    if matrix.ndim != 2 or vector.shape[0] != matrix.shape[1]:
        # 维度不齐（比如混了不同嵌入模型的向量）：退回逐条，交给上层校验处理
        return [max(0.0, cosine_similarity(query, v)) for v in vectors]

    norms = _np.linalg.norm(matrix, axis=1) * _np.linalg.norm(vector)
    norms[norms == 0] = 1.0  # 零向量当作不相似
    scores = (matrix @ vector) / norms
    return [max(0.0, float(score)) for score in scores]


def tokenize(text: str) -> list[str]:
    lowered = (text or "").lower()
    latin = re.findall(r"[a-z0-9][a-z0-9._-]*", lowered)
    cjk = [ch for ch in lowered if "\u3400" <= ch <= "\u9fff"]
    bigrams = [f"{cjk[i]}{cjk[i + 1]}" for i in range(len(cjk) - 1)]
    return list(dict.fromkeys(latin + cjk + bigrams))


def _count(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    count = 0
    start = 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return count
        count += 1
        start = at + len(needle)


def build_idf(candidates: Sequence[dict]) -> dict[str, float]:
    """统计每个词出现在多少个分块里，转成 IDF 权重。"""
    total = len(candidates) or 1
    document_frequency: Counter[str] = Counter()
    for item in candidates:
        tokens = set(tokenize(item.get("text", "")) + tokenize(item.get("document_name", "")))
        for token in tokens:
            document_frequency[token] += 1
    return {
        token: math.log((total + 1) / (df + 1)) + 1.0
        for token, df in document_frequency.items()
    }


def _idf_of(idf_map: dict[str, float], token: str) -> float:
    return idf_map.get(token, math.log(2.0) + 1.0)


def lexical_score(
    query: str,
    title: str,
    text: str,
    idf_map: dict[str, float] | None = None,
) -> tuple[float, float]:
    """返回 (归一化得分, 命中覆盖率)，两个值都在 0~1 之间。"""
    idf_map = idf_map or {}
    query_norm = (query or "").lower().strip()
    text_norm = (text or "").lower()
    title_norm = (title or "").lower()
    if not query_norm or not text_norm:
        return 0.0, 0.0

    tokens = tokenize(query_norm)
    total_weight = sum(_idf_of(idf_map, token) for token in tokens) or 1.0
    score = 0.0
    matched_weight = 0.0
    for token in tokens:
        weight = _idf_of(idf_map, token)
        hits = _count(text_norm, token)
        in_title = token in title_norm
        if hits:
            score += weight * (1 + math.log(hits))
            matched_weight += weight
        if in_title:
            score += weight * 1.6
            matched_weight += weight * 0.5
    if len(query_norm) >= 4 and query_norm in text_norm:
        score += total_weight  # 整句命中：直接顶到接近满分

    normalized = min(1.0, score / (total_weight * 2.0))
    coverage = min(1.0, matched_weight / total_weight)
    return normalized, coverage


@dataclass
class RankedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    chunk_index: int
    text: str
    score: float
    lexical: float
    vector: float


def rank_chunks(
    query: str,
    query_embedding: Sequence[float] | None,
    candidates: Sequence[dict],
    top_k: int = 6,
    lexical_weight: float = 0.6,
    vector_weight: float = 0.4,
    min_score: float = 0.0,
    min_coverage: float = 0.0,
    min_vector_similarity: float = 0.0,
) -> list[RankedChunk]:
    """候选块打分排序。

    candidates 每项需要包含：chunk_id / document_id / document_name /
    chunk_index / text / embedding。
    """
    idf_map = build_idf(candidates)
    # 向量相似度先批量算完（检索里最重的计算在这）
    vector_scores = (
        cosine_scores_batch(
            query_embedding, [item.get("embedding") or [] for item in candidates]
        )
        if query_embedding
        else [0.0] * len(candidates)
    )

    scored: list[RankedChunk] = []
    for position, item in enumerate(candidates):
        lex, coverage = lexical_score(
            query, item.get("document_name", ""), item.get("text", ""), idf_map
        )
        vector = vector_scores[position] if position < len(vector_scores) else 0.0
        # 两道门槛只要过一道就行：要么词面命中够多，要么语义足够接近。
        # 两个都不过，说明这段资料多半和问题无关。
        if coverage < min_coverage and vector < min_vector_similarity:
            continue
        scored.append(
            RankedChunk(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                document_name=item.get("document_name", ""),
                chunk_index=int(item.get("chunk_index", 0)),
                text=item.get("text", ""),
                score=0.0,
                lexical=lex,
                vector=vector,
            )
        )

    for item in scored:
        item.score = lexical_weight * item.lexical + vector_weight * item.vector

    ranked = [c for c in scored if c.score >= max(min_score, 1e-9)]
    ranked.sort(key=lambda c: (-c.score, c.chunk_index))
    return ranked[: max(1, top_k)]
