"""装配向量化实现：hash 离线版 / OpenAI 兼容版。"""

from ..core.config import Settings
from .embedding import EmbeddingProvider, HashEmbedding, OpenAICompatEmbedding


def build_embedding(settings: Settings) -> EmbeddingProvider:
    if (settings.embedding_provider or "hash").lower() == "openai_compat":
        is_local = "127.0.0.1" in settings.llm_base_url or "localhost" in settings.llm_base_url
        if settings.llm_api_key or is_local:
            return OpenAICompatEmbedding(
                base_url=settings.llm_base_url,
                model=settings.embedding_model,
                api_key=settings.llm_api_key,
                dim=settings.embedding_dim,
            )
    return HashEmbedding(dim=settings.embedding_dim)
