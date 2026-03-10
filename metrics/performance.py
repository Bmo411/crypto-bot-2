"""
TradingBot V5 — Performance Metrics

Computes trading performance statistics from trade history.
"""

import math
import logging
from typing import Optional
from core.models import TradeRecord

log = logging.getLogger("metrics.performance")


class PerformanceCalculator:
    """Compute performance metrics from completed trades."""

    @staticmethod
    def compute(
        trades: list[TradeRecord],
        equity: float = 0.0,
        high_water_mark: float = 0.0,
    ) -> dict:
        """
        Compute a full metrics snapshot.

        Returns dict with all performance fields.
        """
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_trade": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "avg_hold_time": 0.0,
                "total_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
            }

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in trades)
        gross_profit = sum(t.pnl for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0

        win_rate = len(wins) / len(trades) if trades else 0.0
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        avg_trade = total_pnl / len(trades) if trades else 0.0
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else float("inf")
        )

        avg_hold = (
            sum(t.hold_time_seconds for t in trades) / len(trades)
            if trades else 0.0
        )

        # Drawdown
        drawdown_pct = 0.0
        if high_water_mark > 0 and equity > 0:
            drawdown_pct = (equity - high_water_mark) / high_water_mark

        # Sharpe ratio (annualized, using trade returns)
        sharpe = PerformanceCalculator._calc_sharpe(trades)
        sortino = PerformanceCalculator._calc_sortino(trades)

        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_trade": avg_trade,
            "profit_factor": profit_factor,
            "max_drawdown": drawdown_pct,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "avg_hold_time": avg_hold,
            "total_pnl": total_pnl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
        }

    @staticmethod
    def _calc_sharpe(trades: list[TradeRecord]) -> float:
        """Annualized Sharpe ratio from trade returns."""
        if len(trades) < 2:
            return 0.0

        returns = [t.pnl_pct for t in trades]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0

        if std_ret == 0:
            return 0.0

        # Annualize: assume ~365 trading days (crypto 24/7)
        # and estimate trades per day from data
        if len(trades) >= 2:
            time_span = trades[-1].exit_time - trades[0].entry_time
            if time_span > 0:
                trades_per_day = len(trades) / (time_span / 86400)
                trades_per_year = trades_per_day * 365
                return (mean_ret / std_ret) * math.sqrt(trades_per_year)

        return mean_ret / std_ret

    @staticmethod
    def _calc_sortino(trades: list[TradeRecord]) -> float:
        """Sortino ratio — penalizes only downside volatility."""
        if len(trades) < 2:
            return 0.0

        returns = [t.pnl_pct for t in trades]
        mean_ret = sum(returns) / len(returns)

        downside = [r for r in returns if r < 0]
        if not downside:
            return float("inf") if mean_ret > 0 else 0.0

        downside_var = sum(r ** 2 for r in downside) / len(downside)
        downside_std = math.sqrt(downside_var)

        if downside_std == 0:
            return 0.0

        return mean_ret / downside_std
