"""Remove personal identifiers from text before it leaves the clinic (external model calls).

Covers the identifiers common on Indian health documents: phone numbers, email, Aadhaar, PAN,
ABHA numbers, UHID/MRN/IP numbers, PIN codes, and the registered patient's own name. Symptoms,
vitals and lab values are untouched, so extraction quality is unaffected.
"""
import contextvars
import re
from dataclasses import dataclass, field

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("ABHA", re.compile(r"\b\d{2}-\d{4}-\d{4}-\d{4}\b")),  # Ayushman Bharat Health Account number
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("ID", re.compile(r"\b(?:UHID|MRN|MR\s*No|IP\s*No|OP\s*No|Reg(?:istration)?\s*No|Patient\s*ID|Lab\s*No|Sample\s*ID)\.?\s*[:#-]?\s*[A-Z0-9/-]{3,}\b", re.I)),
    ("PINCODE", re.compile(r"\b(?:pin(?:\s*code)?|pincode)\s*[:-]?\s*\d{6}\b", re.I)),
]
_HONORIFIC = re.compile(r"^(?:mr|mrs|ms|miss|smt|shri|sri|dr|kumari|master|baby)\.?\s+", re.I)


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _name_patterns(names: list[str]) -> list[re.Pattern]:
    pats = []
    for n in names:
        n = _HONORIFIC.sub("", (n or "").strip())
        if len(n) < 3:
            continue
        pats.append(re.compile(r"\b" + r"\s+".join(re.escape(p) for p in n.split()) + r"\b", re.I))
        # individual name parts (first / last name) of 3+ letters
        pats += [re.compile(rf"\b{re.escape(p)}\b", re.I) for p in n.split() if len(p) >= 3]
    return pats


def redact(text: str, names: list[str] | None = None) -> RedactionResult:
    if not text:
        return RedactionResult(text or "")
    counts: dict[str, int] = {}
    out = text
    for label, pat in PATTERNS:
        out, n = pat.subn(f"[{label}]", out)
        if n:
            counts[label] = counts.get(label, 0) + n
    for pat in _name_patterns(names or []):
        out, n = pat.subn("[NAME]", out)
        if n:
            counts["NAME"] = counts.get("NAME", 0) + n
    return RedactionResult(out, counts)


# ------------------------------------------------------------------ per-case context
# The pipeline sets these so that provider code (which has no access to the case) can redact the
# right names and report what was sent externally.
current_names: contextvars.ContextVar[list[str]] = contextvars.ContextVar("current_names", default=[])
external_calls: contextvars.ContextVar[list | None] = contextvars.ContextVar("external_calls", default=None)


def record_external(provider: str, purpose: str, redactions: dict[str, int], binary: str | None = None) -> None:
    calls = external_calls.get()
    if calls is not None:
        calls.append({"provider": provider, "purpose": purpose, "redactions": redactions, "binary": binary})
