"""Append-only, hash-chained audit log.

Each row stores the SHA-256 of (its own content + the previous row's hash). Editing or deleting any
past row breaks the chain, which `verify_chain` detects. Details deliberately hold only identifiers,
counts, priorities and rule ids, never free text from patients, so erasing a patient's data never
requires rewriting the log.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.audit import AuditLog

GENESIS = "0" * 64


def _ts(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _digest(row: AuditLog, prev: str) -> str:
    body = json.dumps({
        "ts": _ts(row.ts), "actor": row.actor, "actor_type": row.actor_type, "action": row.action,
        "case_id": row.case_id, "patient_id": row.patient_id, "details": row.details or {}, "prev": prev,
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def log(
    session: Session,
    *,
    actor: str,
    actor_type: str,
    action: str,
    case_id: Optional[int] = None,
    patient_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
    commit: bool = False,
) -> AuditLog:
    last = session.exec(select(AuditLog).order_by(AuditLog.id.desc())).first()  # autoflush includes pending rows
    prev = (last.hash if last and last.hash else GENESIS)
    entry = AuditLog(actor=actor, actor_type=actor_type, action=action, case_id=case_id,
                     patient_id=patient_id, details=details or {})
    entry.prev_hash = prev
    entry.hash = _digest(entry, prev)
    session.add(entry)
    session.flush()
    if commit:
        session.commit()
    return entry


def verify_chain(session: Session) -> dict[str, Any]:
    prev = GENESIS
    n = 0
    for row in session.exec(select(AuditLog).order_by(AuditLog.id)).all():
        n += 1
        if row.prev_hash != prev or row.hash != _digest(row, prev):
            return {"ok": False, "entries": n, "broken_at_id": row.id,
                    "detail": f"Entry {row.id} does not match the chain; it or an earlier entry was altered or removed."}
        prev = row.hash
    return {"ok": True, "entries": n, "head": prev}
