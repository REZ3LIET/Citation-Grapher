from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import get_settings
from .core.database import init_db
from .core.runner import runner


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    runner.resume_interrupted()
    yield


settings = get_settings()
app = FastAPI(
    title="Citation Grapher API",
    version="0.1.0",
    description="Restart-safe, keyless citation-connected literature discovery",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

