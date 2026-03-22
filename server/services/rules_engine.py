"""
Strategy Rules Engine
Validates new trades against the systematic CSP strategy rules.
Returns a compliance report with pass/fail for each rule.
"""
from __future__ import annotations

import json
import os
from typing import Optional, List, Dict
from sqlalchemy.orm import Session

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_config() -> dict:
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f)


def check_compliance(
    db: Session,
    ticker: str,
    sector: str,
    strategy: str,
    delta: Optional[float],
    iv_rank: Optional[float],
    dte: int,
    buying_power_used: float,
    total_capital: float,
    vix: Optional[float],
    current_regime: Optional[str],
) -> List[Dict]:
    """
    Check a proposed trade against all strategy rules.

    Returns:
        List of rule check results, each with:
        - rule: str (rule name)
        - passed: bool
        - message: str (description)
        - severity: str (INFO, WARNING, CRITICAL)
    """
    from server.models import Trade

    config = load_config()
    entry_rules = config["entry_rules"]
    regime_rules = config["regime_rules"]
    results = []

    # 1. IV Rank check
    min_iv = entry_rules["min_iv_rank"]
    if iv_rank is not None:
        results.append({
            "rule": "IV Rank Minimum",
            "passed": iv_rank >= min_iv,
            "message": f"IV Rank {iv_rank:.1f} {'≥' if iv_rank >= min_iv else '<'} minimum {min_iv}",
            "severity": "WARNING" if iv_rank < min_iv else "INFO",
        })
    else:
        results.append({
            "rule": "IV Rank Minimum",
            "passed": False,
            "message": "IV Rank not provided — cannot validate",
            "severity": "WARNING",
        })

    # 2. Delta range check
    delta_range = entry_rules["delta_range"]
    # Adjust delta range for high vol regime
    if current_regime in ("HIGH_VOL_BEARISH", "HIGH_VOL_NEUTRAL", "CRISIS"):
        delta_range = regime_rules.get("high_vol_delta_range", [-0.15, -0.10])

    if delta is not None:
        abs_delta = abs(delta)
        in_range = abs(delta_range[0]) >= abs_delta >= abs(delta_range[1])
        results.append({
            "rule": "Delta Range",
            "passed": in_range,
            "message": f"Delta {delta:.2f} {'within' if in_range else 'outside'} range [{delta_range[0]}, {delta_range[1]}]",
            "severity": "WARNING" if not in_range else "INFO",
        })
    else:
        results.append({
            "rule": "Delta Range",
            "passed": False,
            "message": "Delta not provided — cannot validate",
            "severity": "WARNING",
        })

    # 3. DTE range check
    dte_range = entry_rules["dte_range"]
    dte_ok = dte_range[0] <= dte <= dte_range[1]
    results.append({
        "rule": "DTE Range",
        "passed": dte_ok,
        "message": f"DTE {dte} {'within' if dte_ok else 'outside'} range [{dte_range[0]}, {dte_range[1]}]",
        "severity": "WARNING" if not dte_ok else "INFO",
    })

    # 4. Position size check (strategy-aware: CSP 10%, spreads 5%)
    if strategy == "CSP":
        max_size_pct = entry_rules.get("max_position_size_pct_csp", entry_rules.get("max_position_size_pct", 10))
    else:
        max_size_pct = entry_rules.get("max_position_size_pct_spread", entry_rules.get("max_position_size_pct", 5))
    if total_capital > 0:
        position_pct = (buying_power_used / total_capital) * 100
        size_ok = position_pct <= max_size_pct
        results.append({
            "rule": "Position Size",
            "passed": size_ok,
            "message": f"Position {position_pct:.1f}% {'≤' if size_ok else '>'} max {max_size_pct}% of portfolio",
            "severity": "CRITICAL" if not size_ok else "INFO",
        })

    # 5. Sector concentration check (max 2 positions per sector)
    max_per_sector = entry_rules["max_positions_per_sector"]
    sector_count = db.query(Trade).filter(
        Trade.sector == sector,
        Trade.status == "OPEN"
    ).count()
    sector_ok = sector_count < max_per_sector
    results.append({
        "rule": "Sector Position Count",
        "passed": sector_ok,
        "message": f"{sector}: {sector_count} open positions {'<' if sector_ok else '≥'} max {max_per_sector}",
        "severity": "CRITICAL" if not sector_ok else "INFO",
    })

    # 6. Sector exposure % check
    max_sector_pct = entry_rules["max_sector_exposure_pct"]
    if total_capital > 0:
        sector_bp = sum(
            t.effective_bp
            for t in db.query(Trade).filter(Trade.sector == sector, Trade.status == "OPEN").all()
        )
        sector_exposure_pct = ((sector_bp + buying_power_used) / total_capital) * 100
        exposure_ok = sector_exposure_pct <= max_sector_pct
        results.append({
            "rule": "Sector Exposure %",
            "passed": exposure_ok,
            "message": f"{sector} exposure {sector_exposure_pct:.1f}% {'≤' if exposure_ok else '>'} max {max_sector_pct}%",
            "severity": "CRITICAL" if not exposure_ok else "INFO",
        })

    # 7. Total position count check (regime-based)
    if current_regime == "CRISIS":
        max_positions = regime_rules["crisis_max_positions"]
    elif current_regime in ("HIGH_VOL_BEARISH", "HIGH_VOL_NEUTRAL"):
        max_positions = regime_rules["high_vol_max_positions"]
    else:
        max_positions = regime_rules["low_vol_max_positions"]

    open_count = db.query(Trade).filter(Trade.status == "OPEN").count()
    count_ok = open_count < max_positions
    results.append({
        "rule": "Total Positions (Regime)",
        "passed": count_ok,
        "message": f"{open_count} open positions {'<' if count_ok else '≥'} max {max_positions} ({current_regime or 'unknown'} regime)",
        "severity": "CRITICAL" if not count_ok else "INFO",
    })

    # 8. VIX regime filter — suggest spreads in high vol
    if vix is not None and vix >= regime_rules["vix_high_threshold"] and strategy == "CSP":
        results.append({
            "rule": "High Vol Spread Preference",
            "passed": False,
            "message": f"VIX at {vix:.1f} — consider using PUT_SPREAD instead of naked CSP",
            "severity": "WARNING",
        })
    else:
        results.append({
            "rule": "High Vol Spread Preference",
            "passed": True,
            "message": "Strategy appropriate for current VIX environment",
            "severity": "INFO",
        })

    return results
