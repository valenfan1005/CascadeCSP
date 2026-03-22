"""
Report generation endpoints — monthly reports and CSV/JSON exports.
"""

import csv
import io
import json
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import extract

from server.models import Trade, MonthlyReturn, PortfolioSnapshot, get_db
from server.services.metrics import (
    get_closed_trades, calculate_overall_stats, calculate_risk_metrics,
    get_equity_curve, calculate_strategy_breakdown,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/monthly/{year}/{month}", response_class=HTMLResponse)
def generate_monthly_report(year: int, month: int, db: Session = Depends(get_db)):
    """Generate a monthly HTML report suitable for sharing with allocators."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    # Trades closed this month
    month_trades = get_closed_trades(db, start, end)
    month_stats = calculate_overall_stats(month_trades)

    # YTD trades
    ytd_start = date(year, 1, 1)
    ytd_trades = get_closed_trades(db, ytd_start, end)
    ytd_stats = calculate_overall_stats(ytd_trades)
    ytd_risk = calculate_risk_metrics(db, ytd_trades)

    # Monthly return record
    monthly_return = db.query(MonthlyReturn).filter(
        MonthlyReturn.year == year,
        MonthlyReturn.month == month,
    ).first()

    # Build HTML report
    month_name = date(year, month, 1).strftime("%B %Y")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>OptionScout Monthly Report — {month_name}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 40px; color: #1a1a2e; background: #f8f9fa; }}
        h1 {{ color: #0f3460; border-bottom: 3px solid #0f3460; padding-bottom: 10px; }}
        h2 {{ color: #16213e; margin-top: 30px; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .header h1 {{ margin-bottom: 5px; }}
        .header .subtitle {{ color: #666; font-size: 14px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin: 20px 0; }}
        .metric-card {{ background: white; border-radius: 8px; padding: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .metric-card .label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
        .metric-card .value {{ font-size: 24px; font-weight: 700; margin-top: 5px; }}
        .positive {{ color: #0a8754; }}
        .negative {{ color: #d32f2f; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        th {{ background: #0f3460; color: white; padding: 10px 12px; text-align: left; font-size: 13px; }}
        td {{ padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }}
        tr:nth-child(even) {{ background: #f8f9fa; }}
        .disclaimer {{ margin-top: 40px; padding: 15px; background: #fff3cd; border-radius: 8px; font-size: 12px; color: #856404; }}
        .section {{ margin-bottom: 30px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>OptionScout Trading Report</h1>
        <div class="subtitle">{month_name} | Systematic Cash-Secured Put Portfolio</div>
    </div>

    <div class="section">
        <h2>1. Executive Summary</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="label">Monthly P&L</div>
                <div class="value {'positive' if month_stats['total_pnl'] >= 0 else 'negative'}">${month_stats['total_pnl']:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Monthly Return</div>
                <div class="value {'positive' if (monthly_return and monthly_return.net_return_pct and monthly_return.net_return_pct >= 0) else 'negative'}">{monthly_return.net_return_pct if monthly_return and monthly_return.net_return_pct else 'N/A'}%</div>
            </div>
            <div class="metric-card">
                <div class="label">YTD P&L</div>
                <div class="value {'positive' if ytd_stats['total_pnl'] >= 0 else 'negative'}">${ytd_stats['total_pnl']:,.2f}</div>
            </div>
            <div class="metric-card">
                <div class="label">Monthly Win Rate</div>
                <div class="value">{month_stats['win_rate']}%</div>
            </div>
            <div class="metric-card">
                <div class="label">Trades This Month</div>
                <div class="value">{month_stats['total_trades']}</div>
            </div>
            <div class="metric-card">
                <div class="label">Profit Factor</div>
                <div class="value">{month_stats['profit_factor']}</div>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>2. Risk Metrics (YTD)</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="label">Sharpe Ratio</div>
                <div class="value">{ytd_risk['sharpe_ratio']}</div>
            </div>
            <div class="metric-card">
                <div class="label">Sortino Ratio</div>
                <div class="value">{ytd_risk['sortino_ratio']}</div>
            </div>
            <div class="metric-card">
                <div class="label">Max Drawdown</div>
                <div class="value negative">${ytd_risk['max_drawdown']:,.2f}</div>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>3. Trade Log — {month_name}</h2>
        <table>
            <tr>
                <th>Date</th><th>Ticker</th><th>Strategy</th><th>Strike</th>
                <th>Expiry</th><th>Contracts</th><th>Premium</th><th>P&L</th><th>Exit</th>
            </tr>"""

    for t in month_trades:
        pnl_class = "positive" if (t.pnl_dollars or 0) >= 0 else "negative"
        html += f"""
            <tr>
                <td>{t.trade_date_close.strftime('%m/%d') if t.trade_date_close else 'N/A'}</td>
                <td><strong>{t.ticker}</strong></td>
                <td>{t.strategy}</td>
                <td>${t.strike:.0f}</td>
                <td>{t.expiry.strftime('%m/%d') if t.expiry else 'N/A'}</td>
                <td>{t.contracts}</td>
                <td>${t.premium_received:.2f}</td>
                <td class="{pnl_class}">${t.pnl_dollars:,.2f}</td>
                <td>{t.exit_reason or 'N/A'}</td>
            </tr>"""

    if not month_trades:
        html += '<tr><td colspan="9" style="text-align:center;">No trades closed this month</td></tr>'

    html += f"""
        </table>
    </div>

    <div class="section">
        <h2>4. YTD Performance Summary</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Trades (YTD)</td><td>{ytd_stats['total_trades']}</td></tr>
            <tr><td>Win Rate</td><td>{ytd_stats['win_rate']}%</td></tr>
            <tr><td>Average Winner</td><td>${ytd_stats['avg_win_dollars']:,.2f}</td></tr>
            <tr><td>Average Loser</td><td>${ytd_stats['avg_loss_dollars']:,.2f}</td></tr>
            <tr><td>Profit Factor</td><td>{ytd_stats['profit_factor']}</td></tr>
            <tr><td>Expectancy / Trade</td><td>${ytd_stats['expectancy']:,.2f}</td></tr>
            <tr><td>Max Win Streak</td><td>{ytd_risk['max_win_streak']}</td></tr>
            <tr><td>Max Loss Streak</td><td>{ytd_risk['max_loss_streak']}</td></tr>
        </table>
    </div>

    <div class="disclaimer">
        <strong>Disclaimer:</strong> Past performance does not guarantee future results.
        This report is generated for internal tracking purposes and does not constitute investment advice.
        Options trading involves substantial risk of loss. All figures are in USD unless otherwise stated.
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.get("/export/trades")
def export_trades_csv(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Export trade log as CSV."""
    q = db.query(Trade)
    if status:
        q = q.filter(Trade.status == status.upper())
    trades = q.order_by(Trade.trade_date_open).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Date Open", "Date Close", "Ticker", "Sector", "Strategy",
        "Direction", "Strike", "Strike Long", "Expiry", "DTE", "Contracts",
        "Premium Received", "Premium Close", "Price Open", "Price Close",
        "Delta", "IV", "IV Rank", "VIX Open", "VIX Close",
        "Buying Power", "PnL ($)", "PnL (%)", "Exit Reason", "Regime", "Status", "Notes",
    ])

    for t in trades:
        writer.writerow([
            t.id, t.trade_date_open, t.trade_date_close, t.ticker, t.sector,
            t.strategy, t.direction, t.strike, t.strike_long, t.expiry,
            t.dte_at_entry, t.contracts, t.premium_received, t.premium_close,
            t.underlying_price_open, t.underlying_price_close, t.delta_at_entry,
            t.iv_at_entry, t.iv_rank_at_entry, t.vix_at_entry, t.vix_at_close,
            t.buying_power_used, t.pnl_dollars, t.pnl_percent,
            t.exit_reason, t.market_regime, t.status, t.notes,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=optionscout_trades.csv"},
    )


@router.get("/export/equity-curve")
def export_equity_curve_csv(db: Session = Depends(get_db)):
    """Export equity curve as CSV for allocator due diligence."""
    trades = get_closed_trades(db)
    curve = get_equity_curve(trades)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Trade PnL", "Cumulative PnL", "Ticker", "Strategy"])
    for point in curve:
        writer.writerow([point["date"], point["pnl"], point["cumulative_pnl"], point["ticker"], point["strategy"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=optionscout_equity_curve.csv"},
    )


@router.get("/export/performance-json")
def export_performance_json(db: Session = Depends(get_db)):
    """Export performance summary as JSON for API sharing."""
    all_trades = get_closed_trades(db)
    stats = calculate_overall_stats(all_trades)
    risk = calculate_risk_metrics(db, all_trades)
    monthly = db.query(MonthlyReturn).order_by(MonthlyReturn.year, MonthlyReturn.month).all()

    return {
        "generated_at": date.today().isoformat(),
        "strategy": "Systematic Cash-Secured Put Portfolio",
        "currency": "USD",
        "overall_stats": stats,
        "risk_metrics": risk,
        "monthly_returns": [
            {
                "year": m.year, "month": m.month,
                "return_pct": m.net_return_pct,
                "benchmark_pct": m.benchmark_return_pct,
                "alpha_pct": m.alpha_pct,
            }
            for m in monthly
        ],
    }
