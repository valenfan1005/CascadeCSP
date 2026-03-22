"""
Yahoo Finance Client
Provides stock prices, VIX data, and SPY benchmark data.
Primary data source for market data (Moomoo may lack US Securities authority).
"""
from __future__ import annotations

import yfinance as yf
from datetime import date, datetime, timedelta
from functools import lru_cache


def get_stock_price(ticker: str) -> tuple[float | None, str | None]:
    """Get current/latest stock price from Yahoo Finance."""
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1]), None
        return None, f"No data returned for {ticker}"
    except Exception as e:
        return None, str(e)


def get_vix() -> float | None:
    """Get current VIX level."""
    try:
        vix = yf.Ticker("^VIX")
        data = vix.history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception:
        pass
    return None


def get_spy_price() -> float | None:
    """Get current SPY price for benchmark."""
    price, _ = get_stock_price("SPY")
    return price


def get_vix_term_structure() -> dict | None:
    """
    Get VIX term structure with historical percentile context.
    Determines Contango/Backwardation + how extreme the current reading is.

    Contango (VIX < VIX3M):  Normal market — safe to sell premium
    Backwardation (VIX > VIX3M): Fear/panic — premium is fat but risk is real
    """
    try:
        vix_ticker = yf.Ticker("^VIX")
        vix3m_ticker = yf.Ticker("^VIX3M")

        vix_spot = vix_ticker.fast_info.get("lastPrice")
        vix_3m = vix3m_ticker.fast_info.get("lastPrice")
        vix_9d = None
        try:
            vix_9d = yf.Ticker("^VIX9D").fast_info.get("lastPrice")
        except Exception:
            pass

        if not vix_spot or not vix_3m:
            return None

        ratio = vix_spot / vix_3m
        spread = vix_3m - vix_spot  # positive = contango

        # Historical percentile (1 year of spread data)
        spread_percentile = None
        vix_percentile = None
        try:
            import pandas as pd
            vix_hist = vix_ticker.history(period="1y")["Close"]
            vix3m_hist = vix3m_ticker.history(period="1y")["Close"]
            if len(vix_hist) > 50 and len(vix3m_hist) > 50:
                # Normalize index to date (strip timezone) for proper alignment
                vix_hist.index = vix_hist.index.normalize().tz_localize(None)
                vix3m_hist.index = vix3m_hist.index.normalize().tz_localize(None)
                combined = pd.DataFrame({"vix": vix_hist, "vix3m": vix3m_hist}).dropna()
                if len(combined) > 50:
                    hist_spreads = combined["vix3m"] - combined["vix"]
                    spread_percentile = round(
                        float((hist_spreads < spread).mean() * 100), 1
                    )
                    vix_percentile = round(
                        float((combined["vix"] < vix_spot).mean() * 100), 1
                    )
        except Exception:
            pass

        # Enhanced regime classification
        if vix_spot > vix_3m:
            if ratio > 1.15:
                structure = "DEEP_BACKWARDATION"
                label = "Deep Backwardation"
                risk = "very_high"
                csp_signal = "STOP"
                advice = "极端恐慌 — 溢价极肥但风险极高，建议暂停CSP操作"
            else:
                structure = "BACKWARDATION"
                label = "Backwardation"
                risk = "high"
                csp_signal = "CAUTION"
                advice = "市场恐慌 — 溢价丰厚但被行权风险真实存在，需极保守行权价"
        elif vix_spot < 15:
            structure = "CONTANGO_THIN"
            label = "Contango (Thin IV)"
            risk = "low"
            csp_signal = "REDUCE"
            advice = "市场过于平静 — 溢价太薄不值得冒风险，建议减少操作"
        elif vix_spot > 30:
            structure = "CONTANGO_EXTREME"
            label = "Contango (High VIX)"
            risk = "medium"
            csp_signal = "SELECTIVE"
            advice = "VIX极高但结构正常 — 精选高质量标的卖溢价，仓位保守"
        elif ratio < 0.90:
            structure = "STEEP_CONTANGO"
            label = "Steep Contango"
            risk = "low"
            csp_signal = "GO"
            advice = "理想环境 — 期限结构陡峭，IV将自然衰减，积极卖溢价"
        elif ratio < 0.95:
            structure = "CONTANGO"
            label = "Contango"
            risk = "low"
            csp_signal = "GO"
            advice = "正常环境 — 适合卖CSP，正常仓位"
        else:
            structure = "FLAT"
            label = "Flat"
            risk = "medium"
            csp_signal = "CAUTIOUS"
            advice = "结构趋平 — 可能转向，密切关注，用较保守行权价"

        return {
            "vix_9d": round(vix_9d, 2) if vix_9d else None,
            "vix_spot": round(vix_spot, 2),
            "vix_3m": round(vix_3m, 2),
            "ratio": round(ratio, 3),
            "spread": round(spread, 2),
            "spread_percentile": spread_percentile,
            "vix_percentile": vix_percentile,
            "structure": structure,
            "label": label,
            "risk_level": risk,
            "csp_signal": csp_signal,
            "advice": advice,
        }
    except Exception:
        return None


def get_spy_history(days: int = 252) -> list[dict]:
    """Get SPY historical prices for benchmark comparison."""
    try:
        spy = yf.Ticker("SPY")
        end = datetime.now()
        start = end - timedelta(days=days)
        data = spy.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if data.empty:
            return []
        return [
            {"date": idx.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 2)}
            for idx, row in data.iterrows()
        ]
    except Exception:
        return []


def get_spy_monthly_returns(year: int = None) -> list[dict]:
    """Get SPY monthly returns for benchmark comparison."""
    try:
        spy = yf.Ticker("SPY")
        if year:
            data = spy.history(start=f"{year}-01-01", end=f"{year}-12-31")
        else:
            data = spy.history(period="2y")

        if data.empty:
            return []

        data["month"] = data.index.to_period("M")
        monthly = data.groupby("month")["Close"].last()
        returns = monthly.pct_change().dropna()

        return [
            {
                "year": period.year,
                "month": period.month,
                "return_pct": round(float(ret) * 100, 2),
            }
            for period, ret in returns.items()
        ]
    except Exception:
        return []


def get_multiple_prices(tickers: list[str]) -> dict[str, float | None]:
    """Fetch prices for multiple tickers efficiently."""
    prices = {}
    for ticker in tickers:
        price, _ = get_stock_price(ticker)
        prices[ticker] = price
    return prices


# --------------- Ticker Analysis ---------------

def get_ticker_analysis(ticker: str) -> dict:
    """Get comprehensive ticker analysis: fundamentals, earnings, revenue, price history."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        # --- Key Metrics ---
        metrics = {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName") or ticker.upper(),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "previous_close": info.get("previousClose") or info.get("regularMarketPreviousClose"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            # P/E ratios
            "pe_ttm": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "pe_dynamic": info.get("priceEpsCurrentYear"),  # 动态市盈率 – matches Moomoo
            # EPS
            "eps_ttm": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "eps_current_year": info.get("epsCurrentYear"),
            # Revenue & Growth
            "revenue_ttm": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),  # YoY %
            "earnings_growth": info.get("earningsGrowth"),
            # Margins
            "profit_margin": info.get("profitMargins"),
            "gross_margin": info.get("grossMargins"),
            # Dividend
            "dividend_yield": info.get("dividendYield"),
            # Analyst
            "target_mean": info.get("targetMeanPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "recommendation": info.get("recommendationKey"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
            # P/S ratio
            "ps_ratio": info.get("priceToSalesTrailing12Months"),
        }

        return {"success": True, "metrics": metrics}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_earnings_history(ticker: str) -> dict:
    """Get quarterly earnings (EPS) history + forecasts."""
    try:
        stock = yf.Ticker(ticker)

        # --- Long EPS history from get_earnings_dates (up to 40 quarters) ---
        eps_history = []
        eps_forecast = []
        try:
            ed = stock.get_earnings_dates(limit=40)
            if ed is not None and not ed.empty:
                for idx, row in ed.iterrows():
                    dt = idx
                    est = _safe_float(row.get("EPS Estimate"))
                    actual = _safe_float(row.get("Reported EPS"))
                    surprise = _safe_float(row.get("Surprise(%)"))
                    # Build quarter label from date
                    if hasattr(dt, "month"):
                        q_num = ((dt.month - 1) // 3) + 1
                        label = f"Q{q_num}'{str(dt.year)[2:]}"
                        date_str = dt.strftime("%Y-%m-%d")
                    else:
                        label = str(dt)[:10]
                        date_str = str(dt)[:10]
                    entry = {
                        "quarter": label,
                        "date": date_str,
                        "eps_estimate": est,
                        "eps_actual": actual,
                        "surprise_pct": surprise,
                        "is_forecast": actual is None,
                    }
                    if actual is None:
                        # Skip ghost entries: no estimate, or date in the past
                        is_future = hasattr(dt, "year") and dt.year >= date.today().year
                        if est is not None and is_future:
                            eps_forecast.append(entry)
                    else:
                        eps_history.append(entry)
                # Reverse so oldest first (earnings_dates comes newest-first)
                eps_history.reverse()
                eps_forecast.reverse()
        except Exception:
            pass

        # --- Fallback: old earnings_history attr if above failed ---
        if not eps_history:
            try:
                eh = stock.earnings_history
                if eh is not None and not eh.empty:
                    for _, row in eh.iterrows():
                        eps_history.append({
                            "quarter": row.get("Quarter", ""),
                            "date": str(row.get("Earnings Date", "")),
                            "eps_estimate": _safe_float(row.get("EPS Estimate")),
                            "eps_actual": _safe_float(row.get("Reported EPS")),
                            "surprise_pct": _safe_float(row.get("Surprise(%)")),
                            "is_forecast": False,
                        })
            except Exception:
                pass

        # --- Analyst forward estimates (earnings_estimate & revenue_estimate) ---
        earnings_forecast = []
        try:
            ee = stock.earnings_estimate
            if ee is not None and not ee.empty:
                for period, row in ee.iterrows():
                    earnings_forecast.append({
                        "period": str(period),
                        "eps_avg": _safe_float(row.get("avg")),
                        "eps_low": _safe_float(row.get("low")),
                        "eps_high": _safe_float(row.get("high")),
                        "eps_year_ago": _safe_float(row.get("yearAgoEps")),
                        "num_analysts": int(row.get("numberOfAnalysts", 0)) if row.get("numberOfAnalysts") else None,
                        "growth": _safe_float(row.get("growth")),
                    })
        except Exception:
            pass

        revenue_forecast = []
        try:
            re_ = stock.revenue_estimate
            if re_ is not None and not re_.empty:
                for period, row in re_.iterrows():
                    revenue_forecast.append({
                        "period": str(period),
                        "revenue_avg": _safe_float(row.get("avg")),
                        "revenue_low": _safe_float(row.get("low")),
                        "revenue_high": _safe_float(row.get("high")),
                        "revenue_year_ago": _safe_float(row.get("yearAgoRevenue")),
                        "num_analysts": int(row.get("numberOfAnalysts", 0)) if row.get("numberOfAnalysts") else None,
                        "growth": _safe_float(row.get("growth")),
                    })
        except Exception:
            pass

        # --- Growth estimates ---
        growth_estimates = {}
        try:
            ge = stock.growth_estimates
            if ge is not None and not ge.empty:
                for period, row in ge.iterrows():
                    growth_estimates[str(period)] = {
                        "stock": _safe_float(row.get("stockTrend")),
                        "index": _safe_float(row.get("indexTrend")),
                    }
        except Exception:
            pass

        # --- Income statement for revenue history (annual) ---
        revenue_annual = []
        try:
            inc = stock.income_stmt
            if inc is not None and not inc.empty:
                for col in sorted(inc.columns):
                    rev = inc.at["Total Revenue", col] if "Total Revenue" in inc.index else None
                    ni = inc.at["Net Income", col] if "Net Income" in inc.index else None
                    eps_row = inc.at["Basic EPS", col] if "Basic EPS" in inc.index else None
                    revenue_annual.append({
                        "year": str(col.year) if hasattr(col, "year") else str(col),
                        "revenue": _safe_float(rev),
                        "net_income": _safe_float(ni),
                        "eps": _safe_float(eps_row),
                        "is_forecast": False,
                    })
        except Exception:
            pass

        # --- Quarterly income for more granular revenue ---
        revenue_quarterly = []
        try:
            qinc = stock.quarterly_income_stmt
            if qinc is not None and not qinc.empty:
                for col in sorted(qinc.columns):
                    rev = qinc.at["Total Revenue", col] if "Total Revenue" in qinc.index else None
                    ni = qinc.at["Net Income", col] if "Net Income" in qinc.index else None
                    eps_row = qinc.at["Basic EPS", col] if "Basic EPS" in qinc.index else None
                    if eps_row is None:
                        eps_row = qinc.at["Diluted EPS", col] if "Diluted EPS" in qinc.index else None
                    label = f"Q{((col.month - 1) // 3) + 1}'{str(col.year)[2:]}" if hasattr(col, "month") else str(col)
                    revenue_quarterly.append({
                        "quarter": label,
                        "date": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col),
                        "revenue": _safe_float(rev),
                        "net_income": _safe_float(ni),
                        "eps": _safe_float(eps_row),
                        "is_forecast": False,
                    })
        except Exception:
            pass

        # --- Build future quarter labels from earnings_dates timeline ---
        # Use the pattern of announcement dates to derive correct fiscal quarter labels
        # rather than naively mapping from calendar month.
        def _next_quarter_label(label: str) -> str:
            """Given Q2'26, return Q3'26. Given Q4'26, return Q1'27."""
            import re
            m = re.match(r"Q(\d)'(\d{2})", label)
            if not m:
                return label
            q, yr = int(m.group(1)), int(m.group(2))
            q += 1
            if q > 4:
                q = 1
                yr += 1
            return f"Q{q}'{yr:02d}"

        # Collect all known quarter labels (history + forecast from earnings_dates)
        all_known_labels = set()
        for h in eps_history:
            all_known_labels.add(h.get("quarter", ""))
        for f in eps_forecast:
            all_known_labels.add(f.get("quarter", ""))

        # The last forecast from earnings_dates is "0q"; derive "+1q" label from it
        last_forecast_label = eps_forecast[-1]["quarter"] if eps_forecast else None
        if not last_forecast_label and eps_history:
            last_forecast_label = _next_quarter_label(eps_history[-1]["quarter"])

        # Map period codes to labels using earnings_dates timeline
        period_label_map = {}
        if last_forecast_label:
            period_label_map["0q"] = last_forecast_label
            period_label_map["+1q"] = _next_quarter_label(last_forecast_label)

        # --- Append EPS forecasts from earnings_estimate to eps data ---
        for ef in earnings_forecast:
            period = ef["period"]
            if period in period_label_map:
                label = period_label_map[period] + "E"
                base_label = label.rstrip("E")
                # Skip if this quarter already exists in history or forecast
                if base_label in all_known_labels or label in all_known_labels:
                    continue
                eps_forecast.append({
                    "quarter": label,
                    "date": "",
                    "eps_estimate": ef["eps_avg"],
                    "eps_actual": None,
                    "eps_low": ef["eps_low"],
                    "eps_high": ef["eps_high"],
                    "growth": ef["growth"],
                    "num_analysts": ef["num_analysts"],
                    "is_forecast": True,
                })
                all_known_labels.add(label)

        # --- Append revenue forecasts to quarterly & annual ---
        for rf in revenue_forecast:
            period = rf["period"]
            if period in period_label_map:
                label = period_label_map[period] + "E"
                base_label = label.rstrip("E")
                all_rev_labels = set(q.get("quarter", "") for q in revenue_quarterly)
                if base_label not in all_rev_labels and label not in all_rev_labels:
                    revenue_quarterly.append({
                        "quarter": label,
                        "revenue": rf["revenue_avg"],
                        "net_income": None,
                        "eps": None,
                        "is_forecast": True,
                    })
            elif period in ("0y", "+1y"):
                from datetime import datetime as _dt
                now = _dt.now()
                yr = now.year if period == "0y" else now.year + 1
                yr_label = f"{yr}E"
                if not any(a.get("year") == yr_label for a in revenue_annual):
                    revenue_annual.append({
                        "year": yr_label,
                        "revenue": rf["revenue_avg"],
                        "net_income": None,
                        "eps": None,
                        "is_forecast": True,
                    })

        return {
            "success": True,
            "eps_history": eps_history,
            "eps_forecast": eps_forecast,
            "earnings_forecast": earnings_forecast,
            "revenue_forecast": revenue_forecast,
            "growth_estimates": growth_estimates,
            "revenue_annual": revenue_annual,
            "revenue_quarterly": revenue_quarterly,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_price_history(ticker: str, period: str = "5y") -> dict:
    """Get price history for charting."""
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period=period)
        if data.empty:
            return {"success": False, "error": f"No price data for {ticker}"}

        prices = []
        for idx, row in data.iterrows():
            prices.append({
                "date": idx.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]) if "Volume" in row else 0,
            })

        return {"success": True, "prices": prices, "period": period}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_tickers(query: str, limit: int = 10) -> list[dict]:
    """Search for tickers by name or symbol."""
    try:
        import urllib.request
        import json as _json
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount={limit}&newsCount=0&enableFuzzyQuery=false&quotesQueryId=tss_match_phrase_query"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
        results = []
        for q in data.get("quotes", []):
            if q.get("quoteType") in ("EQUITY", "ETF"):
                results.append({
                    "ticker": q.get("symbol", ""),
                    "name": q.get("longname") or q.get("shortname") or q.get("symbol", ""),
                    "type": q.get("quoteType", ""),
                    "exchange": q.get("exchange", ""),
                })
        return results
    except Exception:
        return []


def _safe_float(val) -> float | None:
    """Safely convert to float, handling NaN and None."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None
