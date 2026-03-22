"""
Moomoo CSV Import Parser
Parses exported CSV from Moomoo transaction history into trade journal entries.
Backup import method when OpenD API is not available.
"""
from __future__ import annotations

import csv
import re
import io
from datetime import datetime
from typing import Optional


def parse_option_code_from_name(name: str) -> dict | None:
    """
    Parse option details from Moomoo's stock_name or description field.
    Moomoo CSV may use different formats — handle common patterns.
    """
    # Pattern: "AAPL 250321 180.00 P" or similar
    match = re.search(r"([A-Z]+)\s*(\d{6})\s*(\d+\.?\d*)\s*([PC])", name)
    if match:
        return {
            "ticker": match.group(1),
            "expiry": f"20{match.group(2)[:2]}-{match.group(2)[2:4]}-{match.group(2)[4:6]}",
            "strike": float(match.group(3)),
            "option_type": match.group(4),
        }
    return None


def parse_moomoo_csv(csv_content: str) -> list[dict]:
    """
    Parse Moomoo transaction history CSV export.

    Expected CSV columns (may vary by export version):
    - Date/Time, Symbol, Action (STO/BTC/STC/BTO), Quantity, Price, Fees, etc.

    Returns list of parsed trade records.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    trades = []

    for row in reader:
        # Try multiple column name variations
        trade_date = (
            row.get("Date/Time") or row.get("create_time") or
            row.get("Trade Date") or row.get("date")
        )
        symbol = (
            row.get("Symbol") or row.get("code") or
            row.get("Stock Code") or row.get("symbol")
        )
        action = (
            row.get("Action") or row.get("trd_side") or
            row.get("Side") or row.get("action")
        )
        qty = (
            row.get("Quantity") or row.get("qty") or
            row.get("Qty") or row.get("quantity")
        )
        price = (
            row.get("Price") or row.get("price") or
            row.get("Fill Price") or row.get("avg_price")
        )
        fees = row.get("Fees") or row.get("fees") or row.get("Commission") or "0"
        stock_name = row.get("stock_name") or row.get("Name") or row.get("Description") or ""

        if not symbol or not action:
            continue

        # Parse option details from code
        from server.services.moomoo_client import parse_option_code
        option_info = parse_option_code(symbol)
        if not option_info:
            option_info = parse_option_code_from_name(stock_name)

        # Determine if this is an opening or closing trade
        action_upper = str(action).upper()
        is_sell = action_upper in ("SELL", "STO", "SELL_TO_OPEN", "S")
        is_buy = action_upper in ("BUY", "BTC", "BUY_TO_CLOSE", "B")

        try:
            parsed_qty = abs(int(float(str(qty).replace(",", ""))))
        except (ValueError, TypeError):
            parsed_qty = 1

        try:
            parsed_price = abs(float(str(price).replace(",", "").replace("$", "")))
        except (ValueError, TypeError):
            parsed_price = 0

        try:
            parsed_fees = abs(float(str(fees).replace(",", "").replace("$", "")))
        except (ValueError, TypeError):
            parsed_fees = 0

        try:
            parsed_date = datetime.strptime(str(trade_date).strip(), "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                parsed_date = datetime.strptime(str(trade_date).strip(), "%m/%d/%Y %H:%M:%S")
            except (ValueError, TypeError):
                try:
                    parsed_date = datetime.strptime(str(trade_date).strip(), "%Y-%m-%d")
                except (ValueError, TypeError):
                    parsed_date = datetime.utcnow()

        trades.append({
            "raw_code": symbol,
            "option_info": option_info,
            "is_sell": is_sell,
            "is_buy": is_buy,
            "action": action_upper,
            "qty": parsed_qty,
            "price": parsed_price,
            "fees": parsed_fees,
            "date": parsed_date,
            "stock_name": stock_name,
        })

    return trades


def match_trades(parsed_trades: list[dict]) -> list[dict]:
    """
    Match STO (sell-to-open) trades with BTC (buy-to-close) trades
    to create complete trade journal entries.

    Returns list of matched trade records ready for DB insertion.
    """
    from collections import defaultdict

    # Group by option code/details
    grouped = defaultdict(list)
    for t in parsed_trades:
        info = t.get("option_info")
        if info:
            key = f"{info['ticker']}_{info['strike']}_{info['expiry']}"
        else:
            key = t["raw_code"]
        grouped[key].append(t)

    journal_entries = []

    for key, group_trades in grouped.items():
        sells = sorted([t for t in group_trades if t["is_sell"]], key=lambda x: x["date"])
        buys = sorted([t for t in group_trades if t["is_buy"]], key=lambda x: x["date"])

        for sell in sells:
            info = sell.get("option_info")
            if not info:
                continue

            entry = {
                "ticker": info["ticker"],
                "strike": info["strike"],
                "expiry": info["expiry"],
                "option_type": info["option_type"],
                "trade_date_open": sell["date"],
                "contracts": sell["qty"],
                "premium_received": sell["price"],
                "direction": "SELL",
                "strategy": "CSP" if info["option_type"] == "P" else "COVERED_CALL",
                "status": "OPEN",
                "fees_open": sell["fees"],
            }

            # Try to match with earliest buy
            if buys:
                buy = buys.pop(0)
                entry["premium_close"] = buy["price"]
                entry["trade_date_close"] = buy["date"]
                entry["status"] = "CLOSED"
                entry["fees_close"] = buy["fees"]
                # Calculate P&L
                entry["pnl_dollars"] = (
                    (sell["price"] - buy["price"]) * sell["qty"] * 100
                    - sell["fees"] - buy["fees"]
                )

            journal_entries.append(entry)

    return journal_entries
