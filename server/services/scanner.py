"""
Trade Suggestion Engine
Scans the approved universe, analyzes market conditions, and recommends
specific trades based on strategy rules, portfolio state, and regime.

Supports multiple strategies:
- CSP (Cash-Secured Put) — bullish/neutral markets
- PUT_SPREAD (Bull Put Credit Spread) — cautious/high vol markets
- BEAR_CALL_SPREAD (Bear Call Credit Spread) — bearish markets
- BEAR_PUT_DEBIT (Bear Put Debit Spread) — strongly bearish, directional
- PROTECTIVE_PUT — hedge existing positions
"""
from __future__ import annotations

import json
import os
import math
from datetime import datetime, date, timedelta
from typing import Optional

import yfinance as yf

from server.models import SessionLocal, Trade, TickerInfo, PortfolioSnapshot
from server.services.regime import classify_regime, detect_market_trend, get_regime_position_limits

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_market_context() -> dict:
    """Fetch current market conditions: VIX, SPY, QQQ, trend, regime."""
    try:
        tickers = yf.Tickers("^VIX SPY QQQ")

        vix_data = tickers.tickers["^VIX"].history(period="5d")
        spy_data = tickers.tickers["SPY"].history(period="60d")
        qqq_data = tickers.tickers["QQQ"].history(period="60d")

        vix = float(vix_data["Close"].iloc[-1]) if not vix_data.empty else None
        spy_price = float(spy_data["Close"].iloc[-1]) if not spy_data.empty else None
        qqq_price = float(qqq_data["Close"].iloc[-1]) if not qqq_data.empty else None

        spy_prices = [float(p) for p in spy_data["Close"].tolist()] if not spy_data.empty else []
        trend = detect_market_trend(spy_prices, lookback=20)

        spy_sma20 = sum(spy_prices[-20:]) / 20 if len(spy_prices) >= 20 else None
        spy_sma50 = sum(spy_prices[-50:]) / 50 if len(spy_prices) >= 50 else None
        spy_20d_high = max(spy_prices[-20:]) if len(spy_prices) >= 20 else None
        spy_20d_low = min(spy_prices[-20:]) if len(spy_prices) >= 20 else None

        # SPY % from 20d high (to measure how oversold)
        spy_from_high_pct = ((spy_price - spy_20d_high) / spy_20d_high * 100) if spy_price and spy_20d_high else 0

        qqq_prices = [float(p) for p in qqq_data["Close"].tolist()] if not qqq_data.empty else []
        qqq_sma20 = sum(qqq_prices[-20:]) / 20 if len(qqq_prices) >= 20 else None

        vix_prices = [float(p) for p in vix_data["Close"].tolist()] if not vix_data.empty else []
        vix_5d_ago = vix_prices[0] if len(vix_prices) >= 5 else vix
        vix_trend = "RISING" if vix and vix_5d_ago and vix > vix_5d_ago * 1.05 else \
                    "FALLING" if vix and vix_5d_ago and vix < vix_5d_ago * 0.95 else "STABLE"

        regime = classify_regime(vix, trend) if vix else "SLIGHT_FEAR"

        return {
            "vix": round(vix, 2) if vix else None,
            "vix_trend": vix_trend,
            "spy_price": round(spy_price, 2) if spy_price else None,
            "spy_sma20": round(spy_sma20, 2) if spy_sma20 else None,
            "spy_sma50": round(spy_sma50, 2) if spy_sma50 else None,
            "spy_20d_high": round(spy_20d_high, 2) if spy_20d_high else None,
            "spy_20d_low": round(spy_20d_low, 2) if spy_20d_low else None,
            "spy_from_high_pct": round(spy_from_high_pct, 2),
            "spy_trend": trend,
            "spy_above_sma20": spy_price > spy_sma20 if spy_price and spy_sma20 else None,
            "spy_above_sma50": spy_price > spy_sma50 if spy_price and spy_sma50 else None,
            "qqq_price": round(qqq_price, 2) if qqq_price else None,
            "qqq_sma20": round(qqq_sma20, 2) if qqq_sma20 else None,
            "qqq_above_sma20": qqq_price > qqq_sma20 if qqq_price and qqq_sma20 else None,
            "regime": regime,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_portfolio_state(db) -> dict:
    """Get current portfolio state for position sizing and sector limits."""
    open_trades = db.query(Trade).filter(Trade.status == "OPEN", Trade.strategy != "OTHER").all()

    latest_snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).first()
    total_capital = latest_snap.total_capital if latest_snap else 220000

    capital_deployed = sum(t.effective_bp for t in open_trades)
    capital_available = total_capital - capital_deployed

    sector_counts = {}
    sector_exposure = {}
    for t in open_trades:
        sector_counts[t.sector] = sector_counts.get(t.sector, 0) + 1
        sector_exposure[t.sector] = sector_exposure.get(t.sector, 0) + (t.effective_bp)

    open_tickers = set(t.ticker for t in open_trades)

    return {
        "total_capital": total_capital,
        "capital_deployed": capital_deployed,
        "capital_available": capital_available,
        "utilization_pct": round(capital_deployed / total_capital * 100, 1) if total_capital else 0,
        "open_positions": len(open_trades),
        "sector_counts": sector_counts,
        "sector_exposure": sector_exposure,
        "open_tickers": list(open_tickers),
        "open_trades": [{
            "ticker": t.ticker, "strike": t.strike, "expiry": str(t.expiry),
            "strategy": t.strategy, "premium_received": t.premium_received or 0,
            "contracts": t.contracts or 1, "sector": t.sector,
            "buying_power_used": t.effective_bp,
        } for t in open_trades],
    }


def _find_best_expiry(expirations, dte_range, target_dte, today):
    """Find the best expiry date within a DTE range."""
    best_expiry = None
    best_dte = None
    for exp_str in expirations:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        if dte_range[0] <= dte <= dte_range[1]:
            if best_dte is None or abs(dte - target_dte) < abs(best_dte - target_dte):
                best_expiry = exp_str
                best_dte = dte
    # Fallback to wider range
    if not best_expiry:
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if 21 <= dte <= 60:
                if best_dte is None or abs(dte - target_dte) < abs(best_dte - target_dte):
                    best_expiry = exp_str
                    best_dte = dte
    return best_expiry, best_dte


def _estimate_delta(current_price, strike, iv, option_type="put"):
    """Estimate delta from strike distance and IV."""
    if option_type == "put":
        otm_pct = (current_price - strike) / current_price
    else:  # call
        otm_pct = (strike - current_price) / current_price
    iv_factor = max(iv / 30, 0.5)
    return -max(0.01, 0.5 * math.exp(-3.5 * otm_pct / iv_factor))


def scan_ticker_csp(ticker, sector, current_price, chain_puts, best_expiry, best_dte,
                    config, market, portfolio, regime_limits):
    """Scan for Cash-Secured Put opportunities."""
    entry_rules = config.get("entry_rules", {})
    delta_range = regime_limits.get("delta_range", entry_rules.get("delta_range", [-0.25, -0.15]))

    candidates = []
    for _, row in chain_puts.iterrows():
        strike = float(row["strike"])
        bid = float(row.get("bid", 0) or 0)
        ask = float(row.get("ask", 0) or 0)
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(row.get("lastPrice", 0) or 0)
        iv = float(row.get("impliedVolatility", 0) or 0) * 100
        volume = int(row.get("volume", 0) or 0)
        oi = int(row.get("openInterest", 0) or 0)

        if mid <= 0 or strike <= 0:
            continue

        estimated_delta = _estimate_delta(current_price, strike, iv, "put")
        if not (delta_range[0] <= estimated_delta <= delta_range[1]):
            continue

        buying_power = strike * 100
        position_pct = (buying_power / portfolio["total_capital"] * 100) if portfolio["total_capital"] else 0
        max_position_pct = entry_rules.get("max_position_size_pct_csp", 10)

        if position_pct > max_position_pct or buying_power > portfolio["capital_available"]:
            continue

        premium_return = mid / strike * 100
        annual_return = premium_return / best_dte * 365 if best_dte > 0 else 0
        breakeven = strike - mid
        breakeven_distance_pct = (current_price - breakeven) / current_price * 100

        score = min(annual_return, 30) * 2 + breakeven_distance_pct * 3 + min(iv, 60) * 0.5
        if oi > 100: score += 5
        if volume > 50: score += 5
        spread_pct = (ask - bid) / mid * 100 if mid > 0 and ask > bid else 0
        score -= min(spread_pct, 20) * 0.5

        candidates.append({
            "strategy": "CSP",
            "strategy_label": "Cash-Secured Put",
            "direction": "SELL",
            "ticker": ticker, "sector": sector,
            "current_price": round(current_price, 2),
            "strike": strike, "strike_long": None,
            "expiry": best_expiry, "dte": best_dte,
            "premium": round(mid, 2), "bid": round(bid, 2), "ask": round(ask, 2),
            "iv": round(iv, 1), "estimated_delta": round(estimated_delta, 3),
            "buying_power": round(buying_power, 0),
            "position_pct": round(position_pct, 1),
            "return_on_capital": round(premium_return, 2),
            "annualized_return": round(annual_return, 1),
            "breakeven": round(breakeven, 2),
            "breakeven_distance_pct": round(breakeven_distance_pct, 1),
            "max_profit": round(mid * 100, 0),
            "max_loss": round((strike - mid) * 100, 0),
            "open_interest": oi, "volume": volume,
            "score": round(score, 1),
        })

    if not candidates:
        return None
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[0]


def scan_ticker_put_spread(ticker, sector, current_price, chain_puts, best_expiry, best_dte,
                           config, market, portfolio):
    """
    Scan for Bull Put Credit Spread (sell higher put, buy lower put).
    Used in high vol / cautious markets — defined risk, lower BP requirement.
    """
    candidates = []

    put_rows = []
    for _, row in chain_puts.iterrows():
        strike = float(row["strike"])
        bid = float(row.get("bid", 0) or 0)
        ask = float(row.get("ask", 0) or 0)
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(row.get("lastPrice", 0) or 0)
        iv = float(row.get("impliedVolatility", 0) or 0) * 100
        oi = int(row.get("openInterest", 0) or 0)
        volume = int(row.get("volume", 0) or 0)
        if strike > 0 and mid > 0:
            put_rows.append({"strike": strike, "bid": bid, "ask": ask, "mid": mid, "iv": iv, "oi": oi, "volume": volume})

    put_rows.sort(key=lambda x: x["strike"], reverse=True)

    # Look for OTM put spreads: sell the higher strike, buy the lower
    for i, short_put in enumerate(put_rows):
        otm_pct = (current_price - short_put["strike"]) / current_price
        if otm_pct < 0.05 or otm_pct > 0.20:  # 5-20% OTM for short leg
            continue

        # Find long leg: $5 or $10 wide spread
        for width in [5, 10, 2.5]:
            target_long_strike = short_put["strike"] - width
            long_put = None
            for p in put_rows:
                if abs(p["strike"] - target_long_strike) < 1.0 and p["strike"] < short_put["strike"]:
                    long_put = p
                    break

            if not long_put:
                continue

            net_credit = short_put["bid"] - long_put["ask"]
            if net_credit <= 0.10:
                continue

            spread_width = short_put["strike"] - long_put["strike"]
            max_loss_per_contract = (spread_width - net_credit) * 100
            max_profit_per_contract = net_credit * 100
            buying_power = spread_width * 100  # Max loss = BP required

            if max_loss_per_contract <= 0:
                continue

            position_pct = (buying_power / portfolio["total_capital"] * 100) if portfolio["total_capital"] else 0
            max_spread_pct = entry_rules.get("max_position_size_pct_spread", 5)
            if position_pct > max_spread_pct or buying_power > portfolio["capital_available"]:
                continue

            premium_return = net_credit / spread_width * 100
            annual_return = premium_return / best_dte * 365 if best_dte > 0 else 0
            breakeven = short_put["strike"] - net_credit
            breakeven_distance_pct = (current_price - breakeven) / current_price * 100
            risk_reward = max_profit_per_contract / max_loss_per_contract if max_loss_per_contract > 0 else 0

            score = min(annual_return, 40) * 1.5 + breakeven_distance_pct * 3 + risk_reward * 20
            if short_put["oi"] > 100 and long_put["oi"] > 100: score += 10
            score += min(short_put["iv"], 60) * 0.3

            candidates.append({
                "strategy": "PUT_SPREAD",
                "strategy_label": "Bull Put Credit Spread",
                "direction": "SELL",
                "ticker": ticker, "sector": sector,
                "current_price": round(current_price, 2),
                "strike": short_put["strike"],
                "strike_long": long_put["strike"],
                "expiry": best_expiry, "dte": best_dte,
                "premium": round(net_credit, 2),
                "bid": round(short_put["bid"], 2), "ask": round(long_put["ask"], 2),
                "iv": round(short_put["iv"], 1),
                "estimated_delta": round(_estimate_delta(current_price, short_put["strike"], short_put["iv"]), 3),
                "buying_power": round(buying_power, 0),
                "position_pct": round(position_pct, 1),
                "return_on_capital": round(premium_return, 2),
                "annualized_return": round(annual_return, 1),
                "breakeven": round(breakeven, 2),
                "breakeven_distance_pct": round(breakeven_distance_pct, 1),
                "max_profit": round(max_profit_per_contract, 0),
                "max_loss": round(max_loss_per_contract, 0),
                "spread_width": spread_width,
                "risk_reward": round(risk_reward, 2),
                "open_interest": short_put["oi"], "volume": short_put["volume"],
                "score": round(score, 1),
            })
            break  # One spread per short strike

    if not candidates:
        return None
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[0]


def scan_ticker_bear_call_spread(ticker, sector, current_price, chain_calls, best_expiry, best_dte,
                                 config, market, portfolio):
    """
    Scan for Bear Call Credit Spread (sell lower call, buy higher call).
    Profits when stock stays flat or goes down. Good for bearish markets.
    """
    candidates = []

    call_rows = []
    for _, row in chain_calls.iterrows():
        strike = float(row["strike"])
        bid = float(row.get("bid", 0) or 0)
        ask = float(row.get("ask", 0) or 0)
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else float(row.get("lastPrice", 0) or 0)
        iv = float(row.get("impliedVolatility", 0) or 0) * 100
        oi = int(row.get("openInterest", 0) or 0)
        volume = int(row.get("volume", 0) or 0)
        if strike > 0 and mid > 0:
            call_rows.append({"strike": strike, "bid": bid, "ask": ask, "mid": mid, "iv": iv, "oi": oi, "volume": volume})

    call_rows.sort(key=lambda x: x["strike"])

    for short_call in call_rows:
        otm_pct = (short_call["strike"] - current_price) / current_price
        if otm_pct < 0.03 or otm_pct > 0.15:  # 3-15% OTM
            continue

        for width in [5, 10, 2.5]:
            target_long_strike = short_call["strike"] + width
            long_call = None
            for c in call_rows:
                if abs(c["strike"] - target_long_strike) < 1.0 and c["strike"] > short_call["strike"]:
                    long_call = c
                    break

            if not long_call:
                continue

            net_credit = short_call["bid"] - long_call["ask"]
            if net_credit <= 0.10:
                continue

            spread_width = long_call["strike"] - short_call["strike"]
            max_loss_per_contract = (spread_width - net_credit) * 100
            max_profit_per_contract = net_credit * 100
            buying_power = spread_width * 100

            if max_loss_per_contract <= 0:
                continue

            position_pct = (buying_power / portfolio["total_capital"] * 100) if portfolio["total_capital"] else 0
            max_spread_pct = entry_rules.get("max_position_size_pct_spread", 5)
            if position_pct > max_spread_pct or buying_power > portfolio["capital_available"]:
                continue

            premium_return = net_credit / spread_width * 100
            annual_return = premium_return / best_dte * 365 if best_dte > 0 else 0
            breakeven = short_call["strike"] + net_credit
            breakeven_distance_pct = (breakeven - current_price) / current_price * 100
            risk_reward = max_profit_per_contract / max_loss_per_contract if max_loss_per_contract > 0 else 0

            score = min(annual_return, 40) * 1.5 + breakeven_distance_pct * 4 + risk_reward * 20
            if short_call["oi"] > 100 and long_call["oi"] > 100: score += 10
            score += min(short_call["iv"], 60) * 0.3
            # Bonus in bearish regime
            if market.get("spy_trend") == "DOWN": score += 15
            if not market.get("spy_above_sma20"): score += 10

            candidates.append({
                "strategy": "BEAR_CALL_SPREAD",
                "strategy_label": "Bear Call Credit Spread",
                "direction": "SELL",
                "ticker": ticker, "sector": sector,
                "current_price": round(current_price, 2),
                "strike": short_call["strike"],
                "strike_long": long_call["strike"],
                "expiry": best_expiry, "dte": best_dte,
                "premium": round(net_credit, 2),
                "bid": round(short_call["bid"], 2), "ask": round(long_call["ask"], 2),
                "iv": round(short_call["iv"], 1),
                "estimated_delta": round(-_estimate_delta(current_price, short_call["strike"], short_call["iv"], "call"), 3),
                "buying_power": round(buying_power, 0),
                "position_pct": round(position_pct, 1),
                "return_on_capital": round(premium_return, 2),
                "annualized_return": round(annual_return, 1),
                "breakeven": round(breakeven, 2),
                "breakeven_distance_pct": round(breakeven_distance_pct, 1),
                "max_profit": round(max_profit_per_contract, 0),
                "max_loss": round(max_loss_per_contract, 0),
                "spread_width": spread_width,
                "risk_reward": round(risk_reward, 2),
                "open_interest": short_call["oi"], "volume": short_call["volume"],
                "score": round(score, 1),
            })
            break

    if not candidates:
        return None
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[0]


def scan_ticker_all_strategies(ticker, sector, config, market, portfolio):
    """
    Scan a single ticker across all applicable strategies based on regime.
    Returns list of suggestions (one per strategy type that has a candidate).
    """
    entry_rules = config.get("entry_rules", {})
    regime = market.get("regime", "SLIGHT_FEAR")
    regime_limits = get_regime_position_limits(regime, config)

    # Pre-checks
    max_per_sector = entry_rules.get("max_positions_per_sector", 2)
    if portfolio["sector_counts"].get(sector, 0) >= max_per_sector:
        return []

    max_sector_pct = entry_rules.get("max_sector_exposure_pct", 20)
    current_sector_pct = (portfolio["sector_exposure"].get(sector, 0) / portfolio["total_capital"] * 100) if portfolio["total_capital"] else 0
    if current_sector_pct >= max_sector_pct:
        return []

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return []
        current_price = float(hist["Close"].iloc[-1])

        expirations = stock.options
        if not expirations:
            return []

        target_dte = entry_rules.get("target_dte", 35)
        dte_range = entry_rules.get("dte_range", [30, 45])
        today = date.today()

        best_expiry, best_dte = _find_best_expiry(expirations, dte_range, target_dte, today)
        if not best_expiry:
            return []

        chain = stock.option_chain(best_expiry)
        results = []

        # Decide which strategies to scan based on regime
        is_bearish = regime in ("VERY_FEARFUL", "EXTREME_FEAR") or market.get("spy_trend") == "DOWN"
        is_high_vol = regime in ("FEAR", "VERY_FEARFUL", "EXTREME_FEAR")
        is_crisis = regime == "EXTREME_FEAR"

        # Skip CSPs for tickers already held, but allow spreads on held tickers
        skip_csp = ticker in portfolio["open_tickers"]

        # 1. CSP — only in favorable/neutral, and not already holding
        if not is_crisis and not skip_csp:
            total_open = portfolio["open_positions"]
            if total_open < regime_limits["max_positions"]:
                csp = scan_ticker_csp(ticker, sector, current_price, chain.puts,
                                      best_expiry, best_dte, config, market, portfolio, regime_limits)
                if csp:
                    if is_high_vol:
                        csp["score"] *= 0.6  # Penalize naked CSP in high vol
                        csp["warning"] = "High vol regime — consider the PUT_SPREAD alternative below"
                    results.append(csp)

        # 2. Bull Put Credit Spread — good in all regimes, preferred in high vol
        if not chain.puts.empty:
            spread = scan_ticker_put_spread(ticker, sector, current_price, chain.puts,
                                           best_expiry, best_dte, config, market, portfolio)
            if spread:
                if is_high_vol:
                    spread["score"] *= 1.3  # Boost spreads in high vol
                results.append(spread)

        # 3. Bear Call Credit Spread — bearish directional, profits from decline
        if is_bearish and not chain.calls.empty:
            bear_call = scan_ticker_bear_call_spread(ticker, sector, current_price, chain.calls,
                                                     best_expiry, best_dte, config, market, portfolio)
            if bear_call:
                if is_crisis:
                    bear_call["score"] *= 1.4  # Extra boost in crisis
                results.append(bear_call)

        return results

    except Exception:
        return []


def generate_suggestions(db=None) -> dict:
    """
    Main entry point: scan the universe and generate trade suggestions.
    Returns market analysis + ranked list of trade ideas.
    """
    config = load_config()

    market = get_market_context()
    if "error" in market:
        return {"error": market["error"], "suggestions": [], "market": market}

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        portfolio = get_portfolio_state(db)

        regime = market.get("regime", "SLIGHT_FEAR")
        regime_limits = get_regime_position_limits(regime, config)

        assessment = _generate_assessment(market, portfolio, regime, regime_limits, config)

        # Check cash limits
        min_cash_pct = regime_limits.get("min_cash_pct", 20)
        current_cash_pct = 100 - portfolio["utilization_pct"]
        if current_cash_pct < min_cash_pct:
            return {
                "market": market,
                "portfolio": portfolio,
                "assessment": assessment,
                "suggestions": [],
                "reason": f"Cash level ({current_cash_pct:.1f}%) below regime minimum ({min_cash_pct}%). No new trades recommended.",
            }

        # Scan the universe — all strategies
        universe = db.query(TickerInfo).all()
        all_suggestions = []
        skip_tickers = {"METD", "ETHA", "IBIT"}

        for ti in universe:
            if ti.ticker in skip_tickers:
                continue
            results = scan_ticker_all_strategies(ti.ticker, ti.sector, config, market, portfolio)
            all_suggestions.extend(results)

        # Add hedge suggestions for open positions in bearish regime
        if market.get("spy_trend") == "DOWN" or regime in ("VERY_FEARFUL", "EXTREME_FEAR"):
            hedge_suggestions = _generate_hedge_suggestions(portfolio, market)
            all_suggestions.extend(hedge_suggestions)

        # Rank by score
        all_suggestions.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate: max 1 suggestion per ticker (keep highest score)
        # But allow multiple strategy types
        seen = set()
        deduped = []
        for s in all_suggestions:
            key = f"{s['ticker']}_{s['strategy']}"
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        top_suggestions = deduped[:8]

        for s in top_suggestions:
            s["rationale"] = _generate_rationale(s, market, portfolio, regime)

        return {
            "market": market,
            "portfolio": portfolio,
            "assessment": assessment,
            "suggestions": top_suggestions,
            "total_scanned": len(universe),
            "total_candidates": len(all_suggestions),
        }

    finally:
        if close_db:
            db.close()


def _generate_hedge_suggestions(portfolio, market):
    """
    Generate smart hedge suggestions for open positions during bearish markets.
    Fetches live option pricing to calculate actual P&L and gives specific instructions.
    """
    suggestions = []
    today = date.today()

    for trade in portfolio.get("open_trades", []):
        if trade["strategy"] not in ("CSP", "PUT_SPREAD"):
            continue

        ticker = trade["ticker"]
        strike = trade["strike"]
        exp_str = trade["expiry"]
        premium_received = trade.get("premium_received", 0)
        contracts = trade.get("contracts", 1)

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            if hist.empty:
                continue
            current_price = float(hist["Close"].iloc[-1])

            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days

            # Fetch current option price
            current_mid = 0
            current_bid = 0
            current_ask = 0
            try:
                chain = stock.option_chain(exp_str)
                match = chain.puts[chain.puts["strike"] == strike]
                if not match.empty:
                    row = match.iloc[0]
                    current_bid = float(row.get("bid", 0) or 0)
                    current_ask = float(row.get("ask", 0) or 0)
                    current_mid = (current_bid + current_ask) / 2 if current_bid > 0 else float(row.get("lastPrice", 0) or 0)
            except Exception:
                pass

            # Calculate P&L
            pnl_per_contract = (premium_received - current_mid) * 100 if current_mid > 0 else 0
            total_pnl = pnl_per_contract * contracts
            loss_pct = ((current_mid - premium_received) / premium_received * 100) if premium_received > 0 and current_mid > 0 else 0

            # Moneyness
            otm_pct = ((current_price - strike) / current_price * 100) if current_price > 0 else 0
            breakeven = strike - premium_received
            breakeven_distance = ((current_price - breakeven) / current_price * 100) if current_price > 0 else 0

            # Determine risk level and action
            if loss_pct >= 100:
                # Hit 2x stop loss — put value has tripled
                risk_level = "CRITICAL"
                score = 90
                action_label = "CLOSE NOW"
                action_color = "red"
                instructions = [
                    f"Position has hit 2x stop loss ({loss_pct:.0f}% loss on premium).",
                    f"BUY TO CLOSE {contracts}x {ticker} ${strike}P at ~${current_mid:.2f} (cost: ~${current_mid * 100 * contracts:,.0f}).",
                    f"Realized loss: ~${abs(total_pnl):,.0f}.",
                    f"Do not hold — further downside risk is unlimited on naked CSP.",
                    f"Lesson: consider spreads next time for capped downside.",
                ]
            elif loss_pct >= 50:
                # Approaching stop loss — put value has doubled
                risk_level = "DANGER"
                score = 70
                action_label = "ROLL DOWN & OUT"
                action_color = "orange"

                # Find roll targets
                roll_instructions = _find_roll_targets(stock, ticker, strike, exp_str,
                                                        current_mid, current_price, dte, contracts)
                instructions = [
                    f"Position at {loss_pct:.0f}% loss — approaching stop loss threshold.",
                    f"Current: sold at ${premium_received:.2f}, now worth ${current_mid:.2f} (unrealized: ${total_pnl:,.0f}).",
                    f"Stock ${current_price:.2f} is {otm_pct:.1f}% above your ${strike} strike.",
                ]
                instructions.extend(roll_instructions)
            elif loss_pct >= 20 or otm_pct < 5:
                # Warning zone
                risk_level = "WARNING"
                score = 40
                action_label = "MONITOR CLOSELY"
                action_color = "yellow"
                instructions = [
                    f"Position under pressure: {loss_pct:.0f}% loss on premium, {otm_pct:.1f}% OTM.",
                    f"Current: sold ${premium_received:.2f}, now ${current_mid:.2f} (unrealized: ${total_pnl:,.0f}).",
                    f"Breakeven ${breakeven:.2f} ({breakeven_distance:.1f}% cushion remaining).",
                    f"Set alert: close if loss exceeds 100% (put reaches ~${premium_received * 2:.2f}).",
                    f"DTE: {dte} days — time decay accelerates in final 30 days." if dte > 30 else f"DTE: {dte} days — close to expiry, monitor daily.",
                ]
            else:
                # Position is fine, only show in bearish regime as a gentle reminder
                risk_level = "OK"
                score = 15
                action_label = "HOLD"
                action_color = "green"
                instructions = [
                    f"Position is healthy: {otm_pct:.1f}% OTM, {breakeven_distance:.1f}% to breakeven.",
                    f"Unrealized P&L: ${total_pnl:,.0f} ({dte} DTE remaining).",
                    f"No action needed — time decay working in your favor.",
                ]

            suggestions.append({
                "strategy": "HEDGE",
                "strategy_label": action_label,
                "direction": "BUY",
                "ticker": ticker,
                "sector": trade.get("sector", ""),
                "current_price": round(current_price, 2),
                "strike": strike,
                "strike_long": None,
                "expiry": exp_str,
                "dte": dte,
                "premium": round(current_mid, 2),
                "premium_received": round(premium_received, 2),
                "bid": round(current_bid, 2),
                "ask": round(current_ask, 2),
                "iv": 0,
                "estimated_delta": 0,
                "buying_power": trade.get("buying_power_used", 0),
                "position_pct": 0,
                "return_on_capital": 0,
                "annualized_return": 0,
                "breakeven": round(breakeven, 2),
                "breakeven_distance_pct": round(breakeven_distance, 1),
                "max_profit": round(premium_received * 100 * contracts, 0),
                "max_loss": round((strike - premium_received) * 100 * contracts, 0),
                "open_interest": 0,
                "volume": 0,
                "score": score,
                "risk_level": risk_level,
                "action_color": action_color,
                "loss_pct": round(loss_pct, 1),
                "unrealized_pnl": round(total_pnl, 0),
                "contracts": contracts,
                "instructions": instructions,
                "warning": instructions[0] if instructions else "",
            })

        except Exception:
            continue

    return suggestions


def _find_roll_targets(stock, ticker, current_strike, current_expiry, current_mid,
                       current_price, current_dte, contracts):
    """Find concrete roll-down-and-out targets with actual pricing."""
    instructions = []

    try:
        expirations = stock.options
        today = date.today()

        # Look for expiry 30-60 days further out than current
        current_exp_date = datetime.strptime(current_expiry, "%Y-%m-%d").date()
        target_exp_date = current_exp_date + timedelta(days=30)

        best_roll_expiry = None
        best_roll_dte = None
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            days_out = (exp_date - today).days
            # Want 30-60 days MORE than current expiry, or at least 45+ DTE total
            if days_out >= current_dte + 25 and days_out <= current_dte + 75:
                if best_roll_dte is None or abs(days_out - (current_dte + 35)) < abs(best_roll_dte - (current_dte + 35)):
                    best_roll_expiry = exp_str
                    best_roll_dte = days_out

        if not best_roll_expiry:
            instructions.append(f"Option A: BUY TO CLOSE at ~${current_mid:.2f} (cost: ~${current_mid * 100 * contracts:,.0f}).")
            instructions.append(f"No suitable roll expiry found — consider closing outright.")
            return instructions

        # Fetch the roll target chain
        roll_chain = stock.option_chain(best_roll_expiry)
        roll_puts = roll_chain.puts

        # Target: roll down 5-10% lower strike
        target_strikes = [
            current_strike - 5,
            current_strike - 10,
            current_strike * 0.95,  # 5% lower
            current_strike * 0.90,  # 10% lower
        ]

        roll_options = []
        for target in target_strikes:
            # Find closest available strike
            closest = roll_puts.iloc[(roll_puts["strike"] - target).abs().argsort()[:1]]
            if closest.empty:
                continue
            row = closest.iloc[0]
            new_strike = float(row["strike"])
            if new_strike >= current_strike:
                continue  # Must be lower

            new_bid = float(row.get("bid", 0) or 0)
            if new_bid <= 0:
                continue

            net_debit = current_mid - new_bid  # Cost to close minus credit from new
            new_otm_pct = (current_price - new_strike) / current_price * 100

            # Only show if it makes sense
            if new_otm_pct < 3:  # Too close to ATM
                continue

            roll_options.append({
                "new_strike": new_strike,
                "new_expiry": best_roll_expiry,
                "new_dte": best_roll_dte,
                "new_bid": new_bid,
                "net_debit": net_debit,
                "new_otm_pct": new_otm_pct,
            })

        # Deduplicate by strike
        seen_strikes = set()
        unique_rolls = []
        for r in roll_options:
            if r["new_strike"] not in seen_strikes:
                seen_strikes.add(r["new_strike"])
                unique_rolls.append(r)

        if unique_rolls:
            instructions.append("RECOMMENDED: Roll down and out —")
            for i, r in enumerate(unique_rolls[:2]):  # Show top 2 options
                if r["net_debit"] > 0:
                    instructions.append(
                        f"  Roll {i+1}: BTC ${current_strike}P → STO ${r['new_strike']}P exp {r['new_expiry']} ({r['new_dte']} DTE) "
                        f"| New credit: ${r['new_bid']:.2f} | Net debit: ${r['net_debit']:.2f}/contract (${r['net_debit'] * 100 * contracts:,.0f} total) "
                        f"| New cushion: {r['new_otm_pct']:.1f}% OTM"
                    )
                else:
                    instructions.append(
                        f"  Roll {i+1}: BTC ${current_strike}P → STO ${r['new_strike']}P exp {r['new_expiry']} ({r['new_dte']} DTE) "
                        f"| Net credit: ${abs(r['net_debit']):.2f}/contract "
                        f"| New cushion: {r['new_otm_pct']:.1f}% OTM"
                    )
        else:
            instructions.append(f"Option A: BUY TO CLOSE at ~${current_mid:.2f} (cost: ~${current_mid * 100 * contracts:,.0f}).")
            instructions.append(f"Could not find attractive roll targets — consider closing outright.")

        instructions.append(
            f"Option B: Close outright — BTC {contracts}x ${current_strike}P at ~${current_mid:.2f} "
            f"(cost: ~${current_mid * 100 * contracts:,.0f})."
        )

    except Exception as e:
        instructions.append(f"Option A: BUY TO CLOSE at ~${current_mid:.2f} (cost: ~${current_mid * 100 * contracts:,.0f}).")
        instructions.append(f"Could not fetch roll targets — consider closing outright.")

    return instructions


def _generate_assessment(market, portfolio, regime, regime_limits, config):
    """Generate overall market assessment and trading recommendation."""
    vix = market.get("vix", 0)
    spy_above_20 = market.get("spy_above_sma20")
    spy_above_50 = market.get("spy_above_sma50")
    qqq_above_20 = market.get("qqq_above_sma20")
    vix_trend = market.get("vix_trend", "STABLE")

    signals = []
    bullish_count = 0
    bearish_count = 0

    if spy_above_20:
        signals.append(("SPY above 20-day SMA", "BULLISH"))
        bullish_count += 1
    else:
        signals.append(("SPY below 20-day SMA", "BEARISH"))
        bearish_count += 1

    if spy_above_50:
        signals.append(("SPY above 50-day SMA", "BULLISH"))
        bullish_count += 1
    else:
        signals.append(("SPY below 50-day SMA", "BEARISH"))
        bearish_count += 1

    if qqq_above_20:
        signals.append(("QQQ above 20-day SMA", "BULLISH"))
        bullish_count += 1
    else:
        signals.append(("QQQ below 20-day SMA", "BEARISH"))
        bearish_count += 1

    if vix and vix < 20:
        signals.append((f"VIX at {vix:.1f} — low volatility, favorable for CSP", "BULLISH"))
        bullish_count += 1
    elif vix and vix < 30:
        signals.append((f"VIX at {vix:.1f} — elevated, use spreads + tighter delta", "CAUTION"))
    else:
        signals.append((f"VIX at {vix:.1f} — crisis level, minimal exposure", "BEARISH"))
        bearish_count += 2

    if vix_trend == "RISING":
        signals.append(("VIX trending higher — risk increasing", "BEARISH"))
        bearish_count += 1
    elif vix_trend == "FALLING":
        signals.append(("VIX trending lower — risk decreasing", "BULLISH"))
        bullish_count += 1

    # Oversold bounce opportunity?
    spy_from_high = market.get("spy_from_high_pct", 0)
    if spy_from_high < -5:
        signals.append((f"SPY {spy_from_high:.1f}% from 20d high — possible oversold bounce", "CAUTION"))

    is_bearish = bearish_count >= 3 or regime in ("VERY_FEARFUL", "EXTREME_FEAR")

    if bearish_count >= 3 or regime == "EXTREME_FEAR":
        overall = "AGGRESSIVE_DEPLOY"
        recommendation = (
            "Extreme fear — premiums are fattest! Deploy aggressively up to 95-98% capital. "
            "Use spreads for defined risk. This is where CSP sellers make the most money. "
            "Add new cash to brokerage if available."
        )
    elif regime == "VERY_FEARFUL" or bearish_count >= 2:
        overall = "HIGH_DEPLOY"
        recommendation = (
            "Very fearful market — elevated premiums. Deploy 90-95% of capital. "
            "Prefer put spreads for defined risk + elevated premium. "
            "Tighter deltas (-0.12 to -0.20). Scale into positions."
        )
    elif regime == "FEAR":
        overall = "FAVORABLE"
        recommendation = (
            "Fear regime — great for premium selling. Deploy 85-90% of capital. "
            "Standard deltas. Mix of CSPs and spreads. Good risk/reward."
        )
    elif regime == "SLIGHT_FEAR":
        overall = "FAVORABLE"
        recommendation = (
            "Slight fear — good conditions for CSP selling. Deploy 75-80%. "
            "Standard delta range (-0.15 to -0.25). Full position sizes."
        )
    elif regime == "GREED":
        overall = "CAUTIOUS"
        recommendation = (
            "Greed regime — premiums are thinner. Deploy 60-70%. "
            "Be selective — only highest IV rank setups. Smaller position sizes."
        )
    else:  # EXTREME_GREED
        overall = "DEFENSIVE"
        recommendation = (
            "Extreme greed — VIX very low, premiums thin. Deploy only 50-55%. "
            "Keep 45-50% cash for when fear returns. Only sell CSPs on highest IV names."
        )

    # What strategies to prioritize
    if is_bearish:
        preferred_strategies = ["PUT_SPREAD", "BEAR_CALL_SPREAD", "CSP", "HEDGE"]
        strategy_note = "Fearful market: Deploy heavily! Spreads for defined risk + fat premiums. CSPs on quality names at deep OTM."
    elif regime in ("FEAR",):
        preferred_strategies = ["CSP", "PUT_SPREAD", "BEAR_CALL_SPREAD"]
        strategy_note = "Fear playbook: Deploy aggressively — CSPs and credit spreads both work well at these premium levels"
    elif regime in ("EXTREME_GREED", "GREED"):
        preferred_strategies = ["CSP"]
        strategy_note = "Low vol playbook: Be selective — thin premiums, only best setups"
    else:
        preferred_strategies = ["CSP", "PUT_SPREAD"]
        strategy_note = "Standard playbook: Cash-secured puts on quality names, spreads for larger tickers"

    slots_available = max(0, regime_limits["max_positions"] - portfolio["open_positions"])
    max_new_capital = portfolio["capital_available"] * (1 - regime_limits.get("min_cash_pct", 20) / 100)

    return {
        "overall": overall,
        "recommendation": recommendation,
        "regime": regime,
        "signals": signals,
        "slots_available": slots_available,
        "max_new_positions": min(slots_available, 3),
        "max_new_capital": round(max_new_capital, 0),
        "suggested_delta_range": regime_limits["delta_range"],
        "use_spreads": regime_limits.get("use_spreads", False),
        "preferred_strategies": preferred_strategies,
        "strategy_note": strategy_note,
    }


def _generate_rationale(suggestion, market, portfolio, regime):
    """Generate human-readable rationale for a trade suggestion."""
    s = suggestion
    parts = []

    strat = s.get("strategy", "CSP")

    if strat == "CSP":
        parts.append(f"SELL {s['ticker']} ${s['strike']}P exp {s['expiry']} ({s['dte']} DTE)")
        parts.append(f"Collect ${s['premium']:.2f} premium (${s['max_profit']:.0f} max profit)")
        parts.append(f"Breakeven ${s['breakeven']:.2f} — {s['breakeven_distance_pct']:.1f}% cushion below ${s['current_price']:.2f}")
        parts.append(f"Return: {s['return_on_capital']:.1f}% ({s['annualized_return']:.0f}% ann.) | BP: ${s['buying_power']:.0f} ({s['position_pct']:.1f}%)")

    elif strat == "PUT_SPREAD":
        parts.append(f"SELL {s['ticker']} ${s['strike']}/{s['strike_long']}P spread exp {s['expiry']} ({s['dte']} DTE)")
        parts.append(f"Credit ${s['premium']:.2f} | Max profit ${s['max_profit']:.0f} | Max loss ${s['max_loss']:.0f} | R:R {s.get('risk_reward', 0):.2f}")
        parts.append(f"Breakeven ${s['breakeven']:.2f} — {s['breakeven_distance_pct']:.1f}% cushion")
        parts.append(f"Defined risk: only ${s['buying_power']:.0f} BP required ({s['position_pct']:.1f}%)")

    elif strat == "BEAR_CALL_SPREAD":
        parts.append(f"SELL {s['ticker']} ${s['strike']}/{s['strike_long']}C bear call spread exp {s['expiry']} ({s['dte']} DTE)")
        parts.append(f"Credit ${s['premium']:.2f} | Max profit ${s['max_profit']:.0f} | Max loss ${s['max_loss']:.0f} | R:R {s.get('risk_reward', 0):.2f}")
        parts.append(f"Profits if {s['ticker']} stays below ${s['strike']:.2f} — bearish directional bet")
        parts.append(f"Breakeven ${s['breakeven']:.2f} — {s['breakeven_distance_pct']:.1f}% above current price")

    elif strat == "HEDGE":
        parts.append(s.get("warning", f"Review position in {s['ticker']}"))
        parts.append(f"Market is bearish — consider closing or rolling for risk management")
        return " | ".join(parts)

    # Common context
    if s.get("iv", 0) > 40:
        parts.append(f"IV {s['iv']:.0f}% — elevated premium opportunity")
    if s.get("warning"):
        parts.append(f"⚠ {s['warning']}")
    if regime in ("VERY_FEARFUL", "EXTREME_FEAR") and strat == "CSP":
        parts.append("Note: Consider spread version for defined risk in current regime")
    elif regime == "EXTREME_FEAR":
        parts.append("Max deploy regime — premiums are fattest, deploy aggressively")

    return " | ".join(parts)
