from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, cases, evaluation, learning, privacy, review, system
from app.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    description="Human-in-the-loop healthcare triage assistant. Suggestions only; clinicians decide.",
    version=settings.engine_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(privacy.router)
app.include_router(cases.router)
app.include_router(cases.files_router)
app.include_router(review.router)
app.include_router(learning.router)
app.include_router(evaluation.router)
