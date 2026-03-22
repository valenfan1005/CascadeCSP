"""
Moomoo sync endpoints — position sync, account info, trade history import.
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.models import Trade, PortfolioSnapshot, TickerInfo, get_db
from server.services import moomoo_client
from server.services import yahoo_client
from server.services.regime import classify_regime

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/moomoo/status")
def check_moomoo_status():
    """Check if Moomoo OpenD is connected."""
    if not moomoo_client.is_available():
        return {"connected": False, "message": "moomoo-api package not installed"}
    connected, message = moomoo_client.check_connection()
    return {"connected": connected, "message": message}


@router.get("/market-data")
def get_market_data():
    """Fetch current VIX, SPY, regime classification, and VIX term structure."""
    vix = yahoo_client.get_vix()
    spy = yahoo_client.get_spy_price()
    regime = classify_regime(vix) if vix else None
    vix_term = yahoo_client.get_vix_term_structure()

    return {
        "vix": vix,
        "spy_price": spy,
        "regime": regime,
        "vix_term_structure": vix_term,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stock-price/{ticker}")
def get_stock_price(ticker: str):
    """Fetch current stock price for a ticker."""
    price, error = yahoo_client.get_stock_price(ticker.upper())
    if error:
        return {"ticker": ticker.upper(), "price": None, "error": error}
    return {"ticker": ticker.upper(), "price": price}


@router.post("/positions")
def sync_positions(db: Session = Depends(get_db)):
    """
    Sync open positions from Moomoo.
    - New positions found in Moomoo → auto-create trade entries
    - Positions in tracker but not in Moomoo → mark as closed
    """
    if not moomoo_client.is_available():
        raise HTTPException(status_code=503, detail="Moomoo integration not available")

    positions, error = moomoo_client.get_positions()
    if error:
        raise HTTPException(status_code=500, detail=error)

    # Get current open trades from DB
    db_open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
    db_trade_keys = set()
    for t in db_open_trades:
        key = f"{t.ticker}_{t.strike}_{t.expiry}"
        db_trade_keys.add(key)

    moomoo_keys = set()
    new_imports = 0
    updated = 0

    for pos in positions:
        info = pos.get("option_info")
        if not info:
            continue

        # Skip closed positions (qty == 0)
        if pos["qty"] == 0:
            continue

        key = f"{info['ticker']}_{info['strike']}_{info['expiry']}"
        moomoo_keys.add(key)

        if key not in db_trade_keys:
            # Auto-import new position
            ticker_info = db.query(TickerInfo).filter(
                TickerInfo.ticker == info["ticker"]
            ).first()
            sector = ticker_info.sector if ticker_info else "Technology"

            trade = Trade(
                trade_date_open=datetime.utcnow(),
                ticker=info["ticker"],
                sector=sector,
                strategy="CSP" if info["option_type"] == "P" else "COVERED_CALL",
                direction="SELL" if pos["qty"] < 0 else "BUY",
                strike=info["strike"],
                expiry=datetime.strptime(info["expiry"], "%Y-%m-%d").date(),
                contracts=abs(int(pos["qty"])),
                premium_received=pos["cost_price"],
                status="OPEN",
                auto_imported=True,
                notes="[AUTO-IMPORTED from Moomoo — needs review]",
            )
            trade.calculate_dte_at_entry()
            db.add(trade)
            new_imports += 1

    # Mark positions closed if qty=0 in Moomoo (position was closed)
    closed = 0
    closed_positions_pnl = {}
    for pos in positions:
        info = pos.get("option_info")
        if info and pos["qty"] == 0:
            key = f"{info['ticker']}_{info['strike']}_{info['expiry']}"
            closed_positions_pnl[key] = pos.get("pl_val", 0)

    for t in db_open_trades:
        key = f"{t.ticker}_{t.strike}_{t.expiry}"
        if key not in moomoo_keys:
            t.status = "CLOSED"
            t.trade_date_close = date.today()
            # Use Moomoo P&L if available
            if key in closed_positions_pnl:
                t.pnl_dollars = closed_positions_pnl[key]
            closed += 1

    db.commit()

    return {
        "moomoo_positions": len(positions),
        "new_imports": new_imports,
        "updated": updated,
        "closed": closed,
        "message": f"Synced {len(positions)} positions. {new_imports} new imports."
    }


@router.post("/account")
def sync_account(db: Session = Depends(get_db)):
    """Sync account info from Moomoo and create a portfolio snapshot."""
    if not moomoo_client.is_available():
        raise HTTPException(status_code=503, detail="Moomoo integration not available")

    account, error = moomoo_client.get_account_info()
    if error:
        raise HTTPException(status_code=500, detail=error)

    # Get supplementary data
    vix = yahoo_client.get_vix()
    spy = yahoo_client.get_spy_price()
    regime = classify_regime(vix) if vix else None

    # Calculate from open trades
    open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
    capital_deployed = sum(t.effective_bp for t in open_trades)
    sectors = list(set(t.sector for t in open_trades))

    snapshot = PortfolioSnapshot(
        date=date.today(),
        total_capital=account["total_assets"],
        capital_deployed=capital_deployed,
        capital_available=account["available_funds"],
        open_positions_count=len(open_trades),
        sectors_exposed=json.dumps(sectors),
        vix_level=vix,
        spy_price=spy,
        regime=regime,
    )
    snapshot.capital_utilization_pct = (
        (capital_deployed / account["total_assets"] * 100)
        if account["total_assets"] > 0 else 0
    )

    # Upsert
    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.date == date.today()
    ).first()
    if existing:
        for col in ["total_capital", "capital_deployed", "capital_available",
                     "capital_utilization_pct", "open_positions_count",
                     "sectors_exposed", "vix_level", "spy_price", "regime"]:
            setattr(existing, col, getattr(snapshot, col))
        db.commit()
        return {"message": "Snapshot updated", "account": account}

    db.add(snapshot)
    db.commit()
    return {"message": "Snapshot created", "account": account}


class HistoryImportRequest(BaseModel):
    start_date: str  # "2025-01-01 00:00:00"
    end_date: str    # "2025-03-15 23:59:59"


@router.post("/history")
def import_trade_history(data: HistoryImportRequest, db: Session = Depends(get_db)):
    """Import historical deals from Moomoo to backfill the trade journal."""
    if not moomoo_client.is_available():
        raise HTTPException(status_code=503, detail="Moomoo integration not available")

    deals, error = moomoo_client.get_trade_history(data.start_date, data.end_date)
    if error:
        raise HTTPException(status_code=500, detail=error)

    # Group deals by option code to match STO with BTC
    from collections import defaultdict
    grouped = defaultdict(list)
    for deal in deals:
        grouped[deal["code"]].append(deal)

    imported = 0
    for code, code_deals in grouped.items():
        info = code_deals[0].get("option_info")
        if not info:
            continue

        sells = [d for d in code_deals if d["trd_side"] == "SELL"]
        buys = [d for d in code_deals if d["trd_side"] == "BUY"]

        for sell in sells:
            # Check if already imported
            existing = db.query(Trade).filter(
                Trade.moomoo_deal_id == sell["deal_id"]
            ).first()
            if existing:
                continue

            ticker_info = db.query(TickerInfo).filter(
                TickerInfo.ticker == info["ticker"]
            ).first()
            sector = ticker_info.sector if ticker_info else "Technology"

            trade = Trade(
                trade_date_open=datetime.strptime(sell["create_time"], "%Y-%m-%d %H:%M:%S") if sell["create_time"] else datetime.utcnow(),
                ticker=info["ticker"],
                sector=sector,
                strategy="CSP" if info["option_type"] == "P" else "COVERED_CALL",
                direction="SELL",
                strike=info["strike"],
                expiry=datetime.strptime(info["expiry"], "%Y-%m-%d").date(),
                contracts=int(sell["qty"]),
                premium_received=sell["price"],
                status="OPEN",
                moomoo_deal_id=sell["deal_id"],
                moomoo_order_id=sell["order_id"],
                auto_imported=True,
                notes="[BACKFILL from Moomoo history]",
            )
            trade.calculate_dte_at_entry()

            # Try to match with a buy (close)
            if buys:
                buy = buys.pop(0)
                trade.premium_close = buy["price"]
                trade.trade_date_close = datetime.strptime(buy["create_time"], "%Y-%m-%d %H:%M:%S") if buy["create_time"] else None
                trade.status = "CLOSED"
                trade.exit_reason = "MANUAL"
                trade.calculate_pnl()

            db.add(trade)
            imported += 1

    db.commit()
    return {
        "total_deals": len(deals),
        "trades_imported": imported,
        "message": f"Imported {imported} trades from Moomoo history"
    }


@router.get("/csp-scanner")
async def csp_scan():
    """Full CSP scan - returns top recommendations with options enrichment."""
    from server.services.csp_scanner import run_csp_scan
    results = await run_csp_scan()
    return results


@router.get("/csp-scanner/quick")
async def csp_scan_quick():
    """Quick scan - TradingView data only, no options enrichment."""
    from server.services.csp_scanner import run_quick_scan
    results = await run_quick_scan()
    return results


@router.get("/csp-scanner/signal/{ticker}")
async def csp_signal(ticker: str):
    """Generate AI entry signal for a specific ticker."""
    import asyncio
    from server.services.ai_signal import generate_ai_signal

    loop = asyncio.get_event_loop()
    # Try to get stock data from cache if available
    from server.services.csp_scanner import _cache
    cached_scan = _cache.get("full_scan", {}).get("data", {})
    stock_data = None
    options_data = None
    if cached_scan:
        for s in cached_scan.get("results", []):
            if s.get("ticker") == ticker.upper():
                stock_data = s
                options_data = s.get("options_data")
                break

    result = await loop.run_in_executor(None, generate_ai_signal, ticker.upper(), stock_data, options_data)
    return result


@router.get("/market-intel")
async def market_intelligence():
    """Full market intelligence with AI analysis."""
    from server.services.market_intel import run_market_intel
    return await run_market_intel()


@router.get("/market-intel/quick")
async def market_intelligence_quick():
    """Quick market data without AI analysis."""
    from server.services.market_intel import run_market_intel_quick
    return await run_market_intel_quick()


@router.get("/suggestions")
def get_trade_suggestions(db: Session = Depends(get_db)):
    """
    Scan the approved universe and generate trade suggestions.
    Analyzes market conditions (SPY, QQQ, VIX), checks portfolio state,
    and recommends specific CSP trades with strike, expiry, and rationale.
    """
    from server.services.scanner import generate_suggestions
    return generate_suggestions(db)


class PreTradeCheckRequest(BaseModel):
    ticker: str
    strike: float
    strike_long: Optional[float] = None
    expiry: str  # "2026-04-17"
    strategy: str = "CSP"
    direction: str = "SELL"
    contracts: int = 1
    premium: Optional[float] = None


@router.post("/pre-trade-check")
def pre_trade_risk_check(data: PreTradeCheckRequest, db: Session = Depends(get_db)):
    """
    Comprehensive pre-trade risk check:
    - Fetches live stock price and option chain from Yahoo
    - Checks current portfolio exposure (open positions, sector limits)
    - Validates against regime rules (delta, DTE, position size)
    - Gets live VIX and market regime
    - Returns pass/fail with detailed explanations
    """
    import math
    from server.services.regime import classify_regime, get_regime_position_limits

    ticker = data.ticker.upper()
    checks = []
    warnings = []

    # Load config first (needed for regime classification)
    import os
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config.json"
    )
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception:
        config = {}

    # --- 1. Market Data ---
    vix = yahoo_client.get_vix()
    spy = yahoo_client.get_spy_price()
    regime = classify_regime(vix, config=config) if vix else "SLIGHT_FEAR"

    entry_rules = config.get("entry_rules", {})
    regime_limits = get_regime_position_limits(regime, config)

    # --- 2. Live Stock & Option Data ---
    import yfinance as yf
    import numpy as np
    stock_price = None
    option_data = None
    volatility_data = None
    try:
        stock = yf.Ticker(ticker)

        # Get 1 year of history for HV and IV rank calculation
        hist_1y = stock.history(period="1y")
        if not hist_1y.empty:
            stock_price = float(hist_1y["Close"].iloc[-1])

            # Historical Volatility (20-day and 60-day)
            closes = hist_1y["Close"].values
            log_returns = np.log(closes[1:] / closes[:-1])
            hv_20 = float(np.std(log_returns[-20:]) * np.sqrt(252) * 100) if len(log_returns) >= 20 else None
            hv_60 = float(np.std(log_returns[-60:]) * np.sqrt(252) * 100) if len(log_returns) >= 60 else None

            volatility_data = {
                "hv_20": round(hv_20, 1) if hv_20 else None,
                "hv_60": round(hv_60, 1) if hv_60 else None,
            }

        # Fetch the specific option
        try:
            chain = stock.option_chain(data.expiry)
            if data.strategy in ("CSP", "PUT_SPREAD"):
                opts = chain.puts
            else:
                opts = chain.calls
            match = opts[opts["strike"] == data.strike]
            if not match.empty:
                row = match.iloc[0]
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                mid = (bid + ask) / 2 if bid > 0 else float(row.get("lastPrice", 0) or 0)
                iv = float(row.get("impliedVolatility", 0) or 0) * 100
                oi = int(row.get("openInterest", 0) or 0)
                volume = int(row.get("volume", 0) or 0)
                option_data = {
                    "bid": round(bid, 2), "ask": round(ask, 2), "mid": round(mid, 2),
                    "iv": round(iv, 1), "open_interest": oi, "volume": volume,
                }

            # IV Rank: where current IV sits in 1-year range of ATM put IVs
            # Use all puts in the chain near ATM as proxy for current IV level
            iv_rank = None
            if option_data and option_data.get("iv") and stock_price:
                current_iv = option_data["iv"]
                # Get all available expiries to sample IV history
                all_puts = chain.puts
                all_ivs = all_puts["impliedVolatility"].dropna() * 100
                if len(all_ivs) > 5:
                    iv_min = float(all_ivs.min())
                    iv_max = float(all_ivs.max())
                    if iv_max > iv_min:
                        iv_rank = round((current_iv - iv_min) / (iv_max - iv_min) * 100, 0)
                        iv_rank = max(0, min(100, iv_rank))

                if volatility_data:
                    volatility_data["iv"] = round(current_iv, 1)
                    volatility_data["iv_rank"] = iv_rank
                    if volatility_data.get("hv_20"):
                        volatility_data["iv_hv_ratio"] = round(current_iv / volatility_data["hv_20"], 2)

        except Exception:
            pass
    except Exception:
        pass

    # --- 3. Portfolio State ---
    open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
    latest_snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).first()
    total_capital = latest_snap.total_capital if latest_snap else 220000
    capital_deployed = sum(t.effective_bp for t in open_trades)
    capital_available = total_capital - capital_deployed

    open_tickers = [t.ticker for t in open_trades]
    sector_counts = {}
    for t in open_trades:
        sector_counts[t.sector] = sector_counts.get(t.sector, 0) + 1

    # Get ticker sector
    ticker_info = db.query(TickerInfo).filter(TickerInfo.ticker == ticker).first()
    sector = ticker_info.sector if ticker_info else "Unknown"

    # DTE
    from datetime import datetime as dt
    try:
        exp_date = dt.strptime(data.expiry, "%Y-%m-%d").date()
        dte = (exp_date - date.today()).days
    except Exception:
        dte = 0

    # Buying power
    if data.strategy == "CSP":
        buying_power = data.strike * 100 * data.contracts
    elif data.strategy in ("PUT_SPREAD", "BEAR_CALL_SPREAD") and data.strike_long:
        buying_power = abs(data.strike - data.strike_long) * 100 * data.contracts
    else:
        buying_power = data.strike * 100 * data.contracts

    premium = data.premium or (option_data["mid"] if option_data else 0)
    breakeven = data.strike - premium if data.strategy in ("CSP", "PUT_SPREAD") else data.strike + premium
    otm_pct = ((stock_price - data.strike) / stock_price * 100) if stock_price and data.strategy in ("CSP", "PUT_SPREAD") else \
              ((data.strike - stock_price) / stock_price * 100) if stock_price else 0

    # Estimated delta
    estimated_delta = None
    if stock_price and option_data and option_data.get("iv"):
        iv = option_data["iv"]
        if data.strategy in ("CSP", "PUT_SPREAD"):
            otm_frac = (stock_price - data.strike) / stock_price
            iv_factor = max(iv / 30, 0.5)
            estimated_delta = -max(0.01, 0.5 * math.exp(-3.5 * otm_frac / iv_factor))
        else:
            otm_frac = (data.strike - stock_price) / stock_price
            iv_factor = max(iv / 30, 0.5)
            estimated_delta = max(0.01, 0.5 * math.exp(-3.5 * otm_frac / iv_factor))

    # --- 4. Run Checks ---

    # Check 1: Duplicate ticker
    has_existing = ticker in open_tickers
    checks.append({
        "rule": "Duplicate Position",
        "passed": not has_existing,
        "severity": "WARNING",
        "message": f"Already holding {ticker} — adding increases concentration risk" if has_existing else f"No existing {ticker} position — OK",
    })

    # Check 2: Sector limit
    max_per_sector = entry_rules.get("max_positions_per_sector", 2)
    sector_count = sector_counts.get(sector, 0)
    sector_ok = sector_count < max_per_sector
    checks.append({
        "rule": "Sector Limit",
        "passed": sector_ok,
        "severity": "CRITICAL",
        "message": f"{sector}: {sector_count}/{max_per_sector} positions" + (" — at limit!" if not sector_ok else " — within limit"),
    })

    # Check 3: Position size (strategy-aware: CSP 10%, spreads 5%)
    if data.strategy == "CSP":
        max_position_pct = entry_rules.get("max_position_size_pct_csp", 10)
        size_label = "CSP"
    else:
        max_position_pct = entry_rules.get("max_position_size_pct_spread", 5)
        size_label = "spread"
    position_pct = (buying_power / total_capital * 100) if total_capital else 0
    size_ok = position_pct <= max_position_pct
    checks.append({
        "rule": "Position Size",
        "passed": size_ok,
        "severity": "CRITICAL",
        "message": f"${buying_power:,.0f} = {position_pct:.1f}% of ${total_capital:,.0f} capital ({size_label} limit: {max_position_pct}%)" + (" — exceeds limit!" if not size_ok else " — OK"),
    })

    # Check 4: Capital available
    can_afford = buying_power <= capital_available
    checks.append({
        "rule": "Available Capital",
        "passed": can_afford,
        "severity": "CRITICAL",
        "message": f"Need ${buying_power:,.0f} — ${capital_available:,.0f} available" + (" — insufficient!" if not can_afford else " — OK"),
    })

    # Check 5: DTE range
    dte_range = entry_rules.get("dte_range", [30, 45])
    dte_ok = dte_range[0] <= dte <= dte_range[1]
    checks.append({
        "rule": "DTE Range",
        "passed": dte_ok,
        "severity": "WARNING",
        "message": f"{dte} DTE — target range {dte_range[0]}-{dte_range[1]}" + (" — outside range" if not dte_ok else " — within range"),
    })

    # Check 6: Delta check
    delta_range = regime_limits.get("delta_range", entry_rules.get("delta_range", [-0.25, -0.15]))
    if estimated_delta is not None and data.strategy in ("CSP", "PUT_SPREAD"):
        delta_ok = delta_range[0] <= estimated_delta <= delta_range[1]
        checks.append({
            "rule": "Delta Range",
            "passed": delta_ok,
            "severity": "WARNING",
            "message": f"Est. delta {estimated_delta:.3f} — regime target {delta_range[0]} to {delta_range[1]}" + (" — too aggressive!" if not delta_ok else " — OK"),
        })

    # Check 7: Regime max positions
    max_positions = regime_limits.get("max_positions", 8)
    total_open = len(open_trades)
    pos_ok = total_open < max_positions
    checks.append({
        "rule": "Regime Position Limit",
        "passed": pos_ok,
        "severity": "CRITICAL",
        "message": f"{total_open}/{max_positions} positions open ({regime.replace('_', ' ')})" + (" — at limit!" if not pos_ok else " — OK"),
    })

    # Check 8: Capital deployment cap (regime-aware)
    max_deploy_pct = regime_limits.get("max_deployment_pct", 60)
    new_utilization = ((capital_deployed + buying_power) / total_capital * 100) if total_capital else 0
    deploy_ok = new_utilization <= max_deploy_pct
    checks.append({
        "rule": "Capital Deployment",
        "passed": deploy_ok,
        "severity": "CRITICAL",
        "message": f"Deployment after trade: {new_utilization:.1f}% — {regime.replace('_', ' ')} max {max_deploy_pct}% (${(total_capital * max_deploy_pct / 100):,.0f})" + (" — over limit!" if not deploy_ok else " — OK"),
    })

    # Check 9: Liquidity check (from option data)
    if option_data:
        oi_ok = option_data["open_interest"] >= 50
        checks.append({
            "rule": "Liquidity",
            "passed": oi_ok,
            "severity": "WARNING",
            "message": f"Open interest: {option_data['open_interest']:,} | Volume: {option_data['volume']:,}" + (" — low liquidity!" if not oi_ok else " — adequate"),
        })

        # Bid-ask spread
        if option_data["mid"] > 0 and option_data["ask"] > option_data["bid"]:
            spread_pct = (option_data["ask"] - option_data["bid"]) / option_data["mid"] * 100
            spread_ok = spread_pct < 20
            checks.append({
                "rule": "Bid-Ask Spread",
                "passed": spread_ok,
                "severity": "WARNING",
                "message": f"Spread: ${option_data['bid']:.2f}/${option_data['ask']:.2f} ({spread_pct:.1f}%)" + (" — wide spread!" if not spread_ok else " — tight"),
            })

    # Check 10: Regime-strategy compatibility
    if regime in ("VERY_FEARFUL", "EXTREME_FEAR") and data.strategy == "CSP":
        checks.append({
            "rule": "Strategy vs Regime",
            "passed": True,
            "severity": "WARNING",
            "message": f"CSP in {regime.replace('_', ' ')} — fat premiums! Consider PUT_SPREAD for defined risk, but CSP is OK if conviction is high",
        })
    elif regime in ("EXTREME_GREED",) and data.strategy == "CSP":
        checks.append({
            "rule": "Strategy vs Regime",
            "passed": True,
            "severity": "WARNING",
            "message": "Extreme greed — premiums are thin. Make sure IV rank justifies the trade",
        })
    else:
        checks.append({
            "rule": "Strategy vs Regime",
            "passed": True,
            "severity": "INFO",
            "message": f"{data.strategy} is appropriate for {regime.replace('_', ' ')} regime",
        })

    # Annualized return
    annual_return = 0
    if premium and data.strike and dte > 0:
        premium_return = premium / data.strike * 100
        annual_return = premium_return / dte * 365

    all_passed = all(c["passed"] for c in checks)
    critical_fails = [c for c in checks if not c["passed"] and c["severity"] == "CRITICAL"]
    warning_fails = [c for c in checks if not c["passed"] and c["severity"] == "WARNING"]

    return {
        "checks": checks,
        "all_passed": all_passed,
        "critical_violations": len(critical_fails),
        "warning_count": len(warning_fails),
        "market": {
            "vix": round(vix, 2) if vix else None,
            "spy_price": round(spy, 2) if spy else None,
            "regime": regime,
        },
        "position": {
            "stock_price": round(stock_price, 2) if stock_price else None,
            "option": option_data,
            "volatility": volatility_data,
            "estimated_delta": round(estimated_delta, 3) if estimated_delta else None,
            "buying_power": round(buying_power, 0),
            "position_pct": round(position_pct, 1),
            "breakeven": round(breakeven, 2) if breakeven else None,
            "otm_pct": round(otm_pct, 1),
            "dte": dte,
            "annual_return": round(annual_return, 1),
            "sector": sector,
        },
        "portfolio": {
            "total_capital": total_capital,
            "capital_available": round(capital_available, 0),
            "open_positions": total_open,
            "utilization_after": round(new_utilization, 1),
        },
    }


@router.post("/snapshot/manual")
def create_manual_snapshot(
    total_capital: float,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Create a manual portfolio snapshot (when Moomoo is not connected)."""
    open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
    capital_deployed = sum(t.effective_bp for t in open_trades)
    sectors = list(set(t.sector for t in open_trades))

    vix = yahoo_client.get_vix()
    spy = yahoo_client.get_spy_price()
    regime = classify_regime(vix) if vix else None

    snapshot = PortfolioSnapshot(
        date=date.today(),
        total_capital=total_capital,
        capital_deployed=capital_deployed,
        capital_available=total_capital - capital_deployed,
        capital_utilization_pct=(capital_deployed / total_capital * 100) if total_capital > 0 else 0,
        open_positions_count=len(open_trades),
        sectors_exposed=json.dumps(sectors),
        vix_level=vix,
        spy_price=spy,
        regime=regime,
        notes=notes,
    )

    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.date == date.today()
    ).first()
    if existing:
        for col in snapshot.__table__.columns:
            if col.name not in ("id", "created_at"):
                val = getattr(snapshot, col.name)
                if val is not None:
                    setattr(existing, col.name, val)
        db.commit()
        return {"message": "Snapshot updated"}

    db.add(snapshot)
    db.commit()
    return {"message": "Snapshot created"}


# --- Ticker Analysis ---

@router.get("/ticker/search")
def search_tickers(q: str = ""):
    """Search tickers by name or symbol."""
    if not q or len(q) < 1:
        return []
    return yahoo_client.search_tickers(q, limit=10)


@router.get("/ticker/{ticker}/analysis")
def get_ticker_analysis(ticker: str):
    """Get comprehensive fundamental analysis for a ticker."""
    result = yahoo_client.get_ticker_analysis(ticker.upper())
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Ticker not found"))
    return result


@router.get("/ticker/{ticker}/earnings")
def get_ticker_earnings(ticker: str):
    """Get earnings/EPS and revenue history for a ticker."""
    result = yahoo_client.get_earnings_history(ticker.upper())
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "No earnings data"))
    return result


@router.get("/ticker/{ticker}/price-history")
def get_ticker_price_history(ticker: str, period: str = "5y"):
    """Get historical price data for charting. period: 1mo, 3mo, 6mo, 1y, 2y, 5y, max"""
    valid_periods = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
    if period not in valid_periods:
        period = "5y"
    result = yahoo_client.get_price_history(ticker.upper(), period=period)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "No price data"))
    return result


# --- YouTube Video Analysis ---

class YouTubeAnalyzeRequest(BaseModel):
    url: str


@router.post("/youtube/analyze")
def analyze_youtube_video(data: YouTubeAnalyzeRequest):
    """Scrape a YouTube video transcript and analyze financial content using Claude AI."""
    from server.services.youtube_scraper import scrape_and_analyze

    result = scrape_and_analyze(data.url)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to analyze video"))

    return result


class YouTubeChannelRequest(BaseModel):
    url: str


@router.get("/youtube/channels")
def list_channels():
    """Get all followed YouTube channels."""
    from server.services.youtube_scraper import get_channels
    return {"channels": get_channels()}


@router.post("/youtube/channels")
def add_youtube_channel(data: YouTubeChannelRequest):
    """Add a YouTube channel to follow."""
    from server.services.youtube_scraper import add_channel
    result = add_channel(data.url)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/youtube/channels/{channel_id}")
def remove_youtube_channel(channel_id: str):
    """Remove a YouTube channel."""
    from server.services.youtube_scraper import remove_channel
    result = remove_channel(channel_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/youtube/feed")
def get_youtube_feed():
    """Get latest videos from all followed channels."""
    from server.services.youtube_scraper import fetch_all_latest
    return {"videos": fetch_all_latest(max_per_channel=2)}


@router.get("/youtube/smart-feed")
def get_smart_feed():
    """Get videos posted since last market close (session-aware).
    Returns only videos within the current trading session window."""
    from server.services.youtube_scraper import fetch_smart_feed
    return fetch_smart_feed()


@router.post("/youtube/auto-analyze")
def auto_analyze_all():
    """Fetch smart feed and auto-analyze all videos with Claude AI.
    Results are cached and auto-expire after the next market close."""
    from server.services.youtube_scraper import auto_analyze_feed
    return auto_analyze_feed()


@router.get("/youtube/session")
def get_session_info():
    """Get current market session window info."""
    from server.services.youtube_scraper import get_market_session_window
    session = get_market_session_window()
    return {
        "window_start": session["window_start"].isoformat(),
        "window_end": session["window_end"].isoformat(),
        "expires_at": session["expires_at"].isoformat(),
        "label": session["label"],
    }


# ─── 3-Tier Cascading Analysis ───────────────────────────────

@router.get("/cascading-analysis")
async def cascading_analysis_sse(force: bool = False):
    """SSE endpoint for 3-tier cascading analysis with real-time progress.
    Use ?force=true to bypass cache and re-run analysis."""
    from server.services.cascading_analysis import run_cascading_analysis_sync, _get_cached

    # Check cache first (unless force=true)
    if not force:
        cached = _get_cached("cascading_analysis")
        if cached:
            async def cached_stream():
                yield f"event: cached\ndata: {json.dumps(cached, default=str, ensure_ascii=False)}\n\n"
            return StreamingResponse(cached_stream(), media_type="text/event-stream")

    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def progress_cb(tier: int, step: str, message: str):
        """Called by the sync analysis to report progress."""
        try:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "tier": tier, "step": step, "message": message}
            )
        except Exception:
            pass

    async def event_stream():
        # Run in thread executor (blocking I/O)
        task = loop.run_in_executor(None, lambda: run_cascading_analysis_sync(progress_cb, force=force))

        # Yield progress events while analysis runs
        while not task.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"event: {event.get('type', 'progress')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive
                yield f": keepalive\n\n"

        # Drain remaining events
        while not queue.empty():
            event = queue.get_nowait()
            yield f"event: {event.get('type', 'progress')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        # Get the final result
        try:
            result = task.result()
            yield f"event: complete\ndata: {json.dumps(result, default=str, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/cascading-analysis/cached")
async def cascading_analysis_cached():
    """Return cached cascading analysis result — memory first, then disk."""
    from server.services.cascading_analysis import _get_cached, _load_from_disk, _set_cache
    cached = _get_cached("cascading_analysis")
    if cached:
        return cached
    # Fall back to disk (survives restarts and page refreshes)
    disk = _load_from_disk()
    if disk:
        _set_cache("cascading_analysis", disk)  # Warm memory cache
        return disk
    return {"status": "no_cache", "message": "No cached analysis available"}


@router.get("/stock-options/{ticker}")
async def get_stock_options(ticker: str, dte: int = 35):
    """Get real-time CSP option data + AI analysis for a single stock via Moomoo."""
    try:
        from server.services.moomoo_options import get_csp_options, MOOMOO_AVAILABLE
        if not MOOMOO_AVAILABLE:
            return {"error": "Moomoo OpenD not available", "source": "unavailable"}

        # Get current price
        import yfinance as yf
        price = yf.Ticker(ticker).fast_info.get("lastPrice", 0)
        if not price:
            return {"error": f"Cannot get price for {ticker}"}

        result = get_csp_options(ticker, stock_price=price, target_dte=dte)
        result["stock_price"] = round(price, 2)

        # AI Analysis of the option data
        try:
            from server.services.cascading_analysis import _call_claude
            import json as _json

            # Get Tier 3 cached safety data for this stock
            safety_context = ""
            try:
                cache_path = Path(__file__).resolve().parent.parent / ".cascading_cache.json"
                if cache_path.exists():
                    with open(cache_path) as f:
                        cached = _json.load(f)
                    t3_recs = cached.get("tier3", {}).get("ai", {}).get("recommendations", [])
                    for rec in t3_recs:
                        if rec.get("ticker") == ticker.upper():
                            safety_context = f"""
## 第三层安全评估结果
- 安全评分: {rec.get('safety_score', 'N/A')}/100
- 评估: {rec.get('summary', 'N/A')}
- 支撑位: ${rec.get('safe_support', 'N/A')}
- 最大跌幅预估: {rec.get('max_loss_estimate', 'N/A')}
- 看多理由: {rec.get('bull_case', 'N/A')}
- 看空风险: {rec.get('bear_case', 'N/A')}
"""
                            break
            except Exception:
                pass

            # Format option candidates
            candidates = result.get("candidates", [])
            best = result.get("best_csp")
            atm_iv = result.get("atm_iv", 0)

            options_text = f"ATM IV: {atm_iv:.1%}\n" if atm_iv else ""
            options_text += f"到期日: {result.get('expiry', 'N/A')} (DTE: {result.get('dte', 'N/A')}天)\n\n"

            for c in candidates:
                otm_pct = ((price - c['strike']) / price * 100) if c.get('strike') else 0
                options_text += f"行权价${c['strike']} (OTM {otm_pct:.1f}%) | Bid=${c.get('bid', 0):.2f} Ask=${c.get('ask', 0):.2f} Mid=${c.get('mid', 0):.2f}\n"
                options_text += f"  IV={c.get('iv', 0):.1%} | Delta={c.get('delta', 0):.3f} | Theta={c.get('theta', 0):.4f}\n"
                options_text += f"  OI={c.get('open_interest', 0):,} | Vol={c.get('volume', 0):,} | 年化={c.get('annualized_return', 0):.1%} | BP=${c.get('buying_power', 0):,.0f}\n\n"

            prompt = f"""你是一位资深期权交易分析师。请用中文分析以下{ticker}的CSP（Cash-Secured Put）期权数据，给出可操作的交易建议。

## 股票信息
- 代码: {ticker}
- 当前价格: ${price:.2f}
{safety_context}

## 实时期权数据 (Moomoo)
{options_text}

## 分析要求
1. **最佳行权价推荐**: 综合安全评分、IV水平、Delta、OTM距离，推荐最适合的1-2个行权价
2. **风险收益分析**:
   - 被行权概率（基于Delta和安全评分）
   - 年化收益率是否合理
   - Buying Power使用效率
3. **IV分析**: 当前IV是偏高/正常/偏低？是否是卖权的好时机？
4. **具体操作建议**:
   - 建议卖哪个行权价的Put
   - 预期收入（每手premium × 100股）
   - 最大风险（被行权后的亏损）
   - 持有策略（持有到期 vs 50%利润止盈）

请严格按以下JSON格式返回：
{{
  "recommendation": "STRONG_SELL|SELL|HOLD|AVOID",
  "best_strike": number,
  "best_premium": number,
  "summary": "2-3句中文总结",
  "iv_assessment": "偏高/正常/偏低 + 1句解释",
  "risk_reward": "1句中文：风险收益比评估",
  "action_plan": "具体操作步骤（中文）",
  "expected_income": number,
  "max_risk": "最大风险描述",
  "exit_strategy": "止盈/止损策略"
}}"""

            ai_result = _call_claude(prompt, max_tokens=2000)
            result["ai_analysis"] = ai_result

        except Exception as e:
            logger.error(f"Option AI analysis failed for {ticker}: {e}")
            result["ai_analysis"] = {"error": str(e)}

        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/vix-regime")
async def get_vix_regime(force: bool = False):
    """VIX term structure regime detection — 5 regimes, transitions, sizing, alerts."""
    try:
        from server.services.vix_regime import analyze_vix_regime
        result = analyze_vix_regime(force=force)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


@router.get("/trend-ribbon/{ticker}")
async def get_trend_ribbon(ticker: str, period: str = "1y", interval: str = "1d", ema_fast: int = 13, ema_slow: int = 34, ema_long: int = 120):
    """Trend ribbon (EMA crossover band) data for charting."""
    try:
        from server.services.trend_ribbon import calculate_trend_ribbon
        result = calculate_trend_ribbon(ticker, period=period, interval=interval, ema_fast=ema_fast, ema_slow=ema_slow, ema_long=ema_long)
        return result or {"error": "No data"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Flow Toxicity — per-strike informed flow detection
# ═══════════════════════════════════════════════════════════════

@router.get("/flow-toxicity/{ticker}")
async def get_flow_toxicity(ticker: str, strike: float = 0, expiry: str = ""):
    """Compute flow toxicity for a specific option strike."""
    try:
        from server.services.flow_toxicity import compute_strike_toxicity
        import yfinance as yf

        ticker = ticker.upper()

        # If no expiry provided, find the nearest monthly expiry ~30 DTE
        if not expiry:
            from datetime import datetime, timedelta
            stk = yf.Ticker(ticker)
            expirations = stk.options or []
            target_date = datetime.now() + timedelta(days=30)
            if expirations:
                expiry = min(expirations, key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d") - target_date).days))
            else:
                return {"error": f"No options available for {ticker}"}

        # If no strike provided, pick a ~5% OTM put
        if strike <= 0:
            info = yf.Ticker(ticker).info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            if price <= 0:
                return {"error": f"Cannot get price for {ticker}"}
            strike = round(price * 0.95, 0)  # ~5% OTM

        # Get VIX regime
        regime = "CONTANGO"
        try:
            from server.services.cascading_analysis import _get_cached
            vix_data = _get_cached("vix_regime")
            if vix_data and vix_data.get("regime"):
                regime = vix_data["regime"]
        except Exception:
            pass

        result = compute_strike_toxicity(ticker, expiry, strike, regime)
        return result

    except Exception as e:
        logger.error(f"Flow toxicity endpoint failed for {ticker}: {e}")
        return {"error": str(e)}


def _gather_single_stock_data(ticker: str) -> dict:
    """Gather all data for a single stock: fundamentals, technicals, news, sentiment, institutional, insider.
    Returns dict with keys: stock_data, news, sentiment, support, institutional, insider, stocks_text.
    Shared by stock-safety and stock-safety/debate endpoints."""
    from server.services.cascading_analysis import _fetch_yahoo_news, _fetch_support_levels
    from server.services.finbert_sentiment import score_news_for_ticker
    import yfinance as yf

    ticker = ticker.upper()
    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        price = yf_ticker.fast_info.get("lastPrice")
    if not price:
        raise ValueError(f"Cannot get price for {ticker}")

    stock_data = {
        "ticker": ticker,
        "name": info.get("shortName", info.get("longName", "")),
        "price": round(price, 2),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "market_cap": info.get("marketCap"),
        "pe_ttm": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps_ttm": info.get("trailingEps"),
        "beta": info.get("beta"),
        "dividend_yield": info.get("dividendYield"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
    }

    # Technicals
    try:
        hist = yf_ticker.history(period="6mo")
        if len(hist) >= 14:
            closes = hist['Close'].values
            deltas_arr = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [max(d, 0) for d in deltas_arr[-14:]]
            losses = [-min(d, 0) for d in deltas_arr[-14:]]
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                stock_data["rsi"] = round(100 - (100 / (1 + rs)), 1)
            if len(closes) >= 50:
                stock_data["sma50"] = round(float(closes[-50:].mean()), 2)
            if len(closes) >= 120:
                stock_data["sma200"] = round(float(closes[-min(200, len(closes)):].mean()), 2)
            if len(closes) >= 22:
                stock_data["perf_1m"] = round((closes[-1] / closes[-22] - 1) * 100, 2)
            if len(closes) >= 5:
                stock_data["perf_1w"] = round((closes[-1] / closes[-5] - 1) * 100, 2)
            sma50 = stock_data.get("sma50")
            sma200 = stock_data.get("sma200")
            if sma50 and sma200:
                if price > sma50 and price > sma200:
                    stock_data["trend"] = "UPTREND"
                elif price > sma200:
                    stock_data["trend"] = "PULLBACK"
                else:
                    stock_data["trend"] = "DOWNTREND"
            if len(closes) >= 10:
                peak = closes[0]
                max_dd = 0
                for c in closes:
                    if c > peak: peak = c
                    dd = (c - peak) / peak * 100
                    if dd < max_dd: max_dd = dd
                stock_data["max_drawdown_3m"] = round(max_dd, 2)
                returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                stock_data["daily_vol"] = round((sum(r**2 for r in returns) / len(returns)) ** 0.5 * 100, 2)
    except Exception:
        pass

    # Earnings distance
    try:
        cal = yf_ticker.calendar
        if cal and isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, list) and ed:
                from datetime import date as _date
                d = ed[0]
                if hasattr(d, 'date'): d = d.date()
                stock_data["days_to_earnings"] = max(0, (d - _date.today()).days)
    except Exception:
        pass

    # News + FinBERT
    news = _fetch_yahoo_news(ticker)
    sentiment = None
    try:
        if news:
            sentiment = score_news_for_ticker(news)
    except Exception:
        pass

    # Support/resistance
    support = _fetch_support_levels(ticker, price)

    # Institutional holdings
    institutional = None
    try:
        ih = yf_ticker.institutional_holders
        if ih is not None and not ih.empty:
            top5 = []
            for _, row in ih.head(5).iterrows():
                pct_change = row.get("pctChange", 0) or 0
                top5.append({
                    "holder": row.get("Holder", ""),
                    "pct_held": round(float(row.get("pctHeld", 0) or 0) * 100, 2),
                    "change": round(float(pct_change) * 100, 1),
                })
            changes = [h["change"] for h in top5 if h["change"] != 0]
            net_buying = sum(1 for c in changes if c > 0)
            net_selling = sum(1 for c in changes if c < 0)
            mh = yf_ticker.major_holders
            inst_pct = float(mh.iloc[1]["Value"] * 100) if mh is not None and len(mh) > 1 else None
            institutional = {
                "top5": top5,
                "inst_pct": round(inst_pct, 1) if inst_pct else None,
                "net_signal": "增持" if net_buying > net_selling else "减持" if net_selling > net_buying else "持平",
                "buying_count": net_buying,
                "selling_count": net_selling,
            }
    except Exception:
        pass

    # Insider transactions
    insider = None
    try:
        it = yf_ticker.insider_transactions
        if it is not None and not it.empty:
            recent = it.head(10)
            sales = recent[recent["Text"].str.contains("Sale", case=False, na=False)]
            buys = recent[recent["Text"].str.contains("Purchase", case=False, na=False)]
            total_sold = sales["Value"].sum() if not sales.empty else 0
            total_bought = buys["Value"].sum() if not buys.empty else 0
            insider = {
                "recent_sales": len(sales),
                "recent_buys": len(buys),
                "total_sold_value": int(total_sold),
                "total_bought_value": int(total_bought),
                "net_signal": "内部人买入" if total_bought > total_sold else "内部人抛售" if total_sold > 0 else "无交易",
            }
            notable = []
            for _, row in recent.head(3).iterrows():
                val = row.get("Value", 0) or 0
                if val > 0:
                    notable.append({
                        "who": row.get("Insider", ""),
                        "action": "卖出" if "Sale" in str(row.get("Text", "")) else "买入",
                        "value": int(val),
                    })
            insider["notable"] = notable
    except Exception:
        pass

    # Build text representation for AI prompts
    stocks_text = f"""### {ticker} - {stock_data.get('name', '')}
  价格: ${stock_data['price']} | 板块: {stock_data.get('sector', '')} / {stock_data.get('industry', '')}
  市值: ${(stock_data.get('market_cap') or 0)/1e9:.1f}B | P/E: {stock_data.get('pe_ttm', 'N/A')} | Forward P/E: {stock_data.get('forward_pe', 'N/A')} | Beta: {stock_data.get('beta', 'N/A')}
  RSI: {stock_data.get('rsi', 'N/A')} | SMA50: ${stock_data.get('sma50', 'N/A')} | SMA200: ${stock_data.get('sma200', 'N/A')} | 趋势: {stock_data.get('trend', 'N/A')}
  1W表现: {stock_data.get('perf_1w', 'N/A')}% | 1M表现: {stock_data.get('perf_1m', 'N/A')}% | 距财报: {stock_data.get('days_to_earnings', '未知')}天
  3月最大回撤: {stock_data.get('max_drawdown_3m', 'N/A')}% | 日均波动: {stock_data.get('daily_vol', 'N/A')}%
  52周高: ${stock_data.get('fifty_two_week_high', 'N/A')} | 52周低: ${stock_data.get('fifty_two_week_low', 'N/A')}
"""
    if support:
        stocks_text += f"  支撑位: ${support.get('support_30d', 'N/A')} | 6月低点: ${support.get('low_6m', 'N/A')} | 距52周高点: {support.get('distance_from_high', 'N/A')}%\n"
    if sentiment and sentiment.get("aggregate"):
        agg = sentiment["aggregate"]
        stocks_text += f"  新闻情绪: {agg['sentiment'].upper()} (均分: {agg['avg_score']:+.3f})\n"
        for art in (sentiment.get("articles") or [])[:5]:
            stocks_text += f"    [{art['score']:+.2f}] {art.get('headline', art.get('title', ''))}\n"
    if institutional:
        stocks_text += f"  机构持股: {institutional.get('inst_pct', 'N/A')}% | 动向: {institutional['net_signal']} ({institutional['buying_count']}家增持 vs {institutional['selling_count']}家减持)\n"
        for h in institutional.get("top5", [])[:3]:
            arrow = "↑" if h["change"] > 0 else "↓" if h["change"] < 0 else "→"
            stocks_text += f"    {arrow} {h['holder']}: 持有{h['pct_held']}% (变动{h['change']:+.1f}%)\n"
    if insider:
        stocks_text += f"  内部人交易: {insider['net_signal']} ({insider['recent_sales']}笔卖出 vs {insider['recent_buys']}笔买入)\n"
        for n in insider.get("notable", [])[:2]:
            stocks_text += f"    {n['action']}: {n['who']} ${n['value']:,}\n"

    return {
        "stock_data": stock_data,
        "news": news,
        "sentiment": sentiment,
        "support": support,
        "institutional": institutional,
        "insider": insider,
        "stocks_text": stocks_text,
    }


def _build_analyst_prompt(ticker: str, stocks_text: str) -> str:
    """Build the analyst prompt for single-stock safety analysis."""
    return f"""你是一位资深股票分析师。请用中文对{ticker}进行全面的30天安全评估。

**核心问题：你有多大把握这只股票30天内不会暴跌10%？**

## 评估维度（按重要性排序）
1. **财报风险** — 距财报越近越危险（<21天=高危）
2. **技术面** — 趋势方向、RSI、价格距支撑位远近、均线排列
3. **新闻面** — FinBERT情绪分数，是否有重大事件
4. **资金面** — 机构增减持、内部人买卖
5. **波动性** — Beta、日均波动率、历史回撤
6. **基本面** — P/E、市值、盈利能力

## 股票数据
{stocks_text}

## 输出要求
- **绝对禁止提及任何期权相关内容**（IV、delta、premium、CSP、put、call、期权等）
- 只分析股票本身的安全性

请严格按以下JSON格式返回（全部中文）：
{{
  "safety_score": 0-100,
  "summary": "3-5句中文：全面分析这只股票30天内的安全性",
  "safe_support": 30天预计底部价格,
  "max_loss_estimate": "如果暴跌，预计最大跌幅x%到$xx",
  "bull_case": "2句中文：支撑安全的核心理由",
  "bear_case": "2句中文：可能暴跌的核心风险",
  "key_levels": {{
    "strong_support": 强支撑价格,
    "weak_support": 弱支撑价格,
    "resistance": 阻力位价格
  }},
  "risks": ["风险1", "风险2", "风险3"],
  "catalysts": ["催化剂1", "催化剂2"]
}}"""


@router.get("/stock-safety/{ticker}")
async def get_stock_safety(ticker: str):
    """Single stock AI safety analysis — same as Tier 3 but standalone."""
    try:
        from server.services.cascading_analysis import _call_claude

        gathered = _gather_single_stock_data(ticker)
        prompt = _build_analyst_prompt(ticker.upper(), gathered["stocks_text"])
        ai_result = _call_claude(prompt, max_tokens=3000)

        return {
            "ticker": ticker.upper(),
            "stock": gathered["stock_data"],
            "support": gathered["support"],
            "sentiment": gathered["sentiment"],
            "institutional": gathered["institutional"],
            "insider": gathered["insider"],
            "news": [{"title": n.get("title", ""), "source": n.get("publisher", "")} for n in (gathered["news"] or [])[:5]],
            "ai_analysis": ai_result,
        }

    except Exception as e:
        logger.error(f"Stock safety analysis failed for {ticker}: {e}")
        return {"error": str(e)}


@router.get("/stock-safety/{ticker}/debate")
async def get_stock_safety_debate(ticker: str):
    """AI Debate: Analyst → Devil's Advocate → Arbiter for deep single-stock analysis."""
    try:
        from server.services.cascading_analysis import _call_claude
        import json as _json

        ticker = ticker.upper()

        # ── Step 0: Gather data (once) ──
        gathered = _gather_single_stock_data(ticker)
        stocks_text = gathered["stocks_text"]

        # ── Step 1: Analyst ──
        analyst_prompt = _build_analyst_prompt(ticker, stocks_text)
        analyst_result = _call_claude(analyst_prompt, max_tokens=3000)

        # ── Step 2: Devil's Advocate ──
        analyst_json_str = _json.dumps(analyst_result, ensure_ascii=False, indent=2) if isinstance(analyst_result, dict) else str(analyst_result)

        devil_prompt = f"""你是一位资深**对立面分析师**（Devil's Advocate），你的职责是**从分析师的反方向质疑**。

## 核心原则
- 如果分析师偏乐观（safety_score ≥ 55），你要**重点找风险、看空**
- 如果分析师偏悲观（safety_score < 55），你要**重点找被低估的安全因素、看多**
- 你的目标不是永远唱空，而是**纠正分析师的偏差**，确保评估更客观

## 你的任务
1. 判断分析师的立场偏向（乐观 or 悲观）
2. 从**反方向**找出分析师忽略或低估的因素
3. 举出**历史上类似情况**支持你的反方向论点
4. 给出你认为更合理的safety_score，并解释调整原因

## 分析师的结论
{analyst_json_str}

## 原始股票数据
{stocks_text}

## 质疑方向参考
**如果分析师偏乐观，重点质疑：**
- 是否低估了财报风险、技术面恶化信号、宏观逆风？
- 机构增持数据是否滞后？内部人是否在抛售？
- 历史上类似情况是否有暴跌反例？

**如果分析师偏悲观，重点质疑：**
- 是否忽视了超卖反弹的历史概率？（RSI<30后30天反弹概率）
- 基本面是否足够强劲支撑？（盈利增长、市场地位、护城河）
- 机构是否在逆势加仓？是否有价值投资者介入的信号？
- 恐慌情绪是否过度？历史上类似跌幅后反弹的案例？

## 输出要求
- **全部中文**
- **绝对禁止提及任何期权相关内容**

请严格按以下JSON格式返回：
{{
  "challenge_score": 你认为合理的safety_score(0-100),
  "bias_direction": "分析师偏乐观我看空" 或 "分析师偏悲观我看多",
  "overlooked_factors": ["被忽略的因素1", "被忽略的因素2", "被忽略的因素3"],
  "counter_arguments": "3-5句中文：针对分析师主要论点的逐条反驳",
  "historical_parallels": "2-3句中文：历史上类似情况支持你立场的案例",
  "score_adjustment": "分析师给了X分，我认为应该是Y分，因为..."
}}"""

        devil_result = _call_claude(devil_prompt, max_tokens=3000)

        # ── Step 3: Arbiter (Chief Investment Officer) ──
        devil_json_str = _json.dumps(devil_result, ensure_ascii=False, indent=2) if isinstance(devil_result, dict) else str(devil_result)

        arbiter_prompt = f"""你是**首席投资官**（CIO），需要综合评判两位分析师对{ticker}的分歧，做出最终裁决。

## 分析师的评估（看多倾向）
{analyst_json_str}

## 质疑者的反驳（看空倾向）
{devil_json_str}

## 原始股票数据
{stocks_text}

## 你的任务
1. 客观评判**分析师说对了什么**、**质疑者说对了什么**
2. 综合双方观点，给出**最终safety_score**（可以与双方都不同）
3. 给出**confidence_level**表示你对自己裁决的信心

## 输出要求
- **全部中文**
- **绝对禁止提及任何期权相关内容**
- 你必须独立思考，不能简单取平均

请严格按以下JSON格式返回：
{{
  "final_safety_score": 最终safety_score(0-100),
  "final_summary": "3-5句中文：综合多空双方的最终安全评估",
  "analyst_strengths": "2句中文：分析师说对了什么",
  "advocate_strengths": "2句中文：质疑者说对了什么",
  "final_bull_case": "2句中文：最终的看多理由",
  "final_bear_case": "2句中文：最终的看空风险",
  "final_risks": ["最终风险1", "最终风险2", "最终风险3"],
  "final_catalysts": ["最终催化剂1", "最终催化剂2"],
  "key_levels": {{
    "strong_support": 强支撑价格,
    "weak_support": 弱支撑价格,
    "resistance": 阻力位价格
  }},
  "max_loss_estimate": "最终预估：如果暴跌，预计最大跌幅x%到$xx",
  "confidence_level": "HIGH或MEDIUM或LOW"
}}"""

        arbiter_result = _call_claude(arbiter_prompt, max_tokens=3000)

        return {
            "ticker": ticker,
            "stock": gathered["stock_data"],
            "support": gathered["support"],
            "sentiment": gathered["sentiment"],
            "institutional": gathered["institutional"],
            "insider": gathered["insider"],
            "news": [{"title": n.get("title", ""), "source": n.get("publisher", "")} for n in (gathered["news"] or [])[:5]],
            "debate": {
                "analyst": analyst_result,
                "devil_advocate": devil_result,
                "arbiter": arbiter_result,
            },
        }

    except Exception as e:
        logger.error(f"Stock safety debate failed for {ticker}: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Portfolio Deep Analysis — AI分析持仓并给出建议
# ═══════════════════════════════════════════════════════════════

@router.get("/portfolio-deep-analysis")
async def portfolio_deep_analysis():
    """
    Deep AI analysis of all open positions in the portfolio.
    Fetches real-time data for each holding, then asks Claude for:
    - Per-position risk assessment
    - Portfolio-level risk (concentration, correlation, macro exposure)
    - Actionable recommendations (hold/close/hedge)
    """
    try:
        from server.services.cascading_analysis import _call_claude, _get_api_key, _load_from_disk
        from server.services.finbert_sentiment import score_news_for_ticker
        from server.services.vix_regime import analyze_vix_regime, get_regime_summary_for_ai
        from server.services.yahoo_client import get_vix_term_structure
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor
        from server.models import Trade, PortfolioSnapshot, get_db as _get_db

        # Get DB session
        db = next(_get_db())

        # Get open trades
        open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
        if not open_trades:
            return {"error": "no_positions", "message": "当前没有持仓"}

        # Get portfolio snapshot
        latest_snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).first()
        total_capital = latest_snap.total_capital if latest_snap else 220000

        # Get VIX regime
        vix_regime = None
        try:
            vix_regime = analyze_vix_regime()
        except Exception:
            pass

        vix_ai_summary = ""
        try:
            if vix_regime:
                vix_ai_summary = get_regime_summary_for_ai(vix_regime)
        except Exception:
            pass

        # Load 3-tier cascading analysis results (if available)
        tier_context = ""
        try:
            cached_3tier = _load_from_disk()
            if cached_3tier:
                # Extract Tier 1 macro conclusion
                t1 = cached_3tier.get("tier1", {})
                t1_ai = t1.get("ai_analysis", {})
                if t1_ai:
                    tier_context += f"\n### 3-Tier大盘分析结论（Tier 1）\n"
                    tier_context += f"  大盘判断: {t1_ai.get('market_label', 'N/A')}\n"
                    tier_context += f"  分析摘要: {t1_ai.get('summary', 'N/A')}\n"
                    risks = t1_ai.get('risks', [])
                    if risks:
                        tier_context += f"  主要风险: {', '.join(risks[:3])}\n"

                # Extract Tier 2 sector recommendations
                t2 = cached_3tier.get("tier2", {})
                t2_ai = t2.get("ai_analysis", {})
                if t2_ai:
                    tier_context += f"\n### 3-Tier板块分析结论（Tier 2）\n"
                    recs = t2_ai.get("recommendations", [])
                    if recs:
                        for r in recs:
                            rating = r.get("rating", "")
                            sector = r.get("sector", r.get("industry", ""))
                            reason = r.get("reason", r.get("reasoning", ""))
                            tier_context += f"  [{rating}] {sector}: {reason}\n"
                    avoid = t2_ai.get("avoid", [])
                    if avoid:
                        tier_context += f"  回避板块: {', '.join(str(a) for a in avoid[:5])}\n"

                # Extract Tier 3 stock safety scores
                t3 = cached_3tier.get("tier3", {})
                t3_stocks = t3.get("stocks", [])
                if t3_stocks:
                    tier_context += f"\n### 3-Tier个股安全评估（Tier 3）\n"
                    for s in t3_stocks:
                        ticker_s = s.get("ticker", "")
                        ai = s.get("ai_analysis", {})
                        score = ai.get("safety_score", "N/A")
                        summary = ai.get("summary", "")
                        if summary:
                            tier_context += f"  {ticker_s}: 安全分{score} — {summary[:80]}\n"

                tier_context += f"\n  （3-Tier分析时间: {cached_3tier.get('timestamp', 'N/A')}）\n"
        except Exception as e:
            logger.warning(f"Failed to load 3-tier cache for portfolio analysis: {e}")

        # Gather real-time data for each unique ticker
        tickers = list(set(t.ticker for t in open_trades))

        def _fetch_ticker_data(ticker):
            """Fetch real-time data for a single ticker."""
            result = {"ticker": ticker}
            try:
                yf_ticker = yf.Ticker(ticker)
                info = yf_ticker.info or {}
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                if not price:
                    price = yf_ticker.fast_info.get("lastPrice")
                result["price"] = round(price, 2) if price else None
                result["name"] = info.get("shortName", info.get("longName", ""))
                result["sector"] = info.get("sector", "")
                result["industry"] = info.get("industry", "")
                result["market_cap"] = info.get("marketCap")
                result["pe_ttm"] = info.get("trailingPE")
                result["forward_pe"] = info.get("forwardPE")
                result["beta"] = info.get("beta")
                result["fifty_two_week_high"] = info.get("fiftyTwoWeekHigh")
                result["fifty_two_week_low"] = info.get("fiftyTwoWeekLow")

                # Technicals
                hist = yf_ticker.history(period="6mo")
                if len(hist) >= 14:
                    closes = hist['Close'].values
                    deltas_arr = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                    gains = [max(d, 0) for d in deltas_arr[-14:]]
                    losses = [-min(d, 0) for d in deltas_arr[-14:]]
                    avg_gain = sum(gains) / 14
                    avg_loss = sum(losses) / 14
                    if avg_loss > 0:
                        rs = avg_gain / avg_loss
                        result["rsi"] = round(100 - (100 / (1 + rs)), 1)
                    if len(closes) >= 50:
                        result["sma50"] = round(float(closes[-50:].mean()), 2)
                    if len(closes) >= 120:
                        result["sma200"] = round(float(closes[-min(200, len(closes)):].mean()), 2)
                    if len(closes) >= 22:
                        result["perf_1m"] = round((closes[-1] / closes[-22] - 1) * 100, 2)
                    if len(closes) >= 5:
                        result["perf_1w"] = round((closes[-1] / closes[-5] - 1) * 100, 2)
                    # Max drawdown
                    if len(closes) >= 10:
                        peak = closes[0]
                        max_dd = 0
                        for c in closes:
                            if c > peak: peak = c
                            dd = (c - peak) / peak * 100
                            if dd < max_dd: max_dd = dd
                        result["max_drawdown_6m"] = round(max_dd, 2)

                # Earnings distance
                try:
                    cal = yf_ticker.calendar
                    if cal and isinstance(cal, dict):
                        ed = cal.get("Earnings Date")
                        if isinstance(ed, list) and ed:
                            d = ed[0]
                            if hasattr(d, 'date'): d = d.date()
                            result["days_to_earnings"] = max(0, (d - date.today()).days)
                except Exception:
                    pass

                # News + FinBERT
                try:
                    news = _fetch_yahoo_news(ticker)
                    if news:
                        sentiment = score_news_for_ticker(news)
                        if sentiment and sentiment.get("aggregate"):
                            agg = sentiment["aggregate"]
                            result["news_sentiment"] = agg["sentiment"]
                            result["news_score"] = agg["avg_score"]
                            result["top_news"] = [
                                {"headline": a.get("headline", a.get("title", "")), "score": a["score"]}
                                for a in (sentiment.get("articles") or [])[:3]
                            ]
                except Exception:
                    pass

            except Exception as e:
                result["error"] = str(e)
            return result

        # Parallel fetch
        with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as pool:
            ticker_data_list = list(pool.map(_fetch_ticker_data, tickers))

        ticker_data_map = {d["ticker"]: d for d in ticker_data_list}

        # Build portfolio summary for AI
        total_bp_used = sum(t.effective_bp for t in open_trades)
        utilization = (total_bp_used / total_capital * 100) if total_capital > 0 else 0

        # Sector concentration
        sector_bp = {}
        for t in open_trades:
            sec = t.sector or "Unknown"
            sector_bp[sec] = sector_bp.get(sec, 0) + (t.effective_bp)

        # Build per-position detail text
        positions_text = ""
        for t in open_trades:
            td = ticker_data_map.get(t.ticker, {})
            dte = (t.expiry - date.today()).days if t.expiry else None
            current_price = td.get("price")

            # Distance from strike
            strike_dist = None
            if current_price and t.strike:
                strike_dist = round((current_price - t.strike) / current_price * 100, 2)

            positions_text += f"""
### {t.ticker} — {td.get('name', '')} [{t.strategy}]
  开仓日期: {t.trade_date_open} | 到期日: {t.expiry} | 剩余DTE: {dte}天
  行权价: ${t.strike} | 权利金: ${t.premium_received} | 合约数: {t.contracts}
  入场价格: ${t.underlying_price_open} | 当前价格: ${current_price or 'N/A'}
  距行权价: {strike_dist or 'N/A'}% | 占用资金: ${(t.effective_bp):,.0f}
  最大利润: ${t.max_profit:,.0f} | 盈亏平衡: ${t.breakeven:.2f}
  入场IV: {t.iv_at_entry or 'N/A'} | 入场Delta: {t.delta_at_entry or 'N/A'} | 入场VIX: {t.vix_at_entry or 'N/A'}
  板块: {t.sector or td.get('sector', '')} | Beta: {td.get('beta', 'N/A')}
  RSI: {td.get('rsi', 'N/A')} | SMA50: ${td.get('sma50', 'N/A')} | SMA200: ${td.get('sma200', 'N/A')}
  1周表现: {td.get('perf_1w', 'N/A')}% | 1月表现: {td.get('perf_1m', 'N/A')}%
  6月最大回撤: {td.get('max_drawdown_6m', 'N/A')}%
  距财报: {td.get('days_to_earnings', '未知')}天
  新闻情绪: {td.get('news_sentiment', 'N/A')} ({td.get('news_score', 'N/A')})
"""
            if td.get("top_news"):
                for n in td["top_news"]:
                    positions_text += f"    [{n['score']:+.2f}] {n['headline']}\n"

        # Sector exposure text
        sector_text = "\n".join(f"  {sec}: ${bp:,.0f} ({bp/total_capital*100:.1f}%)" for sec, bp in sorted(sector_bp.items(), key=lambda x: -x[1]))

        prompt = f"""你是一位资深的期权投资组合管理顾问。请用中文对以下持仓进行全面深度分析，并给出具体建议。

## 投资组合概览
- 总资金: ${total_capital:,.0f}
- 已部署资金: ${total_bp_used:,.0f} ({utilization:.1f}%)
- 可用资金: ${total_capital - total_bp_used:,.0f}
- 持仓数量: {len(open_trades)}个

## 板块集中度
{sector_text}

## 当前市场环境
{vix_ai_summary if vix_ai_summary else '(VIX数据未获取)'}

## 3-Tier深度分析结论（最新一次市场分析的结果，请参考）
{tier_context if tier_context else '(暂无3-Tier分析数据)'}

## 每个持仓详情
{positions_text}

## 分析要求

**重要：你的板块调仓建议必须与上面的3-Tier分析结论保持一致。**
- 如果3-Tier分析没有推荐某个板块（如医疗、消费等），则**不要**在调仓建议中推荐买入该板块
- 只推荐3-Tier Tier 2中评级为STRONG_BUY或BUY的板块
- 如果3-Tier分析推荐回避某些板块，你也应该建议减少这些板块的暴露
- 如果没有3-Tier数据，则根据当前市场环境给出通用建议

### 一、逐个持仓分析（对每个持仓给出）：
1. **当前状态判定**: 盈利中/亏损中/临近盈亏平衡
2. **风险评估**: 当前价格距离行权价的安全边际，距财报天数风险
3. **操作建议**: 继续持有/提前平仓锁利/止损平仓/滚仓（roll）
4. **理由**: 2-3句说明为什么这么做
5. **风险等级**: 低/中/高/极高

### 二、投资组合整体分析：
1. **集中度风险** — 板块、个股是否过度集中
2. **相关性风险** — 持仓之间是否高度相关（如全是科技股）
3. **宏观暴露** — VIX环境下的整体风险敞口
4. **资金使用效率** — 资金利用率是否合理
5. **最大亏损估算** — 如果市场暴跌10%，估算整个组合可能的最大损失

### 三、操作建议：
- 整体仓位应该加仓还是减仓
- 具体哪几个持仓需要立即行动
- 是否需要对冲（如买入SPY PUT）
- 是否需要减少某些板块的暴露

请严格按以下JSON格式返回：
{{
  "portfolio_summary": {{
    "overall_risk": "低/中/高/极高",
    "overall_health": "健康/一般/需关注/危险",
    "capital_efficiency": "高/中/低",
    "key_concerns": ["关注点1", "关注点2", "关注点3"],
    "max_loss_scenario": "如果市场暴跌10%，预计最大亏损$xxx，占总资金x%"
  }},
  "positions": [
    {{
      "ticker": "AAPL",
      "status": "盈利中/亏损中/临近盈亏平衡",
      "safety_margin": "当前价格距行权价xx%",
      "risk_level": "低/中/高/极高",
      "action": "继续持有/提前平仓/止损平仓/滚仓",
      "reasoning": "2-3句中文理由",
      "urgency": "立即/本周/可以等待",
      "profit_potential": "预计还能获得$xxx收益 / 应止损减少损失$xxx"
    }}
  ],
  "recommendations": [
    "建议1：具体操作建议",
    "建议2：具体操作建议",
    "建议3：具体操作建议"
  ],
  "hedge_suggestion": "对冲建议（如果需要）",
  "sector_advice": "板块调仓建议"
}}"""

        ai_result = _call_claude(prompt, max_tokens=8000)

        return {
            "analysis": ai_result,
            "portfolio_stats": {
                "total_capital": total_capital,
                "capital_deployed": total_bp_used,
                "utilization_pct": round(utilization, 1),
                "open_count": len(open_trades),
                "sector_exposure": sector_bp,
            },
            "ticker_data": {k: {kk: vv for kk, vv in v.items() if kk != "error"} for k, v in ticker_data_map.items()},
            "vix_regime": {
                "regime": vix_regime.get("regime") if vix_regime else None,
                "direction": vix_regime.get("direction") if vix_regime else None,
                "position_size_pct": vix_regime.get("position_size_pct") if vix_regime else None,
            } if vix_regime else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Portfolio deep analysis failed: {e}", exc_info=True)
        return {"error": str(e)}
