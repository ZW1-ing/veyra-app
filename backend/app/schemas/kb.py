"""知识库出入参。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    source_type: Literal["text", "file", "url"] = "text"
    # 不传就用全局默认。短文或主题密集的文档，切小一点检索更准
    chunk_size: int | None = Field(default=None, ge=50, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: str
    char_count: int
    chunk_size: int = 0
    embedding_model: str = ""
    embedding_dim: int = 0
    created_at: datetime


class DocumentIngestOut(DocumentOut):
    """入库结果：重复入库时 deduplicated 为 true，并把已有那条返回回来。"""

    deduplicated: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceOut(BaseModel):
    id: str
    document_id: str
    document_name: str
    chunk_index: int
    preview: str
    score: float
