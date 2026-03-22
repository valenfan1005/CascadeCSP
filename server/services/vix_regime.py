"""
VIX Term Structure Regime Detection Module
==========================================
Detects market regime from VIX term structure and provides:
- 5 regime states (Deep Contango → Deep Backwardation)
- Transition detection with direction + speed + leading indicator
- Position size multiplier (0.0 - 1.0)
- Alert levels (INFO → CRISIS → GOLDEN)
- 20-day sparkline data for dashboard

Core Principle:
> The absolute level tells you where you are.
> The direction and speed tells you where you're going.
> Decisions should be based on where you're going, not where you are.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# --- State persistence ---
_STATE_FILE = Path(__file__).parent.parent / ".vix_regime_state.json"
_CACHE_FILE = Path(__file__).parent.parent / ".vix_regime_cache.json"
_CACHE_TTL = 300  # 5 minutes during market hours


# ============================================================
# 1. Regime Classification
# ============================================================

def get_regime(primary_ratio: float) -> str:
    """Classify regime from VIX/VIX3M ratio."""
    if primary_ratio < 0.85:
        return "DEEP_CONTANGO"
    elif primary_ratio < 0.95:
        return "CONTANGO"
    elif primary_ratio <= 1.05:
        return "FLAT"
    elif primary_ratio <= 1.15:
        return "BACKWARDATION"
    else:
        return "DEEP_BACKWARDATION"


def get_leading_regime(leading_ratio: float) -> str:
    """Classify leading indicator from VIX9D/VIX ratio."""
    if leading_ratio < 0.95:
        return "NORMAL"
    elif leading_ratio <= 1.05:
        return "ELEVATED"
    else:
        return "SPIKING"


def get_delta_magnitude(delta: float) -> str:
    """Classify daily change speed."""
    abs_delta = abs(delta)
    if abs_delta < 0.01:
        return "NOISE"
    elif abs_delta < 0.03:
        return "MEANINGFUL"
    else:
        return "FAST"


# ============================================================
# 2. Transition Detection
# ============================================================

TRANSITION_MAP = {
    # (previous_regime, current_regime, direction) → transition state
    ("DEEP_CONTANGO", "CONTANGO", "RISING"): "EARLY_WARNING",
    ("CONTANGO", "FLAT", "RISING"): "EARLY_WARNING",
    ("FLAT", "BACKWARDATION", "RISING"): "DANGER",
    ("BACKWARDATION", "DEEP_BACKWARDATION", "RISING"): "CRISIS",
    ("DEEP_BACKWARDATION", "BACKWARDATION", "FALLING"): "POSSIBLE_GOLDEN",
    ("BACKWARDATION", "FLAT", "FALLING"): "GOLDEN_WINDOW",
    ("FLAT", "CONTANGO", "FALLING"): "RECOVERY",
    ("CONTANGO", "DEEP_CONTANGO", "FALLING"): "RECOVERY",
}


def detect_transition(prev_regime: str, curr_regime: str, sma_direction: str,
                      leading_ratio: float, daily_delta: float) -> dict:
    """Detect regime transition and return state + confidence."""

    key = (prev_regime, curr_regime, sma_direction)
    transition = TRANSITION_MAP.get(key)

    # Check for same-regime deterioration
    if not transition and curr_regime == prev_regime:
        if curr_regime in ("BACKWARDATION", "DEEP_BACKWARDATION") and sma_direction == "RISING":
            transition = "CRISIS"
        elif curr_regime == "FLAT" and sma_direction == "RISING":
            transition = "EARLY_WARNING"
        elif curr_regime == "BACKWARDATION" and sma_direction == "FALLING":
            transition = "POSSIBLE_GOLDEN"

    # Fast transition override: single-day spike
    delta_mag = get_delta_magnitude(daily_delta)
    if delta_mag == "FAST" and daily_delta > 0 and curr_regime in ("FLAT", "BACKWARDATION"):
        transition = "CRISIS" if curr_regime == "BACKWARDATION" else "DANGER"

    if not transition:
        # Default: stable in current regime
        if curr_regime in ("DEEP_CONTANGO", "CONTANGO"):
            transition = "STABLE_SAFE"
        elif curr_regime == "FLAT":
            transition = "TRANSITIONAL"
        else:
            transition = "ELEVATED"

    # Leading indicator confirmation
    leading_regime = get_leading_regime(leading_ratio)
    conviction = "MODERATE"

    if transition in ("EARLY_WARNING", "DANGER"):
        if leading_regime == "SPIKING":
            conviction = "HIGH"  # Leading confirms deterioration
        elif leading_regime == "NORMAL":
            conviction = "LOW"   # Might be a blip

    elif transition == "GOLDEN_WINDOW":
        if leading_regime == "NORMAL":
            conviction = "HIGH"  # Leading already normalized
        elif leading_regime == "SPIKING":
            conviction = "LOW"   # Premature — short end hasn't relaxed
            transition = "POSSIBLE_GOLDEN"

    elif transition == "POSSIBLE_GOLDEN":
        if leading_regime == "NORMAL":
            conviction = "HIGH"
            transition = "GOLDEN_WINDOW"  # Upgrade

    return {
        "transition": transition,
        "conviction": conviction,
        "delta_magnitude": delta_mag,
    }


# ============================================================
# 3. Position Size Multiplier
# ============================================================

def position_size_multiplier(primary_ratio: float, sma_direction: str,
                              leading_ratio: float) -> float:
    """Calculate position size multiplier (0.0 - 1.0)."""
    regime = get_regime(primary_ratio)

    if regime == "DEEP_CONTANGO":
        return 1.0

    elif regime == "CONTANGO":
        return 0.85 if sma_direction == "RISING" else 1.0

    elif regime == "FLAT":
        if sma_direction == "RISING":
            return 0.5
        elif sma_direction == "FALLING":
            return 0.7
        else:
            return 0.6

    elif regime in ("BACKWARDATION", "DEEP_BACKWARDATION"):
        if sma_direction == "RISING":
            return 0.0  # No new positions
        elif sma_direction == "FALLING":
            # Golden window — scale based on leading confirmation
            if leading_ratio < 0.95:
                return 0.5  # High conviction reversal
            elif leading_ratio < 1.05:
                return 0.3  # Moderate conviction
            else:
                return 0.0  # Leading still elevated
        else:
            return 0.0

    return 0.6  # Default fallback


# ============================================================
# 4. Alert System
# ============================================================

def get_alert_level(primary_ratio: float, leading_ratio: float,
                    sma_direction: str, daily_delta: float,
                    cycle_state: str) -> dict:
    """Determine alert level and message."""
    regime = get_regime(primary_ratio)
    leading = get_leading_regime(leading_ratio)

    # CRISIS
    if primary_ratio > 1.15 or (daily_delta > 0.05):
        return {
            "level": "CRISIS",
            "color": "#EF4444",
            "pulse": True,
            "message": "深度Backwardation — 危机状态。溢价看起来极其丰厚，但历史上期权卖方在此阶段会遭受灾难性亏损。等待反转确认后再操作。",
            "action": "所有期权卖出策略暂停。专注资金保全。",
            "size_note": "仓位: 0%",
        }

    # GOLDEN WINDOW
    if cycle_state == "POST_BACKWARDATION" and primary_ratio < 1.05 and sma_direction == "FALLING":
        if leading_ratio < 0.95:
            return {
                "level": "GOLDEN",
                "color": "#8B5CF6",
                "pulse": False,
                "message": "黄金窗口 — Backwardation正在消退，前导指标已正常化。IV仍然偏高但正在回归均值。这是卖出溢价的最佳环境。",
                "action": "开始卖出溢价，但保持谨慎。偏好45-60 DTE，比正常更深的OTM行权价。",
                "size_note": "仓位: 40-50%（逐步增加）",
            }
        else:
            return {
                "level": "POSSIBLE_GOLDEN",
                "color": "#8B5CF6",
                "pulse": False,
                "message": "可能的黄金窗口 — 主要比率正在回归但短端尚未放松。等待前导确认。",
                "action": "暂不操作，等待VIX9D/VIX降至0.95以下。",
                "size_note": "仓位: 0%（等待确认）",
            }

    # DANGER
    if primary_ratio > 1.05 or (leading_ratio > 1.05 and primary_ratio > 0.98):
        return {
            "level": "DANGER",
            "color": "#EF4444",
            "pulse": False,
            "message": "Backwardation — 短期恐惧超过长期预期。IV高并非机会而是陷阱。恐惧仍在升级中。",
            "action": "停止所有新的期权卖出。评估现有持仓是否需要对冲或平仓。",
            "size_note": "仓位: 0%",
        }

    # WARNING
    if primary_ratio > 0.95 or leading_ratio > 1.00:
        msg_parts = []
        if primary_ratio > 0.95:
            msg_parts.append("VIX曲线进入平坦区域")
        if leading_ratio > 1.00:
            msg_parts.append("前导指标(VIX9D)开始上升")
        if sma_direction == "RISING":
            msg_parts.append("5日趋势向上")

        return {
            "level": "WARNING",
            "color": "#F59E0B",
            "pulse": False,
            "message": f"{'，'.join(msg_parts)}。检查现有持仓，新仓位降至70%规模。",
            "action": "新仓位只选更深OTM行权价，仓位降至正常的70%。",
            "size_note": "仓位: 70%",
        }

    # INFO (approaching flat)
    if primary_ratio > 0.90 and sma_direction == "RISING":
        return {
            "level": "INFO",
            "color": "#22C55E",
            "pulse": False,
            "message": "VIX曲线正在趋平 — 持续监控中。当前仍属正常环境。",
            "action": "正常操作，保持关注。",
            "size_note": "仓位: 85-100%",
        }

    # SAFE
    return {
        "level": "SAFE",
        "color": "#22C55E",
        "pulse": False,
        "message": f"{'深度' if regime == 'DEEP_CONTANGO' else ''}Contango — 正常市场结构。短期恐惧低于长期预期。这是期权卖方最有利的环境。",
        "action": "正常卖出溢价。全部仓位。",
        "size_note": "仓位: 100%",
    }


# ============================================================
# 5. Data Fetching & Analysis
# ============================================================

def fetch_vix_data(days: int = 30) -> Optional[pd.DataFrame]:
    """Fetch VIX, VIX3M, VIX9D historical data and compute derived metrics."""
    try:
        period = f"{days + 10}d"  # Extra buffer for SMA calculation

        vix_data = yf.Ticker("^VIX").history(period=period)["Close"]
        vix3m_data = yf.Ticker("^VIX3M").history(period=period)["Close"]
        vix9d_data = yf.Ticker("^VIX9D").history(period=period)["Close"]

        # Normalize timezones — yfinance returns different TZs for VIX vs VIX3M
        vix_data.index = vix_data.index.tz_localize(None) if vix_data.index.tz is None else vix_data.index.tz_convert(None)
        vix3m_data.index = vix3m_data.index.tz_localize(None) if vix3m_data.index.tz is None else vix3m_data.index.tz_convert(None)
        vix9d_data.index = vix9d_data.index.tz_localize(None) if vix9d_data.index.tz is None else vix9d_data.index.tz_convert(None)

        # Normalize to date only (remove time component)
        vix_data.index = vix_data.index.normalize()
        vix3m_data.index = vix3m_data.index.normalize()
        vix9d_data.index = vix9d_data.index.normalize()

        df = pd.DataFrame({
            "VIX": vix_data,
            "VIX3M": vix3m_data,
            "VIX9D": vix9d_data,
        }).dropna()

        if len(df) < 6:
            logger.error(f"Insufficient VIX data: {len(df)} rows")
            return None

        # Derived ratios
        df["primary_ratio"] = df["VIX"] / df["VIX3M"]
        df["leading_ratio"] = df["VIX9D"] / df["VIX"]

        # 5-day SMA of primary ratio
        df["primary_sma5"] = df["primary_ratio"].rolling(5).mean()

        # Daily delta
        df["primary_delta"] = df["primary_ratio"].diff()

        # SMA direction — use 3-day change of SMA for more responsive detection
        # (1-day diff can lag when SMA is still catching up to a reversal)
        sma_diff_3d = df["primary_sma5"].diff(3)
        # Also check raw ratio's 3-day direction as tiebreaker
        raw_diff_3d = df["primary_ratio"].diff(3)

        def _determine_direction(sma_d, raw_d):
            # Priority 1: Raw reversal — if raw 3-day change is strong AND contradicts SMA,
            # the raw is more current and SMA is lagging behind
            if raw_d > 0.015 and sma_d < 0:
                return "RISING"  # Raw reversed up but SMA still falling (lagging)
            if raw_d < -0.015 and sma_d > 0:
                return "FALLING"  # Raw reversed down but SMA still rising (lagging)
            # Priority 2: Both agree
            if sma_d > 0.003 or (sma_d > 0 and raw_d > 0.01):
                return "RISING"
            elif sma_d < -0.003 or (sma_d < 0 and raw_d < -0.01):
                return "FALLING"
            # Priority 3: Raw alone is strong enough
            elif raw_d > 0.02:
                return "RISING"
            elif raw_d < -0.02:
                return "FALLING"
            else:
                return "FLAT"

        df["sma_direction"] = [
            _determine_direction(s, r) if not (pd.isna(s) or pd.isna(r)) else "FLAT"
            for s, r in zip(sma_diff_3d, raw_diff_3d)
        ]

        # Regime classification for each day
        df["regime"] = df["primary_ratio"].apply(get_regime)
        df["leading_regime"] = df["leading_ratio"].apply(get_leading_regime)

        return df.dropna()

    except Exception as e:
        logger.error(f"Failed to fetch VIX data: {e}")
        return None


def _load_state() -> dict:
    """Load persisted state."""
    try:
        if _STATE_FILE.exists():
            with open(_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_regime": "CONTANGO",
        "last_primary_ratio": 0.90,
        "last_leading_ratio": 0.88,
        "last_sma5": 0.90,
        "last_alert_level": "SAFE",
        "backwardation_peak_ratio": None,
        "backwardation_peak_date": None,
        "cycle_state": "NORMAL",
    }


def _save_state(state: dict):
    """Persist state."""
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save VIX state: {e}")


def _load_cache() -> Optional[dict]:
    """Load cached result if fresh enough."""
    try:
        if _CACHE_FILE.exists():
            with open(_CACHE_FILE) as f:
                data = json.load(f)
            age = time.time() - data.get("_cached_at", 0)
            if age < _CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _save_cache(result: dict):
    """Cache result to disk."""
    try:
        result["_cached_at"] = time.time()
        with open(_CACHE_FILE, "w") as f:
            json.dump(result, f, indent=2, default=str)
    except Exception:
        pass


import time


def analyze_vix_regime(force: bool = False) -> dict:
    """
    Full VIX regime analysis.
    Returns regime state, transition, alert, sizing, sparkline data.
    """
    # Check cache first
    if not force:
        cached = _load_cache()
        if cached:
            cached.pop("_cached_at", None)
            return cached

    df = fetch_vix_data(days=30)
    if df is None or len(df) < 6:
        return {"error": "Unable to fetch VIX data"}

    # Current values (latest row)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    vix = float(latest["VIX"])
    vix3m = float(latest["VIX3M"])
    vix9d = float(latest["VIX9D"])
    primary_ratio = float(latest["primary_ratio"])
    leading_ratio = float(latest["leading_ratio"])
    sma5 = float(latest["primary_sma5"])
    daily_delta = float(latest["primary_delta"])
    sma_direction = str(latest["sma_direction"])

    # Current regime
    regime = get_regime(primary_ratio)
    leading_regime = get_leading_regime(leading_ratio)

    # Load previous state for transition detection
    state = _load_state()
    prev_regime = state.get("last_regime", "CONTANGO")
    cycle_state = state.get("cycle_state", "NORMAL")

    # Track backwardation peaks
    if regime in ("BACKWARDATION", "DEEP_BACKWARDATION"):
        cycle_state = "IN_BACKWARDATION"
        peak = state.get("backwardation_peak_ratio") or 0
        if primary_ratio > peak:
            state["backwardation_peak_ratio"] = primary_ratio
            state["backwardation_peak_date"] = datetime.now().isoformat()
    elif cycle_state == "IN_BACKWARDATION" and regime in ("FLAT", "CONTANGO"):
        cycle_state = "POST_BACKWARDATION"
    elif cycle_state == "POST_BACKWARDATION" and primary_ratio < 0.90:
        cycle_state = "NORMAL"
        state["backwardation_peak_ratio"] = None
        state["backwardation_peak_date"] = None

    # Detect transition
    transition = detect_transition(prev_regime, regime, sma_direction,
                                    leading_ratio, daily_delta)

    # Position size multiplier
    size_mult = position_size_multiplier(primary_ratio, sma_direction, leading_ratio)

    # Alert level
    alert = get_alert_level(primary_ratio, leading_ratio, sma_direction,
                            daily_delta, cycle_state)

    # Sparkline data (last 20 trading days)
    sparkline = []
    for _, row in df.tail(20).iterrows():
        sparkline.append({
            "date": row.name.strftime("%m/%d") if hasattr(row.name, 'strftime') else str(row.name),
            "primary_ratio": round(float(row["primary_ratio"]), 4),
            "leading_ratio": round(float(row["leading_ratio"]), 4),
            "regime": str(row["regime"]),
        })

    # 5-day trend data
    trend_5d = []
    for _, row in df.tail(5).iterrows():
        trend_5d.append({
            "date": row.name.strftime("%m/%d") if hasattr(row.name, 'strftime') else str(row.name),
            "primary_ratio": round(float(row["primary_ratio"]), 4),
            "delta": round(float(row["primary_delta"]), 4),
            "sma_direction": str(row["sma_direction"]),
        })

    # Historical context: VIX percentile (where current VIX sits vs last year)
    try:
        vix_1y = yf.Ticker("^VIX").history(period="1y")["Close"]
        vix3m_1y = yf.Ticker("^VIX3M").history(period="1y")["Close"]

        # Normalize timezones for 1y data too
        vix_1y.index = vix_1y.index.tz_convert(None).normalize() if vix_1y.index.tz else vix_1y.index.normalize()
        vix3m_1y.index = vix3m_1y.index.tz_convert(None).normalize() if vix3m_1y.index.tz else vix3m_1y.index.normalize()

        vix_percentile = round(float((vix_1y < vix).mean() * 100), 1)

        # Primary ratio percentile
        ratio_1y = vix_1y / vix3m_1y
        ratio_1y = ratio_1y.dropna()
        ratio_percentile = round(float((ratio_1y < primary_ratio).mean() * 100), 1)
    except Exception:
        vix_percentile = None
        ratio_percentile = None

    # Update & save state
    state.update({
        "last_regime": regime,
        "last_primary_ratio": primary_ratio,
        "last_leading_ratio": leading_ratio,
        "last_sma5": sma5,
        "last_alert_level": alert["level"],
        "cycle_state": cycle_state,
    })
    _save_state(state)

    result = {
        "timestamp": datetime.now().isoformat(),

        # Raw values
        "vix": round(vix, 2),
        "vix3m": round(vix3m, 2),
        "vix9d": round(vix9d, 2),

        # Ratios
        "primary_ratio": round(primary_ratio, 4),
        "leading_ratio": round(leading_ratio, 4),
        "sma5": round(sma5, 4),
        "daily_delta": round(daily_delta, 4),
        "sma_direction": sma_direction,

        # Classification
        "regime": regime,
        "leading_regime": leading_regime,
        "delta_magnitude": get_delta_magnitude(daily_delta),

        # Transition
        "transition": transition["transition"],
        "transition_conviction": transition["conviction"],
        "prev_regime": prev_regime,
        "cycle_state": cycle_state,

        # Position sizing
        "size_multiplier": round(size_mult, 2),

        # Alert
        "alert": alert,

        # Percentiles
        "vix_percentile": vix_percentile,
        "ratio_percentile": ratio_percentile,

        # Sparkline (20 days)
        "sparkline": sparkline,

        # 5-day trend
        "trend_5d": trend_5d,

        # Backwardation tracking
        "backwardation_peak": state.get("backwardation_peak_ratio"),
        "backwardation_peak_date": state.get("backwardation_peak_date"),
    }

    _save_cache(result)
    logger.info(f"VIX Regime: {regime} | Ratio: {primary_ratio:.4f} | Direction: {sma_direction} | "
                f"Alert: {alert['level']} | Size: {size_mult:.0%} | Transition: {transition['transition']}")

    return result


def get_regime_summary_for_ai() -> str:
    """Generate a compact text summary for AI prompts."""
    data = analyze_vix_regime()
    if "error" in data:
        return "VIX数据不可用"

    lines = [
        f"VIX期限结构分析:",
        f"  VIX9D={data['vix9d']} | VIX(30D)={data['vix']} | VIX3M={data['vix3m']}",
        f"  主要比率(VIX/VIX3M): {data['primary_ratio']:.4f} → {data['regime']}",
        f"  前导指标(VIX9D/VIX): {data['leading_ratio']:.4f} → {data['leading_regime']}",
        f"  5日趋势: {data['sma_direction']} | 日变动: {data['daily_delta']:+.4f} ({data['delta_magnitude']})",
        f"  VIX历史分位: {data['vix_percentile']}% | 比率分位: {data['ratio_percentile']}%",
        f"  状态: {data['transition']} (确信度: {data['transition_conviction']})",
        f"  仓位建议: {data['size_multiplier']:.0%}",
        f"  警报等级: {data['alert']['level']}",
        f"  建议: {data['alert']['action']}",
    ]

    if data.get("backwardation_peak"):
        lines.append(f"  近期Backwardation峰值: {data['backwardation_peak']:.4f} ({data['backwardation_peak_date']})")

    # 5-day trend
    if data.get("trend_5d"):
        trend_str = " → ".join([f"{t['primary_ratio']:.3f}" for t in data["trend_5d"]])
        lines.append(f"  5日走势: {trend_str}")

    return "\n".join(lines)
