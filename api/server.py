"""
TradingBot V5 — FastAPI Server

Mounts the dashboard router and provides lifecycle hooks.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
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

    return app
