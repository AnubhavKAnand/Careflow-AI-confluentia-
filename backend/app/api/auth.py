from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import Actor, get_actor, require
from app.db import get_session
from app.models.user import User
from app.services.privacy import audit_logger
from app.services.privacy.auth import (clear_failures, create_token, locked_out, permissions_for, record_failure,
                                       verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _user_out(u: User | Actor) -> dict:
    return {"username": u.username, "full_name": u.full_name, "role": u.role, "permissions": permissions_for(u.role)}


@router.post("/login")
def login(body: LoginIn, session: Session = Depends(get_session)):
    username = body.username.strip().lower()
    if locked_out(username):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    user = session.exec(select(User).where(User.username == username)).first()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        record_failure(username)
        audit_logger.log(session, actor=username, actor_type="human", action="login_failed", commit=True)
        raise HTTPException(401, "Wrong username or password.")
    clear_failures(username)
    user.last_login_at = datetime.now(timezone.utc)
    session.add(user)
    audit_logger.log(session, actor=user.username, actor_type="human", action="login", details={"role": user.role})
    session.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "user": _user_out(user)}


@router.get("/me")
def me(actor: Actor = Depends(get_actor)):
    return _user_out(actor)


@router.get("/users")
def users(session: Session = Depends(get_session), _: Actor = Depends(require("users:read"))):
    return [{**_user_out(u), "active": u.active, "last_login_at": u.last_login_at} for u in session.exec(select(User)).all()]
