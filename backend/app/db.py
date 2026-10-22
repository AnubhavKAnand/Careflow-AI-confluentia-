from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {},
)


def init_db() -> None:
    import app.models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)
    from app.services.privacy.auth import seed_demo_users

    with Session(engine) as session:
        seed_demo_users(session)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
