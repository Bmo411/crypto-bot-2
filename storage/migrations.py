"""
TradingBot V5 — Database Migrations

Idempotent schema creation with version tracking.
All tables use CREATE TABLE IF NOT EXISTS for crash-safe restarts.
"""

import logging
from storage.database import Database

log = logging.getLogger("storage.migrations")

SCHEMA_VERSION = 1

MIGRATIONS = [
    # ── Version 1: Initial schema ───────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version     INTEGER PRIMARY KEY,
        applied_at  REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS bars (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       REAL NOT NULL,
        symbol          TEXT NOT NULL,
        timeframe       TEXT NOT NULL DEFAULT '1m',
        open            REAL NOT NULL,
        high            REAL NOT NULL,
        low             REAL NOT NULL,
        close           REAL NOT NULL,
        volume          REAL NOT NULL,
        vwap            REAL,
        trade_count     INTEGER,
        is_carry_forward INTEGER DEFAULT 0,
        created_at      REAL NOT NULL DEFAULT (strftime('%s', 'now')),
        UNIQUE(timestamp, symbol, timeframe)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts ON bars(symbol, timestamp);",

    """
    CREATE TABLE IF NOT EXISTS signals (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        correlation_id      TEXT,
        timestamp           REAL NOT NULL,
        symbol              TEXT NOT NULL,
        signal_type         TEXT NOT NULL,
        strength            REAL,
        price_at_signal     REAL NOT NULL,
        zscore              REAL,
        zscore_ma           REAL,
        trend_slope         REAL,
        volatility          REAL,
        atr                 REAL,
        rsi                 REAL,
        volume_ratio        REAL,
        spread              REAL,
        bar_id              INTEGER REFERENCES bars(id),
        position_before     TEXT,
        position_qty_before REAL DEFAULT 0,
        strategy_name       TEXT NOT NULL,
        created_at          REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_signals_corr ON signals(correlation_id);",

    """
    CREATE TABLE IF NOT EXISTS orders (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        correlation_id      TEXT,
        timestamp           REAL NOT NULL,
        symbol              TEXT NOT NULL,
        broker_order_id     TEXT,
        side                TEXT NOT NULL,
        order_type          TEXT NOT NULL DEFAULT 'market',
        quantity            REAL NOT NULL,
        limit_price         REAL,
        stop_price          REAL,
        time_in_force       TEXT NOT NULL DEFAULT 'gtc',
        status              TEXT NOT NULL,
        signal_id           INTEGER REFERENCES signals(id),
        account_equity      REAL,
        buying_power        REAL,
        risk_amount         REAL,
        expected_price      REAL,
        rejection_reason    TEXT,
        created_at          REAL NOT NULL DEFAULT (strftime('%s', 'now')),
        updated_at          REAL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_orders_broker_id ON orders(broker_order_id);",
    "CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status);",
    "CREATE INDEX IF NOT EXISTS idx_orders_corr ON orders(correlation_id);",

    """
    CREATE TABLE IF NOT EXISTS fills (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        correlation_id      TEXT,
        timestamp           REAL NOT NULL,
        symbol              TEXT NOT NULL,
        broker_order_id     TEXT NOT NULL,
        side                TEXT NOT NULL,
        quantity            REAL NOT NULL,
        fill_price          REAL NOT NULL,
        expected_price      REAL,
        slippage_bps        REAL,
        position_before_qty REAL,
        position_after_qty  REAL,
        position_side       TEXT,
        realized_pnl        REAL DEFAULT 0,
        commission          REAL DEFAULT 0,
        order_id            INTEGER REFERENCES orders(id),
        created_at          REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_fills_symbol_ts ON fills(symbol, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_fills_corr ON fills(correlation_id);",

    """
    CREATE TABLE IF NOT EXISTS positions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol          TEXT NOT NULL UNIQUE,
        side            TEXT NOT NULL DEFAULT 'FLAT',
        quantity        REAL NOT NULL DEFAULT 0,
        avg_entry_price REAL DEFAULT 0,
        unrealized_pnl  REAL DEFAULT 0,
        realized_pnl    REAL DEFAULT 0,
        entry_time      REAL,
        last_fill_id    INTEGER REFERENCES fills(id),
        updated_at      REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS equity_curve (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       REAL NOT NULL,
        equity          REAL NOT NULL,
        cash            REAL NOT NULL,
        buying_power    REAL NOT NULL,
        total_positions REAL NOT NULL,
        open_positions  INTEGER NOT NULL,
        daily_pnl       REAL DEFAULT 0,
        daily_pnl_pct   REAL DEFAULT 0,
        drawdown_pct    REAL DEFAULT 0,
        high_water_mark REAL NOT NULL,
        created_at      REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_curve(timestamp);",

    """
    CREATE TABLE IF NOT EXISTS strategy_metrics (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp             REAL NOT NULL,
        strategy_name         TEXT NOT NULL,
        symbol                TEXT,
        total_trades          INTEGER DEFAULT 0,
        winning_trades        INTEGER DEFAULT 0,
        losing_trades         INTEGER DEFAULT 0,
        win_rate              REAL DEFAULT 0,
        avg_win               REAL DEFAULT 0,
        avg_loss              REAL DEFAULT 0,
        profit_factor         REAL DEFAULT 0,
        max_drawdown          REAL DEFAULT 0,
        sharpe_ratio          REAL DEFAULT 0,
        sortino_ratio         REAL DEFAULT 0,
        avg_hold_time         REAL DEFAULT 0,
        trades_today          INTEGER DEFAULT 0,
        pnl_today             REAL DEFAULT 0,
        avg_zscore_at_entry   REAL,
        avg_spread_at_entry   REAL,
        avg_volume_at_entry   REAL,
        avg_slippage_bps      REAL,
        created_at            REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_metrics_ts ON strategy_metrics(timestamp);",

    """
    CREATE TABLE IF NOT EXISTS reconciliation_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp           REAL NOT NULL,
        broker_positions    TEXT NOT NULL,
        local_positions     TEXT NOT NULL,
        discrepancies       TEXT,
        action_taken        TEXT,
        created_at          REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,

    """
    CREATE TABLE IF NOT EXISTS system_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       REAL NOT NULL,
        event_type      TEXT NOT NULL,
        severity        TEXT NOT NULL,
        message         TEXT NOT NULL,
        details         TEXT,
        created_at      REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """,
]


async def run_migrations(db: Database) -> None:
    """Execute all migrations idempotently."""
    log.info("Running database migrations...")

    for sql in MIGRATIONS:
        await db.execute(sql.strip())

    # Record schema version
    await db.execute(
        "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
        (SCHEMA_VERSION,),
    )

    log.info(f"Migrations complete — schema version {SCHEMA_VERSION}")
