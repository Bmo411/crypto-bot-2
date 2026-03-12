"""
TradingBot V5 — Dashboard API Endpoints

FastAPI endpoints for health checks, metrics, and monitoring.
All data originates from Alpaca (via MetricsCollector + PositionManager).
"""

import time
import logging
from fastapi import APIRouter
from typing import Optional

log = logging.getLogger("metrics.dashboard")

router = APIRouter()

# Set by the application at startup via init_dashboard()
_metrics_collector = None
_position_manager = None
_broker_client = None
_start_time = time.time()


def init_dashboard(metrics_collector, position_manager, broker_client=None) -> None:
    """
    Initialize dashboard with component references.
    Must be called once at application startup before any requests are served.
    """
    global _metrics_collector, _position_manager, _broker_client
    _metrics_collector = metrics_collector
    _position_manager = position_manager
    _broker_client = broker_client


# ── Helpers ──────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """Convert to float, return default on error or NaN."""
    try:
        v = float(value)
        if v != v:   # NaN check
            return default
        return v
    except (TypeError, ValueError):
        return default


def _build_position_list() -> list[dict]:
    """
    Return all open positions enriched with live broker fields.

    Fields returned per position:
      symbol, side, qty, avg_entry_price,
      current_price, unrealized_pl, unrealized_plpc
    """
    result = []
    if _position_manager is None:
        return result

    for symbol, pos in _position_manager.open_positions.items():
        current_price = getattr(pos, "current_price", 0.0) or 0.0
        unrealized_plpc = getattr(pos, "unrealized_plpc", 0.0) or 0.0

        # Fallback: calculate PnL if broker fields missing
        unrealized_pl = pos.unrealized_pnl
        if unrealized_pl == 0.0 and pos.avg_entry_price > 0 and current_price > 0:
            if pos.side == "LONG":
                unrealized_pl = (current_price - pos.avg_entry_price) * pos.quantity
            elif pos.side == "SHORT":
                unrealized_pl = (pos.avg_entry_price - current_price) * pos.quantity

        result.append({
            "symbol": symbol,
            "side": pos.side,
            "qty": pos.quantity,
            "avg_entry_price": _safe_float(pos.avg_entry_price),
            "current_price": _safe_float(current_price),
            "unrealized_pl": _safe_float(unrealized_pl),
            "unrealized_plpc": _safe_float(unrealized_plpc),
            "entry_time": pos.entry_time,
        })
    return result


# ── Endpoints ─────────────────────────────────────────────────────

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
    """
    Current open positions with live broker data.

    Returns current_price, unrealized_pl, and unrealized_plpc from Alpaca.
    """
    if _position_manager is None:
        return {"error": "Position manager not initialized"}

    result = _build_position_list()
    return {"positions": result, "count": len(result)}


@router.get("/equity")
async def equity():
    """Equity data."""
    if _metrics_collector is None:
        return {"error": "Metrics collector not initialized"}
    return {
        "equity": _safe_float(_metrics_collector.equity),
        "high_water_mark": _safe_float(_metrics_collector.high_water_mark),
        "timestamp": time.time(),
    }


@router.get("/equity_curve")
async def equity_curve():
    """Historical equity curve from DB (last 24 hours)."""
    from storage.repository import Repository
    # repo is not injected here — we rely on the metrics collector's repo
    # This endpoint is best served via /dashboard which reads DB directly
    return {"error": "Use /dashboard for equity_curve data"}


@router.get("/dashboard")
async def dashboard():
    """
    Combined dashboard endpoint.

    Returns everything the frontend needs in one call:
    {
      "equity":          float,         # real Alpaca account equity
      "cash":            float,
      "buying_power":    float,
      "daily_pnl":       float,
      "daily_pnl_pct":   float,
      "max_drawdown":    float,         # 0.0 when no drawdown, never NaN
      "total_unrealized_pnl": float,
      "open_positions":  [...],         # enriched with current_price etc.
      "win_rate":        float,
      "total_trades":    int,
      "equity_curve":    [...]          # last 24h from DB
    }
    """
    if _metrics_collector is None or _position_manager is None:
        return {"error": "Dashboard not initialized"}

    snap = _metrics_collector.get_metrics_snapshot()

    # Fetch equity curve from DB
    equity_curve_data = []
    try:
        repo = _metrics_collector._repo
        rows = await repo.get_equity_curve(hours=24)
        equity_curve_data = [
            {
                "timestamp": r["timestamp"],
                "equity": _safe_float(r["equity"]),
            }
            for r in rows
        ]
    except Exception as e:
        log.error(f"Failed to fetch equity_curve from DB: {e}")

    open_positions = _build_position_list()

    return {
        # Account
        "equity": _safe_float(snap.get("equity")),
        "cash": _safe_float(snap.get("cash")),
        "buying_power": _safe_float(snap.get("buying_power")),
        # PnL
        "daily_pnl": _safe_float(snap.get("daily_pnl")),
        "daily_pnl_pct": _safe_float(snap.get("daily_pnl_pct")),
        "total_unrealized_pnl": _safe_float(snap.get("total_unrealized_pnl")),
        # Risk
        "max_drawdown": _safe_float(snap.get("max_drawdown")),    # never NaN
        "high_water_mark": _safe_float(snap.get("high_water_mark")),
        "trading_halted": snap.get("trading_halted", False),
        "halt_reason": snap.get("halt_reason"),
        # Trades / performance
        "win_rate": _safe_float(snap.get("win_rate")),
        "total_trades": snap.get("total_trades", 0),
        "profit_factor": _safe_float(snap.get("profit_factor")),
        "sharpe_ratio": _safe_float(snap.get("sharpe_ratio")),
        # Positions
        "open_positions": open_positions,
        "open_position_count": len(open_positions),
        # Equity curve
        "equity_curve": equity_curve_data,
        # Meta
        "timestamp": time.time(),
    }
