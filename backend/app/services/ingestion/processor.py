"""Turn every raw Source into text + quality flags + English translation, once (idempotent)."""
from dataclasses import asdict
from typing import Any

from sqlmodel import Session

from app.config import get_settings
from app.models.case import Source
from app.services.ingestion.audio import process_audio
from app.services.ingestion.documents import process_document
from app.services.ingestion.language import detect_language
from app.services.ingestion.storage import absolute
from app.services.ingestion.translation import needs_translation, translate
from app.services.privacy import audit_logger

# Languages the multilingual symptom lexicon covers directly, so a missing translation is less serious
LEXICON_LANGS = {"en", "hi", "hi-en"}


def _flag(src: Source, kind: str, detail: str, severity: str = "warning") -> dict[str, Any]:
    return {"source_id": src.id, "kind": kind, "detail": detail, "severity": severity}


def _ingest_report(src: Source, meta: dict, flags: list) -> None:
    res = process_document(absolute(src.file_path), src.mime or "")
    src.original_text = res.text
    meta.update(engine=res.engine, avg_confidence=res.avg_confidence, legibility=res.legibility, pages=res.pages,
                lines=[asdict(ln) for ln in res.lines], attempts=res.attempts, notes=res.notes)
    if res.language:
        src.language, src.language_confidence = res.language, 0.85
    if res.translation_en:
        src.translated_text, src.translation_confidence = res.translation_en, res.translation_confidence
        meta["translation_engine"] = res.engine
    if res.legibility == "unreadable":
        flags.append(_flag(src, "unreadable", "The report could not be read by any OCR engine. Review the original file.", "critical"))
    elif res.legibility == "poor":
        flags.append(_flag(src, "poor_legibility", f"Report is hard to read (OCR confidence {res.avg_confidence:.2f}). "
                                                    "Values from it may be wrong; check against the original."))
    elif res.avg_confidence < 0.75:
        flags.append(_flag(src, "low_ocr_confidence", f"Some parts of the report were read with low confidence ({res.avg_confidence:.2f})."))
    low_lines = [ln for ln in res.lines if ln.confidence < 0.6]
    if low_lines and res.legibility not in ("poor", "unreadable"):
        flags.append(_flag(src, "low_ocr_confidence", f"{len(low_lines)} line(s) read with low confidence."))
    for n in res.notes:
        flags.append(_flag(src, "poor_legibility", n))


def _ingest_voice(src: Source, meta: dict, flags: list) -> None:
    s = get_settings()
    res = process_audio(absolute(src.file_path), src.mime or "")
    src.original_text = res.text
    meta.update(engine=res.engine, avg_confidence=res.avg_confidence, duration_s=res.duration_s,
                segments=[asdict(sg) for sg in res.segments], attempts=res.attempts, unclear_parts=res.unclear_parts)
    if res.language:
        src.language, src.language_confidence = res.language, res.language_confidence
    if res.translation_en:
        src.translated_text, src.translation_confidence = res.translation_en, res.translation_confidence
        meta["translation_engine"] = res.engine
    if not res.segments:
        flags.append(_flag(src, "unreadable", "The voice note could not be transcribed. Listen to the original recording.", "critical"))
        return
    if res.avg_confidence < s.asr_low_confidence:
        flags.append(_flag(src, "low_asr_confidence", f"Transcription confidence is low ({res.avg_confidence:.2f}); "
                                                       "words may have been misheard."))
    low = [sg for sg in res.segments if sg.confidence < s.asr_low_confidence]
    if low and res.avg_confidence >= s.asr_low_confidence:
        flags.append(_flag(src, "low_asr_confidence", f"{len(low)} part(s) of the recording are unclear."))
    for p in res.unclear_parts:
        flags.append(_flag(src, "low_asr_confidence", f"Unclear: {p}"))


def ingest_source(session: Session, src: Source) -> None:
    meta = dict(src.meta or {})
    if meta.get("ingested"):
        return
    s = get_settings()
    flags: list[dict[str, Any]] = []
    try:
        if src.kind == "report":
            _ingest_report(src, meta, flags)
        elif src.kind == "voice":
            _ingest_voice(src, meta, flags)
        if src.kind != "intake_form" and src.original_text and src.language in (None, "unknown"):
            src.language, src.language_confidence = detect_language(src.original_text)

        if src.kind != "intake_form" and src.original_text:
            if (src.language_confidence or 0) < s.language_low_confidence:
                flags.append(_flag(src, "uncertain_language", f"Language detected as '{src.language}' with low confidence."))
            if needs_translation(src.language) and not src.translated_text:
                tr = translate(src.original_text, src.language)
                if tr.text:
                    src.translated_text, src.translation_confidence = tr.text, tr.confidence
                    meta["translation_engine"] = tr.engine
                    meta["translation_uncertain_phrases"] = tr.uncertain_phrases
                else:
                    lex = (src.language or "") in LEXICON_LANGS
                    flags.append(_flag(src, "translation_unavailable",
                                       "No translation model available"
                                       + ("; multilingual keyword scan still applied." if lex else "; a clinician who reads this language should review it."),
                                       "info" if lex else "warning"))
            if src.translated_text and (src.translation_confidence or 0) < s.translation_low_confidence:
                flags.append(_flag(src, "low_translation_confidence",
                                   f"Translation confidence is low ({src.translation_confidence or 0:.2f}); check the original wording."))
            if len(src.original_text) > s.max_source_chars_for_model:
                flags.append(_flag(src, "truncated", "Only the first part of this long source was sent to the model.", "info"))
        src.processing_status = "done"
    except Exception as e:
        src.processing_status = "failed"
        flags.append(_flag(src, "processing_failed", f"Processing failed: {str(e)[:200]}", "critical"))

    meta["quality_flags"] = flags
    meta["ingested"] = True
    src.meta = meta
    session.add(src)
    audit_logger.log(session, actor=meta.get("engine") or "ingestion", actor_type="ai" if src.kind in ("report", "voice") else "system",
                     action=f"{src.kind}_processed", case_id=src.case_id,
                     details={"source_id": src.id, "status": src.processing_status, "language": src.language,
                              "avg_confidence": meta.get("avg_confidence"), "translation_engine": meta.get("translation_engine"),
                              "flags": [f["kind"] for f in flags], "attempts": meta.get("attempts")})
