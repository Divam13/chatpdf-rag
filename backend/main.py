"""
FastAPI application entry-point.
Run: uvicorn main:app --reload --port 8000
"""

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # suppress leaked semaphore warning from HF tokenizers

import logging
import sys
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from routes.auth import router as auth_router
from routes.pdfs import router as pdfs_router
from routes.chats import router as chats_router

# ---------------------------------------------------------------------------
# Logging setup — structured console logging for all chatpdf modules
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s │ %(levelname)-5s │ %(name)s │ %(message)s"
DATE_FORMAT = "%H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    stream=sys.stdout,
    force=True,
)

# Silence noisy third-party loggers
for noisy in ("httpcore", "httpx", "hpack", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("chatpdf.app")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ChatPDF RAG API",
    description="Upload PDFs, ask questions, get AI-powered answers with citations.",
    version="1.0.0",
)

# CORS — origins are configurable via CORS_ORIGINS=a,b,c (comma-separated).
# Falls back to localhost for local dev.
_origins_raw = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
_allow_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request logging middleware — logs every incoming request with timing
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    method = request.method
    path = request.url.path

    # Skip logging for noisy endpoints
    if path in ("/health", "/docs", "/openapi.json", "/favicon.ico"):
        return await call_next(request)

    logger.info(f"→ {method} {path}")

    response = await call_next(request)

    elapsed = time.time() - start
    status = response.status_code
    level = logging.WARNING if status >= 400 else logging.INFO
    logger.log(level, f"← {method} {path} → {status} ({elapsed:.2f}s)")

    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(pdfs_router)
app.include_router(chats_router)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "ChatPDF RAG API is running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Startup log
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    logger.info("═" * 60)
    logger.info("  ChatPDF RAG API starting up...")
    logger.info("  Docs: http://localhost:8000/docs")
    logger.info("═" * 60)