"""Lightweight language detection for Phase 1 (script + Hinglish cue words).
Phase 2 replaces this with model-based detection and translation with confidence."""
import re

_SCRIPTS = {
    "hi": re.compile(r"[ऀ-ॿ]"),  # Devanagari (Hindi, Marathi...)
    "bn": re.compile(r"[ঀ-৿]"),
    "ta": re.compile(r"[஀-௿]"),
    "te": re.compile(r"[ఀ-౿]"),
    "kn": re.compile(r"[ಀ-೿]"),
    "ml": re.compile(r"[ഀ-ൿ]"),
    "gu": re.compile(r"[઀-૿]"),
    "pa": re.compile(r"[਀-੿]"),
}
_HINGLISH = re.compile(
    r"\b(hai|hain|nahi|nahin|mujhe|mera|meri|mere|bahut|dard|bukhar|aur|kya|se|ko|ki|ka|ke|raha|rahi|ho|gaya|gayi|"
    r"pet|sir|saans|ulti|khansi|kal|aaj|din|abhi|thoda|zyada)\b",
    re.I,
)
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> tuple[str, float]:
    """Return (BCP-47-ish code, confidence). 'hi-en' = Hindi-English code-mixed."""
    if not text.strip():
        return "unknown", 0.0
    latin = len(_LATIN.findall(text))
    # The danda (। ॥) sits in the Devanagari block but is used by Bengali, Odia and others too: ignore it
    letters = text.replace("\u0964", "").replace("\u0965", "")
    counts = {code: len(pat.findall(letters)) for code, pat in _SCRIPTS.items()}
    code, n = max(counts.items(), key=lambda kv: kv[1])
    if n:
        if latin > n * 0.5:
            return f"{code}-en", 0.7
        return code, 0.9
    words = max(1, len(text.split()))
    cues = len(_HINGLISH.findall(text))
    ratio = cues / words
    if ratio >= 0.25:
        return "hi-en", min(0.9, 0.5 + ratio)
    if ratio >= 0.1:
        return "hi-en", 0.55
    return "en", 0.85 if ratio == 0 else 0.7
