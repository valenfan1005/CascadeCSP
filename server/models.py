"""
OptionScout Trading Tracker - Database Models
SQLAlchemy ORM models for trades, portfolio snapshots, and monthly returns.
"""
from __future__ import annotations

from datetime import datetime, date
from sqlalchemy import (
    create_engine, Column, Integer, Float, Text, Date, DateTime, String,
    Boolean, event, Enum as SAEnum
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import func
import enum
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "optionscout.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- Enums ---

class StrategyType(str, enum.Enum):
    CSP = "CSP"
    PUT_SPREAD = "PUT_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"
    COVERED_CALL = "COVERED_CALL"
    OTHER = "OTHER"


class Direction(str, enum.Enum):
    SELL = "SELL"
    BUY = "BUY"


class ExitReason(str, enum.Enum):
    TARGET_HIT = "TARGET_HIT"
    STOP_HIT = "STOP_HIT"
    TIME_EXIT = "TIME_EXIT"
    EXPIRY_WORTHLESS = "EXPIRY_WORTHLESS"
    EXPIRY_ITM = "EXPIRY_ITM"
    MANUAL = "MANUAL"
    ADJUSTMENT = "ADJUSTMENT"
    REGIME_SHIFT = "REGIME_SHIFT"


class MarketRegime(str, enum.Enum):
    LOW_VOL_BULLISH = "LOW_VOL_BULLISH"
    LOW_VOL_NEUTRAL = "LOW_VOL_NEUTRAL"
    HIGH_VOL_BEARISH = "HIGH_VOL_BEARISH"
    HIGH_VOL_NEUTRAL = "HIGH_VOL_NEUTRAL"
    CRISIS = "CRISIS"


class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Sector(str, enum.Enum):
    TECHNOLOGY = "Technology"
    FINANCIALS = "Financials"
    HEALTHCARE = "Healthcare"
    ENERGY = "Energy"
    INDUSTRIALS = "Industrials"
    CONSUMER = "Consumer"
    COMMUNICATION = "Communication"
    UTILITIES = "Utilities"
    REAL_ESTATE = "Real Estate"
    ETF = "ETF"


# --- Models ---

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date_open = Column(DateTime, nullable=False, default=datetime.utcnow)
    trade_date_close = Column(DateTime, nullable=True)
    ticker = Column(String(10), nullable=False, index=True)
    sector = Column(String(30), nullable=False)
    strategy = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False, default="SELL")
    strike = Column(Float, nullable=False)
    strike_long = Column(Float, nullable=True)  # For spreads only
    expiry = Column(Date, nullable=False)
    dte_at_entry = Column(Integer, nullable=True)  # Auto-calculated
    contracts = Column(Integer, nullable=False, default=1)
    premium_received = Column(Float, nullable=False)
    premium_close = Column(Float, nullable=True)
    underlying_price_open = Column(Float, nullable=True)
    underlying_price_close = Column(Float, nullable=True)
    delta_at_entry = Column(Float, nullable=True)
    iv_at_entry = Column(Float, nullable=True)
    iv_rank_at_entry = Column(Float, nullable=True)
    vix_at_entry = Column(Float, nullable=True)
    vix_at_close = Column(Float, nullable=True)
    buying_power_used = Column(Float, nullable=True)
    pnl_dollars = Column(Float, nullable=True)  # Auto-calculated on close
    pnl_percent = Column(Float, nullable=True)  # Auto-calculated on close
    exit_reason = Column(String(20), nullable=True)
    market_regime = Column(String(30), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(10), nullable=False, default="OPEN")
    # Moomoo integration fields
    moomoo_deal_id = Column(String(50), nullable=True)
    moomoo_order_id = Column(String(50), nullable=True)
    auto_imported = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def effective_bp(self):
        """Buying power with auto-fallback: if DB value is 0/null, compute from strike × contracts × 100.
        For spreads, use spread width × contracts × 100."""
        bp = self.buying_power_used or 0
        if bp > 0:
            return bp
        # Fallback: compute from strike
        if self.strike_long is not None:
            # Spread: BP = width × contracts × 100
            width = abs(self.strike - self.strike_long)
            return width * (self.contracts or 1) * 100
        # CSP: BP = strike × contracts × 100
        return (self.strike or 0) * (self.contracts or 1) * 100

    @property
    def holding_days(self):
        if self.trade_date_close and self.trade_date_open:
            return (self.trade_date_close - self.trade_date_open).days
        return None

    @property
    def dte_at_close(self):
        if self.trade_date_close and self.expiry:
            close_date = self.trade_date_close.date() if isinstance(self.trade_date_close, datetime) else self.trade_date_close
            return (self.expiry - close_date).days
        return None

    @property
    def max_profit(self):
        """Max profit for the position."""
        return self.premium_received * self.contracts * 100

    @property
    def max_loss(self):
        """Max loss - for CSP it's strike minus premium, for spreads it's width minus premium."""
        if self.strike_long is not None:
            width = abs(self.strike - self.strike_long)
            return (width - self.premium_received) * self.contracts * 100
        return (self.strike - self.premium_received) * self.contracts * 100

    @property
    def breakeven(self):
        """Breakeven price for the position."""
        return self.strike - self.premium_received

    def calculate_pnl(self):
        """Calculate P&L when closing a trade."""
        if self.premium_close is not None:
            self.pnl_dollars = (self.premium_received - self.premium_close) * self.contracts * 100
            if self.buying_power_used and self.buying_power_used > 0:
                self.pnl_percent = (self.pnl_dollars / self.buying_power_used) * 100

    def calculate_dte_at_entry(self):
        """Calculate DTE at entry."""
        if self.expiry and self.trade_date_open:
            open_date = self.trade_date_open.date() if isinstance(self.trade_date_open, datetime) else self.trade_date_open
            self.dte_at_entry = (self.expiry - open_date).days


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    total_capital = Column(Float, nullable=False)
    capital_deployed = Column(Float, nullable=False, default=0)
    capital_available = Column(Float, nullable=False, default=0)
    capital_utilization_pct = Column(Float, nullable=True)
    open_positions_count = Column(Integer, default=0)
    sectors_exposed = Column(Text, nullable=True)  # JSON list
    unrealized_pnl = Column(Float, default=0)
    realized_pnl_mtd = Column(Float, default=0)
    realized_pnl_ytd = Column(Float, default=0)
    portfolio_delta = Column(Float, nullable=True)
    portfolio_theta = Column(Float, nullable=True)
    max_single_position_pct = Column(Float, nullable=True)
    vix_level = Column(Float, nullable=True)
    spy_price = Column(Float, nullable=True)
    regime = Column(String(30), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonthlyReturn(Base):
    __tablename__ = "monthly_returns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    beginning_equity = Column(Float, nullable=False)
    ending_equity = Column(Float, nullable=False)
    deposits = Column(Float, default=0)
    withdrawals = Column(Float, default=0)
    net_return_pct = Column(Float, nullable=True)
    benchmark_return_pct = Column(Float, nullable=True)  # SPY
    alpha_pct = Column(Float, nullable=True)
    max_drawdown_intra_month = Column(Float, nullable=True)
    num_trades = Column(Integer, default=0)
    win_rate = Column(Float, nullable=True)
    sharpe_rolling_12m = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TickerInfo(Base):
    """Approved universe tickers with metadata."""
    __tablename__ = "ticker_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, unique=True, index=True)
    sector = Column(String(30), nullable=False)
    name = Column(String(100), nullable=True)
    earnings_date = Column(Date, nullable=True)
    ex_dividend_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)


class Alert(Base):
    """Alerts for open positions and portfolio compliance."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, nullable=True)
    alert_type = Column(String(30), nullable=False)
    severity = Column(String(10), nullable=False)  # INFO, WARNING, MEDIUM, HIGH, CRITICAL
    message = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)


# --- Database initialization ---

def init_db():
    """Create all tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI - yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_tickers(db: Session):
    """Seed the approved universe tickers."""
    universe_path = os.path.join(BASE_DIR, "..", "data", "approved_universe.json")
    if not os.path.exists(universe_path):
        return

    with open(universe_path) as f:
        universe = json.load(f)

    for sector, tickers in universe.items():
        for ticker in tickers:
            existing = db.query(TickerInfo).filter(TickerInfo.ticker == ticker).first()
            if not existing:
                db.add(TickerInfo(ticker=ticker, sector=sector))
    db.commit()
