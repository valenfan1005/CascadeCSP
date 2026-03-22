"""
Market Intelligence Service
Provides comprehensive US market analysis: technicals, sectors, news, Polymarket events, AI insights.
"""
import os
import json
import logging
import math
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import requests
import yfinance as yf

from server.services.yahoo_client import get_vix_term_structure
from server.services.finbert_sentiment import score_news_for_ticker

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cache for 10 minutes
_cache: dict = {}
_CACHE_TTL = 600

def _get_cached(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None

def _set_cache(key: str, data: dict):
    _cache[key] = {"data": data, "ts": time.time()}

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


def _get_api_key() -> Optional[str]:
    """Get Anthropic API key from environment or .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except PermissionError:
            pass
    return None


# ─── 1. Index Technical Analysis ───────────────────────────────

def _get_index_technicals() -> dict:
    """Get SPY, QQQ, DIA, IWM, VIX technicals."""
    symbols = {
        "SPY": "S&P 500",
        "QQQ": "Nasdaq 100",
        "DIA": "Dow Jones",
        "IWM": "Russell 2000",
        "^VIX": "VIX (Fear Index)",
    }

    results = {}
    for sym, name in symbols.items():
        try:
            stock = yf.Ticker(sym)
            hist = stock.history(period="6mo")
            if hist.empty:
                continue

            close = float(hist['Close'].iloc[-1])
            prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else close
            change_1d = (close - prev_close) / prev_close * 100

            # Calculate SMAs
            sma20 = float(hist['Close'].tail(20).mean()) if len(hist) >= 20 else None
            sma50 = float(hist['Close'].tail(50).mean()) if len(hist) >= 50 else None
            sma200 = float(hist['Close'].mean()) if len(hist) >= 100 else None

            # RSI (14-day)
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else None

            # Performance
            perf_1w = None
            perf_1m = None
            perf_3m = None
            perf_ytd = None
            if len(hist) >= 5:
                perf_1w = (close / float(hist['Close'].iloc[-5]) - 1) * 100
            if len(hist) >= 22:
                perf_1m = (close / float(hist['Close'].iloc[-22]) - 1) * 100
            if len(hist) >= 66:
                perf_3m = (close / float(hist['Close'].iloc[-66]) - 1) * 100
            # YTD
            year_start = hist[hist.index.year == datetime.now().year]
            if not year_start.empty:
                perf_ytd = (close / float(year_start['Close'].iloc[0]) - 1) * 100

            # 52-week high/low
            high_52w = float(hist['High'].max())
            low_52w = float(hist['Low'].min())
            pct_from_high = (close - high_52w) / high_52w * 100

            # Trend
            trend = "neutral"
            if sma50 and sma200:
                if close > sma50 > sma200:
                    trend = "bullish"
                elif close < sma50 < sma200:
                    trend = "bearish"
                elif close > sma200:
                    trend = "mildly_bullish"
                else:
                    trend = "mildly_bearish"

            results[sym] = {
                "name": name,
                "price": round(close, 2),
                "change_1d": round(change_1d, 2),
                "sma20": round(sma20, 2) if sma20 else None,
                "sma50": round(sma50, 2) if sma50 else None,
                "sma200": round(sma200, 2) if sma200 else None,
                "above_sma50": close > sma50 if sma50 else None,
                "above_sma200": close > sma200 if sma200 else None,
                "rsi": round(rsi, 1) if rsi else None,
                "perf_1w": round(perf_1w, 2) if perf_1w is not None else None,
                "perf_1m": round(perf_1m, 2) if perf_1m is not None else None,
                "perf_3m": round(perf_3m, 2) if perf_3m is not None else None,
                "perf_ytd": round(perf_ytd, 2) if perf_ytd is not None else None,
                "high_52w": round(high_52w, 2),
                "low_52w": round(low_52w, 2),
                "pct_from_high": round(pct_from_high, 2),
                "trend": trend,
            }
        except Exception as e:
            logger.warning(f"Failed to get technicals for {sym}: {e}")

    return results


# ─── 2. Sector Performance ─────────────────────────────────────

def _get_sector_performance() -> list:
    """Get sector ETF performance using TradingView scanner."""
    sector_etfs = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLV": "Healthcare",
        "XLE": "Energy",
        "XLY": "Consumer Disc.",
        "XLP": "Consumer Staples",
        "XLI": "Industrials",
        "XLU": "Utilities",
        "XLRE": "Real Estate",
        "XLB": "Materials",
        "XLC": "Communication",
    }

    # Use TradingView scanner for sector ETFs
    tickers = [f"AMEX:{t}" for t in sector_etfs.keys()]
    payload = {
        "symbols": {"tickers": tickers},
        "columns": ["name", "close", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.YTD", "RSI", "Volatility.M"],
    }

    try:
        resp = requests.post(
            "https://scanner.tradingview.com/america/scan",
            json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        cols = payload["columns"]
        for item in data.get("data", []):
            d = item.get("d", [])
            sym_full = item.get("s", "")
            sym = sym_full.split(":")[1] if ":" in sym_full else sym_full
            if len(d) < len(cols):
                continue
            row = dict(zip(cols, d))
            results.append({
                "symbol": sym,
                "sector": sector_etfs.get(sym, sym),
                "price": _safe_float(row.get("close")),
                "change_1d": _safe_float(row.get("change")),
                "perf_1w": _safe_float(row.get("Perf.W")),
                "perf_1m": _safe_float(row.get("Perf.1M")),
                "perf_3m": _safe_float(row.get("Perf.3M")),
                "perf_ytd": _safe_float(row.get("Perf.YTD")),
                "rsi": _safe_float(row.get("RSI")),
                "volatility": _safe_float(row.get("Volatility.M")),
            })

        results.sort(key=lambda x: x.get("perf_1m") or 0, reverse=True)
        return results
    except Exception as e:
        logger.warning(f"Sector performance fetch failed: {e}")
        return []


# ─── 3. Market News ─────────────────────────────────────────────

def _get_market_news() -> list:
    """Get market-wide news from Yahoo Finance for SPY."""
    all_news = []
    for ticker in ["SPY", "QQQ", "^GSPC"]:
        try:
            stock = yf.Ticker(ticker)
            news = stock.news or []
            for n in news[:5]:
                content = n.get("content", {})
                title = content.get("title", n.get("title", ""))
                # Deduplicate by title
                if title and not any(existing["title"] == title for existing in all_news):
                    all_news.append({
                        "title": title,
                        "publisher": content.get("provider", {}).get("displayName", ""),
                        "date": content.get("pubDate", ""),
                        "summary": content.get("summary", ""),
                    })
        except Exception:
            pass

    return all_news[:12]


# ─── 4. Polymarket Events ───────────────────────────────────────

def _get_polymarket_events() -> list:
    """Fetch key prediction market events from Polymarket API."""
    events = []

    # Keywords that MUST appear in the TITLE (not description) to avoid false matches
    # e.g. "market" in desc matches everything since Polymarket says "This market will resolve..."
    TITLE_KEYWORDS = [
        "fed ", "federal reserve", "recession", "gdp", "inflation", "tariff",
        "stock market", "s&p", "nasdaq", "dow jones", "interest rate",
        "fomc", "powell", "cpi", "unemployment", "jobs report", "payroll",
        "treasury", "debt ceiling", "default", "trade war", "sanctions",
        "oil price", "gold price", "bitcoin", "btc", "crypto", "ethereum",
        "rate cut", "rate hike", "economy", "economic", "capital gains tax",
    ]

    try:
        # Fetch all active events and keyword-filter for financial relevance
        resp = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={"active": True, "closed": False, "limit": 200},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return events

        all_events = resp.json() if isinstance(resp.json(), list) else []

        for event in all_events:
            title = (event.get("title", "") or "").lower()
            # Only match keywords in TITLE to avoid false positives from description boilerplate
            if not any(kw in title for kw in TITLE_KEYWORDS):
                continue

            markets = event.get("markets", [])
            market_data = []
            for m in markets[:5]:
                outcome_prices = m.get("outcomePrices", "")
                try:
                    prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                except Exception:
                    prices = []

                outcomes = m.get("outcomes", "")
                try:
                    outcome_names = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                except Exception:
                    outcome_names = []

                yes_price = float(prices[0]) if prices else None

                market_data.append({
                    "question": m.get("question", ""),
                    "yes_price": round(yes_price * 100, 1) if yes_price else None,
                    "volume": _safe_float(m.get("volume")),
                    "outcomes": outcome_names,
                    "outcome_prices": [round(float(p) * 100, 1) for p in prices] if prices else [],
                })

            if market_data:
                events.append({
                    "title": event.get("title", ""),
                    "slug": event.get("slug", ""),
                    "description": (event.get("description", "") or "")[:200],
                    "end_date": event.get("endDate", ""),
                    "markets": market_data,
                    "liquidity": _safe_float(event.get("liquidity")),
                    "volume": _safe_float(event.get("volume")),
                })

    except Exception as e:
        logger.warning(f"Polymarket fetch failed: {e}")

    # Sort by volume/liquidity descending to show most relevant first
    events.sort(key=lambda e: e.get("volume") or 0, reverse=True)
    return events[:15]


# ─── 5. AI Market Analysis ──────────────────────────────────────

def _generate_ai_market_analysis(indices: dict, sectors: list, news: list, polymarket: list, vix_term: dict = None, news_sentiment: dict = None) -> dict:
    """Use Claude to generate comprehensive market analysis."""
    api_key = _get_api_key()
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    # Build indices summary
    indices_text = ""
    for sym, data in indices.items():
        indices_text += f"  {sym} ({data['name']}): ${data['price']} ({data['change_1d']:+.2f}% today)"
        indices_text += f" | RSI={data.get('rsi', 'N/A')} | Trend={data.get('trend', 'N/A')}"
        indices_text += f" | 1W={data.get('perf_1w', 'N/A')}% | 1M={data.get('perf_1m', 'N/A')}% | YTD={data.get('perf_ytd', 'N/A')}%"
        indices_text += f" | From 52w High: {data.get('pct_from_high', 'N/A')}%\n"

    # Sectors
    sectors_text = ""
    for s in sectors:
        change_1d = s.get('change_1d')
        perf_1m = s.get('perf_1m')
        rsi = s.get('rsi')
        sectors_text += f"  {s['sector']}: 1D={f'{change_1d:.1f}' if change_1d is not None else 'N/A'}% | 1M={perf_1m if perf_1m is not None else 'N/A'}% | RSI={rsi if rsi is not None else 'N/A'}\n"

    # News with FinBERT sentiment scores
    if news_sentiment and news_sentiment.get("articles"):
        news_lines = []
        for article in news_sentiment["articles"][:10]:
            score = article.get("score", 0)
            label = article.get("sentiment", "neutral")
            score_str = f"{score:+.2f}" if score != 0 else "0.00"
            publisher = article.get("publisher", "")
            news_lines.append(f"  - [{label.upper()} {score_str}] {article['headline']} ({publisher})")
        news_text = "\n".join(news_lines)

        # Add aggregate summary
        agg = news_sentiment.get("aggregate", {})
        if agg:
            news_text += f"\n\n  FinBERT综合情绪: {agg.get('sentiment', 'neutral').upper()} (均分: {agg.get('avg_score', 0):+.3f})"
            news_text += f"\n  看多: {agg.get('bullish_count', 0)} | 看空: {agg.get('bearish_count', 0)} | 中性: {agg.get('neutral_count', 0)} (共{agg.get('total', 0)}条)"
    else:
        news_text = "\n".join([f"  - {n['title']} ({n['publisher']})" for n in news[:10]])

    # Polymarket
    poly_text = ""
    for e in polymarket[:8]:
        poly_text += f"  Event: {e['title']}\n"
        for m in e.get('markets', [])[:3]:
            poly_text += f"    → {m['question']}: "
            if m.get('outcome_prices') and m.get('outcomes'):
                try:
                    outcomes = m['outcomes'] if isinstance(m['outcomes'], list) else json.loads(m['outcomes'])
                    for name, pct in zip(outcomes, m['outcome_prices']):
                        poly_text += f"{name}={pct}% "
                except Exception:
                    poly_text += f"Yes={m.get('yes_price', 'N/A')}%"
            poly_text += "\n"

    # VIX term structure
    vix_term_text = "  Not available"
    if vix_term:
        vix_term_text = f"""  VIX 9-Day: {vix_term.get('vix_9d', 'N/A')} | VIX Spot (30D): {vix_term['vix_spot']} | VIX 3-Month: {vix_term['vix_3m']}
  Ratio (VIX/VIX3M): {vix_term['ratio']} → {vix_term['label']}
  Risk Level: {vix_term['risk_level'].upper()}
  Implication: {vix_term['advice']}
  Key insight: Contango (ratio < 1) = normal, market expects vol to decrease. Backwardation (ratio > 1) = panic, near-term fear exceeds long-term → premium is fat but assignment risk is elevated."""

    prompt = f"""你是一位资深宏观策略师和期权交易员。请用中文分析当前美股市场状况，为Cash-Secured Put (CSP) 期权卖方提供可操作的建议。

## VIX期限结构（对CSP择时至关重要）
{vix_term_text}

## 市场指数
{indices_text}

## 板块表现（按1个月表现排序）
{sectors_text}

## 近期市场新闻（含FinBERT情绪评分，-1.0=极度看空 到 +1.0=极度看多）
{news_text}

## 预测市场数据（Polymarket）
{poly_text if poly_text else "  暂无相关预测市场数据"}

## 分析要求
请提供全面的市场分析。必须涵盖：
1. 整体市场状态（牛市/熊市/震荡/高波动）
2. SPY和QQQ的关键技术位
3. 板块轮动信号
4. **新闻情绪分析**：结合FinBERT量化评分分析市场新闻情绪倾向，指出哪些重大新闻事件可能影响CSP卖方，
   FinBERT综合情绪是看多还是看空？与技术面信号是否一致？是否有异常看空新闻需要警惕？
5. 预测市场对宏观环境的暗示
6. 针对CSP卖方的具体建议（关注/回避哪些板块，理想DTE/delta）
7. **VIX期限结构深度分析**（这是最关键的部分）：
   - 明确写出VIX现货（30D）的具体数值 vs VIX 3个月期货的具体数值
   - 计算比值并解释含义（ratio < 1 = Contango正常结构，ratio > 1 = Backwardation恐慌结构）
   - 详细说明这个结构对CSP卖方意味着什么：
     * Contango → 市场预期波动率会降低，远期恐惧低于近期 → 正常环境，可以正常卖溢价
     * Backwardation → 市场恐慌，近期恐惧超过远期 → 溢价虽肥但assignment风险真实存在
   - 给出基于VIX结构的具体仓位建议

所有分析和commentary字段请全部使用中文。

请严格按以下JSON格式返回：
{{
  "market_regime": "BULLISH" | "MILDLY_BULLISH" | "NEUTRAL" | "MILDLY_BEARISH" | "BEARISH" | "HIGH_VOLATILITY",
  "regime_confidence": 1-10,
  "summary": "3-4句市场概述（中文），必须包含VIX期限结构的推理过程：VIX现货=X vs VIX3M=Y，ratio=Z，属于Contango/Backwardation，对CSP卖方意味着...",
  "spy_outlook": {{
    "direction": "UP" | "FLAT" | "DOWN",
    "support": <number>,
    "resistance": <number>,
    "commentary": "1-2句中文分析"
  }},
  "qqq_outlook": {{
    "direction": "UP" | "FLAT" | "DOWN",
    "support": <number>,
    "resistance": <number>,
    "commentary": "1-2句中文分析"
  }},
  "sector_picks": {{
    "best_for_csp": ["sector1", "sector2"],
    "avoid": ["sector1"],
    "reasoning": "1-2句中文解释"
  }},
  "csp_strategy": {{
    "recommended_dte": <number>,
    "recommended_delta": <number like -0.16>,
    "position_sizing": "conservative" | "normal" | "aggressive",
    "commentary": "2-3句中文CSP策略建议，必须引用VIX期限结构作为依据"
  }},
  "key_risks": ["风险1", "风险2", "风险3"],
  "key_catalysts": ["催化剂1", "催化剂2"],
  "polymarket_insights": "2-3句中文分析预测市场对宏观环境的暗示",
  "news_impact": "2-3句中文分析近期新闻对期权卖方环境的影响"
}}"""

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text
        json_str = response_text.strip()
        if json_str.startswith('```'):
            first_nl = json_str.index('\n') if '\n' in json_str else len(json_str)
            json_str = json_str[first_nl + 1:]
        if json_str.endswith('```'):
            json_str = json_str[:-3]
        json_str = json_str.strip()
        if not json_str.startswith('{'):
            brace_start = json_str.find('{')
            brace_end = json_str.rfind('}')
            if brace_start != -1 and brace_end != -1:
                json_str = json_str[brace_start:brace_end + 1]

        # Try parsing, if it fails try fixing common issues
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError:
            # Fix unescaped newlines inside JSON string values
            import re
            # Replace literal newlines inside strings with \\n
            fixed = re.sub(r'(?<=": ")(.*?)(?="[,\s*}])', lambda m: m.group(0).replace('\n', '\\n'), json_str, flags=re.DOTALL)
            try:
                raw = json.loads(fixed)
            except json.JSONDecodeError:
                # Last resort: use strict=False
                raw = json.loads(json_str, strict=False)
        # Normalize keys to match frontend expectations
        result = {
            "market_regime": raw.get("market_regime", "NEUTRAL"),
            "regime_confidence": raw.get("regime_confidence"),
            "summary": raw.get("summary", ""),
            "spy_outlook": raw.get("spy_outlook"),
            "qqq_outlook": raw.get("qqq_outlook"),
            "sectors": raw.get("sector_picks", raw.get("sectors")),
            "csp_strategy": {},
            "risks": raw.get("key_risks", raw.get("risks", [])),
            "catalysts": raw.get("key_catalysts", raw.get("catalysts", [])),
            "polymarket_insights": raw.get("polymarket_insights", ""),
            "news_impact": raw.get("news_impact", ""),
        }
        # Normalize csp_strategy fields
        csp = raw.get("csp_strategy", {})
        if csp:
            result["csp_strategy"] = {
                "dte": csp.get("recommended_dte", csp.get("dte")),
                "delta": csp.get("recommended_delta", csp.get("delta")),
                "sizing": csp.get("position_sizing", csp.get("sizing")),
                "commentary": csp.get("commentary", ""),
            }
        return result
    except Exception as e:
        logger.error(f"AI market analysis failed: {e}")
        return {"error": str(e)}


# ─── Public API ──────────────────────────────────────────────────

def _run_market_intel_sync() -> dict:
    """Run full market intelligence gathering."""
    cached = _get_cached("market_intel")
    if cached:
        return cached

    # Fetch all data in parallel
    with ThreadPoolExecutor(max_workers=5) as pool:
        indices_future = pool.submit(_get_index_technicals)
        sectors_future = pool.submit(_get_sector_performance)
        news_future = pool.submit(_get_market_news)
        poly_future = pool.submit(_get_polymarket_events)
        vix_term_future = pool.submit(get_vix_term_structure)

        indices = indices_future.result(timeout=30)
        sectors = sectors_future.result(timeout=15)
        news = news_future.result(timeout=15)
        polymarket = poly_future.result(timeout=15)
        try:
            vix_term = vix_term_future.result(timeout=10)
        except Exception:
            vix_term = None

    # FinBERT sentiment scoring on market news
    try:
        news_sentiment = score_news_for_ticker(news)
    except Exception as e:
        logger.error(f"FinBERT market news scoring failed: {e}")
        news_sentiment = None

    # AI Analysis (includes VIX term structure + FinBERT sentiment)
    ai_analysis = _generate_ai_market_analysis(indices, sectors, news, polymarket, vix_term, news_sentiment)

    result = {
        "generated_at": datetime.now().isoformat(),
        "indices": indices,
        "sectors": sectors,
        "news": news,
        "news_sentiment": news_sentiment,
        "polymarket": polymarket,
        "ai_analysis": ai_analysis,
    }

    _set_cache("market_intel", result)
    return result


def _run_market_intel_quick_sync() -> dict:
    """Quick market data without AI analysis."""
    cached = _get_cached("market_intel_quick")
    if cached:
        return cached

    with ThreadPoolExecutor(max_workers=4) as pool:
        indices_future = pool.submit(_get_index_technicals)
        sectors_future = pool.submit(_get_sector_performance)
        news_future = pool.submit(_get_market_news)
        poly_future = pool.submit(_get_polymarket_events)

        indices = indices_future.result(timeout=30)
        sectors = sectors_future.result(timeout=15)
        news = news_future.result(timeout=15)
        polymarket = poly_future.result(timeout=15)

    # FinBERT sentiment on market news (fast enough for quick load)
    try:
        news_sentiment = score_news_for_ticker(news)
    except Exception:
        news_sentiment = None

    result = {
        "generated_at": datetime.now().isoformat(),
        "indices": indices,
        "sectors": sectors,
        "news": news,
        "news_sentiment": news_sentiment,
        "polymarket": polymarket,
        "ai_analysis": None,
    }

    _set_cache("market_intel_quick", result)
    return result


async def run_market_intel() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_market_intel_sync)

async def run_market_intel_quick() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_market_intel_quick_sync)
