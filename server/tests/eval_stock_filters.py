"""
Stock Filters & Soft Score — Eval Suite
=======================================
Tests hard filters (pass/fail) and soft scoring (0-120) against synthetic stock data.

Usage:
    python -m server.tests.eval_stock_filters
    python -m server.tests.eval_stock_filters --verbose
"""

import sys
import os
import argparse
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from server.services.stock_filters import (
    earnings_filter,
    market_cap_filter,
    rsi_extreme_filter,
    option_liquidity_filter,
    price_filter,
    trend_direction_filter,
    apply_hard_filters,
    compute_soft_score,
)


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
        print("STOCK FILTERS & SOFT SCORE — EVAL REPORT")
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
# Helper: build synthetic stock dicts
# ============================================================================

def _stock(**kwargs) -> dict:
    """Create a stock dict with sensible defaults."""
    defaults = {
        "ticker": "TEST",
        "price": 150.0,
        "market_cap": 50_000_000_000,  # 50B
        "rsi": 55,
        "days_to_earnings": 45,
        "sma50": 145.0,
        "sma200": 130.0,
        "avg_option_volume": 5000,
        "finbert_sentiment": 0.0,
        "relative_strength_1m": 0,
        "trend_label": "UPTREND",
        "volatility_m": 25,
    }
    defaults.update(kwargs)
    return defaults


# ============================================================================
# Suite 1: Hard Filters — Individual
# ============================================================================

def eval_suite_1_hard_filters(summary: EvalSummary):
    suite = "Suite 1: Hard Filters"

    # --- Price filter ---
    ok, _ = price_filter({"price": 5.0})
    summary.add(EvalResult("Price: $5 → REJECT", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = price_filter({"price": 10.0})
    summary.add(EvalResult("Price: $10 → PASS", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    ok, _ = price_filter({"price": 150.0})
    summary.add(EvalResult("Price: $150 → PASS", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    # --- Market cap filter ---
    ok, _ = market_cap_filter({"market_cap": 500_000_000})
    summary.add(EvalResult("MCap: $0.5B → REJECT", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = market_cap_filter({"market_cap": 1_999_999_999})
    summary.add(EvalResult("MCap: $1.99B → REJECT (below 2B)", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = market_cap_filter({"market_cap": 2_000_000_000})
    summary.add(EvalResult("MCap: $2B → PASS (exactly 2B)", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    ok, _ = market_cap_filter({"market_cap": 50_000_000_000})
    summary.add(EvalResult("MCap: $50B → PASS", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    # --- RSI extreme filter ---
    ok, _ = rsi_extreme_filter({"rsi": 50})
    summary.add(EvalResult("RSI: 50 → PASS", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    ok, _ = rsi_extreme_filter({"rsi": 80})
    summary.add(EvalResult("RSI: 80 → PASS (boundary, not excluded)", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    ok, _ = rsi_extreme_filter({"rsi": 81})
    summary.add(EvalResult("RSI: 81 → REJECT", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = rsi_extreme_filter({"rsi": None})
    summary.add(EvalResult("RSI: None → PASS (data unavailable)", suite, ok, "minor", "PASS", "PASS" if ok else "REJECT"))

    # --- Earnings filter ---
    ok, _ = earnings_filter({"days_to_earnings": 10})
    summary.add(EvalResult("Earnings: 10 DTE → REJECT", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = earnings_filter({"days_to_earnings": 21})
    summary.add(EvalResult("Earnings: 21 DTE → REJECT (boundary)", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = earnings_filter({"days_to_earnings": 22})
    summary.add(EvalResult("Earnings: 22 DTE → PASS", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    ok, _ = earnings_filter({"days_to_earnings": None})
    summary.add(EvalResult("Earnings: None → PASS (unknown date)", suite, ok, "minor", "PASS", "PASS" if ok else "REJECT"))

    # --- Trend direction filter ---
    s = {"price": 150, "sma50": 140, "sma200": 130}
    ok, _ = trend_direction_filter(s)
    summary.add(EvalResult("Trend: price > MA50 > MA200 → PASS (uptrend)", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    s = {"price": 135, "sma50": 140, "sma200": 130}
    ok, _ = trend_direction_filter(s)
    summary.add(EvalResult("Trend: MA200 < price < MA50 → PASS (pullback)", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    s = {"price": 120, "sma50": 140, "sma200": 130}
    ok, _ = trend_direction_filter(s)
    summary.add(EvalResult("Trend: price < MA50 & MA200 → REJECT (downtrend)", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    # --- Option liquidity filter ---
    ok, _ = option_liquidity_filter({"avg_option_volume": 100})
    summary.add(EvalResult("OptVol: 100 → REJECT", suite, not ok, "critical", "REJECT", "REJECT" if not ok else "PASS"))

    ok, _ = option_liquidity_filter({"avg_option_volume": 500})
    summary.add(EvalResult("OptVol: 500 → PASS (boundary)", suite, ok, "critical", "PASS", "PASS" if ok else "REJECT"))

    ok, _ = option_liquidity_filter({"avg_option_volume": None})
    summary.add(EvalResult("OptVol: None → PASS (data unavailable)", suite, ok, "minor", "PASS", "PASS" if ok else "REJECT"))


# ============================================================================
# Suite 2: Hard Filter Pipeline (fail-fast, ordering)
# ============================================================================

def eval_suite_2_pipeline(summary: EvalSummary):
    suite = "Suite 2: Filter Pipeline"

    # Perfect stock passes all filters
    perfect = _stock()
    passed, rejected = apply_hard_filters([perfect])
    summary.add(EvalResult(
        "Perfect stock passes all hard filters", suite,
        len(passed) == 1 and len(rejected) == 0, "critical",
        "1 passed, 0 rejected", f"{len(passed)} passed, {len(rejected)} rejected",
    ))

    # Stock with multiple failures → only first reason recorded (fail-fast)
    bad = _stock(price=5, market_cap=100_000_000, rsi=85)
    passed, rejected = apply_hard_filters([bad])
    summary.add(EvalResult(
        "Multi-failure stock: fail-fast on first filter", suite,
        len(rejected) == 1, "major",
        "1 rejected", f"{len(rejected)} rejected",
        details=f"reason: {rejected[0].get('rejection_reason', 'N/A')}" if rejected else "",
    ))

    # Mixed batch: some pass, some fail
    batch = [
        _stock(ticker="GOOD1"),
        _stock(ticker="BAD1", price=5),
        _stock(ticker="GOOD2"),
        _stock(ticker="BAD2", rsi=85),
        _stock(ticker="BAD3", market_cap=100_000_000),
    ]
    passed, rejected = apply_hard_filters(batch)
    summary.add(EvalResult(
        "Mixed batch: 2 pass, 3 reject", suite,
        len(passed) == 2 and len(rejected) == 3, "critical",
        "2 passed, 3 rejected", f"{len(passed)} passed, {len(rejected)} rejected",
    ))

    # All pass
    good_batch = [_stock(ticker=f"G{i}") for i in range(5)]
    passed, rejected = apply_hard_filters(good_batch)
    summary.add(EvalResult(
        "All-good batch: 5 pass, 0 reject", suite,
        len(passed) == 5 and len(rejected) == 0, "critical",
        "5 passed, 0 rejected", f"{len(passed)} passed, {len(rejected)} rejected",
    ))


# ============================================================================
# Suite 3: Soft Score — Individual Factor Impact
# ============================================================================

def eval_suite_3_soft_score(summary: EvalSummary):
    suite = "Suite 3: Soft Score"

    # --- Baseline: neutral stock = 100 ---
    baseline = compute_soft_score(_stock())
    summary.add(EvalResult(
        "Baseline: neutral stock ≈ 100", suite,
        95 <= baseline <= 115, "critical",
        "95 - 115", f"{baseline:.1f}",
        details="All neutral factors, possible trend/vol bonuses",
    ))

    # --- Sentiment factors ---
    s = compute_soft_score(_stock(finbert_sentiment=-0.4))
    summary.add(EvalResult(
        "Strong negative sentiment → -30%", suite,
        s < baseline * 0.80, "critical",
        f"< {baseline * 0.80:.1f}", f"{s:.1f}",
    ))

    s = compute_soft_score(_stock(finbert_sentiment=-0.15))
    summary.add(EvalResult(
        "Mild negative sentiment → -15%", suite,
        s < baseline * 0.95 and s > baseline * 0.75, "major",
        f"{baseline * 0.75:.1f} - {baseline * 0.95:.1f}", f"{s:.1f}",
    ))

    s = compute_soft_score(_stock(finbert_sentiment=0.5))
    summary.add(EvalResult(
        "Strong positive sentiment → +10%", suite,
        s > baseline, "major",
        f"> {baseline:.1f}", f"{s:.1f}",
    ))

    # --- RSI penalties ---
    s = compute_soft_score(_stock(rsi=75))
    summary.add(EvalResult(
        "RSI 75 (elevated) → -15%", suite,
        s < baseline * 0.95, "critical",
        f"< {baseline * 0.95:.1f}", f"{s:.1f}",
    ))

    s = compute_soft_score(_stock(rsi=20))
    summary.add(EvalResult(
        "RSI 20 (deeply oversold) → -15%", suite,
        s < baseline * 0.95, "critical",
        f"< {baseline * 0.95:.1f}", f"{s:.1f}",
    ))

    s_normal = compute_soft_score(_stock(rsi=50))
    summary.add(EvalResult(
        "RSI 50 (neutral) → no penalty", suite,
        abs(s_normal - baseline) < 1.0, "major",
        f"≈ {baseline:.1f}", f"{s_normal:.1f}",
    ))

    # --- Relative strength ---
    s = compute_soft_score(_stock(relative_strength_1m=-15))
    summary.add(EvalResult(
        "RelStrength -15% → -20%", suite,
        s < baseline * 0.90, "critical",
        f"< {baseline * 0.90:.1f}", f"{s:.1f}",
    ))

    s = compute_soft_score(_stock(relative_strength_1m=15))
    summary.add(EvalResult(
        "RelStrength +15% → +5%", suite,
        s > baseline, "major",
        f"> {baseline:.1f}", f"{s:.1f}",
    ))

    # --- Earnings proximity ---
    s = compute_soft_score(_stock(days_to_earnings=25))
    summary.add(EvalResult(
        "Earnings in 25 days → -25%", suite,
        s < baseline * 0.85, "critical",
        f"< {baseline * 0.85:.1f}", f"{s:.1f}",
    ))

    s = compute_soft_score(_stock(days_to_earnings=45))
    s2 = compute_soft_score(_stock(days_to_earnings=36))
    summary.add(EvalResult(
        "Earnings in 36+ days → no penalty", suite,
        abs(s2 - baseline) < 5 or s2 >= baseline * 0.95, "major",
        f"≈ {baseline:.1f}", f"36d={s2:.1f}, 45d={s:.1f}",
    ))

    # --- Option liquidity gradient ---
    s = compute_soft_score(_stock(avg_option_volume=700))
    summary.add(EvalResult(
        "OptVol 700 (marginal) → -10%", suite,
        s < baseline * 0.98, "major",
        f"< {baseline * 0.98:.1f}", f"{s:.1f}",
    ))

    # --- Volatility bonus ---
    s = compute_soft_score(_stock(volatility_m=45))
    summary.add(EvalResult(
        "Volatility 45% → +10%", suite,
        s > baseline, "major",
        f"> {baseline:.1f}", f"{s:.1f}",
    ))

    s = compute_soft_score(_stock(volatility_m=35))
    summary.add(EvalResult(
        "Volatility 35% → +5%", suite,
        s > baseline * 0.99, "minor",
        f"> {baseline * 0.99:.1f}", f"{s:.1f}",
    ))

    # --- Trend bonus ---
    s_up = compute_soft_score(_stock(trend_label="UPTREND"))
    s_pb = compute_soft_score(_stock(trend_label="PULLBACK"))
    summary.add(EvalResult(
        "Uptrend scores >= pullback", suite,
        s_up >= s_pb, "major",
        f"uptrend >= pullback", f"uptrend={s_up:.1f}, pullback={s_pb:.1f}",
    ))


# ============================================================================
# Suite 4: Soft Score — Compound Effects & Ranking
# ============================================================================

def eval_suite_4_compound(summary: EvalSummary):
    suite = "Suite 4: Compound & Ranking"

    # --- Perfect CSP candidate: all bonuses ---
    perfect = _stock(
        finbert_sentiment=0.5,    # +10%
        rsi=50,                    # neutral
        relative_strength_1m=12,   # +5%
        days_to_earnings=60,       # clear
        avg_option_volume=5000,    # good
        trend_label="UPTREND",     # +5%
        volatility_m=45,           # +10%
    )
    s = compute_soft_score(perfect)
    summary.add(EvalResult(
        "Perfect candidate: all bonuses stacked", suite,
        s >= 115, "critical",
        ">= 115", f"{s:.1f}",
        details="sentiment+10%, relStr+5%, trend+5%, vol+10% = should be near cap",
    ))

    # --- Worst non-excluded stock: all penalties ---
    worst = _stock(
        finbert_sentiment=-0.4,    # -30%
        rsi=75,                    # -15%
        relative_strength_1m=-15,  # -20%
        days_to_earnings=25,       # -25%
        avg_option_volume=700,     # -10%
        trend_label="PULLBACK",    # neutral
        volatility_m=15,           # no bonus
    )
    s = compute_soft_score(worst)
    summary.add(EvalResult(
        "Worst non-excluded: all penalties stacked", suite,
        s < 40, "critical",
        "< 40", f"{s:.1f}",
        details="Multiplicative penalties: 0.70 * 0.85 * 0.80 * 0.75 * 0.90 = 0.32 → ~32",
    ))

    # --- Cap at 120 ---
    s = compute_soft_score(perfect, base_score=130)
    summary.add(EvalResult(
        "Score capped at 120 (base=130 with bonuses)", suite,
        s <= 120.0, "critical",
        "<= 120.0", f"{s:.1f}",
    ))

    # --- Score >= 0 with extreme penalties ---
    s = compute_soft_score(worst, base_score=50)
    summary.add(EvalResult(
        "Score >= 0 with extreme penalties", suite,
        s >= 0, "critical",
        ">= 0", f"{s:.1f}",
    ))

    # --- Ranking: perfect > neutral > worst ---
    s_perfect = compute_soft_score(_stock(
        finbert_sentiment=0.5, relative_strength_1m=12,
        trend_label="UPTREND", volatility_m=45,
    ))
    s_neutral = compute_soft_score(_stock())
    s_bad = compute_soft_score(_stock(
        finbert_sentiment=-0.4, relative_strength_1m=-15,
        days_to_earnings=25,
    ))
    summary.add(EvalResult(
        "Ranking: perfect > neutral > penalty-heavy", suite,
        s_perfect > s_neutral > s_bad, "critical",
        f"perfect({s_perfect:.1f}) > neutral({s_neutral:.1f}) > bad({s_bad:.1f})",
        f"{s_perfect:.1f} > {s_neutral:.1f} > {s_bad:.1f}",
    ))

    # --- Two similar stocks: sentiment is the tiebreaker ---
    s_pos = compute_soft_score(_stock(finbert_sentiment=0.4))
    s_neg = compute_soft_score(_stock(finbert_sentiment=-0.2))
    summary.add(EvalResult(
        "Sentiment tiebreaker: positive > negative", suite,
        s_pos > s_neg, "major",
        f"pos({s_pos:.1f}) > neg({s_neg:.1f})",
        f"{s_pos:.1f} > {s_neg:.1f}",
    ))

    # --- Earnings approaching should meaningfully drop score ---
    s_clear = compute_soft_score(_stock(days_to_earnings=60))
    s_near = compute_soft_score(_stock(days_to_earnings=25))
    diff = s_clear - s_near
    summary.add(EvalResult(
        "Earnings proximity: 60d vs 25d → meaningful gap", suite,
        diff >= 15, "critical",
        f"gap >= 15", f"gap = {diff:.1f} (60d={s_clear:.1f}, 25d={s_near:.1f})",
    ))


# ============================================================================
# Suite 5: Edge Cases
# ============================================================================

def eval_suite_5_edges(summary: EvalSummary):
    suite = "Suite 5: Edge Cases"

    # Missing all optional fields
    bare = {"ticker": "BARE", "price": 100, "market_cap": 10_000_000_000}
    s = compute_soft_score(bare)
    summary.add(EvalResult(
        "Bare stock (missing sentiment, RSI, etc.) → score ≈ baseline", suite,
        80 <= s <= 110, "major",
        "80 - 110", f"{s:.1f}",
        details="Missing fields default to neutral, should not crash",
    ))

    # None values for numeric fields
    none_stock = _stock(
        finbert_sentiment=None, rsi=None, relative_strength_1m=None,
        days_to_earnings=None, avg_option_volume=None, volatility_m=None,
    )
    s = compute_soft_score(none_stock)
    summary.add(EvalResult(
        "All numeric fields = None → no crash, score ≈ baseline", suite,
        80 <= s <= 115, "critical",
        "80 - 115", f"{s:.1f}",
    ))

    # Zero market cap
    ok, _ = market_cap_filter({"market_cap": 0})
    summary.add(EvalResult(
        "Market cap = 0 → REJECT", suite,
        not ok, "major",
        "REJECT", "REJECT" if not ok else "PASS",
    ))

    # Negative price
    ok, _ = price_filter({"price": -5})
    summary.add(EvalResult(
        "Negative price → REJECT", suite,
        not ok, "minor",
        "REJECT", "REJECT" if not ok else "PASS",
    ))


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Stock Filters & Soft Score Eval")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--suite", type=int)
    args = parser.parse_args()

    summary = EvalSummary()

    suites = {
        1: ("Hard Filters", eval_suite_1_hard_filters),
        2: ("Filter Pipeline", eval_suite_2_pipeline),
        3: ("Soft Score", eval_suite_3_soft_score),
        4: ("Compound & Ranking", eval_suite_4_compound),
        5: ("Edge Cases", eval_suite_5_edges),
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
