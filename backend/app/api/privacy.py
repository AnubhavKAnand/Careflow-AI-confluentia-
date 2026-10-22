"""Consent withdrawal, erasure (right to be forgotten), and the audit log."""
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, delete, select

from app.api.deps import Actor, require
from app.db import get_session
from app.models import AuditLog, Case, Patient, Review, ShadowPrediction, Source, TriageNote, TriageResult
from app.services.ingestion.storage import UploadRejected, absolute
from app.services.privacy import audit_logger

router = APIRouter(prefix="/api", tags=["privacy"])


class WithdrawIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class PublicWithdrawIn(BaseModel):
    case_id: int
    access_code: str = Field(min_length=4, max_length=20)


def _withdraw(session: Session, patient: Patient, by: str, reason: str | None) -> None:
    if patient.withdrawn_at:
        return
    patient.withdrawn_at = datetime.now(timezone.utc)
    patient.withdrawn_by = by
    patient.withdrawal_reason = reason
    session.add(patient)
    audit_logger.log(session, actor=by, actor_type="human", action="consent_withdrawn", patient_id=patient.id,
                     details={"by_patient": by == "patient", "reason_given": bool(reason)})
    session.commit()


@router.post("/cases/{case_id}/withdraw")
def withdraw_consent(case_id: int, body: WithdrawIn, session: Session = Depends(get_session),
                     actor: Actor = Depends(require("consent:withdraw"))):
    """Staff record that the patient withdrew consent: processing stops and the case leaves the queue."""
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    patient = session.get(Patient, case.patient_id)
    _withdraw(session, patient, actor.username, body.reason)
    return {"withdrawn": True, "patient_id": patient.id, "pending_erasure": True}


@router.post("/public/withdraw")
def public_withdraw(body: PublicWithdrawIn, session: Session = Depends(get_session)):
    """Patient self-service: withdraw consent with the code on the consent receipt (no account needed)."""
    case = session.get(Case, body.case_id)
    patient = session.get(Patient, case.patient_id) if case else None
    code = body.access_code.strip().upper()
    if not patient or not patient.access_code or not hmac.compare_digest(patient.access_code, code):
        raise HTTPException(404, "No case matches that number and code.")
    _withdraw(session, patient, "patient", None)
    return {"withdrawn": True, "message": "Your consent has been withdrawn. Your data will no longer be used and will be deleted."}


@router.get("/privacy/requests")
def erasure_queue(session: Session = Depends(get_session), _: Actor = Depends(require("data:erase"))):
    """Patients who withdrew consent and whose data is waiting to be erased."""
    rows = session.exec(select(Patient).where(Patient.withdrawn_at.is_not(None))).all()  # type: ignore[union-attr]
    out = []
    for p in rows:
        cases = session.exec(select(Case).where(Case.patient_id == p.id)).all()
        files = sum(1 for c in cases for s in session.exec(select(Source).where(Source.case_id == c.id)).all() if s.file_path)
        out.append({"patient_id": p.id, "case_ids": [c.id for c in cases], "withdrawn_at": p.withdrawn_at,
                    "withdrawn_by": p.withdrawn_by, "reason": p.withdrawal_reason, "files": files})
    return out


@router.delete("/patients/{patient_id}")
def erase_patient(patient_id: int, session: Session = Depends(get_session), actor: Actor = Depends(require("data:erase"))):
    """Permanently delete a patient's data: uploaded files, sources, extractions, notes, reviews and the
    patient record. The audit log keeps only a tombstone (ids and counts, no personal data)."""
    patient = session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found (already erased?)")
    if not patient.withdrawn_at:
        raise HTTPException(409, "Record the consent withdrawal before erasing (keeps an auditable reason).")
    cases = session.exec(select(Case).where(Case.patient_id == patient_id)).all()
    counts = {"cases": len(cases), "sources": 0, "files": 0, "notes": 0, "triage_results": 0, "reviews": 0}
    for c in cases:
        for s in session.exec(select(Source).where(Source.case_id == c.id)).all():
            if s.file_path:
                try:
                    path = absolute(s.file_path)
                    if path.exists():
                        path.unlink()
                        counts["files"] += 1
                except UploadRejected:
                    pass
            counts["sources"] += 1
        for model, key in ((TriageNote, "notes"), (TriageResult, "triage_results"), (Review, "reviews")):
            counts[key] += len(session.exec(select(model).where(model.case_id == c.id)).all())
        counts["learning_examples"] = counts.get("learning_examples", 0) + len(
            session.exec(select(ShadowPrediction).where(ShadowPrediction.case_id == c.id)).all())
        session.exec(delete(ShadowPrediction).where(ShadowPrediction.case_id == c.id))  # model recomputes without them
        session.exec(delete(Review).where(Review.case_id == c.id))
        session.exec(delete(TriageNote).where(TriageNote.case_id == c.id))
        session.exec(delete(TriageResult).where(TriageResult.case_id == c.id))
        session.exec(delete(Source).where(Source.case_id == c.id))
        session.delete(c)
    session.delete(patient)
    session.flush()
    audit_logger.log(session, actor=actor.username, actor_type="human", action="patient_data_erased",
                     patient_id=patient_id, details={"case_ids": [c.id for c in cases], **counts})
    session.commit()
    return {"erased": True, **counts}


@router.get("/audit")
def audit_log(
    case_id: int | None = Query(default=None),
    actor_type: str | None = Query(default=None, description="human | ai | system"),
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    limit: int = Query(default=300, le=2000),
    session: Session = Depends(get_session),
    _: Actor = Depends(require("audit:read")),
):
    stmt = select(AuditLog)
    if case_id is not None:
        stmt = stmt.where(AuditLog.case_id == case_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    return session.exec(stmt.order_by(AuditLog.id.desc()).limit(limit)).all()


@router.get("/audit/verify")
def verify_audit(session: Session = Depends(get_session), _: Actor = Depends(require("audit:read"))):
    return audit_logger.verify_chain(session)
