"""
TradingBot V5 — Trading Universe Configuration

Defines which symbols the bot trades.
Easily extensible — add/remove pairs here.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class SymbolConfig:
    """Metadata for a tradeable symbol."""
    symbol: str
    market: str                          # CRYPTO or STOCK
    min_qty: float = 0.001               # minimum order quantity
    qty_precision: int = 6               # decimal places for quantity
    price_precision: int = 2             # decimal places for price
    enabled: bool = True


# ── Crypto Universe ─────────────────────────────────────────────
CRYPTO_SYMBOLS: List[SymbolConfig] = [
    SymbolConfig(symbol="BTC/USD",  market="CRYPTO", min_qty=0.0001,  qty_precision=8, price_precision=2),
    SymbolConfig(symbol="ETH/USD",  market="CRYPTO", min_qty=0.001,   qty_precision=6, price_precision=2),
    SymbolConfig(symbol="SOL/USD",  market="CRYPTO", min_qty=0.01,    qty_precision=4, price_precision=4),
    SymbolConfig(symbol="LINK/USD", market="CRYPTO", min_qty=0.01,    qty_precision=4, price_precision=4),
    SymbolConfig(symbol="AVAX/USD", market="CRYPTO", min_qty=0.01,    qty_precision=4, price_precision=4),
    SymbolConfig(symbol="MATIC/USD",market="CRYPTO", min_qty=1.0,     qty_precision=2, price_precision=6),
]

# ── Stock Universe (optional future extension) ──────────────────
STOCK_SYMBOLS: List[SymbolConfig] = [
    # SymbolConfig(symbol="SPY",  market="STOCK", min_qty=1.0, qty_precision=0),
    # SymbolConfig(symbol="QQQ",  market="STOCK", min_qty=1.0, qty_precision=0),
]


def get_active_symbols(market: str = "CRYPTO") -> List[SymbolConfig]:
    """Return only enabled symbols for the given market."""
    pool = CRYPTO_SYMBOLS if market == "CRYPTO" else STOCK_SYMBOLS
    return [s for s in pool if s.enabled]


def get_symbol_names(market: str = "CRYPTO") -> List[str]:
    """Return just the symbol strings for subscription."""
    return [s.symbol for s in get_active_symbols(market)]


def get_symbol_config(symbol: str) -> SymbolConfig | None:
    """Look up config by symbol name."""
    for s in CRYPTO_SYMBOLS + STOCK_SYMBOLS:
        if s.symbol == symbol:
            return s
    return None
