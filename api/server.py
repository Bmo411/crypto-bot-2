"""
TradingBot V5 — FastAPI Server

Mounts the dashboard router and provides lifecycle hooks.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

from metrics.dashboard import router as dashboard_router

log = logging.getLogger("api.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — startup and shutdown hooks."""
    log.info("FastAPI server starting...")
    yield
    log.info("FastAPI server shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="TradingBot V5",
        description="Algorithmic Trading System — Monitoring Dashboard",
        version="5.0.0",
        lifespan=lifespan,
    )

    app.include_router(dashboard_router, tags=["Dashboard"])

    # Serve Static Files
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    if os.path.exists(frontend_dir):
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
    async def index_dashboard():
        """Serve the main Web Dashboard."""
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            with open(index_file, "r", encoding="utf-8") as f:
                return f.read()
        return "<h1>Dashboard Web UI not found (frontend directory missing)</h1>"

    return app
