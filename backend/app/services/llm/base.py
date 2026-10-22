import json
import re
from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    """A model that returns JSON. Phase 2 adds file (image/audio) inputs for providers that support them."""

    name: str = "base"
    external: bool = False  # True when calls leave the clinic (cloud API)

    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    def generate_json(self, system: str, user: str) -> dict[str, Any]: ...

    def is_available(self) -> bool:
        return True


def parse_json_loose(text: str) -> dict[str, Any]:
    """Parse model output that should be JSON, tolerating ```json fences and leading chatter."""
    if not text:
        raise LLMError("empty model response")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError as e:
                raise LLMError(f"model returned invalid JSON: {e}") from e
        raise LLMError("model response contained no JSON object")
