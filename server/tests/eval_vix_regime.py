"""
Production VIX Regime Detection — Eval Suite
=============================================
Tests the production vix_regime.py module against known scenarios.

Usage:
    python -m server.tests.eval_vix_regime
    python -m server.tests.eval_vix_regime --verbose
"""

import sys
import os
import argparse
from dataclasses import dataclass, field

import numpy as np

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from server.services.vix_regime import (
    get_regime,
    get_leading_regime,
    get_delta_magnitude,
    detect_transition,
    position_size_multiplier,
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
        print("PRODUCTION VIX REGIME — EVAL REPORT")
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


# ============================================================================
# Suite 1: Regime Classification (production thresholds)
# Production uses: <0.85 DEEP_CONTANGO, <0.95 CONTANGO, <=1.05 FLAT,
#                  <=1.15 BACKWARDATION, else DEEP_BACKWARDATION
# ============================================================================

def eval_suite_1(summary: EvalSummary):
    suite = "Suite 1: Regime Classification"

    cases = [
        (0.80, "DEEP_CONTANGO", "Deep contango — very low ratio", "critical"),
        (0.84, "DEEP_CONTANGO", "Deep contango boundary (below 0.85)", "critical"),
        (0.85, "CONTANGO", "Contango lower boundary (exactly 0.85)", "major"),
        (0.90, "CONTANGO", "Contango midpoint", "critical"),
        (0.94, "CONTANGO", "Contango upper edge (just below 0.95)", "major"),
        (0.95, "FLAT", "Flat lower boundary (exactly 0.95)", "critical"),
        (1.00, "FLAT", "Flat midpoint — ratio at parity", "critical"),
        (1.05, "FLAT", "Flat upper boundary (exactly 1.05, inclusive)", "critical"),
        (1.06, "BACKWARDATION", "Backwardation (just above 1.05)", "critical"),
        (1.10, "BACKWARDATION", "Backwardation midpoint", "critical"),
        (1.15, "BACKWARDATION", "Backwardation upper boundary (exactly 1.15, inclusive)", "critical"),
        (1.16, "DEEP_BACKWARDATION", "Deep backwardation (above 1.15)", "critical"),
        (1.30, "DEEP_BACKWARDATION", "Deep backwardation — extreme", "critical"),
    ]

    for ratio, expected, name, severity in cases:
        actual = get_regime(ratio)
        summary.add(EvalResult(
            test_name=name, suite=suite,
            passed=(actual == expected), severity=severity,
            expected=expected, actual=actual,
        ))

    # Leading indicator
    leading_cases = [
        (0.85, "NORMAL", "Leading normal — VIX9D well below VIX", "critical"),
        (0.94, "NORMAL", "Leading normal — just below 0.95", "critical"),
        (0.95, "ELEVATED", "Leading elevated lower boundary", "critical"),
        (1.00, "ELEVATED", "Leading elevated midpoint", "critical"),
        (1.05, "ELEVATED", "Leading elevated upper boundary (inclusive)", "critical"),
        (1.06, "SPIKING", "Leading spiking (above 1.05)", "critical"),
        (1.20, "SPIKING", "Leading spiking — extreme", "critical"),
    ]

    for ratio, expected, name, severity in leading_cases:
        actual = get_leading_regime(ratio)
        summary.add(EvalResult(
            test_name=name, suite=suite,
            passed=(actual == expected), severity=severity,
            expected=expected, actual=actual,
        ))

    # Delta magnitude
    delta_cases = [
        (0.005, "NOISE", "Small delta = noise", "minor"),
        (0.02, "MEANINGFUL", "Medium delta = meaningful", "minor"),
        (0.04, "FAST", "Large delta = fast", "minor"),
    ]

    for delta, expected, name, severity in delta_cases:
        actual = get_delta_magnitude(delta)
        summary.add(EvalResult(
            test_name=name, suite=suite,
            passed=(actual == expected), severity=severity,
            expected=expected, actual=actual,
        ))


# ============================================================================
# Suite 2: Transition Detection
# ============================================================================

def eval_suite_2(summary: EvalSummary):
    suite = "Suite 2: Transitions"

    cases = [
        # (prev, curr, direction, leading_ratio, delta, expected_transition, name, severity)
        ("DEEP_CONTANGO", "CONTANGO", "RISING", 0.90, 0.02,
         "EARLY_WARNING", "DC→C rising = early warning", "critical"),
        ("CONTANGO", "FLAT", "RISING", 0.92, 0.02,
         "EARLY_WARNING", "C→FLAT rising = early warning", "critical"),
        ("FLAT", "BACKWARDATION", "RISING", 1.08, 0.03,
         "CRISIS", "FLAT→BACK rising + fast delta = crisis override", "critical"),
        ("BACKWARDATION", "DEEP_BACKWARDATION", "RISING", 1.15, 0.04,
         "CRISIS", "BACK→DBACK rising = crisis", "critical"),
        ("DEEP_BACKWARDATION", "BACKWARDATION", "FALLING", 1.02, -0.03,
         "POSSIBLE_GOLDEN", "DBACK→BACK falling = possible golden", "major"),
        ("BACKWARDATION", "FLAT", "FALLING", 0.90, -0.03,
         "GOLDEN_WINDOW", "BACK→FLAT falling + normal leading = golden", "critical"),
        ("FLAT", "CONTANGO", "FALLING", 0.88, -0.02,
         "RECOVERY", "FLAT→C falling = recovery", "major"),
        # Same-regime deterioration
        ("BACKWARDATION", "BACKWARDATION", "RISING", 1.10, 0.02,
         "CRISIS", "BACK staying BACK + rising = crisis", "critical"),
        ("FLAT", "FLAT", "RISING", 0.98, 0.01,
         "EARLY_WARNING", "FLAT staying FLAT + rising = early warning", "major"),
        # Fast spike override
        ("FLAT", "FLAT", "FLAT", 0.98, 0.04,
         "DANGER", "FLAT + fast positive delta = danger override", "critical"),
    ]

    for prev, curr, direction, lr, delta, expected, name, severity in cases:
        result = detect_transition(prev, curr, direction, lr, delta)
        actual = result["transition"]
        summary.add(EvalResult(
            test_name=name, suite=suite,
            passed=(actual == expected), severity=severity,
            expected=expected, actual=actual,
        ))


# ============================================================================
# Suite 3: Position Sizing
# ============================================================================

def eval_suite_3(summary: EvalSummary):
    suite = "Suite 3: Position Sizing"

    cases = [
        # (ratio, direction, leading_ratio, expected_range, name, severity)
        (0.80, "FLAT", 0.90, (1.0, 1.0),
         "Deep contango = full size", "critical"),
        (0.90, "RISING", 0.92, (0.8, 0.9),
         "Contango + rising = slightly reduced", "critical"),
        (0.90, "FALLING", 0.92, (0.9, 1.0),
         "Contango + falling = full size", "critical"),
        (1.00, "RISING", 0.92, (0.4, 0.6),
         "Flat + rising = reduced", "critical"),
        (1.00, "FALLING", 0.92, (0.6, 0.8),
         "Flat + falling = moderate", "critical"),
        (1.10, "RISING", 1.10, (0.0, 0.0),
         "Backwardation + rising = zero", "critical"),
        (1.10, "FALLING", 0.90, (0.4, 0.6),
         "Backwardation + falling + normal leading = golden sizing", "critical"),
        (1.10, "FALLING", 1.10, (0.0, 0.0),
         "Backwardation + falling + spiking leading = zero", "critical"),
    ]

    for ratio, direction, lr, (lo, hi), name, severity in cases:
        actual = position_size_multiplier(ratio, direction, lr)
        summary.add(EvalResult(
            test_name=name, suite=suite,
            passed=(lo <= actual <= hi), severity=severity,
            expected=f"{lo:.1f} - {hi:.1f}",
            actual=f"{actual:.2f}",
        ))

    # Monotonicity: as ratio worsens, sizing should decrease
    ratios = [0.80, 0.90, 0.98, 1.10, 1.20]
    mults = [position_size_multiplier(r, "FLAT", 0.92) for r in ratios]
    is_monotonic = all(mults[i] >= mults[i + 1] for i in range(len(mults) - 1))
    summary.add(EvalResult(
        test_name="Monotonicity: sizing decreases as ratio worsens",
        suite=suite,
        passed=is_monotonic, severity="critical",
        expected="Monotonically decreasing",
        actual=f"Values: {[f'{m:.2f}' for m in mults]}",
    ))


# ============================================================================
# Suite 4: Transition Conviction (leading indicator confirmation)
# ============================================================================

def eval_suite_4(summary: EvalSummary):
    suite = "Suite 4: Conviction"

    # Danger with spiking leading = HIGH conviction (use delta=0.02 to avoid FAST override)
    r = detect_transition("FLAT", "BACKWARDATION", "RISING", 1.10, 0.02)
    summary.add(EvalResult(
        test_name="Danger + spiking leading = HIGH conviction",
        suite=suite,
        passed=(r["conviction"] == "HIGH"), severity="major",
        expected="HIGH", actual=r["conviction"],
        details=f"transition={r['transition']}",
    ))

    # Danger with normal leading = LOW conviction
    r = detect_transition("FLAT", "BACKWARDATION", "RISING", 0.90, 0.02)
    summary.add(EvalResult(
        test_name="Danger + normal leading = LOW conviction",
        suite=suite,
        passed=(r["conviction"] == "LOW"), severity="major",
        expected="LOW", actual=r["conviction"],
        details=f"transition={r['transition']}",
    ))

    # Golden + normal leading = HIGH conviction
    r = detect_transition("BACKWARDATION", "FLAT", "FALLING", 0.90, -0.03)
    summary.add(EvalResult(
        test_name="Golden + normal leading = HIGH conviction",
        suite=suite,
        passed=(r["conviction"] == "HIGH"), severity="major",
        expected="HIGH", actual=r["conviction"],
    ))

    # Golden + spiking leading = downgraded to POSSIBLE_GOLDEN
    r = detect_transition("BACKWARDATION", "FLAT", "FALLING", 1.10, -0.03)
    summary.add(EvalResult(
        test_name="Golden + spiking leading = downgraded to POSSIBLE_GOLDEN",
        suite=suite,
        passed=(r["transition"] == "POSSIBLE_GOLDEN"), severity="major",
        expected="POSSIBLE_GOLDEN", actual=r["transition"],
    ))


# ============================================================================
# Suite 5: Hysteresis & Golden Window Duration
# ============================================================================

def eval_suite_5(summary: EvalSummary):
    suite = "Suite 5: Hysteresis & Golden Window"

    # --- Hysteresis at 0.95 boundary ---
    # From CONTANGO, need > 0.965 to switch to FLAT
    r = get_regime(0.96, prev_regime="CONTANGO")
    summary.add(EvalResult(
        "Hysteresis: 0.96 from CONTANGO stays CONTANGO", suite,
        r == "CONTANGO", "critical", "CONTANGO", r,
        details="0.96 < 0.965 threshold → stays in CONTANGO",
    ))

    r = get_regime(0.97, prev_regime="CONTANGO")
    summary.add(EvalResult(
        "Hysteresis: 0.97 from CONTANGO switches to FLAT", suite,
        r == "FLAT", "critical", "FLAT", r,
        details="0.97 > 0.965 threshold → switches to FLAT",
    ))

    # From FLAT, need < 0.935 to switch to CONTANGO
    r = get_regime(0.94, prev_regime="FLAT")
    summary.add(EvalResult(
        "Hysteresis: 0.94 from FLAT stays FLAT", suite,
        r == "FLAT", "critical", "FLAT", r,
        details="0.94 > 0.935 threshold → stays in FLAT",
    ))

    r = get_regime(0.93, prev_regime="FLAT")
    summary.add(EvalResult(
        "Hysteresis: 0.93 from FLAT switches to CONTANGO", suite,
        r == "CONTANGO", "critical", "CONTANGO", r,
        details="0.93 < 0.935 threshold → switches to CONTANGO",
    ))

    # --- Hysteresis at 1.05 boundary ---
    r = get_regime(1.06, prev_regime="FLAT")
    summary.add(EvalResult(
        "Hysteresis: 1.06 from FLAT stays FLAT", suite,
        r == "FLAT", "critical", "FLAT", r,
        details="1.06 < 1.065 threshold → stays in FLAT",
    ))

    r = get_regime(1.07, prev_regime="FLAT")
    summary.add(EvalResult(
        "Hysteresis: 1.07 from FLAT switches to BACKWARDATION", suite,
        r == "BACKWARDATION", "critical", "BACKWARDATION", r,
    ))

    r = get_regime(1.04, prev_regime="BACKWARDATION")
    summary.add(EvalResult(
        "Hysteresis: 1.04 from BACKWARDATION stays BACKWARDATION", suite,
        r == "BACKWARDATION", "critical", "BACKWARDATION", r,
    ))

    r = get_regime(1.03, prev_regime="BACKWARDATION")
    summary.add(EvalResult(
        "Hysteresis: 1.03 from BACKWARDATION switches to FLAT", suite,
        r == "FLAT", "critical", "FLAT", r,
    ))

    # No prev_regime → raw classification (no hysteresis)
    r = get_regime(0.96)
    summary.add(EvalResult(
        "No prev_regime: 0.96 → FLAT (raw)", suite,
        r == "FLAT", "critical", "FLAT", r,
    ))

    # --- Golden window minimum duration ---
    # Short spike (1 day) → should NOT trigger golden window
    r = detect_transition("BACKWARDATION", "FLAT", "FALLING", 0.90, -0.03,
                          backwardation_days=1)
    summary.add(EvalResult(
        "Golden window blocked: only 1 day in backwardation", suite,
        r["transition"] != "GOLDEN_WINDOW", "critical",
        "NOT GOLDEN_WINDOW", r["transition"],
        details="Single-day spike should not trigger golden window",
    ))

    # Sustained backwardation (5 days) → golden window allowed
    r = detect_transition("BACKWARDATION", "FLAT", "FALLING", 0.90, -0.03,
                          backwardation_days=5)
    summary.add(EvalResult(
        "Golden window allowed: 5 days in backwardation", suite,
        r["transition"] == "GOLDEN_WINDOW", "critical",
        "GOLDEN_WINDOW", r["transition"],
    ))

    # Exactly at threshold (3 days) → golden window allowed
    r = detect_transition("BACKWARDATION", "FLAT", "FALLING", 0.90, -0.03,
                          backwardation_days=3)
    summary.add(EvalResult(
        "Golden window at threshold: 3 days", suite,
        r["transition"] == "GOLDEN_WINDOW", "critical",
        "GOLDEN_WINDOW", r["transition"],
    ))

    # 2 days → blocked
    r = detect_transition("BACKWARDATION", "FLAT", "FALLING", 0.90, -0.03,
                          backwardation_days=2)
    summary.add(EvalResult(
        "Golden window blocked: 2 days (below threshold)", suite,
        r["transition"] != "GOLDEN_WINDOW", "critical",
        "NOT GOLDEN_WINDOW", r["transition"],
    ))


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Production VIX Regime Eval")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--suite", type=int)
    args = parser.parse_args()

    summary = EvalSummary()

    suites = {
        1: ("Regime Classification", eval_suite_1),
        2: ("Transitions", eval_suite_2),
        3: ("Position Sizing", eval_suite_3),
        4: ("Conviction", eval_suite_4),
        5: ("Hysteresis & Golden Window", eval_suite_5),
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
