"""
NEET Royale AI Microservice — FastAPI entry point.

Start the server:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Or via the convenience script:
    python -m app.main

Endpoints exposed:
    GET  /match/questions            — serve questions for a match round
    POST /answers/submit             — record a player's answer
    GET  /performance/summary/{id}   — post-match performance report
    POST /performance/end/{id}       — mark a session as completed

    GET  /health                     — liveness check (for deployment)
    GET  /docs                       — Swagger UI (auto-generated)
    GET  /redoc                      — ReDoc UI (auto-generated)
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.answers import router as answers_router
from app.api.match import router as match_router
from app.api.performance import router as performance_router
from app.db.performance_db import init_db as init_performance_db
from app.db.question_registry import init_db as init_question_db
from app.db.source_registry import init_db as init_source_db

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NEET Royale AI Microservice",
    description=(
        "Question sourcing, match serving, answer tracking, and performance "
        "summaries for the NEET Royale multiplayer quiz platform. "
        "All questions are extracted from real NEET past papers."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow any origin during dev — tighten this in production to your gateway's domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup: ensure all DB tables exist
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup() -> None:
    init_source_db()
    init_question_db()
    init_performance_db()


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(match_router)
app.include_router(answers_router)
app.include_router(performance_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"], summary="Liveness probe")
def health():
    return {"status": "ok", "service": "neet-royale-ai"}


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
