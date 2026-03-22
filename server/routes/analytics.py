"""
Analytics endpoints — performance metrics, equity curve, breakdowns, compliance checks.
"""

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.models import Trade, PortfolioSnapshot, get_db
from server.services.metrics import (
    get_closed_trades, calculate_overall_stats, calculate_risk_metrics,
    calculate_strategy_breakdown, get_equity_curve,
    get_monthly_returns_heatmap, get_pnl_distribution,
)
from server.services.rules_engine import check_compliance
from server.services.regime import classify_regime

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/performance")
def get_performance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Get overall performance statistics."""
    trades = get_closed_trades(db, start_date, end_date)
    stats = calculate_overall_stats(trades)
    risk = calculate_risk_metrics(db, trades)
    return {"stats": stats, "risk": risk}


@router.get("/performance/mtd")
def get_mtd_performance(db: Session = Depends(get_db)):
    """Get month-to-date performance."""
    today = date.today()
    start = date(today.year, today.month, 1)
    trades = get_closed_trades(db, start, today)
    return calculate_overall_stats(trades)


@router.get("/performance/ytd")
def get_ytd_performance(db: Session = Depends(get_db)):
    """Get year-to-date performance."""
    today = date.today()
    start = date(today.year, 1, 1)
    trades = get_closed_trades(db, start, today)
    return calculate_overall_stats(trades)


@router.get("/breakdown")
def get_breakdown(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Get performance broken down by strategy, sector, ticker, etc."""
    trades = get_closed_trades(db, start_date, end_date)
    return calculate_strategy_breakdown(trades)


@router.get("/equity-curve")
def get_equity_curve_data(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Get equity curve data for charting."""
    trades = get_closed_trades(db, start_date, end_date)
    return get_equity_curve(trades)


@router.get("/monthly-heatmap")
def get_monthly_heatmap(db: Session = Depends(get_db)):
    """Get monthly returns data for heatmap chart."""
    trades = get_closed_trades(db)
    return get_monthly_returns_heatmap(trades)


@router.get("/pnl-distribution")
def get_pnl_dist(db: Session = Depends(get_db)):
    """Get P&L distribution data for histogram."""
    trades = get_closed_trades(db)
    return get_pnl_distribution(trades)


@router.get("/capital-utilization")
def get_capital_utilization(
    days: int = Query(90, le=365),
    db: Session = Depends(get_db),
):
    """Get capital utilization data from portfolio snapshots."""
    snapshots = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.date.desc())
        .limit(days)
        .all()
    )
    return [
        {
            "date": s.date.isoformat(),
            "total_capital": s.total_capital,
            "capital_deployed": s.capital_deployed,
            "capital_available": s.capital_available,
            "utilization_pct": s.capital_utilization_pct,
        }
        for s in reversed(snapshots)
    ]


class ComplianceCheckRequest(BaseModel):
    ticker: str
    sector: str
    strategy: str = "CSP"
    delta: Optional[float] = None
    iv_rank: Optional[float] = None
    dte: int = 35
    buying_power_used: float = 0
    total_capital: float = 220000
    vix: Optional[float] = None
    current_regime: Optional[str] = None


@router.post("/compliance-check")
def run_compliance_check(data: ComplianceCheckRequest, db: Session = Depends(get_db)):
    """Run strategy compliance check for a proposed trade."""
    # Auto-classify regime if not provided
    regime = data.current_regime
    if not regime and data.vix is not None:
        regime = classify_regime(data.vix)

    results = check_compliance(
        db=db,
        ticker=data.ticker,
        sector=data.sector,
        strategy=data.strategy,
        delta=data.delta,
        iv_rank=data.iv_rank,
        dte=data.dte,
        buying_power_used=data.buying_power_used,
        total_capital=data.total_capital,
        vix=data.vix,
        current_regime=regime,
    )

    all_passed = all(r["passed"] for r in results)
    critical_violations = [r for r in results if not r["passed"] and r["severity"] == "CRITICAL"]

    return {
        "results": results,
        "all_passed": all_passed,
        "critical_violations": len(critical_violations),
        "regime": regime,
    }


@router.get("/alerts")
def get_active_alerts(db: Session = Depends(get_db)):
    """Check all open positions for alert conditions."""
    open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
    alerts = []

    for t in open_trades:
        # Profit target check (50% of max profit)
        if t.premium_received and t.premium_received > 0:
            # Estimate current premium as premium_received (need live data for actual)
            alerts.append({
                "trade_id": t.id,
                "ticker": t.ticker,
                "type": "PROFIT_TARGET",
                "severity": "INFO",
                "message": f"{t.ticker} {t.strike}P {t.expiry} — check if 50% profit target reached",
            })

        # Time exit check (21 DTE)
        if t.expiry:
            days_to_exp = (t.expiry - date.today()).days
            if days_to_exp <= 21:
                alerts.append({
                    "trade_id": t.id,
                    "ticker": t.ticker,
                    "type": "TIME_EXIT",
                    "severity": "WARNING" if days_to_exp > 14 else "HIGH",
                    "message": f"{t.ticker} {t.strike}P — {days_to_exp} DTE remaining, time exit threshold reached",
                })

            if days_to_exp <= 7:
                alerts.append({
                    "trade_id": t.id,
                    "ticker": t.ticker,
                    "type": "EXPIRY_APPROACHING",
                    "severity": "HIGH",
                    "message": f"{t.ticker} {t.strike}P — only {days_to_exp} DTE remaining!",
                })

    # Sector concentration check
    sector_counts = {}
    for t in open_trades:
        sector_counts[t.sector] = sector_counts.get(t.sector, 0) + 1

    for sector, count in sector_counts.items():
        if count > 2:
            alerts.append({
                "trade_id": None,
                "ticker": None,
                "type": "CONCENTRATION",
                "severity": "MEDIUM",
                "message": f"{sector}: {count} open positions exceeds max 2 per sector",
            })

    # Over-deployment check
    total_bp = sum(t.effective_bp for t in open_trades)
    latest_snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).first()
    total_cap = latest_snap.total_capital if latest_snap else 220000
    if total_cap > 0 and (total_bp / total_cap * 100) > 70:
        alerts.append({
            "trade_id": None,
            "ticker": None,
            "type": "OVER_DEPLOYMENT",
            "severity": "MEDIUM",
            "message": f"Capital utilization at {total_bp / total_cap * 100:.1f}% — exceeds 70% threshold",
        })

    return alerts
