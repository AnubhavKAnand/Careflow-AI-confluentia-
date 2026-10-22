"""Gemini via REST (no SDK dependency). Used as fallback in Phase 1 and for OCR/voice in Phase 2."""
from typing import Any

import httpx

from app.config import get_settings
from app.services.llm.base import LLMError, LLMProvider, parse_json_loose
from app.services.privacy.redaction import current_names, record_external, redact

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.gemini_api_key
        self.model = s.gemini_model
        self.timeout = s.gemini_timeout_s

    @property
    def model_id(self) -> str:
        return f"gemini:{self.model}"

    def is_available(self) -> bool:
        return bool(self.api_key)

    external = True  # data leaves the clinic: redact text, log every call

    def generate_json(self, system: str, user: str, parts: list[dict] | None = None, purpose: str = "extraction") -> dict[str, Any]:
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY not set")
        s = get_settings()
        if parts and not s.external_documents_allowed:
            raise LLMError("Sending documents/audio to external models is disabled (EXTERNAL_DOCUMENTS_ALLOWED=false)")
        counts: dict[str, int] = {}
        if s.redact_before_external:
            r = redact(user, current_names.get())
            user, counts = r.text, r.counts
        binary = ",".join(p.get("inline_data", {}).get("mime_type", "?") for p in parts) if parts else None
        record_external(self.model_id, "document/audio reading" if parts else purpose, counts, binary)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}, *(parts or [])]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        try:
            r = httpx.post(
                f"{API_BASE}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPError as e:
            raise LLMError(f"gemini request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected gemini response shape: {e}") from e
        return parse_json_loose(text)
