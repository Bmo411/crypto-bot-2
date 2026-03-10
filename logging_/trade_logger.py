"""
TradingBot V5 — Trade Logger

Unified structured logger for all trading events.
Outputs to both console (human-readable) and file (JSON lines).
"""

import logging
import os
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from config.settings import SETTINGS
from logging_.formatters import ConsoleFormatter, JSONFormatter


def setup_logging() -> None:
    """
    Configure the global logging system.

    Creates three file handlers:
      - trading_YYYY-MM-DD.jsonl  (signals, orders, fills, PnL)
      - system_YYYY-MM-DD.jsonl   (startup, shutdown, reconciliation)
      - errors_YYYY-MM-DD.jsonl   (WARNING and above)
    Plus a colored console handler.
    """
    log_dir = Path(SETTINGS.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Clear existing handlers (for restart safety)
    root_logger.handlers.clear()

    # ── Console Handler ─────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console)

    # ── Trading Log (JSON) ──────────────────────────────────────
    trading_handler = _create_rotating_handler(
        log_dir / "trading.jsonl", logging.DEBUG
    )
    trading_handler.addFilter(_CategoryFilter([
        "strategy", "execution", "positions", "risk",
    ]))
    root_logger.addHandler(trading_handler)

    # ── System Log (JSON) ───────────────────────────────────────
    system_handler = _create_rotating_handler(
        log_dir / "system.jsonl", logging.DEBUG
    )
    system_handler.addFilter(_CategoryFilter([
        "storage", "reconciliation", "recovery", "market_data", "api",
    ]))
    root_logger.addHandler(system_handler)

    # ── Error Log (JSON) ────────────────────────────────────────
    error_handler = _create_rotating_handler(
        log_dir / "errors.jsonl", logging.WARNING
    )
    root_logger.addHandler(error_handler)

    logging.getLogger().info("Logging initialized")


def _create_rotating_handler(
    filepath: Path, level: int
) -> TimedRotatingFileHandler:
    """Create a daily-rotating JSON log handler."""
    handler = TimedRotatingFileHandler(
        filename=str(filepath),
        when="midnight",
        interval=1,
        backupCount=30,
        utc=True,
    )
    handler.setLevel(level)
    handler.setFormatter(JSONFormatter())
    return handler


class _CategoryFilter(logging.Filter):
    """Only allow log records from specific logger name prefixes."""

    def __init__(self, prefixes: list[str]):
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(record.name.startswith(p) for p in self._prefixes)
