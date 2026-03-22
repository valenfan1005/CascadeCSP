"""
AI Entry Signal Service
Uses Claude to analyze a stock and provide a CSP entry signal.
"""
import os
import json
import logging
import math
import time
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
import requests
from anthropic import Anthropic

from server.services.finbert_sentiment import score_news_for_ticker
from server.services.yahoo_client import get_vix_term_structure

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cache signals for 30 minutes
_signal_cache: dict = {}
_SIGNAL_TTL = 1800

def _get_cached_signal(ticker: str) -> Optional[dict]:
    entry = _signal_cache.get(ticker)
    if entry and time.time() - entry["ts"] < _SIGNAL_TTL:
        return entry["data"]
    return None

def _set_signal_cache(ticker: str, data: dict):
    _signal_cache[ticker] = {"data": data, "ts": time.time()}


def _get_api_key() -> Optional[str]:
    """Get Anthropic API key from environment or .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # Try loading from .env
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY=") and not line.endswith("="):
                        return line.split("=", 1)[1].strip()
        except PermissionError:
            pass
    return None


def _fetch_yahoo_news(ticker: str) -> list[dict]:
    """Fetch recent news for a ticker from Yahoo Finance."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        result = []
        for n in news[:8]:
            content = n.get("content", {})
            result.append({
                "title": content.get("title", n.get("title", "")),
                "publisher": content.get("provider", {}).get("displayName", ""),
                "date": content.get("pubDate", ""),
            })
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch news for {ticker}: {e}")
        return []


def _fetch_support_levels(ticker: str, price: float) -> dict:
    """Calculate simple support/resistance levels from price history."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if hist.empty:
            return {}

        low_6m = float(hist['Low'].min())
        high_6m = float(hist['High'].max())
        avg_volume = float(hist['Volume'].mean())

        # Simple support: recent lows
        recent_30d = hist.tail(30)
        support_30d = float(recent_30d['Low'].min())

        return {
            "low_6m": round(low_6m, 2),
            "high_6m": round(high_6m, 2),
            "support_30d": round(support_30d, 2),
            "avg_volume_6m": int(avg_volume),
            "distance_from_high": round((high_6m - price) / high_6m * 100, 1),
            "distance_from_support": round((price - support_30d) / price * 100, 1),
        }
    except Exception:
        return {}


def generate_ai_signal(ticker: str, stock_data: dict = None, options_data: dict = None) -> dict:
    """
    Generate an AI-powered CSP entry signal for a ticker.

    stock_data: TradingView/scanner data (price, RSI, SMA, sector, etc.)
    options_data: Yahoo options chain data (ATM IV, best strikes, etc.)
    """
    # Check cache
    cached = _get_cached_signal(ticker)
    if cached:
        return cached

    # If no stock_data provided, fetch basic info
    if not stock_data:
        try:
            info = yf.Ticker(ticker).info
            stock_data = {
                "ticker": ticker,
                "name": info.get("shortName", ""),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap"),
                "pe_ttm": info.get("trailingPE"),
                "eps_ttm": info.get("trailingEps"),
                "beta": info.get("beta"),
            }
        except Exception:
            stock_data = {"ticker": ticker}

    price = stock_data.get("price", 0)

    # Fetch additional data in parallel
    news = []
    support = {}
    sentiment_data = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        news_future = pool.submit(_fetch_yahoo_news, ticker)
        support_future = pool.submit(_fetch_support_levels, ticker, price or 0)
        try:
            news = news_future.result(timeout=10)
        except Exception:
            pass
        try:
            support = support_future.result(timeout=10)
        except Exception:
            pass

    # Run FinBERT sentiment analysis on news headlines
    if news:
        try:
            sentiment_data = score_news_for_ticker(news)
            logger.info(f"FinBERT sentiment for {ticker}: {sentiment_data['aggregate']}")
        except Exception as e:
            logger.warning(f"FinBERT sentiment failed for {ticker}: {e}")

    # Fetch VIX term structure
    vix_term = None
    try:
        vix_term = get_vix_term_structure()
    except Exception:
        pass

    # Build the prompt (now includes sentiment scores + VIX term structure)
    prompt = _build_signal_prompt(ticker, stock_data, options_data, news, support, sentiment_data, vix_term)

    # Call Claude
    try:
        api_key = _get_api_key()
        if not api_key:
            return {"error": "ANTHROPIC_API_KEY not set", "ticker": ticker}

        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Parse JSON response
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

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            result = json.loads(json_str, strict=False)
        result["ticker"] = ticker
        result["generated_at"] = datetime.now().isoformat()
        result["price"] = price
        result["news"] = news
        result["sentiment"] = sentiment_data

        _set_signal_cache(ticker, result)
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI signal for {ticker}: {e}")
        return {"error": "Failed to parse AI response", "ticker": ticker, "raw": response_text[:500]}
    except Exception as e:
        logger.error(f"AI signal generation failed for {ticker}: {e}")
        return {"error": str(e), "ticker": ticker}


def _build_signal_prompt(ticker: str, stock: dict, options: dict, news: list, support: dict, sentiment: dict = None, vix_term: dict = None) -> str:
    """Build the analysis prompt for Claude."""

    news_text = ""
    if news and sentiment and sentiment.get("articles"):
        # Include FinBERT sentiment scores alongside each headline
        news_lines = []
        for article in sentiment["articles"][:6]:
            score = article.get("score", 0)
            label = article.get("sentiment", "neutral")
            score_str = f"{score:+.2f}" if score != 0 else "0.00"
            news_lines.append(
                f"  - [{label.upper()} {score_str}] {article['headline']} ({article.get('publisher', '')}, {article.get('date', 'recent')[:10] if article.get('date') else 'recent'})"
            )
        news_text = "\n".join(news_lines)
    elif news:
        news_text = "\n".join([f"  - {n['title']} ({n['publisher']}, {n['date'][:10] if n.get('date') else 'recent'})" for n in news[:6]])
    else:
        news_text = "  No recent news available"

    # Aggregate sentiment summary for Claude
    sentiment_text = "  Not available (FinBERT model not loaded)"
    if sentiment and sentiment.get("aggregate"):
        agg = sentiment["aggregate"]
        sentiment_text = f"""  Overall Sentiment: {agg['sentiment'].upper()} (avg score: {agg['avg_score']:+.3f})
  Bullish articles: {agg['bullish_count']} | Bearish: {agg['bearish_count']} | Neutral: {agg['neutral_count']} (total: {agg['total']})
  Score range: -1.0 (very bearish) to +1.0 (very bullish)"""

    options_text = "Not available"
    if options:
        atm_iv = options.get("atm_iv")
        best_16d = options.get("best_csp_16d", {})
        best_ret = options.get("best_csp_return", {})
        options_text = f"""
  ATM Implied Volatility: {f'{atm_iv*100:.1f}%' if atm_iv else 'N/A'}
  Best ~16-delta put: Strike ${best_16d.get('strike', 'N/A')}, Premium ${best_16d.get('mid', 'N/A')}, Delta {best_16d.get('delta', 'N/A')}, DTE {best_16d.get('dte', 'N/A')}, Annual Return {f"{best_16d.get('annualized_return', 0)*100:.1f}%" if best_16d.get('annualized_return') else 'N/A'}
  Best return put: Strike ${best_ret.get('strike', 'N/A')}, Premium ${best_ret.get('mid', 'N/A')}, Annual Return {f"{best_ret.get('annualized_return', 0)*100:.1f}%" if best_ret.get('annualized_return') else 'N/A'}"""

    support_text = "Not available"
    if support:
        support_text = f"""
  6-month Low: ${support.get('low_6m', 'N/A')}
  6-month High: ${support.get('high_6m', 'N/A')}
  30-day Support: ${support.get('support_30d', 'N/A')}
  Distance from High: {support.get('distance_from_high', 'N/A')}%
  Distance from Support: {support.get('distance_from_support', 'N/A')}%"""

    # VIX term structure context
    vix_text = "  Not available"
    if vix_term:
        vix_text = f"""  VIX 9-Day: {vix_term.get('vix_9d', 'N/A')} | VIX Spot (30D): {vix_term['vix_spot']} | VIX 3-Month: {vix_term['vix_3m']}
  Ratio (VIX/VIX3M): {vix_term['ratio']} → {vix_term['label']}
  Risk Level: {vix_term['risk_level'].upper()}
  Implication: {vix_term['advice']}"""

    prompt = f"""你是一位专精于卖Cash-Secured Put (CSP)的期权交易专家。请用中文分析以下股票并给出交易信号。

## VIX期限结构
{vix_text}

## 股票: {ticker} - {stock.get('name', '')}
- 当前价格: ${stock.get('price', 'N/A')}
- 板块: {stock.get('sector', 'N/A')} / {stock.get('industry', 'N/A')}
- 市值: ${f"{stock.get('market_cap', 0)/1e9:.1f}B" if stock.get('market_cap') else 'N/A'}
- P/E TTM: {f"{stock.get('pe_ttm', 0):.1f}" if stock.get('pe_ttm') else 'N/A'}
- EPS TTM: ${stock.get('eps_ttm', 'N/A')}
- Beta: {f"{stock.get('beta', 0):.2f}" if stock.get('beta') else 'N/A'}

## 技术指标
- RSI: {f"{stock.get('rsi', 0):.1f}" if stock.get('rsi') else 'N/A'}
- SMA 50: ${f"{stock.get('sma50', 0):.2f}" if stock.get('sma50') else 'N/A'}
- SMA 200: ${f"{stock.get('sma200', 0):.2f}" if stock.get('sma200') else 'N/A'}
- 1个月表现: {f"{stock.get('perf_1m', 0):.1f}%" if stock.get('perf_1m') is not None else 'N/A'}
- 3个月表现: {f"{stock.get('perf_3m', 0):.1f}%" if stock.get('perf_3m') is not None else 'N/A'}
- 距离财报: {stock.get('days_to_earnings', '未知')}天

## 支撑与阻力
{support_text}

## 期权数据
{options_text}

## 近期新闻（含FinBERT情绪评分）
{news_text}

## FinBERT综合情绪
{sentiment_text}

## 分析要求
基于以上数据，给出CSP入场信号。必须考虑：
1. IV是否足够高来justify卖溢价？
2. 技术面是否有利（超卖、在支撑位上方、在SMA200上方）？
3. 是否有即将到来的催化剂（财报、新闻）增加风险？
4. 若被assign，这只股票的基本面是否值得持有？
5. 推荐什么行权价和DTE？
6. FinBERT新闻情绪暗示什么？看空情绪可能意味着更高的assignment风险。
7. **VIX期限结构分析**：必须在summary中写出推理过程——VIX现货(30D)=X vs VIX3M=Y，ratio=Z，
   Contango(远期>现货)=正常环境可以卖，Backwardation(现货>远期)=恐慌中溢价肥但风险真实。

所有文字输出请全部使用中文。

请严格按以下JSON格式返回（不要markdown，JSON外不要有任何文字）：
{{
  "signal": "STRONG_SELL_CSP" | "SELL_CSP" | "CAUTIOUS" | "AVOID",
  "confidence": 1-10,
  "summary": "2-3句中文分析摘要，必须包含VIX期限结构的推理：VIX现货=X vs VIX3M=Y → ratio=Z → Contango/Backwardation → 对这只股票CSP的影响",
  "recommended_strike": <number or null>,
  "recommended_dte": <number or null>,
  "recommended_premium": <number or null>,
  "bull_case": "1句中文看多理由",
  "bear_case": "1句中文看空理由",
  "risks": ["风险1", "风险2", "风险3"],
  "key_levels": {{
    "support": <number or null>,
    "resistance": <number or null>,
    "max_pain_strike": <number or null>
  }}
}}"""

    return prompt
