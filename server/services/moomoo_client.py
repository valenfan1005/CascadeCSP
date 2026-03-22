"""
Moomoo OpenD API Client
Wraps Moomoo SDK for position sync, account info, greeks, and trade history.

IMPORTANT: Connection drops after ~10-11 sequential requests.
Always use fresh connections and add delays between calls.
"""
from __future__ import annotations

import os
import re
import time
import json
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQUEST_DELAY = 0.5

# Try to import moomoo - may not be installed
try:
    from moomoo import (
        OpenSecTradeContext, OpenQuoteContext, SecurityFirm,
        TrdMarket, TrdEnv, RET_OK, OptionType, OptionCondType
    )
    MOOMOO_AVAILABLE = True
except ImportError:
    MOOMOO_AVAILABLE = False
    logger.warning("moomoo-api not installed. Moomoo integration disabled.")


def _load_config() -> dict:
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path) as f:
        return json.load(f).get("moomoo", {})


def is_available() -> bool:
    """Check if Moomoo SDK is installed."""
    return MOOMOO_AVAILABLE


def get_trade_context():
    """Create a fresh trade context for US market."""
    if not MOOMOO_AVAILABLE:
        raise RuntimeError("moomoo-api not installed")
    cfg = _load_config()
    return OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=cfg.get("host", "127.0.0.1"),
        port=cfg.get("port", 11111),
        security_firm=SecurityFirm.FUTUSG,
    )


def get_quote_context():
    """Create a fresh quote context."""
    if not MOOMOO_AVAILABLE:
        raise RuntimeError("moomoo-api not installed")
    cfg = _load_config()
    return OpenQuoteContext(
        host=cfg.get("host", "127.0.0.1"),
        port=cfg.get("port", 11111),
    )


def _get_trade_password() -> str:
    cfg = _load_config()
    env_var = cfg.get("trade_password_env_var", "MOOMOO_TRADE_PASSWORD")
    password = os.environ.get(env_var)
    if not password:
        raise RuntimeError(f"Trade password not set. Set environment variable: {env_var}")
    return password


def parse_option_code(code: str) -> dict | None:
    """
    Parse Moomoo option code like 'US.AAPL250321P180000'
    Returns: dict with ticker, expiry, option_type, strike
    """
    code = code.replace("US.", "")
    match = re.match(r"([A-Z]+)(\d{6})([PC])(\d+)", code)
    if match:
        ticker = match.group(1)
        date_str = match.group(2)
        option_type = match.group(3)
        strike = int(match.group(4)) / 1000
        expiry = f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}"
        return {
            "ticker": ticker,
            "expiry": expiry,
            "option_type": option_type,
            "strike": strike,
        }
    return None


def check_connection() -> tuple[bool, str]:
    """Test connection to Moomoo OpenD."""
    if not MOOMOO_AVAILABLE:
        return False, "moomoo-api package not installed"
    try:
        ctx = get_quote_context()
        ctx.close()
        return True, "Connected to Moomoo OpenD"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"


def get_account_info() -> tuple[dict | None, str | None]:
    """Fetch account balance and buying power."""
    if not MOOMOO_AVAILABLE:
        return None, "Moomoo not available"

    trd_ctx = get_trade_context()
    try:
        # accinfo_query does not require trade unlock
        ret, data = trd_ctx.accinfo_query(trd_env=TrdEnv.REAL, currency="USD")
        if ret != RET_OK:
            return None, f"Account query failed: {data}"

        row = data.iloc[0]

        def safe_float(val, default=0.0):
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        return {
            "total_assets": safe_float(row.get("total_assets", 0)),
            "cash": safe_float(row.get("cash", 0)),
            "market_val": safe_float(row.get("market_val", 0)),
            "frozen_cash": safe_float(row.get("frozen_cash", 0)),
            "available_funds": safe_float(row.get("power", 0)),  # buying power
            "initial_margin": safe_float(row.get("initial_margin", 0)),
            "maintenance_margin": safe_float(row.get("maintenance_margin", 0)),
            "securities_assets": safe_float(row.get("securities_assets", 0)),
            "currency": str(row.get("currency", "USD")),
        }, None
    except Exception as e:
        return None, str(e)
    finally:
        trd_ctx.close()
        time.sleep(REQUEST_DELAY)


def get_positions() -> tuple[list | None, str | None]:
    """Fetch all open positions from Moomoo US account."""
    if not MOOMOO_AVAILABLE:
        return None, "Moomoo not available"

    trd_ctx = get_trade_context()
    try:
        # position_list_query does not require trade unlock
        ret, data = trd_ctx.position_list_query(trd_env=TrdEnv.REAL)
        if ret != RET_OK:
            return None, f"Position query failed: {data}"

        positions = []
        for _, row in data.iterrows():
            code = str(row.get("code", ""))
            option_info = parse_option_code(code)
            positions.append({
                "code": code,
                "stock_name": str(row.get("stock_name", "")),
                "qty": float(row.get("qty", 0)),
                "cost_price": float(row.get("cost_price", 0)),
                "market_val": float(row.get("market_val", 0)),
                "nominal_price": float(row.get("nominal_price", 0)),
                "pl_val": float(row.get("pl_val", 0)),
                "pl_ratio": float(row.get("pl_ratio", 0)),
                "position_side": str(row.get("position_side", "")),
                "option_info": option_info,
            })
        return positions, None
    except Exception as e:
        return None, str(e)
    finally:
        trd_ctx.close()
        time.sleep(REQUEST_DELAY)


def get_option_greeks(ticker: str, expiry_date: str) -> tuple[list | None, str | None]:
    """Fetch options chain with Greeks for a specific ticker and expiry."""
    if not MOOMOO_AVAILABLE:
        return None, "Moomoo not available"

    quote_ctx = get_quote_context()
    try:
        ret, chain_data = quote_ctx.get_option_chain(
            code=f"US.{ticker}",
            start=expiry_date,
            end=expiry_date,
            option_type=OptionType.PUT,
            option_cond_type=OptionCondType.OUTSIDE,
        )
        if ret != RET_OK:
            return None, f"Chain query failed: {chain_data}"

        greeks = []
        for _, row in chain_data.iterrows():
            greeks.append({
                "code": str(row.get("code", "")),
                "strike_price": float(row.get("strike_price", 0)),
                "iv": float(row.get("option_implied_volatility", 0)),
                "delta": float(row.get("option_delta", 0)),
                "gamma": float(row.get("option_gamma", 0)),
                "theta": float(row.get("option_theta", 0)),
                "vega": float(row.get("option_vega", 0)),
                "open_interest": int(row.get("option_open_interest", 0)),
                "volume": int(row.get("option_volume", 0)),
                "premium": float(row.get("option_premium", 0)),
            })
        return greeks, None
    except Exception as e:
        return None, str(e)
    finally:
        quote_ctx.close()
        time.sleep(REQUEST_DELAY)


def get_trade_history(start_date: str, end_date: str) -> tuple[list | None, str | None]:
    """Fetch historical filled orders from Moomoo (max 90 days per query)."""
    if not MOOMOO_AVAILABLE:
        return None, "Moomoo not available"

    trd_ctx = get_trade_context()
    try:
        ret, data = trd_ctx.unlock_trade(_get_trade_password())
        if ret != RET_OK:
            return None, f"Unlock failed: {data}"

        ret, data = trd_ctx.history_deal_list_query(
            trd_env=TrdEnv.REAL,
            start=start_date,
            end=end_date,
        )
        if ret != RET_OK:
            return None, f"History query failed: {data}"

        deals = []
        for _, row in data.iterrows():
            code = str(row.get("code", ""))
            option_info = parse_option_code(code)
            deals.append({
                "code": code,
                "stock_name": str(row.get("stock_name", "")),
                "deal_id": str(row.get("deal_id", "")),
                "order_id": str(row.get("order_id", "")),
                "qty": float(row.get("qty", 0)),
                "price": float(row.get("price", 0)),
                "trd_side": str(row.get("trd_side", "")),
                "create_time": str(row.get("create_time", "")),
                "option_info": option_info,
            })
        return deals, None
    except Exception as e:
        return None, str(e)
    finally:
        trd_ctx.close()
        time.sleep(REQUEST_DELAY)
