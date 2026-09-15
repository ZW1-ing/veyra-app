"""知识库接口：入库、列表、删除、检索。"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...db.models import DocumentRow
from ...kb.embedding import EmbeddingProvider
from ...kb.service import delete_document, ingest_document, search_knowledge
from ...schemas.kb import DocumentCreate, DocumentIngestOut, DocumentOut, SearchRequest, SourceOut
from ..deps import embedding_dep, enforce_rate_limit, get_db, settings_dep

router = APIRouter(prefix="/kb", tags=["knowledge-base"], dependencies=[Depends(enforce_rate_limit)])


@router.post("/documents", response_model=DocumentIngestOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    embedding: EmbeddingProvider = Depends(embedding_dep),
    settings: Settings = Depends(settings_dep),
) -> DocumentIngestOut:
    document, deduplicated = await ingest_document(
        db,
        embedding,
        settings,
        name=payload.name,
        text=payload.text,
        source_type=payload.source_type,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )
    return DocumentIngestOut(
        **DocumentOut.model_validate(document).model_dump(),
        deduplicated=deduplicated,
    )


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentRow]:
    rows = db.execute(
        select(DocumentRow).order_by(DocumentRow.created_at.desc())
    ).scalars().all()
    return list(rows)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(document_id: str, db: Session = Depends(get_db)) -> None:
    """删除文档及其分块。删完这部分知识就不再参与检索。"""
    removed = await run_in_threadpool(delete_document, db, document_id)
    if not removed:
        raise HTTPException(status_code=404, detail="文档不存在")


@router.post("/search", response_model=list[SourceOut])
async def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    embedding: EmbeddingProvider = Depends(embedding_dep),
    settings: Settings = Depends(settings_dep),
) -> list:
    sources = await search_knowledge(db, embedding, settings, payload.query, payload.top_k)
    return sources
