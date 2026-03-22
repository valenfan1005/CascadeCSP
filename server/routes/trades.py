"""
Trade CRUD endpoints — create, read, update, close trades.
"""

from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.models import Trade, TickerInfo, get_db

router = APIRouter(prefix="/api/trades", tags=["trades"])


# --- Schemas ---

class TradeCreate(BaseModel):
    ticker: str
    sector: str
    strategy: str = "CSP"
    direction: str = "SELL"
    strike: float
    strike_long: Optional[float] = None
    expiry: date
    contracts: int = 1
    premium_received: float
    underlying_price_open: Optional[float] = None
    delta_at_entry: Optional[float] = None
    iv_at_entry: Optional[float] = None
    iv_rank_at_entry: Optional[float] = None
    vix_at_entry: Optional[float] = None
    buying_power_used: Optional[float] = None
    market_regime: Optional[str] = None
    notes: Optional[str] = None
    trade_date_open: Optional[datetime] = None


class TradeClose(BaseModel):
    premium_close: float
    underlying_price_close: Optional[float] = None
    vix_at_close: Optional[float] = None
    exit_reason: str = "MANUAL"
    notes: Optional[str] = None
    trade_date_close: Optional[datetime] = None


class TradeUpdate(BaseModel):
    ticker: Optional[str] = None
    sector: Optional[str] = None
    strategy: Optional[str] = None
    strike: Optional[float] = None
    strike_long: Optional[float] = None
    expiry: Optional[date] = None
    contracts: Optional[int] = None
    premium_received: Optional[float] = None
    underlying_price_open: Optional[float] = None
    delta_at_entry: Optional[float] = None
    iv_at_entry: Optional[float] = None
    iv_rank_at_entry: Optional[float] = None
    vix_at_entry: Optional[float] = None
    buying_power_used: Optional[float] = None
    market_regime: Optional[str] = None
    notes: Optional[str] = None


class TradeResponse(BaseModel):
    id: int
    trade_date_open: Optional[datetime]
    trade_date_close: Optional[datetime]
    ticker: str
    sector: str
    strategy: str
    direction: str
    strike: float
    strike_long: Optional[float]
    expiry: date
    dte_at_entry: Optional[int]
    contracts: int
    premium_received: float
    premium_close: Optional[float]
    underlying_price_open: Optional[float]
    underlying_price_close: Optional[float]
    delta_at_entry: Optional[float]
    iv_at_entry: Optional[float]
    iv_rank_at_entry: Optional[float]
    vix_at_entry: Optional[float]
    vix_at_close: Optional[float]
    buying_power_used: Optional[float]
    pnl_dollars: Optional[float]
    pnl_percent: Optional[float]
    exit_reason: Optional[str]
    market_regime: Optional[str]
    notes: Optional[str]
    status: str
    auto_imported: bool = False
    # Computed fields
    holding_days: Optional[int] = None
    dte_at_close: Optional[int] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakeven: Optional[float] = None

    class Config:
        from_attributes = True


def _trade_to_response(t: Trade) -> dict:
    """Convert a Trade model to a response dict with computed fields."""
    return {
        "id": t.id,
        "trade_date_open": t.trade_date_open,
        "trade_date_close": t.trade_date_close,
        "ticker": t.ticker,
        "sector": t.sector,
        "strategy": t.strategy,
        "direction": t.direction,
        "strike": t.strike,
        "strike_long": t.strike_long,
        "expiry": t.expiry,
        "dte_at_entry": t.dte_at_entry,
        "contracts": t.contracts,
        "premium_received": t.premium_received,
        "premium_close": t.premium_close,
        "underlying_price_open": t.underlying_price_open,
        "underlying_price_close": t.underlying_price_close,
        "delta_at_entry": t.delta_at_entry,
        "iv_at_entry": t.iv_at_entry,
        "iv_rank_at_entry": t.iv_rank_at_entry,
        "vix_at_entry": t.vix_at_entry,
        "vix_at_close": t.vix_at_close,
        "buying_power_used": t.buying_power_used,
        "pnl_dollars": t.pnl_dollars,
        "pnl_percent": t.pnl_percent,
        "exit_reason": t.exit_reason,
        "market_regime": t.market_regime,
        "notes": t.notes,
        "status": t.status,
        "auto_imported": t.auto_imported,
        "holding_days": t.holding_days,
        "dte_at_close": t.dte_at_close,
        "max_profit": t.max_profit,
        "max_loss": t.max_loss,
        "breakeven": t.breakeven,
    }


# --- Endpoints ---

@router.get("/", response_model=list[TradeResponse])
def list_trades(
    status: Optional[str] = Query(None, description="Filter by OPEN or CLOSED"),
    ticker: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """List all trades with optional filters."""
    q = db.query(Trade)
    if status:
        q = q.filter(Trade.status == status.upper())
    if ticker:
        q = q.filter(Trade.ticker == ticker.upper())
    if sector:
        q = q.filter(Trade.sector == sector)
    if strategy:
        q = q.filter(Trade.strategy == strategy.upper())

    trades = q.order_by(Trade.trade_date_open.desc()).offset(offset).limit(limit).all()
    return [_trade_to_response(t) for t in trades]


@router.get("/open", response_model=list[TradeResponse])
def list_open_trades(db: Session = Depends(get_db)):
    """List all open positions."""
    trades = db.query(Trade).filter(Trade.status == "OPEN").order_by(Trade.expiry).all()
    return [_trade_to_response(t) for t in trades]


@router.get("/{trade_id}", response_model=TradeResponse)
def get_trade(trade_id: int, db: Session = Depends(get_db)):
    """Get a single trade by ID."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return _trade_to_response(trade)


@router.post("/", response_model=TradeResponse, status_code=201)
def create_trade(data: TradeCreate, db: Session = Depends(get_db)):
    """Create a new trade entry."""
    trade = Trade(
        trade_date_open=data.trade_date_open or datetime.utcnow(),
        ticker=data.ticker.upper(),
        sector=data.sector,
        strategy=data.strategy.upper(),
        direction=data.direction.upper(),
        strike=data.strike,
        strike_long=data.strike_long,
        expiry=data.expiry,
        contracts=data.contracts,
        premium_received=data.premium_received,
        underlying_price_open=data.underlying_price_open,
        delta_at_entry=data.delta_at_entry,
        iv_at_entry=data.iv_at_entry,
        iv_rank_at_entry=data.iv_rank_at_entry,
        vix_at_entry=data.vix_at_entry,
        buying_power_used=data.buying_power_used,
        market_regime=data.market_regime,
        notes=data.notes,
        status="OPEN",
    )

    # Auto-calculate DTE
    trade.calculate_dte_at_entry()

    # Auto-calculate buying power if not provided (CSP: strike * 100 * contracts)
    if not trade.buying_power_used:
        if trade.strategy == "CSP":
            trade.buying_power_used = trade.strike * 100 * trade.contracts
        elif trade.strategy == "PUT_SPREAD" and trade.strike_long:
            width = abs(trade.strike - trade.strike_long)
            trade.buying_power_used = width * 100 * trade.contracts

    # Auto-detect sector from ticker_info if not explicitly set
    if not trade.sector or trade.sector == "":
        ticker_info = db.query(TickerInfo).filter(TickerInfo.ticker == trade.ticker).first()
        if ticker_info:
            trade.sector = ticker_info.sector

    db.add(trade)
    db.commit()
    db.refresh(trade)
    return _trade_to_response(trade)


@router.put("/{trade_id}", response_model=TradeResponse)
def update_trade(trade_id: int, data: TradeUpdate, db: Session = Depends(get_db)):
    """Update an open trade."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(trade, key, value)

    trade.calculate_dte_at_entry()
    trade.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(trade)
    return _trade_to_response(trade)


@router.post("/{trade_id}/close", response_model=TradeResponse)
def close_trade(trade_id: int, data: TradeClose, db: Session = Depends(get_db)):
    """Close an open trade and calculate P&L."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status == "CLOSED":
        raise HTTPException(status_code=400, detail="Trade is already closed")

    trade.premium_close = data.premium_close
    trade.underlying_price_close = data.underlying_price_close
    trade.vix_at_close = data.vix_at_close
    trade.exit_reason = data.exit_reason
    trade.trade_date_close = data.trade_date_close or datetime.utcnow()
    trade.status = "CLOSED"

    if data.notes:
        trade.notes = (trade.notes or "") + f"\n[CLOSE] {data.notes}"

    trade.calculate_pnl()
    trade.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(trade)
    return _trade_to_response(trade)


@router.delete("/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)):
    """Delete a trade (use with caution)."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    db.delete(trade)
    db.commit()
    return {"message": f"Trade {trade_id} deleted"}


@router.get("/tickers/universe")
def get_approved_universe(db: Session = Depends(get_db)):
    """Get the approved ticker universe with sectors."""
    tickers = db.query(TickerInfo).order_by(TickerInfo.sector, TickerInfo.ticker).all()
    result = {}
    for t in tickers:
        if t.sector not in result:
            result[t.sector] = []
        result[t.sector].append({
            "ticker": t.ticker,
            "name": t.name,
            "earnings_date": t.earnings_date.isoformat() if t.earnings_date else None,
            "ex_dividend_date": t.ex_dividend_date.isoformat() if t.ex_dividend_date else None,
            "notes": t.notes,
        })
    return result
