from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.patient import utcnow


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    full_name: str
    role: str  # doctor | nurse | intake | admin
    password_hash: str
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: Optional[datetime] = None
