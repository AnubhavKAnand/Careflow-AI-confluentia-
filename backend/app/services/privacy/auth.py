"""Authentication (PBKDF2 passwords + signed JWT) and role-based permissions."""
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from sqlmodel import Session, select

from app.config import get_settings
from app.models.user import User

PBKDF2_ITERATIONS = 240_000

# Who may do what. Least privilege: the intake desk cannot read clinical notes or finalize; the data
# protection officer (admin) manages consent, erasure, users and the audit log but cannot read raw
# clinical text or make triage decisions.
PERMISSIONS: dict[str, set[str]] = {
    "case:create": {"intake", "nurse", "doctor"},
    "case:read": {"intake", "nurse", "doctor", "admin"},
    "case:read_clinical": {"nurse", "doctor"},  # draft/final triage note
    "case:read_sources": {"intake", "nurse", "doctor"},  # raw text of messages, reports, transcripts; original files
    "case:upload": {"intake", "nurse", "doctor"},
    "case:answer": {"intake", "nurse", "doctor"},
    "case:retriage": {"nurse", "doctor"},
    "note:edit": {"nurse", "doctor"},
    "triage:finalize": {"nurse", "doctor"},
    "audit:read": {"nurse", "doctor", "admin"},
    "consent:withdraw": {"intake", "nurse", "doctor", "admin"},
    "data:erase": {"admin"},
    "patient:contact": {"intake", "admin"},  # phone number
    "users:read": {"admin"},
    "learning:read": {"nurse", "doctor", "admin"},
    "learning:manage": {"doctor"},
    "evaluation:read": {"nurse", "doctor", "admin"},  # clinical lead: switch shadow / recommendation mode
}

DEMO_USERS = [
    ("dr.mehra", "Dr. Anjali Mehra", "doctor"),
    ("sr.thomas", "Sister Mary Thomas", "nurse"),
    ("desk.ravi", "Ravi Kumar", "intake"),
    ("admin", "Data Protection Officer", "admin"),
]


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def can(role: str, perm: str) -> bool:
    return role in PERMISSIONS.get(perm, set())


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------ tokens
def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": user.username, "role": user.role, "name": user.full_name,
               "iat": now, "exp": now + timedelta(minutes=s.token_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ------------------------------------------------------------------ brute-force protection (per username, in memory)
_FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW_S = 5, 300


def locked_out(username: str) -> bool:
    recent = [t for t in _FAILS.get(username, []) if time.time() - t < WINDOW_S]
    _FAILS[username] = recent
    return len(recent) >= MAX_FAILS


def record_failure(username: str) -> None:
    _FAILS.setdefault(username, []).append(time.time())


def clear_failures(username: str) -> None:
    _FAILS.pop(username, None)


def seed_demo_users(session: Session) -> None:
    """Create the demo accounts on first start (password from DEMO_PASSWORD)."""
    if session.exec(select(User)).first():
        return
    pw = get_settings().demo_password
    for username, name, role in DEMO_USERS:
        session.add(User(username=username, full_name=name, role=role, password_hash=hash_password(pw)))
    session.commit()
