"""End-to-end case processing: sources -> extraction -> triage -> draft note, with an audit trail."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.config import get_settings
from app.models import Case, CaseStatus, Patient, Source, TriageNote, TriageResult
from app.schemas.api import VitalsIn
from app.services.extraction.extractor import extract
from app.services.ingestion.language import detect_language
from app.services.ingestion.processor import ingest_source
from app.services.ingestion.storage import guess_mime, kind_for, save_upload
from app.services.privacy import audit_logger
from app.services.privacy.redaction import current_names, external_calls
from app.services.triage.engine import compute_triage
from app.services.triage.notes import generate_note
from app.services.learning.shadow import apply_to_triage, predict_for_case
from app.services.validation import scan_injections, validate

_FORM_FIELDS = [
    ("spo2", "SpO2", "%"), ("pulse", "Pulse", " /min"), ("resp_rate", "Respiratory rate", " /min"),
    ("temperature_c", "Temperature", " C"), ("consciousness", "Consciousness", ""),
]


def vitals_form_text(v: VitalsIn) -> Optional[str]:
    """Render intake-form vitals as text, so they get exact source spans like any other evidence."""
    parts = [f"{label}: {getattr(v, k):g}{unit}" if isinstance(getattr(v, k), float) else f"{label}: {getattr(v, k)}{unit}"
             for k, label, unit in _FORM_FIELDS if getattr(v, k) is not None]
    if v.systolic_bp is not None:
        parts.append(f"BP: {v.systolic_bp:g}/{v.diastolic_bp:g}" if v.diastolic_bp is not None else f"BP: {v.systolic_bp:g}/0")
    if v.on_oxygen is not None:
        parts.append(f"Supplemental oxygen: {'yes' if v.on_oxygen else 'no'}")
    return ("Vitals entered at intake: " + "; ".join(parts)) if parts else None


def add_text_source(session: Session, case: Case, text: str, kind: str = "patient_message", label: str | None = None) -> Source:
    lang, conf = detect_language(text) if kind != "intake_form" else ("en", 1.0)
    src = Source(case_id=case.id, kind=kind, label=label, original_text=text, language=lang, language_confidence=conf,
                 mime="text/plain")
    session.add(src)
    session.flush()
    return src


def add_file_source(session: Session, case: Case, filename: str, content: bytes, declared_mime: str | None,
                    label: str | None = None) -> Source:
    mime = guess_mime(filename, declared_mime)
    kind = kind_for(mime)
    if kind == "patient_message":
        return add_text_source(session, case, content.decode("utf-8", errors="replace"), label=label or filename)
    rel, sha = save_upload(case.id, filename, content, mime)
    src = Source(case_id=case.id, kind=kind, label=label or filename, file_path=rel, mime=mime,
                 meta={"filename": filename, "sha256": sha, "size_bytes": len(content)})
    session.add(src)
    session.flush()
    return src


def process_case(session: Session, case: Case) -> TriageResult:
    """Run the pipeline with privacy context: the patient's name is redacted from anything sent to an
    external model, and every external call is written to the audit log."""
    patient = session.get(Patient, case.patient_id)
    names_token = current_names.set([patient.name] if patient and patient.name else [])
    calls: list = []
    calls_token = external_calls.set(calls)
    try:
        return _process_case(session, case)
    finally:
        current_names.reset(names_token)
        external_calls.reset(calls_token)
        if calls:
            audit_logger.log(session, actor="privacy-guard", actor_type="system", action="data_sent_external",
                             case_id=case.id, details={"calls": calls}, commit=True)


def _process_case(session: Session, case: Case) -> TriageResult:
    settings = get_settings()
    case.status = CaseStatus.PROCESSING
    patient = session.get(Patient, case.patient_id)
    sources = list(session.exec(select(Source).where(Source.case_id == case.id).order_by(Source.id)))
    for src in sources:  # OCR / transcription / translation, once per source
        ingest_source(session, src)
    scan_injections(sources)  # before extraction, so suspicious text is masked from the model
    for src in sources:
        session.add(src)
    session.flush()

    try:
        ex, latency = extract(sources, patient)
    except Exception as e:  # never lose a case: mark it and keep it visible
        case.status = CaseStatus.ERROR
        case.priority, case.sort_score = "P3", 45.0
        audit_logger.log(session, actor="system", actor_type="system", action="extraction_failed",
                         case_id=case.id, details={"error": str(e)[:500]})
        session.commit()
        raise

    audit_logger.log(session, actor=ex.provider or "rules", actor_type="ai", action="extraction_completed",
                     case_id=case.id, details={"latency_ms": latency, "fallback_used": ex.fallback_used,
                                               "errors": ex.provider_errors, "symptoms": len(ex.symptoms),
                                               "discrepancies": len(ex.discrepancies)})

    first = compute_triage(ex)  # red flags decide which checklists apply
    report, ai_model = validate(ex, sources, patient, {f.rule_id for f in first.red_flags})
    tri = compute_triage(ex, report)
    text = "\n".join(f"{s.original_text}\n{s.translated_text or ''}" for s in sources if s.kind != "intake_form")
    agent_row, agent_pred = predict_for_case(session, case.id, ex, tri, report, text)
    tri = apply_to_triage(tri, agent_row, agent_pred)
    # In shadow mode the suggestion itself is not written to the (clinician-readable) audit log: it stays blind
    audit_logger.log(session, actor=f"shadow-agent:v{agent_row.model_version}", actor_type="ai", action="agent_predicted",
                     case_id=case.id, details={"mode": agent_row.mode, "visible": not agent_row.hidden,
                                               "abstained": agent_row.abstained,
                                               **({"suggested": agent_row.predicted} if not agent_row.hidden else {})})
    if report.injections:
        audit_logger.log(session, actor="injection-detector", actor_type="system", action="suspicious_instruction_detected",
                         case_id=case.id, details={"findings": [{"source_id": i.source_id, "pattern": i.pattern} for i in report.injections]})
    audit_logger.log(session, actor=f"validator:{settings.engine_version}" + (f"+{ai_model}" if ai_model else ""),
                     actor_type="ai", action="validation_completed", case_id=case.id,
                     details={"missing": [m.id for m in report.missing], "conflicts": [c.id for c in report.conflicts],
                              "followups": len(report.followups), "completeness": report.completeness})
    result = TriageResult(case_id=case.id, priority=tri.priority, sort_score=tri.sort_score,
                          payload=tri.model_dump(mode="json"), engine_version=settings.engine_version)
    session.add(result)
    audit_logger.log(session, actor=f"triage-engine:{settings.engine_version}", actor_type="ai",
                     action="triage_suggested", case_id=case.id,
                     details={"priority": tri.priority, "red_flags": [f.rule_id for f in tri.red_flags],
                              "news2": tri.news2.total if tri.news2 else None,
                              "uncertain": tri.data_quality.uncertain})

    prev = session.exec(select(TriageNote).where(TriageNote.case_id == case.id).order_by(TriageNote.version.desc())).first()
    note = TriageNote(case_id=case.id, version=(prev.version + 1) if prev else 1,
                      content=generate_note(patient, ex, tri, sources), status="draft",
                      author=f"triage-engine:{settings.engine_version}", author_type="ai")
    session.add(note)
    session.flush()
    audit_logger.log(session, actor=note.author, actor_type="ai", action="note_drafted",
                     case_id=case.id, details={"note_id": note.id, "version": note.version})

    case.extraction = ex.model_dump(mode="json")
    case.extraction_provider = ex.provider
    case.extraction_latency_ms = latency
    case.priority = tri.priority
    case.sort_score = tri.sort_score
    case.chief_complaint = ex.chief_complaint.value if ex.chief_complaint.present else None
    case.status = CaseStatus.AWAITING_REVIEW
    case.updated_at = datetime.now(timezone.utc)
    session.add(case)
    session.commit()
    session.refresh(result)
    return result
