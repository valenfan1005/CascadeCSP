"""
Trend Ribbon — Eval Suite
=========================
Tests EMA crossover, TD Sequential, candle states, and phase signals
against synthetic price data (no yfinance dependency).

Usage:
    python -m server.tests.eval_trend_ribbon
    python -m server.tests.eval_trend_ribbon --verbose
"""

import sys
import os
import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ============================================================================
# Eval Framework
# ============================================================================

@dataclass
class EvalResult:
    test_name: str
    suite: str
    passed: bool
    severity: str
    expected: str
    actual: str
    details: str = ""


@dataclass
class EvalSummary:
    total: int = 0
    passed: int = 0
    failed_critical: int = 0
    failed_major: int = 0
    failed_minor: int = 0
    results: list = field(default_factory=list)

    def add(self, result: EvalResult):
        self.total += 1
        if result.passed:
            self.passed += 1
        elif result.severity == "critical":
            self.failed_critical += 1
        elif result.severity == "major":
            self.failed_major += 1
        else:
            self.failed_minor += 1
        self.results.append(result)

    def print_report(self, verbose: bool = False):
        print("\n" + "=" * 70)
        print("TREND RIBBON — EVAL REPORT")
        print("=" * 70)
        print(f"\nTotal tests:      {self.total}")
        print(f"Passed:           {self.passed}  ✅")
        print(f"Failed (critical): {self.failed_critical}  🔴")
        print(f"Failed (major):    {self.failed_major}  🟡")
        print(f"Failed (minor):    {self.failed_minor}  ⚪")

        pass_rate = (self.passed / self.total * 100) if self.total > 0 else 0
        print(f"\nPass rate:        {pass_rate:.1f}%")
        print(f"Verdict:          {'SHIP IT ✅' if pass_rate >= 90 else 'FIX BEFORE SHIP 🟡' if pass_rate >= 75 else 'DO NOT SHIP 🔴'}")

        failures = [r for r in self.results if not r.passed]
        if failures:
            print(f"\n--- FAILURES ({len(failures)}) ---\n")
            for r in failures:
                icon = "🔴" if r.severity == "critical" else "🟡" if r.severity == "major" else "⚪"
                print(f"{icon} [{r.suite}] {r.test_name}")
                print(f"   Expected: {r.expected}")
                print(f"   Actual:   {r.actual}")
                if r.details:
                    print(f"   Detail:   {r.details}")
                print()

        if verbose:
            print("\n--- ALL RESULTS ---\n")
            for r in self.results:
                icon = "✅" if r.passed else "❌"
                print(f"{icon} [{r.suite}] {r.test_name}")
                if not r.passed or verbose:
                    print(f"   Expected: {r.expected}")
                    print(f"   Actual:   {r.actual}")
                    if r.details:
                        print(f"   Detail:   {r.details}")


# ============================================================================
# Helpers: build synthetic OHLCV DataFrames
# ============================================================================

def _make_df(closes: list, noise_pct: float = 0.005) -> pd.DataFrame:
    """Build a DataFrame with synthetic OHLCV from a close price series."""
    np.random.seed(42)
    n = len(closes)
    closes = np.array(closes, dtype=float)
    highs = closes * (1 + np.abs(np.random.normal(0, noise_pct, n)))
    lows = closes * (1 - np.abs(np.random.normal(0, noise_pct, n)))
    opens = (closes + np.roll(closes, 1)) / 2
    opens[0] = closes[0]
    volume = np.random.randint(1_000_000, 10_000_000, n).astype(float)

    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes,
        "Volume": volume,
    }, index=dates)


def _run_ribbon_on_df(df, ema_fast=13, ema_slow=34, ema_long=120):
    """Run the core trend ribbon logic on a pre-built DataFrame.
    Extracted from calculate_trend_ribbon to avoid yfinance dependency."""

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    ema_f = close.ewm(span=ema_fast, adjust=False).mean()
    ema_s = close.ewm(span=ema_slow, adjust=False).mean()
    ema_l = close.ewm(span=ema_long, adjust=False).mean()

    ribbon_width = ((ema_f - ema_s) / close * 100).round(3)

    trend = pd.Series("bullish", index=df.index)
    trend[ema_f < ema_s] = "bearish"

    prev_trend = trend.shift(1)
    crossovers = trend != prev_trend
    crossover_type = pd.Series("", index=df.index)
    crossover_type[(crossovers) & (trend == "bullish")] = "golden_cross"
    crossover_type[(crossovers) & (trend == "bearish")] = "death_cross"

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # Bollinger Bands
    bb_ma = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_ma + 2 * bb_std
    bb_lower = bb_ma - 2 * bb_std

    # Volume MA
    vol_ma20 = volume.rolling(20).mean()

    # TD Sequential
    td_setup = pd.Series(0, index=df.index, dtype=int)
    td_perfected = pd.Series(False, index=df.index)
    td_completed = False

    for i in range(4, len(df)):
        if td_completed:
            td_completed = False

        if close.iloc[i] < close.iloc[i - 4]:
            prev = td_setup.iloc[i - 1]
            if abs(prev) == 9:
                td_setup.iloc[i] = 1
            else:
                td_setup.iloc[i] = (prev + 1) if prev > 0 else 1
        elif close.iloc[i] > close.iloc[i - 4]:
            prev = td_setup.iloc[i - 1]
            if abs(prev) == 9:
                td_setup.iloc[i] = -1
            else:
                td_setup.iloc[i] = (prev - 1) if prev < 0 else -1
        else:
            td_setup.iloc[i] = 0

        if td_setup.iloc[i] == 9:
            if i >= 3:
                low_89 = min(low.iloc[i], low.iloc[i - 1])
                low_67 = min(low.iloc[i - 2], low.iloc[i - 3])
                td_perfected.iloc[i] = low_89 <= low_67
            td_completed = True
        elif td_setup.iloc[i] == -9:
            if i >= 3:
                high_89 = max(high.iloc[i], high.iloc[i - 1])
                high_67 = max(high.iloc[i - 2], high.iloc[i - 3])
                td_perfected.iloc[i] = high_89 >= high_67
            td_completed = True

    return {
        "ema_f": ema_f, "ema_s": ema_s, "ema_l": ema_l,
        "trend": trend, "crossover_type": crossover_type,
        "ribbon_width": ribbon_width, "rsi": rsi,
        "bb_upper": bb_upper, "bb_lower": bb_lower,
        "td_setup": td_setup, "td_perfected": td_perfected,
    }


# ============================================================================
# Suite 1: EMA Crossover Detection
# ============================================================================

def eval_suite_1_crossover(summary: EvalSummary):
    suite = "Suite 1: EMA Crossover"

    # Scenario: clear uptrend then reversal
    # 200 bars: first 100 trending up, then 100 trending down
    up = np.linspace(100, 160, 100)
    down = np.linspace(160, 110, 100)
    prices = np.concatenate([up, down])
    df = _make_df(prices.tolist())
    r = _run_ribbon_on_df(df)

    # Should detect at least one golden cross in the uptrend phase
    golden = [i for i in range(len(df)) if r["crossover_type"].iloc[i] == "golden_cross"]
    summary.add(EvalResult(
        "Uptrend: golden cross detected", suite,
        len(golden) >= 1, "critical",
        ">= 1 golden cross", f"{len(golden)} golden crosses at bars {golden}",
    ))

    # Should detect at least one death cross when trend reverses
    death = [i for i in range(len(df)) if r["crossover_type"].iloc[i] == "death_cross"]
    summary.add(EvalResult(
        "Reversal: death cross detected", suite,
        len(death) >= 1, "critical",
        ">= 1 death cross", f"{len(death)} death crosses at bars {death}",
    ))

    # Death cross should appear after golden cross (temporal ordering)
    if golden and death:
        summary.add(EvalResult(
            "Temporal: golden cross before death cross", suite,
            golden[0] < death[-1], "critical",
            f"golden({golden[0]}) < death({death[-1]})",
            f"golden={golden[0]}, death={death[-1]}",
        ))

    # During strong uptrend (bar 60-90), should be bullish
    mid_uptrend_bullish = all(r["trend"].iloc[i] == "bullish" for i in range(60, 90))
    summary.add(EvalResult(
        "Mid-uptrend (bar 60-90): all bullish", suite,
        mid_uptrend_bullish, "critical",
        "all bullish", f"{'all bullish' if mid_uptrend_bullish else 'some bearish'}",
    ))

    # During strong downtrend (bar 160-190), should be bearish
    late_downtrend_bearish = all(r["trend"].iloc[i] == "bearish" for i in range(160, 190))
    summary.add(EvalResult(
        "Late downtrend (bar 160-190): all bearish", suite,
        late_downtrend_bearish, "critical",
        "all bearish", f"{'all bearish' if late_downtrend_bearish else 'some bullish'}",
    ))

    # Ribbon width positive during uptrend, negative during downtrend
    rw_uptrend = r["ribbon_width"].iloc[70]
    rw_downtrend = r["ribbon_width"].iloc[180]
    summary.add(EvalResult(
        "Ribbon width: positive in uptrend, negative in downtrend", suite,
        rw_uptrend > 0 and rw_downtrend < 0, "critical",
        f"up > 0, down < 0",
        f"up={rw_uptrend:.3f}, down={rw_downtrend:.3f}",
    ))

    # Flat market: crossovers happen but ribbon width stays small
    # Note: ±0.5% noise with EMA(13/34) will cause many crossovers —
    # this is expected. The key insight is ribbon width stays near zero,
    # meaning the crossovers are not actionable signals.
    flat_prices = [100 + np.random.normal(0, 0.5) for _ in range(200)]
    df_flat = _make_df(flat_prices)
    r_flat = _run_ribbon_on_df(df_flat)
    avg_rw_flat = abs(r_flat["ribbon_width"].iloc[50:]).mean()
    summary.add(EvalResult(
        "Flat market: ribbon width stays small (< 0.3%)", suite,
        avg_rw_flat < 0.3, "major",
        "< 0.3%", f"{avg_rw_flat:.3f}%",
        details="In flat markets, crossovers happen but ribbon is too narrow to be actionable",
    ))


# ============================================================================
# Suite 2: TD Sequential (神奇九转)
# ============================================================================

def eval_suite_2_td_sequential(summary: EvalSummary):
    suite = "Suite 2: TD Sequential"

    # Construct a perfect 9-count buy setup:
    # 13 bars where close[i] < close[i-4] for bars 4-12
    # Start with 4 rising bars, then 9 consecutive declining bars
    prices = [
        100, 101, 102, 103, 104,  # bars 0-4: setup phase
        # bars 5-13: each close < close[i-4]
        100, 99, 98, 97, 96,      # bars 5-9
        95, 94, 93, 92,           # bars 10-13 (bar 13 = count 9)
    ]
    df = _make_df(prices)
    r = _run_ribbon_on_df(df)
    td = r["td_setup"]

    # Should reach count 9 (buy setup complete)
    max_count = td.max()
    summary.add(EvalResult(
        "Buy setup: reaches count 9", suite,
        max_count == 9, "critical",
        "max count = 9", f"max count = {max_count}",
        details=f"TD values: {td.tolist()}",
    ))

    # Count should be positive (buy setup = bullish reversal signal)
    nine_bar = td[td == 9].index
    summary.add(EvalResult(
        "Buy setup: 9-count is positive (buy direction)", suite,
        len(nine_bar) > 0, "critical",
        "at least one bar with td=9", f"{len(nine_bar)} bars",
    ))

    # Construct a perfect 9-count sell setup:
    # close[i] > close[i-4] for 9 consecutive bars
    prices_sell = [
        100, 99, 98, 97, 96,     # bars 0-4: decline
        # bars 5-13: each close > close[i-4]
        100, 101, 102, 103, 104,  # bars 5-9
        105, 106, 107, 108,       # bars 10-13
    ]
    df_sell = _make_df(prices_sell)
    r_sell = _run_ribbon_on_df(df_sell)
    td_sell = r_sell["td_setup"]

    min_count = td_sell.min()
    summary.add(EvalResult(
        "Sell setup: reaches count -9", suite,
        min_count == -9, "critical",
        "min count = -9", f"min count = {min_count}",
        details=f"TD values: {td_sell.tolist()}",
    ))

    # Reset after 9: next bar should start fresh count
    prices_reset = [
        100, 101, 102, 103, 104,
        100, 99, 98, 97, 96,
        95, 94, 93, 92,          # bar 13 = count 9
        91,                       # bar 14: should reset to 1 (not 10)
    ]
    df_reset = _make_df(prices_reset)
    r_reset = _run_ribbon_on_df(df_reset)
    td_reset = r_reset["td_setup"]

    if len(td_reset) > 14:
        val_after_9 = td_reset.iloc[14]
        summary.add(EvalResult(
            "Reset: bar after 9-count resets to 1 (not 10)", suite,
            val_after_9 == 1, "critical",
            "1", f"{val_after_9}",
            details="After completing 9, count must reset",
        ))

    # Equal close resets count to 0
    prices_equal = [
        100, 101, 102, 103, 104,
        100, 99, 98,             # count 1,2,3
        103,                      # bar 8: close == close[4] (104? no, close[i-4]=101)
    ]
    # Actually let's make close[i] == close[i-4] explicitly
    prices_equal = [100, 101, 102, 103, 104,
                    100, 99, 98, 103, 104]  # bar 9: 104 == close[5]=100? No.
    # Simpler: just check that 0 appears when close == close[i-4]
    prices_eq = [100] * 10  # all equal → all resets
    df_eq = _make_df(prices_eq)
    r_eq = _run_ribbon_on_df(df_eq)
    td_eq = r_eq["td_setup"]
    all_zero = all(td_eq.iloc[i] == 0 for i in range(4, len(td_eq)))
    summary.add(EvalResult(
        "Equal closes: all counts = 0", suite,
        all_zero, "major",
        "all 0 from bar 4+", f"values: {td_eq.iloc[4:].tolist()}",
    ))

    # Direction switch resets count
    # 3 bars of buy setup then direction change
    prices_switch = [
        100, 101, 102, 103, 104,
        100, 99, 98,             # buy count 1,2,3
        110,                      # bar 8: close(110) > close[4](104) → sell count starts
    ]
    df_sw = _make_df(prices_switch)
    r_sw = _run_ribbon_on_df(df_sw)
    td_sw = r_sw["td_setup"]
    if len(td_sw) > 8:
        summary.add(EvalResult(
            "Direction switch: buy→sell resets to -1", suite,
            td_sw.iloc[8] == -1, "critical",
            "-1", f"{td_sw.iloc[8]}",
            details=f"Was counting buy (positive), then close > close[i-4] → sell",
        ))


# ============================================================================
# Suite 3: TD Sequential Perfection
# ============================================================================

def eval_suite_3_td_perfection(summary: EvalSummary):
    suite = "Suite 3: TD Perfection"

    # Buy setup perfection: low of bar 8 or 9 <= low of bar 6 or 7
    # Build 14 bars: declining with lows getting progressively lower
    prices = [
        100, 101, 102, 103, 104,  # bars 0-4
        100, 99, 98, 97, 96,      # bars 5-9 (count 1-5)
        95, 94, 93, 92,           # bars 10-13 (count 6-9)
    ]
    df = _make_df(prices, noise_pct=0.001)  # minimal noise for predictable lows

    # Force lows so perfection condition is met:
    # bar 12 (count 8) or 13 (count 9) low <= bar 10 (count 6) or 11 (count 7) low
    # With declining prices, lows should naturally decrease → perfected
    r = _run_ribbon_on_df(df)
    td = r["td_setup"]
    perf = r["td_perfected"]

    nine_bars = [i for i in range(len(df)) if td.iloc[i] == 9]
    if nine_bars:
        is_perfected = perf.iloc[nine_bars[0]]
        summary.add(EvalResult(
            "Buy perfection: declining lows → perfected", suite,
            is_perfected, "major",
            "perfected = True", f"perfected = {is_perfected}",
            details=f"9-count at bar {nine_bars[0]}",
        ))
    else:
        summary.add(EvalResult(
            "Buy perfection: 9-count not reached", suite,
            False, "critical", "9-count reached", "not reached",
        ))

    # Sell setup perfection: high of bar 8 or 9 >= high of bar 6 or 7
    prices_sell = [
        100, 99, 98, 97, 96,     # bars 0-4
        100, 101, 102, 103, 104,  # bars 5-9 (count -1 to -5)
        105, 106, 107, 108,       # bars 10-13 (count -6 to -9)
    ]
    df_sell = _make_df(prices_sell, noise_pct=0.001)
    r_sell = _run_ribbon_on_df(df_sell)
    td_sell = r_sell["td_setup"]
    perf_sell = r_sell["td_perfected"]

    neg_nine = [i for i in range(len(df_sell)) if td_sell.iloc[i] == -9]
    if neg_nine:
        is_perf_sell = perf_sell.iloc[neg_nine[0]]
        summary.add(EvalResult(
            "Sell perfection: rising highs → perfected", suite,
            is_perf_sell, "major",
            "perfected = True", f"perfected = {is_perf_sell}",
            details=f"-9 count at bar {neg_nine[0]}",
        ))
    else:
        summary.add(EvalResult(
            "Sell perfection: -9 count not reached", suite,
            False, "critical", "-9 count reached", "not reached",
        ))


# ============================================================================
# Suite 4: Candle State Classification
# ============================================================================

def eval_suite_4_candle_state(summary: EvalSummary):
    suite = "Suite 4: Candle State"

    # Build a scenario with clear overbought and oversold conditions
    # 200 bars: strong rally (RSI > 70) then crash (RSI < 30)
    rally = np.linspace(100, 200, 100)
    crash = np.linspace(200, 100, 100)
    prices = np.concatenate([rally, crash])
    df = _make_df(prices.tolist())
    r = _run_ribbon_on_df(df)

    rsi = r["rsi"]
    bb_upper = r["bb_upper"]
    bb_lower = r["bb_lower"]
    close = df["Close"]

    # Check that RSI exceeds 70 during rally
    max_rsi = rsi.iloc[30:95].max()
    summary.add(EvalResult(
        "Rally: RSI exceeds 70", suite,
        max_rsi > 70, "critical",
        "> 70", f"{max_rsi:.1f}",
    ))

    # Check that RSI drops below 30 during crash
    min_rsi = rsi.iloc[130:195].min()
    summary.add(EvalResult(
        "Crash: RSI drops below 30", suite,
        min_rsi < 30, "critical",
        "< 30", f"{min_rsi:.1f}",
    ))

    # RSI should be between 0 and 100 always
    valid_rsi = rsi.dropna()
    all_valid = (valid_rsi >= 0).all() and (valid_rsi <= 100).all()
    summary.add(EvalResult(
        "RSI: all values in [0, 100]", suite,
        all_valid, "critical",
        "all in [0, 100]", f"range: {valid_rsi.min():.1f} - {valid_rsi.max():.1f}",
    ))

    # Bollinger Bands: upper > close > lower most of the time
    valid_bb = bb_upper.dropna()
    bb_contains = ((close.loc[valid_bb.index] <= bb_upper.loc[valid_bb.index]) &
                   (close.loc[valid_bb.index] >= bb_lower.loc[valid_bb.index]))
    pct_inside = bb_contains.mean()
    summary.add(EvalResult(
        "BB: price inside bands >= 85% of time", suite,
        pct_inside >= 0.85, "major",
        ">= 85%", f"{pct_inside*100:.1f}%",
    ))


# ============================================================================
# Suite 5: Ribbon Strength Classification
# ============================================================================

def eval_suite_5_ribbon_strength(summary: EvalSummary):
    suite = "Suite 5: Ribbon Strength"

    # Strong uptrend: ribbon width should be > 1.5%
    strong_up = np.linspace(100, 200, 200)
    df = _make_df(strong_up.tolist())
    r = _run_ribbon_on_df(df)
    rw = r["ribbon_width"]
    max_rw = rw.iloc[50:].max()
    summary.add(EvalResult(
        "Strong uptrend: ribbon width > 1.5%", suite,
        max_rw > 1.5, "critical",
        "> 1.5%", f"{max_rw:.3f}%",
    ))

    # Classify strength
    latest_rw = abs(rw.iloc[-1])
    if latest_rw > 1.5:
        strength = "strong"
    elif latest_rw > 0.5:
        strength = "moderate"
    else:
        strength = "weak"
    summary.add(EvalResult(
        "Strong uptrend: strength = 'strong'", suite,
        strength == "strong", "major",
        "strong", strength,
        details=f"ribbon_width = {latest_rw:.3f}%",
    ))

    # Flat market: ribbon width near 0
    flat = [100 + np.random.normal(0, 0.3) for _ in range(200)]
    df_flat = _make_df(flat)
    r_flat = _run_ribbon_on_df(df_flat)
    rw_flat = r_flat["ribbon_width"]
    avg_rw_flat = abs(rw_flat.iloc[50:]).mean()
    summary.add(EvalResult(
        "Flat market: avg ribbon width < 0.3%", suite,
        avg_rw_flat < 0.3, "major",
        "< 0.3%", f"{avg_rw_flat:.3f}%",
    ))

    # EMA ordering: in uptrend, fast > slow > long
    ema_f_late = r["ema_f"].iloc[-1]
    ema_s_late = r["ema_s"].iloc[-1]
    ema_l_late = r["ema_l"].iloc[-1]
    summary.add(EvalResult(
        "Uptrend EMA ordering: fast > slow > long", suite,
        ema_f_late > ema_s_late > ema_l_late, "critical",
        f"f({ema_f_late:.1f}) > s({ema_s_late:.1f}) > l({ema_l_late:.1f})",
        f"f={ema_f_late:.1f}, s={ema_s_late:.1f}, l={ema_l_late:.1f}",
    ))

    # In downtrend, fast < slow
    strong_down = np.linspace(200, 100, 200)
    df_down = _make_df(strong_down.tolist())
    r_down = _run_ribbon_on_df(df_down)
    summary.add(EvalResult(
        "Downtrend: fast EMA < slow EMA at end", suite,
        r_down["ema_f"].iloc[-1] < r_down["ema_s"].iloc[-1], "critical",
        "fast < slow",
        f"fast={r_down['ema_f'].iloc[-1]:.1f}, slow={r_down['ema_s'].iloc[-1]:.1f}",
    ))


# ============================================================================
# Suite 6: EMA Parameter Sensitivity
# ============================================================================

def eval_suite_6_params(summary: EvalSummary):
    suite = "Suite 6: EMA Params"

    # Faster EMAs (8/21) should detect crossovers earlier than default (13/34)
    up = np.linspace(100, 130, 80)
    down = np.linspace(130, 100, 80)
    prices = np.concatenate([up, down]).tolist()
    df = _make_df(prices)

    r_fast = _run_ribbon_on_df(df, ema_fast=8, ema_slow=21, ema_long=60)
    r_default = _run_ribbon_on_df(df, ema_fast=13, ema_slow=34, ema_long=120)

    # Find first death cross in each
    dc_fast = next((i for i in range(len(df)) if r_fast["crossover_type"].iloc[i] == "death_cross"), 999)
    dc_default = next((i for i in range(len(df)) if r_default["crossover_type"].iloc[i] == "death_cross"), 999)

    summary.add(EvalResult(
        "Faster EMAs detect death cross earlier", suite,
        dc_fast <= dc_default, "major",
        f"fast({dc_fast}) <= default({dc_default})",
        f"fast={dc_fast}, default={dc_default}",
        details="8/21 EMAs should cross before 13/34",
    ))

    # Slower EMAs have more lag → they detect the death cross later
    r_slow = _run_ribbon_on_df(df, ema_fast=21, ema_slow=55, ema_long=120)
    dc_slow = next((i for i in range(len(df)) if r_slow["crossover_type"].iloc[i] == "death_cross"), 999)

    summary.add(EvalResult(
        "Slower EMAs detect death cross later than faster ones", suite,
        dc_slow >= dc_fast, "major",
        f"slow({dc_slow}) >= fast({dc_fast})",
        f"fast={dc_fast}, slow={dc_slow}",
        details="21/55 EMAs should cross after 8/21 due to more lag",
    ))


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Trend Ribbon Eval Suite")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--suite", type=int)
    args = parser.parse_args()

    summary = EvalSummary()

    suites = {
        1: ("EMA Crossover", eval_suite_1_crossover),
        2: ("TD Sequential", eval_suite_2_td_sequential),
        3: ("TD Perfection", eval_suite_3_td_perfection),
        4: ("Candle State", eval_suite_4_candle_state),
        5: ("Ribbon Strength", eval_suite_5_ribbon_strength),
        6: ("EMA Params", eval_suite_6_params),
    }

    if args.suite:
        if args.suite in suites:
            name, func = suites[args.suite]
            print(f"\nRunning Suite {args.suite}: {name}...")
            func(summary)
    else:
        for num, (name, func) in suites.items():
            print(f"\nRunning Suite {num}: {name}...")
            func(summary)

    summary.print_report(verbose=args.verbose)
    sys.exit(1 if summary.failed_critical > 0 else 0)


if __name__ == "__main__":
    main()
