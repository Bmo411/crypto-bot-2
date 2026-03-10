"""
TradingBot V5 — Global Settings

Loads configuration from environment variables (.env file).
All settings are typed and validated at startup.
"""

from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Immutable application configuration."""

    # ── Alpaca API ──────────────────────────────────────────────
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    alpaca_base_url: str = os.getenv(
        "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
    )
    paper_mode: bool = os.getenv("PAPER_MODE", "true").lower() == "true"

    # ── Capital & Risk ──────────────────────────────────────────
    initial_capital: float = 84_000.0
    risk_per_trade: float = 0.003          # 0.3%
    max_position_pct: float = 0.10         # 10% of equity
    max_daily_loss_pct: float = 0.03       # 3%
    max_positions: int = 5

    # ── System Paths ────────────────────────────────────────────
    project_root: str = str(_PROJECT_ROOT)
    db_path: str = str(_PROJECT_ROOT / "data" / "trading_v5.db")
    log_dir: str = str(_PROJECT_ROOT / "data" / "logs")
    pid_file: str = str(_PROJECT_ROOT / "data" / "trading_v5.pid")

    # ── Intervals (seconds) ────────────────────────────────────
    bar_interval: int = 60                 # 1-minute bars
    reconciliation_interval: int = 300     # 5 minutes
    heartbeat_interval: int = 60           # 1 minute
    equity_snapshot_interval: int = 60     # 1 minute
    metrics_snapshot_interval: int = 60    # 1 minute

    # ── API Server ──────────────────────────────────────────────
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8080"))

    # ── WebSocket ───────────────────────────────────────────────
    ws_reconnect_min: float = 1.0          # seconds
    ws_reconnect_max: float = 60.0         # seconds
    ws_reconnect_factor: float = 2.0       # exponential factor

    # ── Execution ───────────────────────────────────────────────
    order_timeout: float = 10.0            # seconds
    fill_timeout: float = 30.0             # seconds — cancel if no fill
    buying_power_buffer: float = 0.95      # use max 95% of BP

    # ── Recovery ────────────────────────────────────────────────
    warmup_bars: int = 200                 # bars to load on startup
    max_component_failures: int = 5        # failures before halt
    component_failure_window: int = 600    # 10 minutes

    def validate(self) -> None:
        """Raise if critical settings are missing."""
        if not self.alpaca_api_key:
            raise ValueError("ALPACA_API_KEY is required")
        if not self.alpaca_secret_key:
            raise ValueError("ALPACA_SECRET_KEY is required")


# Singleton instance
SETTINGS = Settings()
