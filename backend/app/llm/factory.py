"""根据配置装配模型后端；缺密钥时自动退回 mock，保证界面永远能演示。"""

from ..core.config import Settings
from .base import LLMProvider
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider


def build_provider(settings: Settings) -> LLMProvider:
    provider = (settings.llm_provider or "mock").lower()

    if provider == "openai_compat":
        # 本地 Ollama 不需要密钥；云端服务必须有密钥，否则降级
        is_local = "127.0.0.1" in settings.llm_base_url or "localhost" in settings.llm_base_url
        if settings.llm_api_key or is_local:
            return OpenAICompatProvider(
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout_seconds,
            )

    return MockProvider()
