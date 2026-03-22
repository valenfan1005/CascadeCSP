"""
Performance Metrics Engine
Calculates Sharpe, Sortino, drawdown, win rate, profit factor, and all
analytics from the trade journal and portfolio snapshots.
"""
from __future__ import annotations

import math
from datetime import datetime, date
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import extract

from server.models import Trade, PortfolioSnapshot, MonthlyReturn


def get_closed_trades(db: Session, start_date: date = None, end_date: date = None) -> list[Trade]:
    """Fetch closed trades, optionally filtered by date range."""
    q = db.query(Trade).filter(Trade.status == "CLOSED")
    if start_date:
        q = q.filter(Trade.trade_date_close >= start_date)
    if end_date:
        q = q.filter(Trade.trade_date_close <= end_date)
    return q.order_by(Trade.trade_date_close).all()


def calculate_overall_stats(trades: list[Trade]) -> dict:
    """Calculate overall performance statistics from a set of closed trades."""
    if not trades:
        return _empty_stats()

    winners = [t for t in trades if (t.pnl_dollars or 0) > 0]
    losers = [t for t in trades if (t.pnl_dollars or 0) < 0]
    breakevens = [t for t in trades if (t.pnl_dollars or 0) == 0]

    total_trades = len(trades)
    win_rate = len(winners) / total_trades * 100 if total_trades > 0 else 0

    gross_wins = sum(t.pnl_dollars for t in winners) if winners else 0
    gross_losses = abs(sum(t.pnl_dollars for t in losers)) if losers else 0

    avg_win = gross_wins / len(winners) if winners else 0
    avg_loss = gross_losses / len(losers) if losers else 0
    avg_win_pct = sum(t.pnl_percent or 0 for t in winners) / len(winners) if winners else 0
    avg_loss_pct = abs(sum(t.pnl_percent or 0 for t in losers) / len(losers)) if losers else 0

    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 999.99

    win_rate_decimal = win_rate / 100
    loss_rate_decimal = 1 - win_rate_decimal
    expectancy = (avg_win * win_rate_decimal) - (avg_loss * loss_rate_decimal)

    total_pnl = sum(t.pnl_dollars or 0 for t in trades)

    return {
        "total_trades": total_trades,
        "winners": len(winners),
        "losers": len(losers),
        "breakevens": len(breakevens),
        "win_rate": round(win_rate, 2),
        "avg_win_dollars": round(avg_win, 2),
        "avg_loss_dollars": round(avg_loss, 2),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "gross_wins": round(gross_wins, 2),
        "gross_losses": round(gross_losses, 2),
        "total_pnl": round(total_pnl, 2),
    }


def calculate_risk_metrics(db: Session, trades: list[Trade], risk_free_rate: float = 0.05) -> dict:
    """Calculate risk-adjusted performance metrics."""
    if not trades:
        return {
            "sharpe_ratio": 0, "sortino_ratio": 0,
            "max_drawdown": 0, "max_drawdown_duration_days": 0,
            "current_drawdown": 0, "avg_drawdown": 0,
            "max_win_streak": 0, "max_loss_streak": 0,
            "current_streak": 0, "current_streak_type": "N/A",
        }

    # --- Monthly returns for Sharpe/Sortino ---
    monthly_returns = _get_monthly_pnl_returns(trades)
    if len(monthly_returns) >= 2:
        avg_monthly = sum(monthly_returns) / len(monthly_returns)
        monthly_rf = risk_free_rate / 12
        stdev_monthly = _stdev(monthly_returns)
        downside_returns = [r for r in monthly_returns if r < monthly_rf]
        downside_dev = _stdev(downside_returns) if len(downside_returns) >= 2 else 0.001

        sharpe = ((avg_monthly - monthly_rf) / stdev_monthly * math.sqrt(12)) if stdev_monthly > 0 else 0
        sortino = ((avg_monthly - monthly_rf) / downside_dev * math.sqrt(12)) if downside_dev > 0 else 0
    else:
        sharpe = 0
        sortino = 0

    # --- Drawdown from equity curve ---
    cumulative_pnl = []
    running = 0
    for t in trades:
        running += (t.pnl_dollars or 0)
        cumulative_pnl.append(running)

    max_dd, max_dd_duration, current_dd, avg_dd = _calculate_drawdowns(cumulative_pnl)

    # --- Win/loss streaks ---
    max_win_streak, max_loss_streak, current_streak, streak_type = _calculate_streaks(trades)

    return {
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_duration_days": max_dd_duration,
        "current_drawdown": round(current_dd, 2),
        "avg_drawdown": round(avg_dd, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "current_streak": current_streak,
        "current_streak_type": streak_type,
    }


def calculate_strategy_breakdown(trades: list[Trade]) -> dict:
    """Break down performance by strategy, sector, ticker, regime, DTE bucket, delta bucket, month, day of week."""
    breakdowns = {
        "by_strategy": defaultdict(list),
        "by_sector": defaultdict(list),
        "by_ticker": defaultdict(list),
        "by_regime": defaultdict(list),
        "by_dte_bucket": defaultdict(list),
        "by_delta_bucket": defaultdict(list),
        "by_month": defaultdict(list),
        "by_day_of_week": defaultdict(list),
    }

    for t in trades:
        breakdowns["by_strategy"][t.strategy].append(t)
        breakdowns["by_sector"][t.sector].append(t)
        breakdowns["by_ticker"][t.ticker].append(t)
        breakdowns["by_regime"][t.market_regime or "UNKNOWN"].append(t)

        # DTE bucket
        dte = t.dte_at_entry or 0
        if dte <= 35:
            dte_bucket = "30-35"
        elif dte <= 40:
            dte_bucket = "35-40"
        else:
            dte_bucket = "40-45"
        breakdowns["by_dte_bucket"][dte_bucket].append(t)

        # Delta bucket
        delta = abs(t.delta_at_entry or 0)
        if delta <= 0.175:
            delta_bucket = "0.15-0.20"
        elif delta <= 0.225:
            delta_bucket = "0.20-0.25"
        else:
            delta_bucket = "0.25+"
        breakdowns["by_delta_bucket"][delta_bucket].append(t)

        # Month
        if t.trade_date_open:
            month_key = t.trade_date_open.strftime("%Y-%m")
            breakdowns["by_month"][month_key].append(t)
            dow = t.trade_date_open.strftime("%A")
            breakdowns["by_day_of_week"][dow].append(t)

    # Calculate stats for each group
    result = {}
    for dimension, groups in breakdowns.items():
        result[dimension] = {}
        for key, group_trades in groups.items():
            result[dimension][key] = calculate_overall_stats(group_trades)

    return result


def get_equity_curve(trades: list[Trade]) -> list[dict]:
    """Build equity curve data points from closed trades."""
    if not trades:
        return []

    curve = []
    cumulative = 0
    for t in trades:
        cumulative += (t.pnl_dollars or 0)
        curve.append({
            "date": t.trade_date_close.isoformat() if t.trade_date_close else None,
            "pnl": round(t.pnl_dollars or 0, 2),
            "cumulative_pnl": round(cumulative, 2),
            "ticker": t.ticker,
            "strategy": t.strategy,
        })
    return curve


def get_monthly_returns_heatmap(trades: list[Trade]) -> list[dict]:
    """Build monthly returns data for heatmap visualization."""
    monthly = defaultdict(float)
    for t in trades:
        if t.trade_date_close:
            key = (t.trade_date_close.year, t.trade_date_close.month)
            monthly[key] += (t.pnl_dollars or 0)

    result = []
    for (year, month), pnl in sorted(monthly.items()):
        result.append({
            "year": year,
            "month": month,
            "pnl": round(pnl, 2),
        })
    return result


def get_pnl_distribution(trades: list[Trade]) -> dict:
    """Get P&L distribution data for histogram."""
    pnls = [t.pnl_dollars or 0 for t in trades]
    if not pnls:
        return {"pnls": [], "mean": 0, "stdev": 0, "skew": 0, "kurtosis": 0}

    mean_val = sum(pnls) / len(pnls)
    variance = sum((x - mean_val) ** 2 for x in pnls) / len(pnls) if len(pnls) > 1 else 0
    stdev_val = math.sqrt(variance)

    # Skewness and kurtosis
    if stdev_val > 0 and len(pnls) >= 3:
        n = len(pnls)
        skew = (n / ((n - 1) * (n - 2))) * sum(((x - mean_val) / stdev_val) ** 3 for x in pnls)
        kurt = ((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * sum(((x - mean_val) / stdev_val) ** 4 for x in pnls) - (3 * (n - 1) ** 2) / ((n - 2) * (n - 3))
    else:
        skew = 0
        kurt = 0

    return {
        "pnls": [round(p, 2) for p in pnls],
        "mean": round(mean_val, 2),
        "stdev": round(stdev_val, 2),
        "skew": round(skew, 3),
        "kurtosis": round(kurt, 3),
    }


# --- Helpers ---

def _empty_stats():
    return {
        "total_trades": 0, "winners": 0, "losers": 0, "breakevens": 0,
        "win_rate": 0, "avg_win_dollars": 0, "avg_loss_dollars": 0,
        "avg_win_pct": 0, "avg_loss_pct": 0, "profit_factor": 0,
        "expectancy": 0, "gross_wins": 0, "gross_losses": 0, "total_pnl": 0,
    }


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.001
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _get_monthly_pnl_returns(trades: list[Trade]) -> list[float]:
    """Group P&L by month and return a list of monthly return percentages."""
    monthly = defaultdict(float)
    monthly_bp = defaultdict(float)
    for t in trades:
        if t.trade_date_close:
            key = (t.trade_date_close.year, t.trade_date_close.month)
            monthly[key] += (t.pnl_dollars or 0)
            monthly_bp[key] += (t.effective_bp)

    returns = []
    for key in sorted(monthly.keys()):
        bp = monthly_bp[key]
        if bp > 0:
            returns.append(monthly[key] / bp)
        elif monthly[key] != 0:
            returns.append(monthly[key] / 10000)  # fallback
    return returns


def _calculate_drawdowns(cumulative_pnl: list[float]) -> tuple:
    """Calculate max drawdown, duration, current drawdown, average drawdown."""
    if not cumulative_pnl:
        return 0, 0, 0, 0

    peak = cumulative_pnl[0]
    max_dd = 0
    drawdowns = []
    dd_start = 0
    max_dd_duration = 0
    current_dd_start = 0
    in_dd = False

    for i, val in enumerate(cumulative_pnl):
        if val > peak:
            if in_dd:
                drawdowns.append(peak - min(cumulative_pnl[dd_start:i + 1]))
                duration = i - dd_start
                max_dd_duration = max(max_dd_duration, duration)
            peak = val
            in_dd = False
        else:
            dd = peak - val
            if dd > 0 and not in_dd:
                in_dd = True
                dd_start = i
            max_dd = max(max_dd, dd)

    current_dd = peak - cumulative_pnl[-1] if cumulative_pnl[-1] < peak else 0
    avg_dd = sum(drawdowns) / len(drawdowns) if drawdowns else 0

    return max_dd, max_dd_duration, current_dd, avg_dd


def _calculate_streaks(trades: list[Trade]) -> tuple:
    """Calculate win/loss streaks."""
    max_win = max_loss = current = 0
    streak_type = "N/A"
    prev_win = None

    for t in trades:
        is_win = (t.pnl_dollars or 0) > 0
        if is_win:
            if prev_win is True:
                current += 1
            else:
                current = 1
            max_win = max(max_win, current)
            streak_type = "WIN"
        else:
            if prev_win is False:
                current += 1
            else:
                current = 1
            max_loss = max(max_loss, current)
            streak_type = "LOSS"
        prev_win = is_win

    return max_win, max_loss, current, streak_type
