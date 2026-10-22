"""Authenticated actor + permission checks (JWT bearer tokens, see services/privacy/auth.py)."""
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.db import get_session
from app.models.user import User
from app.services.privacy.auth import can, decode_token, permissions_for

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Actor:
    username: str
    role: str  # doctor | nurse | intake | admin
    full_name: str = ""
    permissions: list[str] = field(default_factory=list)

    def can(self, perm: str) -> bool:
        return can(self.role, perm)


def get_actor(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Actor:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(creds.credentials)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid; sign in again",
                            headers={"WWW-Authenticate": "Bearer"})
    user = session.exec(select(User).where(User.username == claims.get("sub"))).first()
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return Actor(username=user.username, role=user.role, full_name=user.full_name, permissions=permissions_for(user.role))


def require(perm: str):
    """Route dependency: the signed-in user must hold `perm`."""

    def check(actor: Actor = Depends(get_actor)) -> Actor:
        if not actor.can(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({actor.role}) is not allowed to do this ({perm}).")
        return actor

    return check
