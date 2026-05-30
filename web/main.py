import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .brain_registry import BRAIN_REGISTRY, load_brains
from .db import get_supabase
from .limiter import limiter
from .routers import admin, billing, brains, chat, group_chat, webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_brains()
    logger.info("Brain registry ready — %d brain(s) loaded", len(BRAIN_REGISTRY))
    await get_supabase()
    logger.info("Database connection ready")
    yield


app = FastAPI(title="Sageroom", lifespan=lifespan, docs_url=None, redoc_url=None)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: __import__("fastapi").responses.JSONResponse(
    status_code=429,
    content={"detail": "Too many requests. Please slow down and try again."},
))
app.add_middleware(SlowAPIMiddleware)

# CORS
allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGIN", "http://localhost:8000").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# API routers
app.include_router(brains.router)
app.include_router(chat.router)
app.include_router(group_chat.router)
app.include_router(billing.router)
app.include_router(admin.router)

# Webhook router — no CORS, no auth middleware
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "brains_loaded": len(BRAIN_REGISTRY)}


# Static files — mounted last so API routes take precedence
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
