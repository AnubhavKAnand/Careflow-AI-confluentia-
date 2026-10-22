"""Local small language model (<20B parameters) served by Ollama."""
from typing import Any

import httpx

from app.config import get_settings
from app.services.llm.base import LLMError, LLMProvider, parse_json_loose


class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_schema = True

    def __init__(self) -> None:
        s = get_settings()
        self.url = s.ollama_url.rstrip("/")
        self.model = s.ollama_model
        self.timeout = s.ollama_timeout_s

    @property
    def model_id(self) -> str:
        return f"ollama:{self.model}"

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.url}/api/tags", timeout=3)
            r.raise_for_status()
            names = {m.get("name", "") for m in r.json().get("models", [])}
            return any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names)
        except Exception:
            return False

    def generate_json(self, system: str, user: str, schema: dict | None = None) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # a JSON schema makes Ollama constrain decoding to exactly that shape (Ollama >= 0.5);
            # plain "json" only guarantees valid JSON
            "format": schema or "json",
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 1024},
        }
        try:
            r = httpx.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            if r.status_code == 400 and schema is not None:  # older Ollama: no schema support
                payload["format"] = "json"
                r = httpx.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"ollama request failed: {e}") from e
        return parse_json_loose(r.json().get("message", {}).get("content", ""))
