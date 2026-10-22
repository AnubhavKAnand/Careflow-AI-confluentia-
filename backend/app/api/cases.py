from datetime import datetime, timezone

import json
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.api.deps import Actor, require
from app.db import get_session
from app.models import Case, CaseStatus, Patient, ShadowPrediction, Source, TriageNote, TriageResult
from app.services.learning.memory import similar_cases
from app.services.learning.shadow import agent_view, get_config
from app.schemas.api import AnswersIn, CaseCreate, CaseDetail, CaseIntake, CaseListItem, NoteOut, SourceOut
from app.services.triage.text_match import load_lexicon
from app.schemas.triage import PRIORITY_INFO
from app.services.ingestion.storage import UploadRejected, absolute
from app.services.pipeline import add_file_source, add_text_source, process_case, vitals_form_text
from app.services.privacy import audit_logger
from app.services.triage.engine import BASE_SCORE

router = APIRouter(prefix="/api/cases", tags=["cases"])

CONSENT_TEXT_VERSION = "v1-2026-10"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


MAX_ESCALATION = 20.0
_NEXT_BAND_FLOOR = {"P2": BASE_SCORE["P1"], "P3": BASE_SCORE["P2"], "P4": BASE_SCORE["P3"]}


def waiting_escalation(waiting: int, target: int) -> float:
    """Overdue cases climb the queue: +10 points per target-length of overdue time, capped."""
    overdue_by = waiting - target
    return min(MAX_ESCALATION - 0.5, overdue_by / max(target, 10) * 10)


def queue_score(sort_score: float, priority: str | None, waiting: int, target: int | None, overdue: bool) -> float:
    """Waiting lifts a case within its band but never above a fresh case of a more urgent band."""
    if not overdue or target is None:
        return sort_score
    score = sort_score + waiting_escalation(waiting, target)
    ceiling = _NEXT_BAND_FLOOR.get(priority or "")
    return min(score, ceiling - 0.5) if ceiling is not None else score


def latest_triage(session: Session, case_id: int) -> TriageResult | None:
    return session.exec(
        select(TriageResult).where(TriageResult.case_id == case_id).order_by(TriageResult.id.desc())
    ).first()


def latest_note(session: Session, case_id: int) -> TriageNote | None:
    return session.exec(
        select(TriageNote).where(TriageNote.case_id == case_id).order_by(TriageNote.version.desc())
    ).first()


READING_KEYS = ("engine", "avg_confidence", "legibility", "pages", "lines", "segments", "duration_s",
                "quality_flags", "attempts", "translation_engine", "translation_uncertain_phrases", "filename")


def source_out(s: Source) -> SourceOut:
    meta = s.meta or {}
    return SourceOut(
        id=s.id, kind=s.kind, label=s.label, original_text=s.original_text, language=s.language,
        language_confidence=s.language_confidence, translated_text=s.translated_text,
        translation_confidence=s.translation_confidence, mime=s.mime, processing_status=s.processing_status,
        has_file=bool(s.file_path), reading={k: meta[k] for k in READING_KEYS if k in meta},
    )


def _strip_quotes(obj: Any) -> Any:
    """Remove verbatim patient text (evidence quotes) from a payload, keeping structure and source ids."""
    if isinstance(obj, dict):
        return {k: (None if k in ("quote", "text") and "source_id" in obj else _strip_quotes(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_quotes(x) for x in obj]
    return obj


def build_detail(session: Session, case: Case, actor: Actor, receipt: Optional[dict] = None) -> CaseDetail:
    """Shape the case for the signed-in role (least privilege)."""
    patient = session.get(Patient, case.patient_id)
    sources = session.exec(select(Source).where(Source.case_id == case.id).order_by(Source.id)).all()
    tri = latest_triage(session, case.id)
    note = latest_note(session, case.id)
    see_sources = actor.can("case:read_sources")
    hidden = {"access_code", "withdrawal_reason"} | (set() if actor.can("patient:contact") else {"phone"})
    src_out = [source_out(s) for s in sources]
    if not see_sources:
        for so in src_out:
            so.original_text, so.translated_text, so.has_file = "", None, False
            so.reading = {k: v for k, v in so.reading.items() if k not in ("lines", "segments", "filename")}
    return CaseDetail(
        id=case.id,
        status=case.status,
        patient=patient.model_dump(exclude=hidden) if patient else {},
        sources=src_out,
        extraction=case.extraction if see_sources else None,
        extraction_provider=case.extraction_provider,
        extraction_latency_ms=case.extraction_latency_ms,
        triage=(tri.payload if see_sources else _strip_quotes(tri.payload)) if tri else None,
        note=NoteOut.model_validate(note, from_attributes=True) if note and actor.can("case:read_clinical") else None,
        final_priority=case.final_priority,
        created_at=case.created_at,
        permissions=actor.permissions,
        withdrawn=bool(patient and patient.withdrawn_at),
        learning_mode=get_config(session).mode,
        agent=agent_view(session.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == case.id)).first())
        if actor.can("case:read_clinical") else None,
        receipt=receipt,
    )


def ensure_active(session: Session, case: Case) -> None:
    """No further processing once consent is withdrawn."""
    patient = session.get(Patient, case.patient_id)
    if patient and patient.withdrawn_at:
        raise HTTPException(409, "The patient has withdrawn consent; this case can no longer be processed.")


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def new_access_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def receipt_for(patient: Patient, case: Case) -> dict:
    return {"case_id": case.id, "access_code": patient.access_code, "consent_version": patient.consent_text_version,
            "consent_at": patient.consent_at, "withdraw_url": "/withdraw"}


def _new_case(session: Session, body: CaseCreate | CaseIntake, actor: Actor) -> Case:
    if not body.consent_given:
        raise HTTPException(status_code=422, detail="Patient consent is required before any data is processed.")

    now = datetime.now(timezone.utc)
    patient = Patient(**body.patient.model_dump(), consent_given=True, consent_at=now,
                      consent_text_version=CONSENT_TEXT_VERSION, access_code=new_access_code())
    session.add(patient)
    session.flush()
    audit_logger.log(session, actor=actor.username, actor_type="human", action="consent_recorded",
                     patient_id=patient.id, details={"version": CONSENT_TEXT_VERSION})

    case = Case(patient_id=patient.id)
    session.add(case)
    session.flush()
    if body.message and body.message.strip():
        add_text_source(session, case, body.message, kind="patient_message", label="Patient message")
    if body.vitals:
        form = vitals_form_text(body.vitals)
        if form:
            add_text_source(session, case, form, kind="intake_form", label="Intake form (vitals)")
    audit_logger.log(session, actor=actor.username, actor_type="human", action="case_created",
                     case_id=case.id, patient_id=patient.id, details={"role": actor.role})
    return case


async def _attach_files(session: Session, case: Case, files: list[UploadFile], actor: Actor) -> None:
    for f in files:
        content = await f.read()
        try:
            src = add_file_source(session, case, f.filename or "upload", content, f.content_type)
        except UploadRejected as e:
            session.rollback()
            raise HTTPException(422, f"{f.filename}: {e}") from e
        audit_logger.log(session, actor=actor.username, actor_type="human", action="source_uploaded", case_id=case.id,
                         details={"source_id": src.id, "kind": src.kind, "mime": src.mime,
                                  "size_bytes": len(content)})


@router.post("", response_model=CaseDetail, status_code=201)
def create_case(body: CaseCreate, session: Session = Depends(get_session), actor: Actor = Depends(require("case:create"))):
    """Text-only intake (JSON)."""
    case = _new_case(session, body, actor)
    session.commit()
    process_case(session, case)
    session.refresh(case)
    return build_detail(session, case, actor, receipt_for(session.get(Patient, case.patient_id), case))


@router.post("/intake", response_model=CaseDetail, status_code=201)
async def create_case_with_files(
    payload: str = Form(..., description="CaseIntake as JSON"),
    files: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("case:create")),
):
    """Multipart intake: patient details + optional message/vitals + reports (images/PDF) and voice notes."""
    try:
        body = CaseIntake.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(422, f"Invalid payload: {e}") from e
    if not (body.message and body.message.strip()) and not files:
        raise HTTPException(422, "Provide a message, a file, or both.")
    case = _new_case(session, body, actor)
    await _attach_files(session, case, files, actor)
    session.commit()
    process_case(session, case)
    session.refresh(case)
    return build_detail(session, case, actor, receipt_for(session.get(Patient, case.patient_id), case))


@router.post("/{case_id}/sources", response_model=CaseDetail)
async def add_sources(
    case_id: int,
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("case:upload")),
):
    """Attach more reports / voice notes to an open case and re-run triage."""
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status == CaseStatus.FINALIZED:
        raise HTTPException(409, "Case is finalized.")
    ensure_active(session, case)
    await _attach_files(session, case, files, actor)
    session.commit()
    process_case(session, case)
    session.refresh(case)
    return build_detail(session, case, actor)


@router.get("", response_model=list[CaseListItem])
def list_cases(
    status: str | None = Query(default=None, description="awaiting_review | finalized | error"),
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("case:read")),
):
    stmt = select(Case, Patient).join(Patient, Patient.id == Case.patient_id)
    if status:
        stmt = stmt.where(Case.status == status)
    now = datetime.now(timezone.utc)
    items: list[CaseListItem] = []
    for case, patient in session.exec(stmt).all():
        if patient.withdrawn_at:
            continue
        tri = latest_triage(session, case.id)
        payload = tri.payload if tri else {}
        waiting = int((now - _aware(case.created_at)).total_seconds() // 60)
        pr = case.final_priority or case.priority
        target = PRIORITY_INFO[pr]["target_minutes"] if pr else None
        reasons = payload.get("reasons") or []
        validation = payload.get("validation") or {}
        flags = [f for f in validation.get("flags") or [] if f.get("severity") != "info"]
        counts = {k: sum(1 for f in flags if f["type"] == k) for k in ("suspicious", "conflicting", "unclear", "missing")}
        overdue = case.status == CaseStatus.AWAITING_REVIEW and target is not None and waiting > target
        qscore = queue_score(case.sort_score, pr, waiting, target, overdue)
        kinds = sorted({s.kind for s in session.exec(select(Source).where(Source.case_id == case.id)).all()})
        items.append(CaseListItem(
            id=case.id, patient_name=patient.name, age_years=patient.age_years, sex=patient.sex,
            status=case.status, priority=case.priority,
            priority_label=PRIORITY_INFO[case.priority]["label"] if case.priority else None,
            final_priority=case.final_priority, chief_complaint=case.chief_complaint,
            red_flag_count=len(payload.get("red_flags") or []),
            top_reason=reasons[0]["text"] if reasons else None,
            uncertain=bool((payload.get("data_quality") or {}).get("uncertain")),
            sort_score=case.sort_score, created_at=case.created_at, waiting_minutes=waiting,
            overdue=overdue, target_minutes=target, queue_score=round(qscore, 2),
            completeness=validation.get("completeness"), flag_counts=counts,
            critical_flags=sum(1 for f in flags if f["severity"] == "critical"), source_kinds=kinds,
        ))
    # Open cases first, then by urgency (with waiting-time escalation), then longest waiting
    items.sort(key=lambda c: (c.status != CaseStatus.AWAITING_REVIEW, -c.queue_score, -c.waiting_minutes))
    return items


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: int, session: Session = Depends(get_session), actor: Actor = Depends(require("case:read"))):
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    patient = session.get(Patient, case.patient_id)
    if patient and patient.withdrawn_at and not actor.can("data:erase"):
        raise HTTPException(410, "The patient withdrew consent. This case is hidden pending erasure.")
    audit_logger.log(session, actor=actor.username, actor_type="human", action="case_viewed",
                     case_id=case.id, commit=True)
    return build_detail(session, case, actor)


@router.post("/{case_id}/retriage", response_model=CaseDetail)
def retriage(case_id: int, session: Session = Depends(get_session), actor: Actor = Depends(require("case:retriage"))):
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    ensure_active(session, case)
    if case.status == CaseStatus.FINALIZED:
        raise HTTPException(409, "Case is finalized; re-triage is disabled.")
    audit_logger.log(session, actor=actor.username, actor_type="human", action="retriage_requested", case_id=case.id)
    process_case(session, case)
    session.refresh(case)
    return build_detail(session, case, actor)


_YES = {"yes", "y", "haan", "ha", "han", "hanji", "ji haan", "ji", "हाँ", "हां", "true"}
_NO = {"no", "n", "nahi", "nahin", "nhi", "na", "ji nahi", "नहीं", "false"}


def _phrase(cid: str) -> str:
    syns = load_lexicon().get(cid, {}).get("synonyms", [])
    return next((str(x) for x in syns if str(x).isascii()), cid.replace("_", " "))


@router.post("/{case_id}/answers", response_model=CaseDetail)
def answer_followups(case_id: int, body: AnswersIn, session: Session = Depends(get_session),
                     actor: Actor = Depends(require("case:answer"))):
    """Record answers to follow-up questions (from the patient or staff) and re-run triage.

    Yes/no answers to symptom questions become explicit statements ("Patient denies sweating."), so the
    deterministic scanner reads them reliably; the question text itself is never fed back as evidence."""
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status == CaseStatus.FINALIZED:
        raise HTTPException(409, "Case is finalized.")
    ensure_active(session, case)
    tri = latest_triage(session, case.id)
    questions = {q["id"]: q for q in ((tri.payload.get("validation") or {}).get("followups") or [])} if tri else {}

    lines, recorded = [], []
    for a in body.answers:
        q = questions.get(a.question_id)
        if q is None:
            raise HTTPException(422, f"Unknown question id: {a.question_id}")
        yes = a.yes
        if yes is None and a.answer and a.answer.strip().lower().strip(".!") in _YES | _NO:
            yes = a.answer.strip().lower().strip(".!") in _YES
        if q.get("symptom") and yes is not None:
            lines.append(f"Patient {'reports' if yes else 'denies'} {_phrase(q['symptom'])}.")
        elif a.answer and a.answer.strip():
            label = q["reason"].removeprefix("Missing: ")
            lines.append(f"{label}: {a.answer.strip()}")
        else:
            continue
        recorded.append({"question_id": a.question_id, "question": q["text_en"], "answer": a.answer, "yes": yes})
    if not lines:
        raise HTTPException(422, "No usable answers.")

    src = add_text_source(session, case, "\n".join(lines), kind="followup_answer", label="Follow-up answers")
    src.meta = {"answers": recorded, "answered_by": actor.username}
    session.add(src)
    audit_logger.log(session, actor=actor.username, actor_type="human", action="followup_answered", case_id=case.id,
                     details={"source_id": src.id, "questions": [r["question_id"] for r in recorded]})
    session.commit()
    process_case(session, case)
    session.refresh(case)
    return build_detail(session, case, actor)


@router.get("/{case_id}/similar")
def similar(case_id: int, session: Session = Depends(get_session), _: Actor = Depends(require("case:read_clinical"))):
    """Past cases already decided by clinicians that look most like this one (no identifiers)."""
    if not session.get(Case, case_id):
        raise HTTPException(404, "Case not found")
    found = similar_cases(session, case_id)
    return found[0] if found else {"summary": None, "cases": []}


files_router = APIRouter(prefix="/api/sources", tags=["sources"])


@files_router.get("/{source_id}/file")
def source_file(source_id: int, session: Session = Depends(get_session), actor: Actor = Depends(require("case:read_sources"))):
    """Original upload, for the source viewer (report image / PDF, voice note)."""
    src = session.get(Source, source_id)
    if not src or not src.file_path:
        raise HTTPException(404, "No file for this source")
    case = session.get(Case, src.case_id)
    patient = session.get(Patient, case.patient_id) if case else None
    if patient and patient.withdrawn_at:
        raise HTTPException(410, "Patient withdrew consent")
    try:
        path = absolute(src.file_path)
    except UploadRejected as e:
        raise HTTPException(400, str(e)) from e
    if not path.exists():
        raise HTTPException(404, "File missing")
    audit_logger.log(session, actor=actor.username, actor_type="human", action="source_file_viewed",
                     case_id=src.case_id, details={"source_id": src.id}, commit=True)
    return FileResponse(path, media_type=src.mime or "application/octet-stream")
