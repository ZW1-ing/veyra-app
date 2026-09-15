"""FastAPI 应用装配。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import chat, health, kb, sessions
from .core.config import get_settings
from .core.logging import setup_logging
from .db.session import init_db
from .kb.factory import build_embedding
from .llm.factory import build_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    app.state.settings = settings
    app.state.provider = build_provider(settings)
    app.state.embedding = build_embedding(settings)
    if settings.auto_create_tables:
        init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Veyra Agent API",
        version="0.1.0",
        description="Veyra Agent 引擎的 Python 实现：FastAPI + LangGraph + MySQL",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(kb.router)
    app.include_router(chat.router)
    return app


app = create_app()
