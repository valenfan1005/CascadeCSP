"""
Trend Ribbon (变色趋势通道) Service
====================================
Calculates EMA ribbon data for candlestick + trend visualization.
- Purple ribbon = bullish (EMA_fast > EMA_slow)
- Orange ribbon = bearish (EMA_fast < EMA_slow)
- "变" markers at crossover points
"""

import logging
import yfinance as yf
import pandas as pd
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

# Default EMA parameters
EMA_FAST = 13
EMA_SLOW = 34
EMA_LONG = 120  # Long-term trend line (white line in the original)


def calculate_trend_ribbon(
    ticker: str = "QQQ",
    period: str = "1y",
    interval: str = "1d",
    ema_fast: int = EMA_FAST,
    ema_slow: int = EMA_SLOW,
    ema_long: int = EMA_LONG,
) -> Optional[dict]:
    """Calculate trend ribbon data for a given ticker."""
    try:
        # Smart period constraints for different intervals
        # yfinance: intraday (1m-90m) max 60 days, weekly/monthly unlimited
        if interval in ("1m", "2m", "5m"):
            period = "7d"
        elif interval in ("15m", "30m", "60m", "90m"):
            period = "60d"  # max for intraday
        elif interval == "1wk":
            if period in ("3mo", "6mo"):
                period = "5y"  # need more data for weekly to fill ema_long
            elif period == "1y":
                period = "5y"
            elif period == "2y":
                period = "10y"

        df = yf.download(ticker, period=period, interval=interval, progress=False)

        # For intraday/weekly, allow fewer bars if ema_long is too demanding
        min_bars = min(ema_long, max(60, len(df) // 2)) if interval != "1d" else ema_long
        if df.empty or len(df) < min_bars:
            logger.warning(f"Not enough data for {ticker} ({interval}): {len(df)} rows, need {min_bars}")
            return None

        # Flatten multi-level columns if needed
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        open_ = df["Open"]
        volume = df["Volume"]

        # Calculate EMAs
        ema_f = close.ewm(span=ema_fast, adjust=False).mean()
        ema_s = close.ewm(span=ema_slow, adjust=False).mean()
        ema_l = close.ewm(span=ema_long, adjust=False).mean()

        # Ribbon width (strength)
        ribbon_width = ((ema_f - ema_s) / close * 100).round(3)  # as % of price

        # Trend direction
        trend = pd.Series("bullish", index=df.index)
        trend[ema_f < ema_s] = "bearish"

        # Detect crossover points ("变")
        prev_trend = trend.shift(1)
        crossovers = trend != prev_trend
        crossover_type = pd.Series("", index=df.index)
        crossover_type[(crossovers) & (trend == "bullish")] = "golden_cross"  # 金叉
        crossover_type[(crossovers) & (trend == "bearish")] = "death_cross"  # 死叉

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # Bollinger Bands (for overbought/oversold candle coloring)
        bb_ma = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_ma + 2 * bb_std
        bb_lower = bb_ma - 2 * bb_std

        # Volume MA
        vol_ma20 = volume.rolling(20).mean()

        # Ribbon width rolling stats (for 蓄势/落势 detection)
        abs_ribbon = ribbon_width.abs()
        ribbon_ma10 = abs_ribbon.rolling(10).mean()
        vol_ma10 = volume.rolling(10).mean()

        # Candle color logic:
        # yellow = overbought (RSI > 70 OR close > BB upper)
        # blue = oversold (RSI < 30 OR close < BB lower)
        # normal = green (up) / red (down)
        def _candle_color(i):
            r = rsi.iloc[i] if not pd.isna(rsi.iloc[i]) else 50
            c = close.iloc[i]
            bbu = bb_upper.iloc[i] if not pd.isna(bb_upper.iloc[i]) else float('inf')
            bbl = bb_lower.iloc[i] if not pd.isna(bb_lower.iloc[i]) else 0
            if r > 70 or c > bbu:
                return "overbought"  # yellow
            elif r < 30 or c < bbl:
                return "oversold"  # blue
            return "normal"

        # 蓄势/落势/底部信号 detection
        def _phase_signal(i):
            if i < 15:
                return None
            rw = abs_ribbon.iloc[i] if not pd.isna(abs_ribbon.iloc[i]) else 0
            rw_ma = ribbon_ma10.iloc[i] if not pd.isna(ribbon_ma10.iloc[i]) else 0
            r = rsi.iloc[i] if not pd.isna(rsi.iloc[i]) else 50
            vr = (volume.iloc[i] / vol_ma10.iloc[i]) if not pd.isna(vol_ma10.iloc[i]) and vol_ma10.iloc[i] > 0 else 1
            t = trend.iloc[i]

            # 蓄势 (accumulation): ribbon narrowing + low volatility + volume shrinking
            if rw < 0.3 and rw < rw_ma * 0.6 and vr < 0.8:
                return "accumulation"  # 蓄势

            # 落势 (declining): bearish trend + ribbon widening + strong momentum
            if t == "bearish" and rw > 1.0 and rw > rw_ma * 1.3:
                return "declining"  # 落势

            # 底部信号 (bottom): oversold + volume spike + near support
            if r < 30 and vr > 1.5:
                return "bottom_signal"  # 🔔

            return None

        # Build candlestick + ribbon data
        # Skip initial rows to allow EMA convergence; adjust for shorter datasets
        start_idx = max(min(ema_long, len(df) - 20), 60)
        if start_idx >= len(df):
            start_idx = max(20, len(df) // 2)
        result_data = []

        # Date format: include time for intraday intervals
        is_intraday = interval in ("1m", "2m", "5m", "15m", "30m", "60m", "90m")

        for i in range(start_idx, len(df)):
            idx = df.index[i]
            date_str = idx.strftime("%m-%d %H:%M") if is_intraday else idx.strftime("%Y-%m-%d")

            candle_state = _candle_color(i)
            phase = _phase_signal(i)

            row = {
                "date": date_str,
                "open": round(float(open_.iloc[i]), 2),
                "high": round(float(high.iloc[i]), 2),
                "low": round(float(low.iloc[i]), 2),
                "close": round(float(close.iloc[i]), 2),
                "volume": int(volume.iloc[i]),
                "ema_fast": round(float(ema_f.iloc[i]), 2),
                "ema_slow": round(float(ema_s.iloc[i]), 2),
                "ema_long": round(float(ema_l.iloc[i]), 2),
                "trend": str(trend.iloc[i]),
                "ribbon_width": float(ribbon_width.iloc[i]),
                "rsi": round(float(rsi.iloc[i]), 1) if not pd.isna(rsi.iloc[i]) else None,
                "vol_ratio": round(float(volume.iloc[i] / vol_ma20.iloc[i]), 2) if not pd.isna(vol_ma20.iloc[i]) and vol_ma20.iloc[i] > 0 else None,
                "candle_state": candle_state,
            }

            # Add phase signal
            if phase:
                row["phase"] = phase

            # Add crossover marker
            if crossover_type.iloc[i]:
                row["crossover"] = str(crossover_type.iloc[i])

            result_data.append(row)

        # Current status summary
        latest = result_data[-1] if result_data else {}
        prev_cross = None
        for d in reversed(result_data):
            if d.get("crossover"):
                prev_cross = d
                break

        # Count consecutive days in current trend
        consecutive = 0
        current_trend = latest.get("trend", "")
        for d in reversed(result_data):
            if d["trend"] == current_trend:
                consecutive += 1
            else:
                break

        summary = {
            "ticker": ticker,
            "interval": interval,
            "current_trend": latest.get("trend", "unknown"),
            "ribbon_width": latest.get("ribbon_width", 0),
            "ribbon_strength": "strong" if abs(latest.get("ribbon_width", 0)) > 1.5 else "moderate" if abs(latest.get("ribbon_width", 0)) > 0.5 else "weak",
            "ema_fast": latest.get("ema_fast"),
            "ema_slow": latest.get("ema_slow"),
            "ema_long": latest.get("ema_long"),
            "price": latest.get("close"),
            "price_vs_long_ema": "above" if latest.get("close", 0) > latest.get("ema_long", 0) else "below",
            "rsi": latest.get("rsi"),
            "consecutive_trend_days": consecutive,
            "last_crossover": {
                "type": prev_cross.get("crossover"),
                "date": prev_cross.get("date"),
                "price": prev_cross.get("close"),
            } if prev_cross else None,
            "ema_params": {"fast": ema_fast, "slow": ema_slow, "long": ema_long},
        }

        return {
            "candles": result_data,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Trend ribbon calculation failed for {ticker}: {e}")
        return {"error": str(e)}
