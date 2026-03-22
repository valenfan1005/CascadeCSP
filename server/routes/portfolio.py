"""
Portfolio snapshot and monthly returns endpoints.
"""

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import extract

from server.models import PortfolioSnapshot, MonthlyReturn, Trade, get_db

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# --- Schemas ---

class SnapshotCreate(BaseModel):
    date: date
    total_capital: float
    capital_deployed: float = 0
    capital_available: float = 0
    open_positions_count: int = 0
    sectors_exposed: Optional[str] = None
    unrealized_pnl: float = 0
    realized_pnl_mtd: float = 0
    realized_pnl_ytd: float = 0
    portfolio_delta: Optional[float] = None
    portfolio_theta: Optional[float] = None
    max_single_position_pct: Optional[float] = None
    vix_level: Optional[float] = None
    spy_price: Optional[float] = None
    regime: Optional[str] = None
    notes: Optional[str] = None


class MonthlyReturnCreate(BaseModel):
    year: int
    month: int
    beginning_equity: float
    ending_equity: float
    deposits: float = 0
    withdrawals: float = 0
    benchmark_return_pct: Optional[float] = None
    max_drawdown_intra_month: Optional[float] = None


# --- Portfolio Snapshots ---

@router.get("/snapshots")
def list_snapshots(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(90, le=365),
    db: Session = Depends(get_db),
):
    """List portfolio snapshots."""
    q = db.query(PortfolioSnapshot)
    if start_date:
        q = q.filter(PortfolioSnapshot.date >= start_date)
    if end_date:
        q = q.filter(PortfolioSnapshot.date <= end_date)
    return q.order_by(PortfolioSnapshot.date.desc()).limit(limit).all()


@router.post("/snapshots", status_code=201)
def create_snapshot(data: SnapshotCreate, db: Session = Depends(get_db)):
    """Create or update a daily portfolio snapshot."""
    # Upsert - update if exists for this date
    existing = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.date == data.date).first()

    if existing:
        for key, value in data.model_dump().items():
            setattr(existing, key, value)
        existing.capital_utilization_pct = (
            (data.capital_deployed / data.total_capital * 100)
            if data.total_capital > 0 else 0
        )
        db.commit()
        db.refresh(existing)
        return existing

    snapshot = PortfolioSnapshot(**data.model_dump())
    snapshot.capital_utilization_pct = (
        (data.capital_deployed / data.total_capital * 100)
        if data.total_capital > 0 else 0
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/snapshots/latest")
def get_latest_snapshot(db: Session = Depends(get_db)):
    """Get the most recent portfolio snapshot."""
    snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshots found")
    return snapshot


@router.get("/summary")
def get_portfolio_summary(db: Session = Depends(get_db)):
    """Get current portfolio summary from open trades and latest snapshot."""
    open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
    latest_snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).first()

    total_capital = latest_snapshot.total_capital if latest_snapshot else 220000
    capital_deployed = sum(t.effective_bp for t in open_trades)
    capital_available = total_capital - capital_deployed

    # Sector exposure
    sector_exposure = {}
    for t in open_trades:
        sector_exposure[t.sector] = sector_exposure.get(t.sector, 0) + (t.effective_bp)

    # Largest position
    max_position_bp = max((t.effective_bp for t in open_trades), default=0)
    max_position_pct = (max_position_bp / total_capital * 100) if total_capital > 0 else 0

    # MTD and YTD realized P&L
    today = date.today()
    mtd_trades = db.query(Trade).filter(
        Trade.status == "CLOSED",
        extract("year", Trade.trade_date_close) == today.year,
        extract("month", Trade.trade_date_close) == today.month,
    ).all()
    ytd_trades = db.query(Trade).filter(
        Trade.status == "CLOSED",
        extract("year", Trade.trade_date_close) == today.year,
    ).all()

    realized_pnl_mtd = sum(t.pnl_dollars or 0 for t in mtd_trades)
    realized_pnl_ytd = sum(t.pnl_dollars or 0 for t in ytd_trades)

    return {
        "total_capital": total_capital,
        "capital_deployed": round(capital_deployed, 2),
        "capital_available": round(capital_available, 2),
        "capital_utilization_pct": round(capital_deployed / total_capital * 100, 2) if total_capital > 0 else 0,
        "open_positions_count": len(open_trades),
        "sector_exposure": {k: round(v, 2) for k, v in sector_exposure.items()},
        "sector_exposure_pct": {k: round(v / total_capital * 100, 2) for k, v in sector_exposure.items()} if total_capital > 0 else {},
        "max_single_position_pct": round(max_position_pct, 2),
        "realized_pnl_mtd": round(realized_pnl_mtd, 2),
        "realized_pnl_ytd": round(realized_pnl_ytd, 2),
        "vix_level": latest_snapshot.vix_level if latest_snapshot else None,
        "regime": latest_snapshot.regime if latest_snapshot else None,
    }


# --- Monthly Returns ---

@router.get("/monthly-returns")
def list_monthly_returns(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List monthly return records."""
    q = db.query(MonthlyReturn)
    if year:
        q = q.filter(MonthlyReturn.year == year)
    return q.order_by(MonthlyReturn.year.desc(), MonthlyReturn.month.desc()).all()


@router.post("/monthly-returns", status_code=201)
def create_monthly_return(data: MonthlyReturnCreate, db: Session = Depends(get_db)):
    """Create or update a monthly return record."""
    # Calculate return using Modified Dietz method
    adjusted_beginning = data.beginning_equity + data.deposits - data.withdrawals
    if adjusted_beginning > 0:
        net_return_pct = ((data.ending_equity - adjusted_beginning) / adjusted_beginning) * 100
    else:
        net_return_pct = 0

    alpha_pct = (net_return_pct - data.benchmark_return_pct) if data.benchmark_return_pct is not None else None

    # Count trades for this month
    num_trades = db.query(Trade).filter(
        Trade.status == "CLOSED",
        extract("year", Trade.trade_date_close) == data.year,
        extract("month", Trade.trade_date_close) == data.month,
    ).count()

    # Win rate for this month
    closed_trades = db.query(Trade).filter(
        Trade.status == "CLOSED",
        extract("year", Trade.trade_date_close) == data.year,
        extract("month", Trade.trade_date_close) == data.month,
    ).all()
    winners = sum(1 for t in closed_trades if (t.pnl_dollars or 0) > 0)
    win_rate = (winners / len(closed_trades) * 100) if closed_trades else 0

    # Upsert
    existing = db.query(MonthlyReturn).filter(
        MonthlyReturn.year == data.year,
        MonthlyReturn.month == data.month,
    ).first()

    if existing:
        existing.beginning_equity = data.beginning_equity
        existing.ending_equity = data.ending_equity
        existing.deposits = data.deposits
        existing.withdrawals = data.withdrawals
        existing.net_return_pct = round(net_return_pct, 4)
        existing.benchmark_return_pct = data.benchmark_return_pct
        existing.alpha_pct = round(alpha_pct, 4) if alpha_pct is not None else None
        existing.max_drawdown_intra_month = data.max_drawdown_intra_month
        existing.num_trades = num_trades
        existing.win_rate = round(win_rate, 2)
        db.commit()
        db.refresh(existing)
        return existing

    record = MonthlyReturn(
        year=data.year,
        month=data.month,
        beginning_equity=data.beginning_equity,
        ending_equity=data.ending_equity,
        deposits=data.deposits,
        withdrawals=data.withdrawals,
        net_return_pct=round(net_return_pct, 4),
        benchmark_return_pct=data.benchmark_return_pct,
        alpha_pct=round(alpha_pct, 4) if alpha_pct is not None else None,
        max_drawdown_intra_month=data.max_drawdown_intra_month,
        num_trades=num_trades,
        win_rate=round(win_rate, 2),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
