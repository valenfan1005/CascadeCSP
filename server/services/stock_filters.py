"""
Stock Filtering Pipeline for Tier 2/3 Cascading Analysis
Core principle: Rules belong in code. Judgment belongs to Claude.

Hard filters: binary pass/fail — removes stocks that should NEVER be CSP candidates
Soft scoring: adjusts ranking — penalizes risky attributes without excluding
Trend filter: direction-based exclusion — prevents selling puts on falling knives
"""
import logging
import math
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# HARD FILTERS — Binary pass/fail
# ═══════════════════════════════════════════════════════════════

def earnings_filter(stock: dict) -> tuple[bool, str]:
    """
    Exclude stocks with earnings within 21 days.
    Selling CSP into earnings = collecting poisoned premium.
    - Pre-earnings: IV artificially inflated
    - Post-earnings: IV crush regardless of direction
    - Wrong direction: double loss (price move + IV crush)
    """
    dte = stock.get("days_to_earnings")

    if dte is None:
        # Unknown earnings date — risky, but don't hard-exclude
        # (many stocks don't have calendar data in yfinance)
        return True, "earnings_date_unknown"

    if dte <= 21:
        return False, f"earnings_in_{dte}d"

    return True, "earnings_clear"


def market_cap_filter(stock: dict) -> tuple[bool, str]:
    """
    Minimum 2B market cap for adequate option liquidity.
    Small caps have wide bid/ask spreads that eat into premium.
    """
    mcap = stock.get("market_cap", 0) or 0

    if mcap < 2_000_000_000:
        return False, f"market_cap_{mcap/1e9:.1f}B_below_2B"

    return True, "market_cap_ok"


def rsi_extreme_filter(stock: dict) -> tuple[bool, str]:
    """
    Exclude extremely overbought stocks (RSI > 80).
    For CSP sellers, overbought means the put strike is priced
    above fair value support — stock has more room to fall.
    RSI 70-80 is handled by soft scoring (penalty, not exclusion).
    """
    rsi = stock.get("rsi")
    if rsi is None:
        return True, "rsi_data_unavailable"

    if rsi > 80:
        return False, f"rsi_overbought_{rsi:.0f}"

    return True, "rsi_ok"


def option_liquidity_filter(stock: dict) -> tuple[bool, str]:
    """
    Minimum average daily option volume.
    Below 500: spread risk too high, skip.
    500-1000: marginal, handled by soft penalty.
    """
    avg_vol = stock.get("avg_option_volume", None)

    # If we don't have option volume data, pass through
    if avg_vol is None:
        return True, "option_vol_data_unavailable"

    if avg_vol < 500:
        return False, f"option_vol_{avg_vol:.0f}_below_500"

    return True, "option_liquidity_ok"


def price_filter(stock: dict) -> tuple[bool, str]:
    """
    Minimum $10 stock price.
    Sub-$10 stocks have tiny absolute premiums even with high IV.
    """
    price = stock.get("price", 0) or 0

    if price < 10:
        return False, f"price_{price:.2f}_below_10"

    return True, "price_ok"


def trend_direction_filter(stock: dict) -> tuple[bool, str]:
    """
    Exclude confirmed downtrend stocks.
    For CSP sellers: we want uptrends or healthy pullbacks.

    UPTREND: price > MA50 (and MA200 if available)
    PULLBACK: price < MA50 but > MA200 (healthy dip in uptrend)
    DOWNTREND: price < both MA50 and MA200 → EXCLUDE
    """
    price = stock.get("price")
    ma50 = stock.get("sma50")
    ma200 = stock.get("sma200")

    if price is None or ma50 is None:
        stock["trend_label"] = "UNKNOWN"
        return True, "trend_data_unavailable"

    # Strong uptrend
    if price > ma50 and (ma200 is None or price > ma200):
        stock["trend_label"] = "UPTREND"
        return True, "uptrend_confirmed"

    # Healthy pullback within longer uptrend
    if ma200 and price < ma50 and price > ma200:
        stock["trend_label"] = "PULLBACK"
        return True, "pullback_within_uptrend"

    # Downtrend
    stock["trend_label"] = "DOWNTREND"
    return False, "downtrend_confirmed"


# ═══════════════════════════════════════════════════════════════
# MASTER HARD FILTER
# ═══════════════════════════════════════════════════════════════

# Ordered by cost: cheapest checks first
HARD_FILTERS = [
    ("price", price_filter),
    ("market_cap", market_cap_filter),
    ("rsi_extreme", rsi_extreme_filter),
    ("earnings", earnings_filter),
    ("trend", trend_direction_filter),
    # option_liquidity is checked after enrichment (see enrich_and_filter)
]

LIQUIDITY_FILTER = ("option_liquidity", option_liquidity_filter)


def apply_hard_filters(
    stocks: list[dict],
    include_liquidity: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Apply all hard filters. Returns (passed, rejected).
    Rejected list includes rejection_reason for audit trail.

    Fail-fast: first failure stops checking remaining filters.
    """
    filters = list(HARD_FILTERS)
    if include_liquidity:
        filters.append(LIQUIDITY_FILTER)

    passed = []
    rejected = []

    for stock in stocks:
        stock_passed = True
        rejection_reason = None

        for filter_name, filter_fn in filters:
            ok, reason = filter_fn(stock)
            if not ok:
                stock_passed = False
                rejection_reason = reason
                break  # fail fast

        if stock_passed:
            passed.append(stock)
        else:
            rejected.append({**stock, "rejection_reason": rejection_reason})

    logger.info(
        f"Hard filters: {len(passed)} passed, {len(rejected)} rejected "
        f"out of {len(stocks)} total"
    )
    if rejected:
        reasons = {}
        for r in rejected:
            key = r["rejection_reason"].split("_")[0]
            reasons[key] = reasons.get(key, 0) + 1
        logger.info(f"Rejection breakdown: {reasons}")

    return passed, rejected


# ═══════════════════════════════════════════════════════════════
# SOFT SCORING — Adjusts ranking, does NOT exclude
# ═══════════════════════════════════════════════════════════════

def compute_soft_score(stock: dict, base_score: float = 100.0) -> float:
    """
    Adjust base score based on soft signals.
    Score range: 0-100 (higher = more attractive for CSP).
    Stocks with penalties still reach Claude — just ranked lower.
    """
    score = base_score

    # --- FinBERT Sentiment ---
    sentiment = stock.get("finbert_sentiment", 0) or 0
    if sentiment < -0.3:
        score *= 0.70   # strong negative news: -30%
    elif sentiment < -0.1:
        score *= 0.85   # mild negative news: -15%
    elif sentiment > 0.3:
        score *= 1.10   # strong positive news: +10%

    # --- RSI Range Penalty ---
    rsi = stock.get("rsi", 50) or 50
    if 70 < rsi <= 80:
        score *= 0.85   # elevated but not extreme: -15%
    elif rsi < 25:
        score *= 0.85   # deeply oversold = possible falling knife: -15%
    elif rsi < 30:
        score *= 0.92   # oversold: -8%

    # --- Relative Strength vs SPY ---
    rel_strength = stock.get("relative_strength_1m", 0) or 0
    if rel_strength < -10:
        score *= 0.80   # significantly underperforming: -20%
    elif rel_strength < -5:
        score *= 0.90   # mildly underperforming: -10%
    elif rel_strength > 10:
        score *= 1.05   # outperforming: +5%

    # --- Earnings Proximity Penalty (22-35 day zone) ---
    dte = stock.get("days_to_earnings")
    if dte is not None and 22 <= dte <= 35:
        score *= 0.75   # approaching earnings window: -25%

    # --- Option Liquidity Gradient ---
    avg_opt_vol = stock.get("avg_option_volume")
    if avg_opt_vol is not None and 500 <= avg_opt_vol < 1000:
        score *= 0.90   # marginal liquidity: -10%

    # --- Trend Bonus ---
    trend = stock.get("trend_label", "UNKNOWN")
    if trend == "UPTREND":
        score *= 1.05   # confirmed uptrend: +5%
    elif trend == "PULLBACK":
        score *= 1.00   # neutral
    # DOWNTREND should already be filtered out by hard filter

    # --- Volatility Bonus (higher vol = fatter premium) ---
    vol = stock.get("volatility_m", 0) or 0
    if vol > 40:
        score *= 1.10   # high vol: +10%
    elif vol > 30:
        score *= 1.05   # moderate vol: +5%

    return min(round(score, 1), 120.0)  # soft cap at 120


# ═══════════════════════════════════════════════════════════════
# UNUSUAL OPTIONS ACTIVITY DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_unusual_options(ticker: str) -> dict:
    """
    Basic unusual options detection using yfinance.
    Volume/OI ratio > 2 on calls = potential institutional interest.
    """
    try:
        tk = yf.Ticker(ticker)
        exps = tk.options
        if not exps:
            return {"unusual_activity": False, "signal": "NO_OPTIONS"}

        # Check nearest 2 expiries
        unusual_calls = 0
        unusual_puts = 0
        total_checked = 0

        for exp in exps[:2]:
            chain = tk.option_chain(exp)

            # Calls
            calls = chain.calls
            if not calls.empty:
                calls_with_vol = calls[calls["volume"] > 0]
                for _, row in calls_with_vol.iterrows():
                    oi = row.get("openInterest", 0) or 0
                    vol = row.get("volume", 0) or 0
                    if oi > 0 and vol / oi > 2.0:
                        unusual_calls += 1
                    total_checked += 1

            # Puts
            puts = chain.puts
            if not puts.empty:
                puts_with_vol = puts[puts["volume"] > 0]
                for _, row in puts_with_vol.iterrows():
                    oi = row.get("openInterest", 0) or 0
                    vol = row.get("volume", 0) or 0
                    if oi > 0 and vol / oi > 2.0:
                        unusual_puts += 1
                    total_checked += 1

        has_unusual = unusual_calls > 2 or unusual_puts > 2

        if unusual_calls > unusual_puts and unusual_calls > 2:
            signal = "BULLISH_FLOW"
        elif unusual_puts > unusual_calls and unusual_puts > 2:
            signal = "BEARISH_FLOW"
        elif has_unusual:
            signal = "MIXED_FLOW"
        else:
            signal = "NORMAL"

        return {
            "unusual_activity": has_unusual,
            "unusual_calls": unusual_calls,
            "unusual_puts": unusual_puts,
            "total_checked": total_checked,
            "signal": signal,
        }

    except Exception as e:
        logger.debug(f"Unusual options check failed for {ticker}: {e}")
        return {"unusual_activity": False, "signal": "ERROR"}


# ═══════════════════════════════════════════════════════════════
# OPTION VOLUME ENRICHMENT
# ═══════════════════════════════════════════════════════════════

def get_avg_option_volume(ticker: str) -> Optional[float]:
    """Get average put option volume for nearest expiry."""
    try:
        tk = yf.Ticker(ticker)
        exps = tk.options
        if not exps:
            return None
        chain = tk.option_chain(exps[0])
        puts = chain.puts
        if puts.empty:
            return None
        vol = puts["volume"].dropna()
        return round(vol.mean(), 1) if len(vol) > 0 else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# COMPLETE FILTER PIPELINE
# ═══════════════════════════════════════════════════════════════

def tier2_filter_pipeline(
    raw_stocks: list[dict],
    spy_perf_1m: float = 0,
    max_candidates: int = 20,
) -> dict:
    """
    Full Tier 2 filtering pipeline.
    Returns structured output ready for Claude prompt.

    1. Hard filters (fail fast)
    2. Soft scoring (rank)
    3. Cap at max_candidates for Claude
    """
    # Step 1: Hard filters (includes trend filter)
    passed, hard_rejected = apply_hard_filters(raw_stocks)

    # Step 2: Compute relative strength and soft score
    for stock in passed:
        perf = stock.get("perf_1m", 0) or 0
        stock["relative_strength_1m"] = round(perf - spy_perf_1m, 2)
        stock["soft_score"] = compute_soft_score(stock)

    # Step 3: Sort by soft score descending
    passed.sort(key=lambda x: x.get("soft_score", 0), reverse=True)

    # Step 4: Cap for Claude
    candidates = passed[:max_candidates]
    overflow = passed[max_candidates:]

    logger.info(
        f"Filter pipeline: {len(raw_stocks)} scanned → "
        f"{len(hard_rejected)} hard-rejected → "
        f"{len(passed)} passed → "
        f"{len(candidates)} sent to Claude"
    )

    return {
        "candidates": candidates,
        "hard_rejected": hard_rejected,
        "overflow": overflow,  # passed filters but didn't make top N
        "stats": {
            "total_scanned": len(raw_stocks),
            "hard_rejected": len(hard_rejected),
            "passed": len(passed),
            "sent_to_claude": len(candidates),
        },
    }
