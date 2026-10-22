"""Central configuration, loaded from environment / backend/.env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
RULES_DIR = BACKEND_DIR / "app" / "rules"
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_name: str = "CareFlow AI"
    engine_version: str = "phase5-0.5"

    # LLM providers: "ollama" | "gemini" | "rules"
    llm_provider: str = "ollama"
    llm_fallback_provider: str = "gemini"

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_timeout_s: float = 120.0

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_s: float = 60.0

    database_url: str = f"sqlite:///{DATA_DIR / 'careflow.db'}"
    cors_origins: str = "http://localhost:5173"

    # ---- Phase 2: documents, voice, translation
    upload_dir: str = str(DATA_DIR / "uploads")
    max_upload_mb: int = 20
    # Local OCR first; escalate to Gemini only when the local result is weak (saves latency + cost)
    ocr_engines: str = "tesseract,gemini"
    ocr_escalate_below: float = 0.75  # average local OCR confidence below which we escalate
    tesseract_langs: str = "eng+hin"  # languages that are not installed are skipped automatically
    # Speech: local faster-whisper first, Gemini as fallback
    audio_engines: str = "whisper,gemini"
    whisper_model: str = "small"  # tiny | base | small | medium | large-v3 (multilingual)
    whisper_device: str = "auto"  # auto | cuda | cpu
    # Below these, a source is flagged as uncertain
    asr_low_confidence: float = 0.6
    translation_low_confidence: float = 0.7
    language_low_confidence: float = 0.5
    max_source_chars_for_model: int = 6000

    # ---- Phase 3: follow-up questions
    ai_followups: bool = True  # small model suggests up to 3 extra questions (skipped when LLM_PROVIDER=rules)

    # ---- Phase 5: security and privacy
    jwt_secret: str = "dev-only-change-me-in-backend-.env"
    token_minutes: int = 12 * 60  # one clinic shift
    demo_password: str = "careflow-demo"
    # Gemini receives report images / voice notes as-is (they cannot be text-redacted). Set false to keep
    # all documents and audio on local engines only.
    external_documents_allowed: bool = True
    redact_before_external: bool = True

    # Below this average field confidence, a case is treated as "uncertain"
    low_confidence_threshold: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()
