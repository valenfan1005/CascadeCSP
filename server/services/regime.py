"""
Market Regime Classifier
Classifies market conditions based on VIX tiers.

VIX-based deployment strategy (sell into fear):
  VIX <= 12 (Extreme Greed)  -> 50-60% invested, premiums thin
  VIX 12-15 (Greed)          -> 60-70% invested
  VIX 15-20 (Slight Fear)    -> 75-80% invested
  VIX 20-25 (Fear)           -> 85-90% invested, premiums getting fat
  VIX 25-30 (Very Fearful)   -> 90-95% invested, spreads recommended
  VIX >= 30 (Extreme Fear)   -> 95-100% invested, add cash if possible
"""
from __future__ import annotations


# Default tiers if config doesn't have them
DEFAULT_TIERS = [
    {"label": "EXTREME_GREED",  "vix_max": 12, "max_deployment_pct": 55, "max_positions": 6,  "delta_range": [-0.20, -0.12], "use_spreads": False},
    {"label": "GREED",          "vix_max": 15, "max_deployment_pct": 65, "max_positions": 8,  "delta_range": [-0.22, -0.15], "use_spreads": False},
    {"label": "SLIGHT_FEAR",    "vix_max": 20, "max_deployment_pct": 78, "max_positions": 10, "delta_range": [-0.25, -0.15], "use_spreads": False},
    {"label": "FEAR",           "vix_max": 25, "max_deployment_pct": 88, "max_positions": 12, "delta_range": [-0.25, -0.18], "use_spreads": False},
    {"label": "VERY_FEARFUL",   "vix_max": 30, "max_deployment_pct": 93, "max_positions": 14, "delta_range": [-0.20, -0.12], "use_spreads": True},
    {"label": "EXTREME_FEAR",   "vix_max": 999,"max_deployment_pct": 98, "max_positions": 16, "delta_range": [-0.15, -0.10], "use_spreads": True},
]


def _get_tiers(config: dict) -> list[dict]:
    """Get VIX tiers from config or defaults."""
    return config.get("regime_rules", {}).get("vix_tiers", DEFAULT_TIERS)


def classify_regime(vix: float, market_trend: str = "NEUTRAL", config: dict | None = None) -> str:
    """
    Classify market regime based on VIX level using 6-tier system.

    Returns regime label like "EXTREME_GREED", "FEAR", "EXTREME_FEAR", etc.
    """
    if vix is None:
        return "SLIGHT_FEAR"

    tiers = _get_tiers(config or {})
    for tier in tiers:
        if vix <= tier["vix_max"]:
            return tier["label"]
    return "EXTREME_FEAR"


def detect_market_trend(spy_prices: list[float], lookback: int = 20) -> str:
    """
    Detect market trend using simple moving average comparison.

    Returns "UP", "DOWN", or "NEUTRAL"
    """
    if not spy_prices or len(spy_prices) < lookback:
        return "NEUTRAL"

    recent = spy_prices[-lookback:]
    sma = sum(recent) / len(recent)
    current = recent[-1]

    pct_diff = (current - sma) / sma * 100

    if pct_diff > 2:
        return "UP"
    elif pct_diff < -2:
        return "DOWN"
    return "NEUTRAL"


def get_regime_position_limits(regime: str, config: dict) -> dict:
    """
    Get position limits based on current VIX regime tier.

    Returns dict with max_positions, delta_range, use_spreads, max_deployment_pct, min_cash_pct
    """
    tiers = _get_tiers(config)

    for tier in tiers:
        if tier["label"] == regime:
            max_deploy = tier["max_deployment_pct"]
            return {
                "max_positions": tier["max_positions"],
                "delta_range": tier["delta_range"],
                "use_spreads": tier["use_spreads"],
                "max_deployment_pct": max_deploy,
                "min_cash_pct": 100 - max_deploy,
            }

    # Fallback
    return {
        "max_positions": 10,
        "delta_range": [-0.25, -0.15],
        "use_spreads": False,
        "max_deployment_pct": 60,
        "min_cash_pct": 40,
    }
