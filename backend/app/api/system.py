from fastapi import APIRouter

from app.config import get_settings
from app.services.llm import provider_chain

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    s = get_settings()
    chain = [] if s.llm_provider == "rules" else provider_chain()
    return {
        "status": "ok",
        "engine_version": s.engine_version,
        "providers": [{"name": p.model_id, "available": p.is_available()} for p in chain],
        "final_fallback": "rules",
        "security_warnings": (["JWT_SECRET is the development default; set it in backend/.env"]
                              if s.jwt_secret.startswith("dev-only") else []),
        "external_documents_allowed": s.external_documents_allowed,
    }
