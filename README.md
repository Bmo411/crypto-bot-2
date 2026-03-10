# TradingBot V5

Production-grade algorithmic trading system for crypto markets.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Alpaca API keys

# 3. Run the bot
python run.py
```

## Architecture

Event-driven async system with 12 modules:

| Module | Purpose |
|---|---|
| `config/` | Settings, symbols, strategy parameters |
| `core/` | Events, enums, domain models |
| `market_data/` | WebSocket ingestion, bar aggregation |
| `strategy/` | Mean reversion Z-score strategy |
| `risk/` | Position sizing, daily loss limits |
| `execution/` | Order submission, fill tracking |
| `positions/` | Fill-only position management |
| `reconciliation/` | Periodic broker state verification |
| `storage/` | SQLite persistence (WAL mode) |
| `logging_/` | Structured JSON logging |
| `metrics/` | Performance stats, dashboard API |
| `recovery/` | Crash-safe state reconstruction |

## Strategy

**Mean Reversion with Z-Score** (median/MAD for robustness)

- Timeframe: 1-minute bars
- Entry: |Z| > 1.5
- Exit: |Z| < 0.3
- Stop Loss: 1.0%
- Take Profit: 1.2%
- Trend filter: 200-bar SMA slope
- Volatility filter: ATR regime gating

## Risk Management

- Risk per trade: 0.3% ($252 on $84K)
- Max position: 10% of equity
- Max daily loss: 3% (circuit breaker)
- Max positions: 5 simultaneous

## Dashboard

Once running, access metrics at:
- `GET http://localhost:8080/health`
- `GET http://localhost:8080/metrics`
- `GET http://localhost:8080/positions`
- `GET http://localhost:8080/equity`

## Trading Universe

BTC/USD, ETH/USD, SOL/USD, LINK/USD, AVAX/USD, MATIC/USD

## Testing

```bash
python -m pytest tests/ -v
```
