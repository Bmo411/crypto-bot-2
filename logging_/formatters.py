"""
TradingBot V5 — Log Formatters

Console (human-readable) and file (JSON lines) formatters.
"""

import json
import logging
from datetime import datetime, timezone


class ConsoleFormatter(logging.Formatter):
    """
    Colored, human-readable console output.
    Format: [HH:MM:SS] LEVEL    module    message
    """

    COLORS = {
        "DEBUG": "\033[36m",      # cyan
        "INFO": "\033[32m",       # green
        "WARNING": "\033[33m",    # yellow
        "ERROR": "\033[31m",      # red
        "CRITICAL": "\033[41m",   # red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).strftime("%H:%M:%S")

        return (
            f"{color}[{ts}] {record.levelname:<8}{self.RESET} "
            f"\033[90m{record.name:<30}{self.RESET} "
            f"{record.getMessage()}"
        )


class JSONFormatter(logging.Formatter):
    """
    Structured JSON log output — one JSON object per line.
    Suitable for log ingestion and analytics.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # Include extra fields if attached
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        return json.dumps(log_entry, default=str)
