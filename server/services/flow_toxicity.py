"""
Flow Toxicity Detection Module — Phase 1 (IVLD + PCCR)

Detects whether rich premium at a specific strike is genuine fear premium
(safe to harvest via CSP) or informed flow (someone with information is buying protection).

Phase 1 signals (no historical data needed):
  - IVLD: IV Local Distortion — strike IV elevated vs neighbors on the vol surface
  - PCCR: Put/Call Concentration — put activity disproportionately high vs calls in a zone

Phase 2 (requires 20-day snapshot accumulation):
  - VAS: Volume Anomaly Score
  - SWS: Spread Widening Score
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Regime-adjusted thresholds (from spec Section 5.1)
# ═══════════════════════════════════════════════════════════════

REGIME_THRESHOLDS = {
    "DEEP_CONTANGO":      {"caution": 0.30, "toxic": 0.55},
    "CONTANGO":           {"caution": 0.25, "toxic": 0.50},
    "FLAT":               {"caution": 0.20, "toxic": 0.45},
    "BACKWARDATION":      {"caution": 0.15, "toxic": 0.35},
    "DEEP_BACKWARDATION": {"caution": 0.10, "toxic": 0.25},
}

# Label maps for UI
IVLD_LABELS = [(0.70, "SEVERE"), (0.40, "DISTORTED"), (0.15, "MILD_BUMP"), (0.0, "NORMAL")]
PCCR_LABELS = [(0.80, "EXTREME_PUT"), (0.50, "BEARISH_TILT"), (0.20, "PUT_HEAVY"), (0.0, "BALANCED")]
COMPOSITE_LABELS = [(0.70, "HIGHLY_TOXIC"), (0.45, "TOXIC"), (0.20, "CAUTION"), (0.0, "CLEAN")]


def _get_label(score: float, labels: list) -> str:
    for threshold, label in labels:
        if score >= threshold:
            return label
    return labels[-1][1]


# ═══════════════════════════════════════════════════════════════
# Signal 2: IV Local Distortion (IVLD)
# ═══════════════════════════════════════════════════════════════

def iv_local_distortion(strike_iv: float, neighbor_ivs: list, atm_iv: float) -> float:
    """
    Detects whether a specific strike's IV is elevated relative to its neighbors
    on the volatility surface — a "local bump" suggesting targeted demand.

    Args:
        strike_iv: IV at the target strike
        neighbor_ivs: IVs at neighboring strikes (2 below + 2 above, ordered)
        atm_iv: IV at the ATM strike (baseline)

    Returns:
        ivld: 0.0-1.0 (1.0 = maximum distortion)
    """
    if not neighbor_ivs or atm_iv == 0 or strike_iv == 0:
        return 0.0

    neighbor_avg = sum(neighbor_ivs) / len(neighbor_ivs)

    # How much does this strike's IV exceed the local neighborhood?
    # Express as percentage points above neighbor average
    local_excess_pp = (strike_iv - neighbor_avg) * 100

    # Normalize: 0pp = no distortion, 3pp = moderate, 8pp+ = extreme
    local_score = min(local_excess_pp / 8.0, 1.0)
    local_score = max(local_score, 0.0)

    # Skew residual: compare to linear interpolation of immediate neighbors
    if len(neighbor_ivs) >= 4:
        # neighbor_ivs ordered: [strike-2, strike-1, strike+1, strike+2]
        expected_iv = (neighbor_ivs[1] + neighbor_ivs[2]) / 2  # midpoint of immediate neighbors
        skew_residual_pp = (strike_iv - expected_iv) * 100
        skew_score = min(skew_residual_pp / 5.0, 1.0)
        skew_score = max(skew_score, 0.0)
    else:
        skew_score = 0.0

    ivld = 0.5 * local_score + 0.5 * skew_score
    return round(ivld, 3)


# ═══════════════════════════════════════════════════════════════
# Signal 4: Put/Call Concentration Ratio (PCCR)
# ═══════════════════════════════════════════════════════════════

def put_call_concentration(put_volume_zone: int, call_volume_zone: int,
                           put_oi_zone: int, call_oi_zone: int,
                           overall_equity_pcr: float = 0.85) -> float:
    """
    Detects whether put activity at a zone is disproportionately high
    relative to call activity — indicating directional bearish positioning.

    Args:
        put_volume_zone: total put volume at target strike ± 2 strikes
        call_volume_zone: total call volume at same zone
        put_oi_zone: total put OI across zone
        call_oi_zone: total call OI across zone
        overall_equity_pcr: CBOE equity put/call ratio (default 0.85 long-term avg)

    Returns:
        pccr: 0.0-1.0 (1.0 = extreme put concentration)
    """
    # Volume-based P/C ratio for this zone
    if call_volume_zone < 10:
        zone_pcr = 3.0  # very few calls — assign high ratio
    else:
        zone_pcr = put_volume_zone / call_volume_zone

    # OI-based P/C ratio for this zone
    if call_oi_zone < 50:
        zone_oi_pcr = 3.0
    else:
        zone_oi_pcr = put_oi_zone / call_oi_zone

    if overall_equity_pcr <= 0:
        overall_equity_pcr = 0.85

    # Compare zone PCR to overall market PCR
    volume_excess = zone_pcr / overall_equity_pcr
    oi_excess = zone_oi_pcr / overall_equity_pcr

    # Normalize: 1x = in line, 2x = elevated, 4x+ = extreme
    vol_score = min((volume_excess - 1.0) / 3.0, 1.0)
    oi_score = min((oi_excess - 1.0) / 3.0, 1.0)
    vol_score = max(vol_score, 0.0)
    oi_score = max(oi_score, 0.0)

    # Weight: volume is more timely, OI confirms persistence
    pccr = 0.65 * vol_score + 0.35 * oi_score
    return round(pccr, 3)


# ═══════════════════════════════════════════════════════════════
# Composite Score (Phase 1: 2 signals)
# ═══════════════════════════════════════════════════════════════

def composite_toxicity_phase1(ivld: float, pccr: float, regime_state: str) -> tuple:
    """
    Combine IVLD + PCCR into a composite toxicity score (Phase 1: 50/50 weight).

    Returns:
        (score: float, confidence: str, label: str)
    """
    toxicity = 0.50 * ivld + 0.50 * pccr

    # Confidence based on agreement
    signals_elevated = sum(1 for s in [ivld, pccr] if s > 0.4)
    if signals_elevated >= 2:
        confidence = "HIGH"
        # Amplifier: both signals agree and elevated
        if ivld > 0.5 and pccr > 0.5:
            toxicity = min(toxicity * 1.15, 1.0)
    elif signals_elevated == 1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    toxicity = round(toxicity, 3)

    # Regime-adjusted label
    thresholds = REGIME_THRESHOLDS.get(regime_state, REGIME_THRESHOLDS["CONTANGO"])
    if toxicity >= thresholds["toxic"] * 1.4:
        label = "HIGHLY_TOXIC"
    elif toxicity >= thresholds["toxic"]:
        label = "TOXIC"
    elif toxicity >= thresholds["caution"]:
        label = "CAUTION"
    else:
        label = "CLEAN"

    return toxicity, confidence, label


# ═══════════════════════════════════════════════════════════════
# Position Size Dampener
# ═══════════════════════════════════════════════════════════════

def final_position_multiplier(regime_multiplier: float, toxicity_score: float, toxicity_label: str) -> float:
    """Compute final position size multiplier combining regime and toxicity."""
    if toxicity_label in ("HIGHLY_TOXIC", "TOXIC"):
        return 0.0  # do not sell at this strike
    if toxicity_label == "CAUTION":
        toxicity_dampener = 1.0 - (toxicity_score * 0.6)
    else:
        toxicity_dampener = 1.0
    return round(regime_multiplier * toxicity_dampener, 3)


# ═══════════════════════════════════════════════════════════════
# Main Entry Point: compute toxicity for a specific strike
# ═══════════════════════════════════════════════════════════════

def compute_strike_toxicity(ticker: str, expiry: str, target_strike: float,
                            regime_state: str = "CONTANGO") -> dict:
    """
    Fetch option chain and compute flow toxicity for a specific strike.

    Args:
        ticker: stock ticker
        expiry: option expiry date string (YYYY-MM-DD)
        target_strike: the put strike to evaluate
        regime_state: current VIX regime from regime detection module

    Returns:
        dict with toxicity scores, labels, and details
    """
    import yfinance as yf

    try:
        stk = yf.Ticker(ticker)
        chain = stk.option_chain(expiry)
        puts = chain.puts
        calls = chain.calls

        if puts.empty:
            return {"error": f"No put data for {ticker} expiry {expiry}"}

        # Get current price for ATM reference
        info = stk.info or {}
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or 0

        # ── Find target strike and neighbors in puts ──
        strikes_sorted = sorted(puts["strike"].unique())
        if target_strike not in strikes_sorted:
            # Find closest strike
            target_strike = min(strikes_sorted, key=lambda s: abs(s - target_strike))

        strike_idx = strikes_sorted.index(target_strike)

        # Target strike data
        target_row = puts[puts["strike"] == target_strike].iloc[0]
        strike_iv = float(target_row.get("impliedVolatility", 0) or 0)
        strike_volume = int(target_row.get("volume", 0) or 0)
        strike_oi = int(target_row.get("openInterest", 0) or 0)

        # ATM IV (closest to current price)
        atm_strike = min(strikes_sorted, key=lambda s: abs(s - current_price)) if current_price > 0 else target_strike
        atm_row = puts[puts["strike"] == atm_strike].iloc[0]
        atm_iv = float(atm_row.get("impliedVolatility", 0) or 0)

        # Neighbor IVs (±2 strikes)
        neighbor_ivs = []
        neighbor_indices = []
        for offset in [-2, -1, 1, 2]:
            ni = strike_idx + offset
            if 0 <= ni < len(strikes_sorted):
                neighbor_indices.append(ni)
                ns = strikes_sorted[ni]
                nr = puts[puts["strike"] == ns].iloc[0]
                neighbor_ivs.append(float(nr.get("impliedVolatility", 0) or 0))

        # ── Compute IVLD ──
        ivld = iv_local_distortion(strike_iv, neighbor_ivs, atm_iv)
        ivld_label = _get_label(ivld, IVLD_LABELS)
        neighbor_avg_iv = sum(neighbor_ivs) / len(neighbor_ivs) if neighbor_ivs else 0
        iv_excess_pp = round((strike_iv - neighbor_avg_iv) * 100, 2) if neighbor_ivs else 0

        # ── Compute PCCR (zone = target ± 2 strikes) ──
        zone_strikes = [target_strike]
        for offset in [-2, -1, 1, 2]:
            ni = strike_idx + offset
            if 0 <= ni < len(strikes_sorted):
                zone_strikes.append(strikes_sorted[ni])

        # Put volume/OI in zone
        zone_puts = puts[puts["strike"].isin(zone_strikes)]
        put_vol_zone = int(zone_puts["volume"].fillna(0).sum())
        put_oi_zone = int(zone_puts["openInterest"].fillna(0).sum())

        # Call volume/OI in zone (same strikes)
        call_vol_zone = 0
        call_oi_zone = 0
        if not calls.empty:
            zone_calls = calls[calls["strike"].isin(zone_strikes)]
            call_vol_zone = int(zone_calls["volume"].fillna(0).sum())
            call_oi_zone = int(zone_calls["openInterest"].fillna(0).sum())

        pccr = put_call_concentration(put_vol_zone, call_vol_zone, put_oi_zone, call_oi_zone)
        pccr_label = _get_label(pccr, PCCR_LABELS)

        zone_pcr = round(put_vol_zone / max(call_vol_zone, 1), 2)

        # ── Composite ──
        toxicity, confidence, label = composite_toxicity_phase1(ivld, pccr, regime_state)

        # Position multiplier suggestion
        # Default regime multiplier based on state
        regime_multipliers = {
            "DEEP_CONTANGO": 1.0, "CONTANGO": 1.0, "FLAT": 0.85,
            "BACKWARDATION": 0.50, "DEEP_BACKWARDATION": 0.25,
        }
        regime_mult = regime_multipliers.get(regime_state, 0.85)
        position_mult = final_position_multiplier(regime_mult, toxicity, label)

        return {
            "ticker": ticker,
            "expiry": expiry,
            "strike": target_strike,
            "ivld": ivld,
            "ivld_label": ivld_label,
            "pccr": pccr,
            "pccr_label": pccr_label,
            "composite": toxicity,
            "confidence": confidence,
            "label": label,
            "regime": regime_state,
            "position_multiplier": position_mult,
            "details": {
                "strike_iv": round(strike_iv, 4),
                "neighbor_avg_iv": round(neighbor_avg_iv, 4),
                "iv_excess_pp": iv_excess_pp,
                "atm_iv": round(atm_iv, 4),
                "zone_pcr": zone_pcr,
                "market_pcr": 0.85,
                "zone_put_vol": put_vol_zone,
                "zone_call_vol": call_vol_zone,
                "zone_put_oi": put_oi_zone,
                "zone_call_oi": call_oi_zone,
                "strike_volume": strike_volume,
                "strike_oi": strike_oi,
            },
        }

    except Exception as e:
        logger.error(f"Flow toxicity computation failed for {ticker} {expiry} {target_strike}: {e}")
        return {"error": str(e), "ticker": ticker, "strike": target_strike}
