"""
Moomoo OpenD Option Chain Data Fetcher
Primary data source for real-time option data (IV, Greeks, Bid/Ask).
Falls back to yfinance if Moomoo is unavailable.

Usage:
    data = get_csp_options(ticker="AAPL", target_dte=35)
    Returns best CSP candidates with IV, delta, bid/ask, annualized return.
"""
import logging
import time
import math
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import moomoo
try:
    from moomoo import OpenQuoteContext, RET_OK, SubType
    MOOMOO_AVAILABLE = True
except ImportError:
    MOOMOO_AVAILABLE = False

MOOMOO_HOST = "127.0.0.1"
MOOMOO_PORT = 11111
REQUEST_DELAY = 3.5  # Moomoo rate limit: max 10 calls per 30s → 3s between calls


def _get_context():
    """Create a fresh Moomoo quote context."""
    return OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)


def _find_best_expiry(ctx, us_code: str, target_dte: int = 35) -> Optional[str]:
    """Find the expiry date closest to target DTE."""
    ret, data = ctx.get_option_expiration_date(code=us_code)
    if ret != RET_OK:
        logger.warning(f"Failed to get expiry dates for {us_code}: {data}")
        return None

    today = date.today()
    target_date = today + timedelta(days=target_dte)

    dates = data["strike_time"].tolist()
    if not dates:
        return None

    # Find closest to target DTE, preferring slightly longer
    best = min(dates, key=lambda d: abs((date.fromisoformat(d) - target_date).days))
    return best


def _get_put_chain(ctx, us_code: str, expiry: str) -> list[dict]:
    """Get all put options for a given expiry."""
    ret, chain = ctx.get_option_chain(code=us_code, start=expiry, end=expiry)
    if ret != RET_OK:
        logger.warning(f"Failed to get option chain for {us_code} {expiry}: {chain}")
        return []

    puts = chain[chain["option_type"] == "PUT"]
    return puts["code"].tolist()


def _get_option_snapshots(ctx, codes: list[str]) -> list[dict]:
    """Get market snapshots (bid/ask/IV/Greeks) for option codes.
    Must subscribe first, then get snapshot."""
    results = []

    # Subscribe in batches (Moomoo has limits)
    batch_size = 10
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]

        # Subscribe all in batch
        for code in batch:
            try:
                ret, _ = ctx.subscribe(code, [SubType.QUOTE], subscribe_push=False)
                if ret != RET_OK:
                    logger.debug(f"Subscribe failed for {code}")
            except Exception:
                pass

        time.sleep(REQUEST_DELAY)

        # Get snapshots for batch
        try:
            ret, snap = ctx.get_market_snapshot(batch)
            if ret == RET_OK:
                for _, row in snap.iterrows():
                    results.append({
                        "code": row["code"],
                        "last_price": row.get("last_price"),
                        "bid_price": row.get("bid_price"),
                        "ask_price": row.get("ask_price"),
                        "bid_vol": row.get("bid_vol"),
                        "ask_vol": row.get("ask_vol"),
                        "volume": row.get("volume"),
                        "open_interest": row.get("option_open_interest"),
                        "iv": row.get("option_implied_volatility"),
                        "delta": row.get("option_delta"),
                        "gamma": row.get("option_gamma"),
                        "theta": row.get("option_theta"),
                        "vega": row.get("option_vega"),
                        "strike_price": row.get("option_strike_price"),
                        "option_type": row.get("option_type"),
                        "dte": row.get("option_expiry_date_distance"),
                    })
        except Exception as e:
            logger.warning(f"Snapshot failed for batch: {e}")

    return results


def get_csp_options(
    ticker: str,
    stock_price: float,
    target_dte: int = 35,
    delta_range: tuple = (-0.35, -0.10),
    max_results: int = 5,
) -> dict:
    """
    Get CSP option candidates from Moomoo with real IV/Greeks/Bid/Ask.

    Returns:
    {
        "source": "moomoo",
        "expiry": "2026-04-17",
        "dte": 30,
        "atm_iv": 0.25,
        "candidates": [
            {
                "strike": 210, "bid": 1.50, "ask": 1.80, "mid": 1.65,
                "iv": 0.28, "delta": -0.20, "theta": -0.05,
                "open_interest": 1500, "volume": 200,
                "annualized_return": 0.12, "buying_power": 21000,
                "moneyness": "OTM_5%"
            }
        ],
        "best_csp": {...},  # Top candidate
    }
    """
    if not MOOMOO_AVAILABLE:
        return {"source": "unavailable", "error": "moomoo-api not installed"}

    us_code = f"US.{ticker}"
    ctx = None

    try:
        ctx = _get_context()

        # Step 1: Find best expiry
        expiry = _find_best_expiry(ctx, us_code, target_dte)
        if not expiry:
            return {"source": "moomoo", "error": "no_expiry_dates"}

        actual_dte = (date.fromisoformat(expiry) - date.today()).days
        logger.info(f"[Moomoo] {ticker}: expiry={expiry} DTE={actual_dte}")

        time.sleep(REQUEST_DELAY)

        # Step 2: Get put chain
        put_codes = _get_put_chain(ctx, us_code, expiry)
        if not put_codes:
            return {"source": "moomoo", "error": "no_put_chain"}

        logger.info(f"[Moomoo] {ticker}: {len(put_codes)} puts found")

        # Step 3: Filter to OTM puts (strike < stock price)
        # We'll get snapshots to check actual strike prices
        # Limit to reasonable range (80% to 100% of stock price)
        # Can't filter by strike before snapshot, so limit to ~20 contracts
        otm_codes = put_codes[-20:]  # Last 20 (closer to ATM)

        # Step 4: Get snapshots with Greeks
        snapshots = _get_option_snapshots(ctx, otm_codes)

        if not snapshots:
            return {"source": "moomoo", "error": "no_snapshots"}

        # Step 5: Filter and score candidates
        candidates = []
        atm_iv = None

        for snap in snapshots:
            strike = snap.get("strike_price")
            if not strike or not stock_price:
                continue

            # Only OTM puts (strike < stock price)
            if strike >= stock_price:
                # Track ATM IV
                if atm_iv is None and snap.get("iv"):
                    atm_iv = snap["iv"] / 100  # Moomoo returns percentage
                continue

            # Calculate metrics
            bid = snap.get("bid_price") or 0
            ask = snap.get("ask_price") or 0
            last = snap.get("last_price") or 0
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last

            # Allow candidates even with mid=0 after hours — still useful for IV/delta info
            # But skip if truly no data at all
            if mid <= 0 and not snap.get("iv"):
                continue

            iv = (snap.get("iv") or 0) / 100  # Convert from percentage
            delta = snap.get("delta") or 0
            theta = snap.get("theta") or 0
            oi = snap.get("open_interest") or 0
            vol = snap.get("volume") or 0

            # Annualized return
            buying_power = strike * 100
            premium = mid * 100
            days = actual_dte if actual_dte > 0 else 1
            annualized = (premium / buying_power) * (365 / days) if buying_power > 0 else 0

            # Moneyness
            otm_pct = round((1 - strike / stock_price) * 100, 1)

            # Delta filter — also accept positive delta (some sources return abs value for puts)
            abs_delta = abs(delta) if delta != 0 else 0
            in_delta_range = (delta_range[0] <= delta <= delta_range[1]) or (abs(delta_range[0]) >= abs_delta >= abs(delta_range[1]) and abs_delta > 0)
            # If delta is 0 (after hours), include based on OTM distance (5-25% OTM)
            if delta == 0 and 5 <= otm_pct <= 25:
                in_delta_range = True
            if in_delta_range:
                candidates.append({
                    "strike": strike,
                    "bid": bid,
                    "ask": ask,
                    "mid": round(mid, 2),
                    "iv": round(iv, 4),
                    "delta": round(delta, 3),
                    "theta": round(theta, 4),
                    "gamma": round(snap.get("gamma") or 0, 5),
                    "open_interest": oi,
                    "volume": vol,
                    "annualized_return": round(annualized, 4),
                    "buying_power": round(buying_power),
                    "otm_pct": otm_pct,
                    "moneyness": f"OTM_{otm_pct}%",
                })

        # Also include near-delta candidates even if outside strict range
        if not candidates:
            # Fallback: get any OTM put with some premium
            for snap in snapshots:
                strike = snap.get("strike_price")
                if not strike or strike >= stock_price:
                    continue
                mid = ((snap.get("bid_price") or 0) + (snap.get("ask_price") or 0)) / 2
                if mid <= 0:
                    mid = snap.get("last_price") or 0
                if mid <= 0:
                    continue

                buying_power = strike * 100
                annualized = (mid * 100 / buying_power) * (365 / max(actual_dte, 1))
                otm_pct = round((1 - strike / stock_price) * 100, 1)

                candidates.append({
                    "strike": strike,
                    "bid": snap.get("bid_price") or 0,
                    "ask": snap.get("ask_price") or 0,
                    "mid": round(mid, 2),
                    "iv": round((snap.get("iv") or 0) / 100, 4),
                    "delta": round(snap.get("delta") or 0, 3),
                    "theta": round(snap.get("theta") or 0, 4),
                    "open_interest": snap.get("open_interest") or 0,
                    "volume": snap.get("volume") or 0,
                    "annualized_return": round(annualized, 4),
                    "buying_power": round(buying_power),
                    "otm_pct": otm_pct,
                    "moneyness": f"OTM_{otm_pct}%",
                })

        # Sort by annualized return (best first)
        candidates.sort(key=lambda x: x["annualized_return"], reverse=True)
        candidates = candidates[:max_results]

        best = candidates[0] if candidates else None

        return {
            "source": "moomoo",
            "expiry": expiry,
            "dte": actual_dte,
            "atm_iv": round(atm_iv, 4) if atm_iv else None,
            "candidates": candidates,
            "best_csp": best,
            "total_puts_scanned": len(snapshots),
        }

    except Exception as e:
        logger.error(f"Moomoo option fetch failed for {ticker}: {e}")
        return {"source": "moomoo", "error": str(e)}

    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:
                pass


def get_csp_options_batch(
    tickers: list[str],
    stock_prices: dict[str, float],
    target_dte: int = 35,
) -> dict[str, dict]:
    """
    Get CSP options for multiple tickers using a single Moomoo context.
    Optimized: batch API calls, share expiry cache, respect rate limits.

    Moomoo rate limit: 10 calls per 30 seconds for get_option_chain/get_option_expiration_date.
    Strategy: space calls 3.5s apart, use a single context.
    """
    if not MOOMOO_AVAILABLE:
        return {t: {"source": "unavailable"} for t in tickers}

    results = {}
    ctx = None
    _call_count = [0]  # mutable counter for rate limiting
    _last_call = [0.0]

    def _rate_limited_sleep():
        """Ensure minimum gap between Moomoo API calls."""
        _call_count[0] += 1
        elapsed = time.time() - _last_call[0]
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        _last_call[0] = time.time()

    try:
        ctx = _get_context()

        # Cache expiry: query once from first ticker, reuse for all
        # Most US stocks share the same monthly option expiry dates
        cached_expiry = None
        cached_dte = None

        for ticker in tickers:
            us_code = f"US.{ticker}"
            price = stock_prices.get(ticker, 0)
            if not price:
                results[ticker] = {"source": "moomoo", "error": "no_price"}
                continue

            try:
                # Find expiry — use cache if available, otherwise query
                if cached_expiry is None:
                    _rate_limited_sleep()
                    cached_expiry = _find_best_expiry(ctx, us_code, target_dte)
                    if cached_expiry:
                        cached_dte = (date.fromisoformat(cached_expiry) - date.today()).days
                        logger.info(f"[Moomoo] Cached expiry: {cached_expiry} (DTE={cached_dte})")

                expiry = cached_expiry
                actual_dte = cached_dte
                if not expiry:
                    results[ticker] = {"source": "moomoo", "error": "no_expiry"}
                    continue

                # Get put chain (rate limited)
                _rate_limited_sleep()
                put_codes = _get_put_chain(ctx, us_code, expiry)
                if not put_codes:
                    results[ticker] = {"source": "moomoo", "error": "no_puts"}
                    continue

                # Get OTM puts near ATM (limit to 10 to reduce snapshot calls)
                otm_codes = put_codes[-10:]

                # Get snapshots (rate limited internally)
                _rate_limited_sleep()
                snapshots = _get_option_snapshots(ctx, otm_codes)

                # Process
                candidates = []
                atm_iv = None

                for snap in snapshots:
                    strike = snap.get("strike_price")
                    if not strike:
                        continue

                    if strike >= price:
                        if atm_iv is None and snap.get("iv"):
                            atm_iv = snap["iv"] / 100
                        continue

                    bid = snap.get("bid_price") or 0
                    ask = snap.get("ask_price") or 0
                    mid = (bid + ask) / 2 if bid and ask else snap.get("last_price") or 0
                    if mid <= 0:
                        continue

                    bp = strike * 100
                    ann = (mid * 100 / bp) * (365 / max(actual_dte, 1)) if bp > 0 else 0
                    otm_pct = round((1 - strike / price) * 100, 1)
                    delta = snap.get("delta") or 0

                    if -0.35 <= delta <= -0.10:
                        candidates.append({
                            "strike": strike,
                            "bid": bid,
                            "ask": ask,
                            "mid": round(mid, 2),
                            "iv": round((snap.get("iv") or 0) / 100, 4),
                            "delta": round(delta, 3),
                            "theta": round(snap.get("theta") or 0, 4),
                            "open_interest": snap.get("open_interest") or 0,
                            "volume": snap.get("volume") or 0,
                            "annualized_return": round(ann, 4),
                            "buying_power": round(bp),
                            "otm_pct": otm_pct,
                        })

                candidates.sort(key=lambda x: x["annualized_return"], reverse=True)

                results[ticker] = {
                    "source": "moomoo",
                    "expiry": expiry,
                    "dte": actual_dte,
                    "atm_iv": round(atm_iv, 4) if atm_iv else None,
                    "candidates": candidates[:5],
                    "best_csp": candidates[0] if candidates else None,
                }

                logger.info(f"[Moomoo] {ticker}: {len(candidates)} CSP candidates found")

            except Exception as e:
                logger.warning(f"[Moomoo] {ticker} failed: {e}")
                results[ticker] = {"source": "moomoo", "error": str(e)}

            time.sleep(REQUEST_DELAY)

    except Exception as e:
        logger.error(f"Moomoo batch fetch failed: {e}")
        for t in tickers:
            if t not in results:
                results[t] = {"source": "moomoo", "error": str(e)}
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:
                pass

    return results
