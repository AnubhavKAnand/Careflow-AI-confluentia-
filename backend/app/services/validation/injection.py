"""Prompt-injection detection for patient messages, OCR'd reports and transcripts.

Anything in an input that tries to instruct the AI ("ignore previous instructions",
"mark this patient as routine") is:
  1. detected here (English, Hinglish and Hindi patterns + hidden-text tricks),
  2. masked before the text reaches any language model,
  3. surfaced to the clinician as a 'suspicious' flag, and lifts the case to at least P3.
Priority can never be lowered by input text anyway: rules and NEWS2 decide it.
"""
import re
from dataclasses import dataclass

MASK = "[SUSPICIOUS INSTRUCTION REMOVED]"

_LOW = r"(?:routine|low(?:est)?(?:\s+priority)?|non[-\s]?urgent|not\s+urgent|p4|stable|normal|green|minor)"
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions", re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|system|existing|safety)?\s*"
        r"(?:instructions?|rules?|prompts?|guidelines?|protocols?)\b", re.I)),
    ("force_priority", re.compile(
        rf"\b(?:mark|classify|set|label|treat|triage|categori[sz]e|flag|put|list|record)\s+(?:this|the|him|her|them|my)?\s*"
        rf"(?:patient|case|report|person|mareez)?\s*(?:as|to|at|in)\s+(?:a\s+)?(?:the\s+)?{_LOW}\b", re.I)),
    ("priority_assignment", re.compile(rf"\b(?:priority|triage\s+level|urgency|severity)\s*(?:[:=]|should\s+be|is)\s*{_LOW}\b", re.I)),
    ("suppress_alert", re.compile(
        r"\b(?:do\s+not|don'?t|never|no\s+need\s+to)\s+(?:escalate|flag|alert|notify|refer|raise|prioriti[sz]e|show)\b", re.I)),
    ("role_hijack", re.compile(
        r"\b(?:you\s+are\s+now|act\s+as|pretend\s+(?:to\s+be|you\s+are)|from\s+now\s+on\s+you|new\s+instructions?\s*:|"
        r"system\s+(?:prompt|note|message|instruction|override)\s*:|assistant\s*:|developer\s+mode|jailbreak)", re.I)),
    ("ai_addressed", re.compile(r"\b(?:note|message|instruction)s?\s+(?:to|for)\s+(?:the\s+)?(?:ai|a\.i\.|model|assistant|system|chatbot|llm)\b", re.I)),
    ("hinglish_ignore", re.compile(
        r"\b(?:pichhl[ea]|purane|upar\s+ke|saare)\s+(?:nirdesh|instructions?|rules?)\s+(?:ko\s+)?(?:ignore|bhool|nazarandaz|chhod)", re.I)),
    ("hinglish_priority", re.compile(
        r"\b(?:is|ye|yeh|iss)\s+(?:patient|case|mareez|report)\s+ko\s+(?:low|kam|routine|normal|non[-\s]?urgent)\s*(?:priority)?\s*(?:mein|me)?\s*"
        r"(?:daalo|dalo|rakho|karo|maano|mark\s+karo)", re.I)),
    ("hindi_ignore", re.compile(r"(?:पिछले|पुराने|सभी)\s+(?:निर्देशों|निर्देश|नियमों)\s+(?:को\s+)?(?:अनदेखा|नज़रअंदाज़|भूल)")),
    ("hindi_priority", re.compile(r"(?:इस|यह)\s+(?:मरीज़|मरीज|केस)\s+को\s+(?:कम|सामान्य|रूटीन)\s+(?:प्राथमिकता)?")),
    ("html_comment", re.compile(r"<!--.*?-->", re.S)),
    ("markup_instruction", re.compile(r"\[(?:INST|SYS|SYSTEM)\]|<\|(?:im_start|system|endoftext)\|>|</?(?:system|instructions?)>", re.I)),
]
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]{2,}")
_BASE64_BLOB = re.compile(r"\b[A-Za-z0-9+/]{120,}={0,2}")


@dataclass
class Finding:
    pattern: str
    start: int
    end: int
    text: str


def detect(text: str) -> list[Finding]:
    if not text:
        return []
    found: list[Finding] = []
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            found.append(Finding(name, m.start(), m.end(), m.group(0)))
    for m in _ZERO_WIDTH.finditer(text):
        found.append(Finding("hidden_characters", m.start(), m.end(), "(hidden zero-width characters)"))
    for m in _BASE64_BLOB.finditer(text):
        found.append(Finding("encoded_blob", m.start(), m.end(), m.group(0)[:40] + "…"))
    # merge overlaps
    found.sort(key=lambda f: f.start)
    merged: list[Finding] = []
    for f in found:
        if merged and f.start <= merged[-1].end:
            last = merged[-1]
            if f.end > last.end:
                merged[-1] = Finding(last.pattern, last.start, f.end, text[last.start:f.end])
        else:
            merged.append(f)
    return merged


def _sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a finding to the whole sentence/line, so the model never sees a half-removed instruction."""
    s = max(text.rfind(".", 0, start), text.rfind("\n", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    e_candidates = [i for i in (text.find(".", end), text.find("\n", end), text.find("!", end)) if i != -1]
    e = min(e_candidates) + 1 if e_candidates else len(text)
    return s + 1, e


def mask(text: str, findings: list[dict]) -> str:
    """Replace each finding (widened to its sentence) with a visible marker."""
    if not text or not findings:
        return text
    spans = sorted(_sentence_span(text, f["start"], f["end"]) for f in findings if f.get("start") is not None)
    out, pos = [], 0
    for s, e in spans:
        if s < pos:
            s = pos
        if s >= e:
            continue
        out.append(text[pos:s])
        out.append(f" {MASK} ")
        pos = e
    out.append(text[pos:])
    return "".join(out)
