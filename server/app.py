"""
OptionScout Trading Tracker — FastAPI Application
Main entry point for the backend server.
"""

import os
import sys

# Ensure project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env into os.environ at startup (once), so modules don't need to open the file themselves
_env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except PermissionError:
        pass  # macOS sandbox — rely on env vars set externally

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.models import init_db, SessionLocal, seed_tickers
from server.routes import trades, portfolio, analytics, sync, reports

app = FastAPI(
    title="OptionScout Trading Tracker",
    description="Options trading journal and portfolio analytics for systematic CSP strategy",
    version="1.0.0",
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(trades.router)
app.include_router(portfolio.router)
app.include_router(analytics.router)
app.include_router(sync.router)
app.include_router(reports.router)


@app.on_event("startup")
def on_startup():
    """Initialize database and seed data on startup."""
    init_db()
    db = SessionLocal()
    try:
        seed_tickers(db)
    finally:
        db.close()


@app.get("/")
def root():
    return {
        "app": "OptionScout Trading Tracker",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/config")
def get_config():
    """Return strategy configuration (non-sensitive)."""
    import json
    config_path = os.path.join(PROJECT_ROOT, "config.json")
    with open(config_path) as f:
        config = json.load(f)
    # Remove sensitive moomoo fields
    safe_config = {k: v for k, v in config.items() if k != "moomoo"}
    safe_config["moomoo"] = {"connected": False}  # Will be updated by status check
    return safe_config


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
