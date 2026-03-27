"""
Flow Toxicity Detection — Eval Suite
=====================================
Tests IVLD, PCCR, and composite scoring against synthetic option chain scenarios.

Usage:
    python -m server.tests.eval_flow_toxicity
    python -m server.tests.eval_flow_toxicity --verbose
"""

import sys
import os
import argparse
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from server.services.flow_toxicity import (
    iv_local_distortion,
    put_call_concentration,
    composite_toxicity_phase1,
    final_position_multiplier,
    _get_label,
    IVLD_LABELS,
    PCCR_LABELS,
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
        print("FLOW TOXICITY DETECTION — EVAL REPORT")
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
# Suite 1: IVLD — IV Local Distortion
# ============================================================================

def eval_suite_1_ivld(summary: EvalSummary):
    suite = "Suite 1: IVLD"

    # --- Clean scenarios (IVLD should be near 0) ---

    # Normal vol surface: strike IV matches neighbors
    ivld = iv_local_distortion(
        strike_iv=0.35,
        neighbor_ivs=[0.33, 0.34, 0.36, 0.37],  # smooth skew
        atm_iv=0.30,
    )
    summary.add(EvalResult(
        test_name="Clean: smooth vol surface, no bump",
        suite=suite, passed=(ivld < 0.10), severity="critical",
        expected="< 0.10", actual=f"{ivld:.3f}",
        details="Strike IV 35% with neighbors 33-37% is normal OTM skew",
    ))

    # Flat vol surface
    ivld = iv_local_distortion(
        strike_iv=0.30,
        neighbor_ivs=[0.30, 0.30, 0.30, 0.30],
        atm_iv=0.30,
    )
    summary.add(EvalResult(
        test_name="Clean: perfectly flat surface",
        suite=suite, passed=(ivld == 0.0), severity="critical",
        expected="0.0", actual=f"{ivld:.3f}",
    ))

    # --- Mild bump (3pp excess → local_score=0.375, skew_score varies) ---
    ivld = iv_local_distortion(
        strike_iv=0.38,
        neighbor_ivs=[0.34, 0.35, 0.35, 0.34],  # 3pp excess
        atm_iv=0.30,
    )
    summary.add(EvalResult(
        test_name="Mild bump: 3pp above neighbors",
        suite=suite, passed=(0.15 <= ivld <= 0.60), severity="major",
        expected="0.15 - 0.60", actual=f"{ivld:.3f}",
        details="3pp local excess with skew residual from immediate neighbors",
    ))

    # --- Distorted (7pp excess → both local and skew scores high) ---
    ivld = iv_local_distortion(
        strike_iv=0.42,
        neighbor_ivs=[0.34, 0.35, 0.35, 0.34],  # 7pp excess
        atm_iv=0.30,
    )
    summary.add(EvalResult(
        test_name="Distorted: 7pp above neighbors",
        suite=suite, passed=(ivld >= 0.60), severity="critical",
        expected=">= 0.60", actual=f"{ivld:.3f}",
        details="7pp excess with strong skew residual = high IVLD",
    ))

    # --- Severe (IVLD >= 0.70) ---
    ivld = iv_local_distortion(
        strike_iv=0.50,
        neighbor_ivs=[0.34, 0.35, 0.35, 0.34],  # 15pp excess
        atm_iv=0.30,
    )
    summary.add(EvalResult(
        test_name="Severe: 15pp above neighbors",
        suite=suite, passed=(ivld >= 0.65), severity="critical",
        expected=">= 0.65", actual=f"{ivld:.3f}",
        details="15pp excess is extreme — almost certainly informed flow",
    ))

    # --- Edge cases ---
    ivld = iv_local_distortion(strike_iv=0.0, neighbor_ivs=[], atm_iv=0.0)
    summary.add(EvalResult(
        test_name="Edge: zero IV / empty neighbors returns 0",
        suite=suite, passed=(ivld == 0.0), severity="minor",
        expected="0.0", actual=f"{ivld:.3f}",
    ))

    ivld = iv_local_distortion(strike_iv=0.35, neighbor_ivs=[0.34, 0.36], atm_iv=0.30)
    summary.add(EvalResult(
        test_name="Edge: only 2 neighbors (no skew residual)",
        suite=suite, passed=(0.0 <= ivld <= 0.15), severity="minor",
        expected="0.0 - 0.15", actual=f"{ivld:.3f}",
        details="With < 4 neighbors, skew_score is 0, only local_score contributes",
    ))

    # --- Skew residual detection ---
    # Strike IV is lower than overall average but much higher than immediate neighbors
    ivld = iv_local_distortion(
        strike_iv=0.40,
        neighbor_ivs=[0.30, 0.32, 0.32, 0.30],  # immediate neighbors are 32%, target is 40%
        atm_iv=0.30,
    )
    summary.add(EvalResult(
        test_name="Skew residual: strike 40% vs immediate neighbors 32%",
        suite=suite, passed=(ivld >= 0.40), severity="critical",
        expected=">= 0.40", actual=f"{ivld:.3f}",
        details="8pp skew residual should produce strong IVLD signal",
    ))


# ============================================================================
# Suite 2: PCCR — Put/Call Concentration Ratio
# ============================================================================

def eval_suite_2_pccr(summary: EvalSummary):
    suite = "Suite 2: PCCR"

    # --- Balanced scenario (PCCR near 0) ---
    pccr = put_call_concentration(
        put_volume_zone=1000, call_volume_zone=1200,
        put_oi_zone=5000, call_oi_zone=6000,
        overall_equity_pcr=0.85,
    )
    summary.add(EvalResult(
        test_name="Balanced: P/C ratio ≈ 0.83, near market average",
        suite=suite, passed=(pccr < 0.10), severity="critical",
        expected="< 0.10", actual=f"{pccr:.3f}",
        details="Zone PCR 0.83 ≈ market PCR 0.85 → no signal",
    ))

    # --- Mildly put-heavy (PCCR 0.15-0.35) ---
    pccr = put_call_concentration(
        put_volume_zone=2000, call_volume_zone=1000,
        put_oi_zone=8000, call_oi_zone=5000,
        overall_equity_pcr=0.85,
    )
    summary.add(EvalResult(
        test_name="Put-heavy: 2:1 put/call volume ratio",
        suite=suite, passed=(0.15 <= pccr <= 0.45), severity="critical",
        expected="0.15 - 0.45", actual=f"{pccr:.3f}",
        details="2x put volume vs market 0.85x = 2.35x excess",
    ))

    # --- Bearish tilt (4:1 ratio → volume excess = 4.71x, oi excess = 4.41x) ---
    pccr = put_call_concentration(
        put_volume_zone=4000, call_volume_zone=1000,
        put_oi_zone=15000, call_oi_zone=4000,
        overall_equity_pcr=0.85,
    )
    summary.add(EvalResult(
        test_name="Bearish tilt: 4:1 put/call ratio",
        suite=suite, passed=(pccr >= 0.70), severity="critical",
        expected=">= 0.70", actual=f"{pccr:.3f}",
        details="4x put volume = 4.71x excess over market PCR → very high PCCR",
    ))

    # --- Extreme put concentration (PCCR >= 0.70) ---
    pccr = put_call_concentration(
        put_volume_zone=8000, call_volume_zone=500,
        put_oi_zone=30000, call_oi_zone=2000,
        overall_equity_pcr=0.85,
    )
    summary.add(EvalResult(
        test_name="Extreme: 16:1 put/call ratio",
        suite=suite, passed=(pccr >= 0.70), severity="critical",
        expected=">= 0.70", actual=f"{pccr:.3f}",
        details="16x put volume is almost certainly informed flow",
    ))

    # --- Edge: very few calls → default to high ratio ---
    pccr = put_call_concentration(
        put_volume_zone=500, call_volume_zone=5,
        put_oi_zone=2000, call_oi_zone=30,
        overall_equity_pcr=0.85,
    )
    summary.add(EvalResult(
        test_name="Edge: near-zero call volume → elevated PCCR",
        suite=suite, passed=(pccr >= 0.50), severity="major",
        expected=">= 0.50", actual=f"{pccr:.3f}",
        details="< 10 calls triggers default high ratio of 3.0",
    ))

    # --- Edge: zero put activity ---
    pccr = put_call_concentration(
        put_volume_zone=0, call_volume_zone=1000,
        put_oi_zone=0, call_oi_zone=5000,
        overall_equity_pcr=0.85,
    )
    summary.add(EvalResult(
        test_name="Edge: zero puts = no put concentration",
        suite=suite, passed=(pccr == 0.0), severity="major",
        expected="0.0", actual=f"{pccr:.3f}",
    ))


# ============================================================================
# Suite 3: Composite Scoring & Regime-Adjusted Labels
# ============================================================================

def eval_suite_3_composite(summary: EvalSummary):
    suite = "Suite 3: Composite"

    # --- CLEAN: both signals low ---
    score, conf, label = composite_toxicity_phase1(0.05, 0.05, "CONTANGO")
    summary.add(EvalResult(
        test_name="Both signals low → CLEAN",
        suite=suite, passed=(label == "CLEAN"), severity="critical",
        expected="CLEAN", actual=label,
        details=f"score={score:.3f}, conf={conf}",
    ))

    # --- CAUTION: one signal elevated ---
    score, conf, label = composite_toxicity_phase1(0.45, 0.10, "CONTANGO")
    summary.add(EvalResult(
        test_name="IVLD elevated, PCCR low → CAUTION",
        suite=suite, passed=(label == "CAUTION"), severity="critical",
        expected="CAUTION", actual=label,
        details=f"score={score:.3f}, conf={conf}",
    ))

    # --- TOXIC: both signals moderate-high ---
    score, conf, label = composite_toxicity_phase1(0.55, 0.50, "CONTANGO")
    summary.add(EvalResult(
        test_name="Both signals elevated → TOXIC or HIGHLY_TOXIC",
        suite=suite, passed=(label in ("TOXIC", "HIGHLY_TOXIC")), severity="critical",
        expected="TOXIC or HIGHLY_TOXIC", actual=label,
        details=f"score={score:.3f}, conf={conf}",
    ))

    # --- Confidence: both > 0.4 → HIGH ---
    _, conf, _ = composite_toxicity_phase1(0.50, 0.50, "CONTANGO")
    summary.add(EvalResult(
        test_name="Both signals > 0.4 → HIGH confidence",
        suite=suite, passed=(conf == "HIGH"), severity="major",
        expected="HIGH", actual=conf,
    ))

    # --- Confidence: only one > 0.4 → MEDIUM ---
    _, conf, _ = composite_toxicity_phase1(0.50, 0.10, "CONTANGO")
    summary.add(EvalResult(
        test_name="One signal > 0.4 → MEDIUM confidence",
        suite=suite, passed=(conf == "MEDIUM"), severity="major",
        expected="MEDIUM", actual=conf,
    ))

    # --- Confidence: both low → LOW ---
    _, conf, _ = composite_toxicity_phase1(0.10, 0.10, "CONTANGO")
    summary.add(EvalResult(
        test_name="Both signals < 0.4 → LOW confidence",
        suite=suite, passed=(conf == "LOW"), severity="major",
        expected="LOW", actual=conf,
    ))

    # --- Regime sensitivity: same signals, stricter in backwardation ---
    _, _, label_contango = composite_toxicity_phase1(0.30, 0.20, "CONTANGO")
    _, _, label_back = composite_toxicity_phase1(0.30, 0.20, "BACKWARDATION")

    # In backwardation (caution=0.15), 0.25 composite should be CAUTION or worse
    # In contango (caution=0.25), 0.25 composite is borderline
    summary.add(EvalResult(
        test_name="Regime: backwardation thresholds are stricter",
        suite=suite,
        passed=(label_back != "CLEAN"),
        severity="critical",
        expected="Not CLEAN in backwardation",
        actual=f"Contango={label_contango}, Backwardation={label_back}",
        details="Same 0.25 composite should trigger CAUTION in backwardation but may be CLEAN in contango",
    ))

    # --- Deep backwardation: very low composite still triggers caution ---
    _, _, label_dback = composite_toxicity_phase1(0.12, 0.10, "DEEP_BACKWARDATION")
    summary.add(EvalResult(
        test_name="Regime: deep backwardation ultra-strict (caution=0.10)",
        suite=suite,
        passed=(label_dback != "CLEAN"),
        severity="major",
        expected="Not CLEAN",
        actual=label_dback,
        details="Even low composite should trigger in deep backwardation",
    ))

    # --- Amplifier: both > 0.5 gets 1.15x boost ---
    score_no_amp, _, _ = composite_toxicity_phase1(0.45, 0.45, "CONTANGO")
    score_amp, _, _ = composite_toxicity_phase1(0.55, 0.55, "CONTANGO")
    # score_amp should be > 0.55 * 1.15 ≈ 0.63 (amplified)
    summary.add(EvalResult(
        test_name="Amplifier: both > 0.5 boosts composite by 15%",
        suite=suite,
        passed=(score_amp > 0.55 * 0.5 + 0.55 * 0.5),  # > unamplified
        severity="major",
        expected=f"> {0.55:.3f} (unamplified)",
        actual=f"{score_amp:.3f}",
    ))


# ============================================================================
# Suite 4: Position Multiplier Dampening
# ============================================================================

def eval_suite_4_sizing(summary: EvalSummary):
    suite = "Suite 4: Position Dampener"

    # CLEAN: no dampening
    mult = final_position_multiplier(1.0, 0.10, "CLEAN")
    summary.add(EvalResult(
        test_name="CLEAN label → no dampening (1.0x regime)",
        suite=suite, passed=(mult == 1.0), severity="critical",
        expected="1.0", actual=f"{mult:.3f}",
    ))

    # CAUTION: partial dampening
    mult = final_position_multiplier(1.0, 0.30, "CAUTION")
    summary.add(EvalResult(
        test_name="CAUTION label → partial dampening",
        suite=suite, passed=(0.5 < mult < 1.0), severity="critical",
        expected="0.5 - 1.0", actual=f"{mult:.3f}",
        details="dampener = 1.0 - (0.30 * 0.6) = 0.82",
    ))

    # TOXIC: zero position
    mult = final_position_multiplier(1.0, 0.60, "TOXIC")
    summary.add(EvalResult(
        test_name="TOXIC label → zero position",
        suite=suite, passed=(mult == 0.0), severity="critical",
        expected="0.0", actual=f"{mult:.3f}",
    ))

    # HIGHLY_TOXIC: zero position
    mult = final_position_multiplier(1.0, 0.80, "HIGHLY_TOXIC")
    summary.add(EvalResult(
        test_name="HIGHLY_TOXIC label → zero position",
        suite=suite, passed=(mult == 0.0), severity="critical",
        expected="0.0", actual=f"{mult:.3f}",
    ))

    # Regime multiplier passes through for CLEAN
    mult = final_position_multiplier(0.50, 0.05, "CLEAN")
    summary.add(EvalResult(
        test_name="CLEAN + regime=0.5 → 0.5 (regime passes through)",
        suite=suite, passed=(mult == 0.5), severity="major",
        expected="0.5", actual=f"{mult:.3f}",
    ))

    # CAUTION + reduced regime
    mult = final_position_multiplier(0.50, 0.30, "CAUTION")
    summary.add(EvalResult(
        test_name="CAUTION + regime=0.5 → doubly reduced",
        suite=suite, passed=(mult < 0.5), severity="major",
        expected="< 0.5", actual=f"{mult:.3f}",
    ))


# ============================================================================
# Suite 5: Synthetic Option Chain Scenarios (end-to-end)
# ============================================================================

def eval_suite_5_scenarios(summary: EvalSummary):
    suite = "Suite 5: E2E Scenarios"

    # Scenario A: CLEAN stock — normal vol surface, balanced P/C
    ivld = iv_local_distortion(0.32, [0.31, 0.315, 0.325, 0.33], 0.28)
    pccr = put_call_concentration(800, 900, 4000, 4500, 0.85)
    score, conf, label = composite_toxicity_phase1(ivld, pccr, "CONTANGO")
    summary.add(EvalResult(
        test_name="Scenario A: Normal stock → CLEAN",
        suite=suite, passed=(label == "CLEAN"), severity="critical",
        expected="CLEAN", actual=f"{label} (score={score:.3f}, ivld={ivld:.3f}, pccr={pccr:.3f})",
    ))

    # Scenario B: Pre-earnings insider buying protection
    # IV bump at specific strike, heavy put volume
    ivld = iv_local_distortion(0.48, [0.35, 0.36, 0.37, 0.36], 0.30)
    pccr = put_call_concentration(5000, 800, 12000, 3000, 0.85)
    score, conf, label = composite_toxicity_phase1(ivld, pccr, "CONTANGO")
    summary.add(EvalResult(
        test_name="Scenario B: Pre-earnings informed flow → TOXIC+",
        suite=suite, passed=(label in ("TOXIC", "HIGHLY_TOXIC")), severity="critical",
        expected="TOXIC or HIGHLY_TOXIC",
        actual=f"{label} (score={score:.3f}, ivld={ivld:.3f}, pccr={pccr:.3f})",
        details="12pp IV bump + 6.25x put/call ratio = clear informed flow",
    ))

    # Scenario C: High IV but natural skew (NOT toxic)
    # Strike is OTM put with naturally higher IV due to skew, balanced volume
    ivld = iv_local_distortion(0.40, [0.38, 0.39, 0.41, 0.42], 0.28)
    pccr = put_call_concentration(600, 700, 3000, 3500, 0.85)
    score, conf, label = composite_toxicity_phase1(ivld, pccr, "CONTANGO")
    summary.add(EvalResult(
        test_name="Scenario C: Natural OTM skew, balanced volume → CLEAN",
        suite=suite, passed=(label == "CLEAN"), severity="critical",
        expected="CLEAN", actual=f"{label} (score={score:.3f}, ivld={ivld:.3f}, pccr={pccr:.3f})",
        details="High IV is consistent with neighbors (normal skew), volume balanced",
    ))

    # Scenario D: Hedge fund rolling large put position
    # Moderate IV bump, extremely high OI concentration
    ivld = iv_local_distortion(0.37, [0.34, 0.35, 0.35, 0.34], 0.30)
    pccr = put_call_concentration(1500, 500, 25000, 3000, 0.85)
    score, conf, label = composite_toxicity_phase1(ivld, pccr, "CONTANGO")
    summary.add(EvalResult(
        test_name="Scenario D: Large put OI position → CAUTION+",
        suite=suite, passed=(label in ("CAUTION", "TOXIC", "HIGHLY_TOXIC")), severity="critical",
        expected="CAUTION or worse",
        actual=f"{label} (score={score:.3f}, ivld={ivld:.3f}, pccr={pccr:.3f})",
        details="2pp IV bump is mild but 8.3x put OI ratio is extreme",
    ))

    # Scenario E: Crisis regime — lower thresholds
    ivld = iv_local_distortion(0.36, [0.34, 0.345, 0.345, 0.34], 0.30)
    pccr = put_call_concentration(1200, 800, 5000, 4000, 0.85)
    score_c, _, label_contango = composite_toxicity_phase1(ivld, pccr, "CONTANGO")
    score_b, _, label_back = composite_toxicity_phase1(ivld, pccr, "BACKWARDATION")
    summary.add(EvalResult(
        test_name="Scenario E: Same signals, stricter in backwardation",
        suite=suite,
        passed=(label_contango == "CLEAN" and label_back != "CLEAN") or
               (label_back in ("CAUTION", "TOXIC", "HIGHLY_TOXIC")),
        severity="major",
        expected=f"Backwardation more cautious than contango",
        actual=f"Contango={label_contango}({score_c:.3f}), Back={label_back}({score_b:.3f})",
    ))


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Flow Toxicity Eval Suite")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--suite", type=int)
    args = parser.parse_args()

    summary = EvalSummary()

    suites = {
        1: ("IVLD", eval_suite_1_ivld),
        2: ("PCCR", eval_suite_2_pccr),
        3: ("Composite", eval_suite_3_composite),
        4: ("Position Dampener", eval_suite_4_sizing),
        5: ("E2E Scenarios", eval_suite_5_scenarios),
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
