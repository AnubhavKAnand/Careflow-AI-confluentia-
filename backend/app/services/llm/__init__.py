from app.config import get_settings
from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.ollama_slm import OllamaProvider

_REGISTRY = {"ollama": OllamaProvider, "gemini": GeminiProvider}


def get_provider(name: str) -> LLMProvider | None:
    cls = _REGISTRY.get((name or "").lower())
    return cls() if cls else None


def provider_chain() -> list[LLMProvider]:
    """Primary then fallback model. An empty chain (or 'rules') means the deterministic extractor only."""
    s = get_settings()
    chain = []
    for name in (s.llm_provider, s.llm_fallback_provider):
        p = get_provider(name)
        if p and all(p.name != q.name for q in chain):
            chain.append(p)
    return chain


__all__ = ["LLMError", "LLMProvider", "get_provider", "provider_chain"]
