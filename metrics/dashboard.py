"""
TradingBot V5 — Dashboard API Endpoints

FastAPI endpoints for health checks, metrics, and monitoring.
"""

import time
import logging
from fastapi import APIRouter
from typing import Optional

log = logging.getLogger("metrics.dashboard")

router = APIRouter()

# These will be set by the application at startup
_metrics_collector = None
_position_manager = None
_start_time = time.time()


def init_dashboard(metrics_collector, position_manager) -> None:
    """Initialize dashboard with component references."""
    global _metrics_collector, _position_manager
    _metrics_collector = metrics_collector
    _position_manager = position_manager


@router.get("/health")
async def health():
    """System health check."""
    return {
        "status": "running",
        "uptime_seconds": time.time() - _start_time,
        "trading_halted": (
            _metrics_collector.get_metrics_snapshot().get("trading_halted", False)
            if _metrics_collector else False
        ),
        "timestamp": time.time(),
    }


@router.get("/metrics")
async def metrics():
    """Full metrics snapshot."""
    if _metrics_collector is None:
        return {"error": "Metrics collector not initialized"}
    return _metrics_collector.get_metrics_snapshot()


@router.get("/positions")
async def positions():
    """Current open positions."""
    if _position_manager is None:
        return {"error": "Position manager not initialized"}

    result = []
    for symbol, pos in _position_manager.open_positions.items():
        result.append({
            "symbol": symbol,
            "side": pos.side,
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "entry_time": pos.entry_time,
        })
    return {"positions": result, "count": len(result)}


@router.get("/equity")
async def equity():
    """Equity data."""
    if _metrics_collector is None:
        return {"error": "Metrics collector not initialized"}
    return {
        "equity": _metrics_collector.equity,
        "high_water_mark": _metrics_collector.high_water_mark,
        "timestamp": time.time(),
    }
