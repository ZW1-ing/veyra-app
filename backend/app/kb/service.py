"""知识库编排：入库（分块 + 向量化）与检索。

这里所有同步的数据库操作都走 run_in_threadpool：
接口是 async 的，如果在里面直接执行同步 SQL，会把事件循环卡住，
并发一上来整个服务就排队。
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..db.models import ChunkRow, DocumentRow
from .chunking import chunk_text
from .embedding import EmbeddingProvider
from .retrieval import rank_chunks

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeSource:
    id: str
    document_id: str
    document_name: str
    chunk_index: int
    preview: str
    score: float


async def ingest_document(
    db: Session,
    embedding: EmbeddingProvider,
    settings: Settings,
    name: str,
    text: str,
    source_type: str = "text",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    owner_id: str = "anonymous",
) -> tuple[DocumentRow, bool]:
    """入库文档。返回 (文档, 是否命中重复)。"""
    size = chunk_size or settings.chunk_size
    model_label = str(getattr(embedding, "model", "") or getattr(embedding, "name", ""))
    content_hash = sha256((text or "").encode("utf-8")).hexdigest()

    # 先查重，命中就直接返回，省掉一次向量化调用
    existing = await run_in_threadpool(
        _find_duplicate, db, content_hash, size, model_label, owner_id
    )
    if existing is not None:
        logger.info("文档内容与配置均未变化，复用已有记录 %s（跳过重复入库）", existing.id)
        return existing, True

    chunks = chunk_text(
        text,
        size=size,
        overlap=chunk_overlap if chunk_overlap is not None else settings.chunk_overlap,
    )
    vectors = await embedding.embed(chunks) if chunks else []
    dim = len(vectors[0]) if vectors else 0

    document = await run_in_threadpool(
        _persist_document,
        db,
        name,
        text,
        source_type,
        chunks,
        vectors,
        size,
        model_label,
        dim,
        content_hash,
        owner_id,
    )
    return document, False


def _find_duplicate(
    db: Session,
    content_hash: str,
    chunk_size: int,
    embedding_model: str,
    owner_id: str,
) -> DocumentRow | None:
    """同一份内容 + 同一套处理配置 = 同一条记录。

    只比内容不比配置的话，用户改小分块后重新入库会被当成重复而静默忽略——
    那才是真的坑。
    """
    if not content_hash:
        return None
    return db.execute(
        select(DocumentRow).where(
            DocumentRow.content_hash == content_hash,
            DocumentRow.chunk_size == chunk_size,
            DocumentRow.embedding_model == embedding_model,
            DocumentRow.owner_id == owner_id,
        )
    ).scalars().first()


def delete_document(db: Session, document_id: str, owner_id: str = "anonymous") -> bool:
    """删除文档及其全部分块。同步操作，由调用方放进线程池。"""
    document = db.get(DocumentRow, document_id)
    if document is None or document.owner_id != owner_id:
        return False
    db.delete(document)  # 关系上配了 cascade，分块会一起删掉
    db.commit()
    return True


def _persist_document(
    db: Session,
    name: str,
    text: str,
    source_type: str,
    chunks: list[str],
    vectors: list[list[float]],
    chunk_size: int,
    embedding_model: str,
    embedding_dim: int,
    content_hash: str,
    owner_id: str,
) -> DocumentRow:
    """同步落库，交给线程池执行。

    同时记下入库时的分块大小与嵌入模型：换模型之后能从数据里看出差异，
    而不是等检索变差了才发现。
    """

    document = DocumentRow(
        owner_id=owner_id,
        name=name.strip() or "未命名文档",
        source_type=source_type,
        char_count=len(text or ""),
        chunk_size=chunk_size,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        content_hash=content_hash,
    )
    db.add(document)
    db.flush()  # 拿到 document.id

    for index, chunk in enumerate(chunks):
        db.add(
            ChunkRow(
                document_id=document.id,
                chunk_index=index,
                text=chunk,
                embedding=vectors[index] if index < len(vectors) else None,
                token_count=len(chunk),
            )
        )
    db.commit()
    db.refresh(document)
    return document


async def search_knowledge(
    db: Session,
    embedding: EmbeddingProvider,
    settings: Settings,
    query: str,
    top_k: int | None = None,
    owner_id: str = "anonymous",
) -> list[KnowledgeSource]:
    started = time.perf_counter()
    candidates = await run_in_threadpool(_load_candidates, db, owner_id)
    if not candidates:
        return []

    query_vector = (await embedding.embed([query]))[0]
    candidates, skipped = _drop_dimension_mismatch(candidates, len(query_vector))
    if skipped:
        logger.warning(
            "有 %d 个分块的向量维度与当前嵌入模型不一致（当前 %d 维），已跳过。"
            "换过嵌入模型的话，需要重新入库才能用上新模型。",
            skipped,
            len(query_vector),
        )
        if not candidates:
            return []

    ranked = rank_chunks(
        query=query,
        query_embedding=query_vector,
        candidates=candidates,
        top_k=top_k or settings.retrieval_top_k,
        lexical_weight=settings.lexical_weight,
        vector_weight=settings.vector_weight,
        min_score=settings.retrieval_min_score,
        min_coverage=settings.retrieval_min_coverage,
        min_vector_similarity=settings.retrieval_min_vector_similarity,
    )
    logger.info(
        "retrieval_completed candidates=%d skipped=%d hits=%d duration_ms=%.1f",
        len(candidates),
        skipped,
        len(ranked),
        (time.perf_counter() - started) * 1000,
    )

    return [
        KnowledgeSource(
            id=f"S{index + 1}",  # 与 Veyra 一致：回答里引用 [S1]
            document_id=item.document_id,
            document_name=item.document_name,
            chunk_index=item.chunk_index,
            preview=item.text[:260],
            score=round(item.score, 4),
        )
        for index, item in enumerate(ranked)
    ]


def _load_candidates(db: Session, owner_id: str = "anonymous") -> list[dict]:
    """读出全部分块参与打分（同步操作，由调用方放进线程池）。"""
    rows: Sequence[tuple[ChunkRow, str]] = db.execute(
        select(ChunkRow, DocumentRow.name)
        .join(DocumentRow, DocumentRow.id == ChunkRow.document_id)
        .where(DocumentRow.owner_id == owner_id)
    ).all()  # type: ignore[assignment]
    return [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_name": document_name,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "embedding": chunk.embedding,
        }
        for chunk, document_name in rows
    ]


def _drop_dimension_mismatch(candidates: list[dict], query_dim: int) -> tuple[list[dict], int]:
    """剔除维度对不上的分块。

    不剔除的话，余弦相似度会因为维度不同直接返回 0，检索质量悄悄下降，
    日志里什么都看不到——这类「不报错的错」最难排查。
    """
    kept: list[dict] = []
    skipped = 0
    for item in candidates:
        vector = item.get("embedding")
        if vector and len(vector) != query_dim:
            skipped += 1
            continue
        kept.append(item)
    return kept, skipped


def render_sources(sources: Sequence[KnowledgeSource]) -> str:
    """把检索结果拼成提示词里的一段，带编号方便模型引用。"""
    if not sources:
        return ""
    lines = [
        "以下是与问题相关的资料片段。",
        "引用时直接写编号，格式为 [S1]（不要再套一层方括号），没有用到的片段不要提及：",
    ]
    for source in sources:
        lines.append(f"[{source.id}] 来源：{source.document_name}｜{source.preview}")
    return "\n".join(lines)
