"""Clinician review: edit the draft note, then approve or override the AI's suggested priority."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.cases import build_detail, latest_note
from app.api.deps import Actor, require
from app.db import get_session
from app.models import Case, CaseStatus, Review, TriageNote
from app.schemas.api import CaseDetail, NoteUpdate, ReviewIn
from app.services.learning.shadow import learn_from_review
from app.services.privacy import audit_logger

router = APIRouter(prefix="/api/cases", tags=["review"])

def _new_version(session: Session, case: Case, content: str, actor: Actor) -> TriageNote:
    prev = latest_note(session, case.id)
    note = TriageNote(case_id=case.id, version=(prev.version + 1) if prev else 1, content=content,
                      status="edited", author=actor.username, author_type="human")
    session.add(note)
    session.flush()
    audit_logger.log(session, actor=actor.username, actor_type="human", action="note_edited", case_id=case.id,
                     details={"note_id": note.id, "version": note.version,
                              "previous_version": prev.version if prev else None})
    return note


@router.put("/{case_id}/note", response_model=CaseDetail)
def edit_note(case_id: int, body: NoteUpdate, session: Session = Depends(get_session),
              actor: Actor = Depends(require("note:edit"))):
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status == CaseStatus.FINALIZED:
        raise HTTPException(409, "Case is finalized.")
    _new_version(session, case, body.content, actor)
    session.commit()
    return build_detail(session, case, actor)


@router.post("/{case_id}/review", response_model=CaseDetail)
def review_case(case_id: int, body: ReviewIn, session: Session = Depends(get_session),
                actor: Actor = Depends(require("triage:finalize"))):
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status == CaseStatus.FINALIZED:
        raise HTTPException(409, "Case is already finalized.")
    if not case.priority:
        raise HTTPException(409, "Case has no AI suggestion yet.")

    ai = case.priority
    if body.action == "approve" and body.final_priority != ai:
        raise HTTPException(422, "Approving keeps the suggested priority; use action='override' to change it.")
    if body.action == "override" and not (body.reason and body.reason.strip()):
        raise HTTPException(422, "A reason is required when overriding the suggested priority.")

    note = _new_version(session, case, body.note_content, actor) if body.note_content else latest_note(session, case.id)
    if note:
        note.status = "approved"
        session.add(note)

    session.add(Review(case_id=case.id, reviewer=actor.username, reviewer_role=actor.role, action=body.action,
                       ai_priority=ai, final_priority=body.final_priority, reason=body.reason,
                       note_id=note.id if note else None))
    case.final_priority = body.final_priority
    case.status = CaseStatus.FINALIZED
    learn_from_review(session, case.id, body.final_priority, actor.username)
    case.updated_at = datetime.now(timezone.utc)
    session.add(case)
    audit_logger.log(session, actor=actor.username, actor_type="human",
                     action="priority_overridden" if body.action == "override" else "triage_approved",
                     case_id=case.id, details={"ai_priority": ai, "final_priority": body.final_priority,
                                               "reason_given": bool(body.reason), "note_id": note.id if note else None})
    session.commit()
    return build_detail(session, case, actor)
