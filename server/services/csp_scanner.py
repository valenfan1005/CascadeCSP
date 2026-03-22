"""
CSP Scanner Service
Scans for high-quality Cash-Secured Put opportunities by combining
TradingView broad market screening with Yahoo Finance options enrichment.
"""

import asyncio
import math
import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests
import yfinance as yf
from scipy.stats import norm

logger = logging.getLogger(__name__)

# --------------- Cache ---------------

_cache: dict = {}
_CACHE_TTL = 900  # 15 minutes


def _get_cached(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cache(key: str, data: dict):
    _cache[key] = {"data": data, "ts": time.time()}


# --------------- Step 1: TradingView Scan ---------------

TRADINGVIEW_URL = "https://scanner.tradingview.com/america/scan"

TV_COLUMNS = [
    "name", "description", "close", "Volatility.D", "Volatility.W", "Volatility.M",
    "market_cap_basic", "sector", "industry", "price_earnings_ttm",
    "earnings_per_share_diluted_ttm", "earnings_release_next_date",
    "beta_1_year", "average_volume_10d_calc", "RSI", "Perf.1M", "Perf.3M",
    "SMA50", "SMA200", "Recommend.All", "relative_volume_10d_calc",
]


def _parse_tv_row(item: dict) -> Optional[dict]:
    """Parse a single TradingView scan row into our format."""
    d = item.get("d", [])
    if len(d) < len(TV_COLUMNS):
        return None
    row = dict(zip(TV_COLUMNS, d))
    ticker = row.get("name", "")
    if not ticker or "." in ticker:
        return None  # skip ADRs / foreign tickers with dots
    return {
        "ticker": ticker,
        "name": row.get("description", ""),
        "price": _safe_num(row.get("close")),
        "volatility_d": _safe_num(row.get("Volatility.D")),
        "volatility_w": _safe_num(row.get("Volatility.W")),
        "volatility_m": _safe_num(row.get("Volatility.M")),
        "market_cap": _safe_num(row.get("market_cap_basic")),
        "sector": row.get("sector", ""),
        "industry": row.get("industry", ""),
        "pe_ttm": _safe_num(row.get("price_earnings_ttm")),
        "eps_ttm": _safe_num(row.get("earnings_per_share_diluted_ttm")),
        "earnings_date": row.get("earnings_release_next_date"),
        "beta": _safe_num(row.get("beta_1_year")),
        "avg_volume_10d": _safe_num(row.get("average_volume_10d_calc")),
        "rsi": _safe_num(row.get("RSI")),
        "perf_1m": _safe_num(row.get("Perf.1M")),
        "perf_3m": _safe_num(row.get("Perf.3M")),
        "sma50": _safe_num(row.get("SMA50")),
        "sma200": _safe_num(row.get("SMA200")),
        "recommendation": _safe_num(row.get("Recommend.All")),
        "relative_volume": _safe_num(row.get("relative_volume_10d_calc")),
    }


# Popular high-IV tickers that CSP sellers commonly trade — always include these
# even if their realized vol doesn't rank in the top scan results
MUST_INCLUDE_TICKERS = [
    "TSLA", "NVDA", "AMD", "META", "AMZN", "GOOGL", "AAPL", "MSFT",
    "NFLX", "COIN", "MSTR", "PLTR", "SQ", "SHOP", "SNOW", "CRWD",
    "SOFI", "RIVN", "NIO", "BABA", "BA", "DIS", "PYPL", "UBER",
]


def _tradingview_scan() -> list[dict]:
    """Call TradingView scanner API and return parsed results."""
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

    # Main scan: top 150 by monthly volatility
    payload = {
        "filter": [
            {"left": "market_cap_basic", "operation": "greater", "right": 10_000_000_000},
            {"left": "average_volume_10d_calc", "operation": "greater", "right": 1_000_000},
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "is_primary", "operation": "equal", "right": True},
            {"left": "Volatility.M", "operation": "greater", "right": 2.0},
        ],
        "options": {"lang": "en"},
        "columns": TV_COLUMNS,
        "sort": {"sortBy": "Volatility.M", "sortOrder": "desc"},
        "range": [0, 150],
    }

    resp = requests.post(TRADINGVIEW_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    seen_tickers = set()
    for item in data.get("data", []):
        parsed = _parse_tv_row(item)
        if parsed:
            results.append(parsed)
            seen_tickers.add(parsed["ticker"])

    # Ensure must-include tickers are present
    missing = [t for t in MUST_INCLUDE_TICKERS if t not in seen_tickers]
    if missing:
        try:
            exchanges = {"TSLA": "NASDAQ", "NVDA": "NASDAQ", "AMD": "NASDAQ", "META": "NASDAQ",
                         "AMZN": "NASDAQ", "GOOGL": "NASDAQ", "AAPL": "NASDAQ", "MSFT": "NASDAQ",
                         "NFLX": "NASDAQ", "COIN": "NASDAQ", "MSTR": "NASDAQ", "PLTR": "NASDAQ",
                         "SQ": "NYSE", "SHOP": "NYSE", "SNOW": "NYSE", "CRWD": "NASDAQ",
                         "SOFI": "NASDAQ", "RIVN": "NASDAQ", "NIO": "NYSE", "BABA": "NYSE",
                         "BA": "NYSE", "DIS": "NYSE", "PYPL": "NASDAQ", "UBER": "NYSE"}
            tickers_list = [f"{exchanges.get(t, 'NASDAQ')}:{t}" for t in missing]
            extra_payload = {
                "symbols": {"tickers": tickers_list},
                "columns": TV_COLUMNS,
            }
            extra_resp = requests.post(TRADINGVIEW_URL, json=extra_payload, headers=headers, timeout=10)
            if extra_resp.status_code == 200:
                for item in extra_resp.json().get("data", []):
                    parsed = _parse_tv_row(item)
                    if parsed and parsed["ticker"] not in seen_tickers:
                        results.append(parsed)
                        seen_tickers.add(parsed["ticker"])
        except Exception as e:
            logger.warning(f"Failed to fetch must-include tickers: {e}")

    return results


# --------------- Step 2: Yahoo Finance IV Enrichment ---------------

def black_scholes_delta(S, K, T, r, sigma):
    """Calculate put delta using Black-Scholes."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1) - 1  # put delta is negative


def _enrich_with_options(ticker: str, price: float) -> Optional[dict]:
    """Fetch options chain from Yahoo Finance and find best CSP candidates."""
    try:
        stock = yf.Ticker(ticker)
        exps = stock.options
        if not exps:
            return None

        today = datetime.now()

        # Find expiration in 25-45 DTE range
        best_exp = None
        for exp in exps:
            dte = (datetime.strptime(exp, "%Y-%m-%d") - today).days
            if 25 <= dte <= 45:
                best_exp = exp
                break
        if not best_exp:
            # Try 20-60 range
            for exp in exps:
                dte = (datetime.strptime(exp, "%Y-%m-%d") - today).days
                if 20 <= dte <= 60:
                    best_exp = exp
                    break
        if not best_exp:
            best_exp = exps[min(2, len(exps) - 1)]

        dte = (datetime.strptime(best_exp, "%Y-%m-%d") - today).days
        T = dte / 365.0

        chain = stock.option_chain(best_exp)
        puts = chain.puts

        if puts.empty:
            return None

        # ATM IV
        atm_idx = (puts["strike"] - price).abs().idxmin()
        atm_iv = float(puts.loc[atm_idx, "impliedVolatility"])

        # Find best CSP: ~20 delta put with good liquidity
        candidates = []
        for _, row in puts.iterrows():
            strike = float(row["strike"])
            iv = float(row["impliedVolatility"]) if not math.isnan(row["impliedVolatility"]) else 0
            bid = float(row["bid"]) if not math.isnan(row["bid"]) else 0
            ask = float(row["ask"]) if not math.isnan(row["ask"]) else 0
            oi = int(row["openInterest"]) if not math.isnan(row.get("openInterest", float("nan"))) else 0
            vol = int(row["volume"]) if not math.isnan(row.get("volume", float("nan"))) else 0

            if strike >= price or strike < price * 0.70:
                continue
            if bid <= 0:
                continue

            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else 999

            # Calculate delta
            delta = black_scholes_delta(price, strike, T, 0.05, iv)

            # We want puts in -0.10 to -0.30 delta range
            if not (-0.35 <= delta <= -0.08):
                continue

            premium_per_contract = mid * 100
            bp_used = strike * 100
            annualized_return = (premium_per_contract / bp_used) * (365 / max(dte, 1))
            otm_pct = (price - strike) / price

            candidates.append({
                "strike": strike,
                "expiry": best_exp,
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": round(mid, 2),
                "iv": round(iv, 4),
                "delta": round(delta, 3),
                "open_interest": oi,
                "volume": vol,
                "spread_pct": round(spread_pct, 4),
                "premium_100": round(premium_per_contract, 2),
                "bp_used": round(bp_used, 2),
                "annualized_return": round(annualized_return, 4),
                "otm_pct": round(otm_pct, 4),
            })

        # Sort by best delta near -0.16 (1 std dev)
        candidates.sort(key=lambda c: abs(c["delta"] + 0.16))
        best_csp = candidates[0] if candidates else None

        # Also get highest annualized return with decent liquidity
        liquid = [c for c in candidates if c["open_interest"] >= 50 and c["spread_pct"] < 0.15]
        best_return = max(liquid, key=lambda c: c["annualized_return"]) if liquid else None

        return {
            "atm_iv": round(atm_iv, 4),
            "best_exp": best_exp,
            "dte": dte,
            "num_strikes": len(puts),
            "best_csp_16d": best_csp,
            "best_csp_return": best_return,
            "all_candidates": sorted(candidates, key=lambda c: c["strike"])[:10],
        }

    except Exception as e:
        logger.warning(f"Options enrichment failed for {ticker}: {e}")
        return None


def _enrich_batch(stocks: list[dict], max_tickers: int = 30) -> dict[str, dict]:
    """Fetch options data for multiple tickers in parallel."""
    subset = stocks[:max_tickers]
    results = {}

    def _fetch(item):
        ticker = item["ticker"]
        price = item.get("price")
        if not price or price <= 0:
            return ticker, None
        return ticker, _enrich_with_options(ticker, price)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch, s): s["ticker"] for s in subset}
        for future in futures:
            try:
                ticker, data = future.result(timeout=30)
                if data:
                    results[ticker] = data
            except Exception as e:
                logger.warning(f"Thread failed for {futures[future]}: {e}")

    return results


# --------------- Step 3: CSP Scoring ---------------

def _score_stock(stock: dict, options: Optional[dict]) -> dict:
    """Score a stock 0-100 for CSP attractiveness."""
    scores = {}

    # --- IV Score (30pts): Higher ATM IV = better premium ---
    iv_score = 0
    atm_iv = None
    if options and options.get("atm_iv"):
        atm_iv = options["atm_iv"] * 100  # convert to percentage
        # Scale 20-80% IV to 0-30pts
        iv_score = max(0, min(30, (atm_iv - 20) / (80 - 20) * 30))
    scores["iv_score"] = round(iv_score, 1)

    # --- Liquidity Score (20pts) ---
    liq_score = 5  # base
    if options:
        best = options.get("best_csp_16d")
        if best:
            oi = best.get("open_interest", 0)
            if oi > 500:
                liq_score = 20
            elif oi > 200:
                liq_score = 15
            elif oi > 50:
                liq_score = 10

            # Penalize wide spreads
            spread = best.get("spread_pct", 1.0)
            if spread > 0.20:
                liq_score = max(0, liq_score - 5)
            elif spread > 0.10:
                liq_score = max(0, liq_score - 2)
    scores["liquidity_score"] = round(liq_score, 1)

    # --- Annualized Return Score (20pts) ---
    ret_score = 0
    if options:
        best = options.get("best_csp_16d")
        if best and best.get("annualized_return"):
            annual = best["annualized_return"] * 100  # convert to pct
            # Scale 10-100% annualized to 0-20pts
            ret_score = max(0, min(20, (annual - 10) / (100 - 10) * 20))
    scores["return_score"] = round(ret_score, 1)

    # --- Technical Score (15pts) ---
    tech_score = 5  # base
    rsi = stock.get("rsi")
    if rsi is not None:
        if 30 <= rsi <= 50:
            tech_score = 12  # oversold but not crashing — best zone for CSP
        elif 50 < rsi <= 60:
            tech_score = 8
        else:
            tech_score = 5

    # Price above SMA200 bonus
    price = stock.get("price")
    sma200 = stock.get("sma200")
    if price and sma200 and price > sma200:
        tech_score = min(15, tech_score + 3)
    scores["technical_score"] = round(tech_score, 1)

    # --- Safety Score (15pts) ---
    safety_score = 5  # base
    beta = stock.get("beta")
    if beta is not None:
        if beta < 1.5:
            safety_score = 10
        elif beta < 2.0:
            safety_score = 7
        else:
            safety_score = 3

    # Earnings > 14 days away bonus
    earnings_date = stock.get("earnings_date")
    if earnings_date:
        try:
            if isinstance(earnings_date, (int, float)):
                # TradingView returns epoch seconds
                earn_dt = datetime.fromtimestamp(earnings_date)
            else:
                earn_dt = datetime.strptime(str(earnings_date), "%Y-%m-%d")
            days_to_earnings = (earn_dt - datetime.now()).days
            if days_to_earnings > 14:
                safety_score = min(15, safety_score + 5)
            # If earnings within 14 days, no bonus (IV crush risk)
        except Exception:
            pass
    else:
        # Unknown earnings date — give partial bonus
        safety_score = min(15, safety_score + 2)
    scores["safety_score"] = round(safety_score, 1)

    # Total
    total = iv_score + liq_score + ret_score + tech_score + safety_score
    scores["total"] = round(total, 1)

    return scores


# --------------- Public API ---------------

def _run_quick_scan_sync() -> dict:
    """TradingView scan only (no options enrichment). Returns quickly."""
    cached = _get_cached("quick_scan")
    if cached:
        return cached

    try:
        stocks = _tradingview_scan()
    except Exception as e:
        logger.error(f"TradingView scan failed: {e}")
        return {"error": str(e), "results": [], "total_scanned": 0, "scan_time": datetime.now().isoformat()}

    # Add basic scores (no IV data)
    for s in stocks:
        scores = _score_stock(s, None)
        s["score_breakdown"] = scores
        s["csp_score"] = scores["total"]
        s["days_to_earnings"] = _days_to_earnings(s.get("earnings_date"))
        s["avg_volume"] = s.get("avg_volume_10d")
        s["options_data"] = None

    stocks.sort(key=lambda s: s.get("csp_score", 0), reverse=True)

    result = {
        "scan_time": datetime.now().isoformat(),
        "total_scanned": len(stocks),
        "results": stocks,
    }
    _set_cache("quick_scan", result)
    return result


def _run_full_scan_sync() -> dict:
    """Full CSP scan with TradingView + Yahoo Finance options enrichment."""
    cached = _get_cached("full_scan")
    if cached:
        return cached

    # Step 1: TradingView scan
    try:
        stocks = _tradingview_scan()
    except Exception as e:
        logger.error(f"TradingView scan failed: {e}")
        return {"error": str(e), "results": [], "total_scanned": 0, "scan_time": datetime.now().isoformat()}

    if not stocks:
        return {"results": [], "total_scanned": 0, "scan_time": datetime.now().isoformat()}

    # Step 2: Options enrichment (top 30)
    options_data = _enrich_batch(stocks, max_tickers=30)

    # Step 3: Score and assemble
    results = []
    for s in stocks:
        ticker = s["ticker"]
        opts = options_data.get(ticker)
        scores = _score_stock(s, opts)
        s["options_data"] = opts
        s["score_breakdown"] = scores
        s["csp_score"] = scores["total"]
        s["days_to_earnings"] = _days_to_earnings(s.get("earnings_date"))
        s["avg_volume"] = s.get("avg_volume_10d")
        results.append(s)

    # Sort by total score descending
    results.sort(key=lambda s: s.get("csp_score", 0), reverse=True)

    result = {
        "scan_time": datetime.now().isoformat(),
        "total_scanned": len(stocks),
        "enriched_count": len(options_data),
        "results": results,
    }
    _set_cache("full_scan", result)
    return result


async def run_quick_scan() -> dict:
    """Async wrapper for the quick scan."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_quick_scan_sync)


async def run_csp_scan() -> dict:
    """Async wrapper for the full CSP scan."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_full_scan_sync)


# --------------- Helpers ---------------

def _days_to_earnings(earnings_date) -> Optional[int]:
    """Calculate days until next earnings from TradingView epoch timestamp."""
    if earnings_date is None:
        return None
    try:
        if isinstance(earnings_date, (int, float)):
            earn_dt = datetime.fromtimestamp(earnings_date)
        else:
            earn_dt = datetime.strptime(str(earnings_date), "%Y-%m-%d")
        days = (earn_dt - datetime.now()).days
        return days if days >= 0 else None
    except Exception:
        return None


def _safe_num(val) -> Optional[float]:
    """Safely convert to number, handling None/NaN."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None
