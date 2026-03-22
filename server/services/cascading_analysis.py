"""
3-Tier Cascading CSP Analysis System
Tier 1: 大盘分析 (Macro) → Tier 2: 板块分析 (Sector/Industry) → Tier 3: 个股推荐 (Stock CSP)
Each tier's AI conclusion is passed as context to the next tier.
"""
import os
import json
import logging
import math
import time
import asyncio
from datetime import datetime
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor

import requests
import yfinance as yf

# Reuse existing services
from server.services.market_intel import (
    _get_index_technicals,
    _get_sector_performance,
    _get_market_news,
    _get_polymarket_events,
    _get_cached,
    _set_cache,
)
from server.services.yahoo_client import get_vix_term_structure
from server.services.finbert_sentiment import score_news_for_ticker
from server.services.csp_scanner import (
    _enrich_with_options,
    _score_stock,
    _parse_tv_row,
    TV_COLUMNS,
    TRADINGVIEW_URL,
)
from server.services.ai_signal import _fetch_yahoo_news, _fetch_support_levels
from server.services.stock_filters import (
    apply_hard_filters,
    compute_soft_score,
    tier2_filter_pipeline,
    detect_unusual_options,
)
from server.services.moomoo_options import get_csp_options, MOOMOO_AVAILABLE as MOOMOO_OPTS_AVAILABLE

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Sector ETF ↔ TradingView sector name mapping
SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Communication Services": "XLC",
}

# TradingView uses different sector names — map them
TV_SECTOR_NAMES = {
    "Technology": ["Technology Services", "Electronic Technology"],
    "Financials": ["Finance", "Financial Services"],
    "Healthcare": ["Health Technology", "Health Services"],
    "Energy": ["Energy Minerals", "Non-Energy Minerals"],
    "Consumer Discretionary": ["Consumer Durables", "Retail Trade", "Consumer Services"],
    "Consumer Staples": ["Consumer Non-Durables", "Distribution Services"],
    "Industrials": ["Producer Manufacturing", "Industrial Services", "Transportation"],
    "Utilities": ["Utilities"],
    "Real Estate": ["Real Estate"],
    "Materials": ["Process Industries", "Non-Energy Minerals"],
    "Communication Services": ["Communications"],
}

_CACHE_TTL = 14400  # 4 hours for in-memory cache

# Persist cascading results to disk so they survive restarts/refreshes
_PERSIST_FILE = os.path.join(os.path.dirname(__file__), "..", ".cascading_cache.json")


def _save_to_disk(result: dict):
    """Save cascading analysis result to disk."""
    try:
        with open(_PERSIST_FILE, "w") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save cascading cache to disk: {e}")


def _load_from_disk() -> Optional[dict]:
    """Load cascading analysis result from disk (no TTL — persists until user re-runs)."""
    try:
        if os.path.exists(_PERSIST_FILE):
            with open(_PERSIST_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load cascading cache from disk: {e}")
    return None


def _get_api_key() -> Optional[str]:
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


def _parse_claude_json(response_text: str) -> dict:
    """Extract and parse JSON from Claude response, handling truncation."""
    json_str = response_text.strip()
    if json_str.startswith('```'):
        first_nl = json_str.index('\n') if '\n' in json_str else len(json_str)
        json_str = json_str[first_nl + 1:]
    if json_str.endswith('```'):
        json_str = json_str[:-3]
    json_str = json_str.strip()
    if not json_str.startswith('{'):
        brace_start = json_str.find('{')
        if brace_start != -1:
            json_str = json_str[brace_start:]
    # Find the matching closing brace for the top-level object
    if json_str.startswith('{'):
        depth = 0
        in_string = False
        escape = False
        end_pos = len(json_str)
        for i, ch in enumerate(json_str):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break
        json_str = json_str[:end_pos]

    # Try normal parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Try strict=False
    try:
        return json.loads(json_str, strict=False)
    except json.JSONDecodeError:
        pass

    # Handle truncated JSON — progressively strip from the end until it parses
    # Strategy: find the last valid comma/bracket position and close everything
    repaired = json_str

    # First attempt: simple close
    for _ in range(3):
        if repaired.count('"') % 2 == 1:
            repaired += '"'
        open_brackets = repaired.count('[') - repaired.count(']')
        open_braces = repaired.count('{') - repaired.count('}')
        repaired += ']' * max(0, open_brackets)
        repaired += '}' * max(0, open_braces)
        try:
            return json.loads(repaired, strict=False)
        except json.JSONDecodeError:
            pass

        # Strip back to last clean delimiter and retry
        # Remove trailing partial value (find last , or [ or { before the break)
        for trim_char in [',', '[', '{', ':']:
            last_pos = json_str.rfind(trim_char)
            if last_pos > len(json_str) * 0.5:  # Only trim if we keep >50%
                repaired = json_str[:last_pos]
                if trim_char == ',':
                    pass  # Just remove trailing comma + incomplete value
                elif trim_char in ('[', '{'):
                    repaired += trim_char  # Keep the opener
                break
        else:
            break  # No good trim point found

    # Last resort: try truncating at each ] or } from the end
    for i in range(len(json_str) - 1, max(len(json_str) // 2, 0), -1):
        if json_str[i] in (']', '}'):
            candidate = json_str[:i+1]
            open_b = candidate.count('[') - candidate.count(']')
            open_c = candidate.count('{') - candidate.count('}')
            candidate += ']' * max(0, open_b)
            candidate += '}' * max(0, open_c)
            try:
                result = json.loads(candidate, strict=False)
                logger.warning(f"JSON repaired by truncation at position {i}/{len(json_str)}")
                return result
            except json.JSONDecodeError:
                continue

    logger.error(f"JSON parse failed even after all repair attempts, len={len(json_str)}")
    return {"error": f"JSON parse failed after repair attempts", "raw_truncated": True}


def _call_claude(prompt: str, max_tokens: int = 6000) -> dict:
    """Call Claude API and return parsed JSON."""
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = message.content[0].text
    if message.stop_reason == "max_tokens":
        logger.warning(f"Claude response truncated (max_tokens={max_tokens}, output_len={len(raw_text)}). Consider increasing max_tokens.")
    return _parse_claude_json(raw_text)


# ═══════════════════════════════════════════════════════════════
# TIER 1: 大盘分析 (Macro Market Analysis)
# ═══════════════════════════════════════════════════════════════

def _run_tier1(progress_cb: Callable = None) -> dict:
    """Tier 1: Macro market analysis. Returns AI conclusions + raw data."""
    if progress_cb:
        progress_cb(1, "fetching", "获取大盘指数、新闻、板块数据...")

    # Parallel data fetch (reuse existing functions)
    with ThreadPoolExecutor(max_workers=6) as pool:
        idx_f = pool.submit(_get_index_technicals)
        sec_f = pool.submit(_get_sector_performance)
        news_f = pool.submit(_get_market_news)
        poly_f = pool.submit(_get_polymarket_events)
        vix_f = pool.submit(get_vix_term_structure)

        # New: full VIX regime analysis
        from server.services.vix_regime import analyze_vix_regime, get_regime_summary_for_ai
        vix_regime_f = pool.submit(analyze_vix_regime)

        indices = idx_f.result(timeout=30)
        sectors = sec_f.result(timeout=15)
        news = news_f.result(timeout=15)
        polymarket = poly_f.result(timeout=15)
        try:
            vix_term = vix_f.result(timeout=10)
        except Exception:
            vix_term = None
        try:
            vix_regime = vix_regime_f.result(timeout=30)
        except Exception:
            vix_regime = None

    # FinBERT on market news
    try:
        news_sentiment = score_news_for_ticker(news)
    except Exception:
        news_sentiment = None

    if progress_cb:
        progress_cb(1, "analyzing", "AI分析宏观市场环境...")

    # Build prompt
    indices_text = ""
    for sym, data in indices.items():
        indices_text += f"  {sym}: ${data['price']} ({data['change_1d']:+.2f}%)"
        indices_text += f" RSI={data.get('rsi', 'N/A')} Trend={data.get('trend', 'N/A')}"
        indices_text += f" 1M={data.get('perf_1m', 'N/A')}% YTD={data.get('perf_ytd', 'N/A')}%"
        indices_text += f" 距52周高点: {data.get('pct_from_high', 'N/A')}%\n"

    sectors_text = ""
    for s in sectors:
        sectors_text += f"  {s['sector']}({s.get('etf', '')}): "
        sectors_text += f"1D={s.get('change_1d', 'N/A')}% 1M={s.get('perf_1m', 'N/A')}% RSI={s.get('rsi', 'N/A')}\n"

    # News with FinBERT
    if news_sentiment and news_sentiment.get("articles"):
        news_lines = []
        for a in news_sentiment["articles"][:10]:
            score = a.get("score", 0)
            label = a.get("sentiment", "neutral")
            news_lines.append(f"  [{label.upper()} {score:+.2f}] {a['headline']} ({a.get('publisher', '')})")
        news_text = "\n".join(news_lines)
        agg = news_sentiment.get("aggregate", {})
        if agg:
            news_text += f"\n  综合情绪: {agg.get('sentiment', 'neutral').upper()} (均分: {agg.get('avg_score', 0):+.3f})"
    else:
        news_text = "\n".join([f"  - {n['title']} ({n['publisher']})" for n in news[:10]])

    # Polymarket
    poly_text = ""
    for e in polymarket[:6]:
        poly_text += f"  {e['title']}: "
        for m in e.get('markets', [])[:2]:
            if m.get('outcome_prices') and m.get('outcomes'):
                try:
                    outcomes = m['outcomes'] if isinstance(m['outcomes'], list) else json.loads(m['outcomes'])
                    for name, pct in zip(outcomes, m['outcome_prices']):
                        poly_text += f"{name}={pct}% "
                except Exception:
                    pass
        poly_text += "\n"

    # VIX term structure — enhanced with full regime detection
    vix_text = "  不可用"
    if vix_regime and "error" not in vix_regime:
        alert = vix_regime.get("alert", {})
        trend_str = ""
        if vix_regime.get("trend_5d"):
            trend_str = " → ".join([f"{t['primary_ratio']:.3f}" for t in vix_regime["trend_5d"]])

        vix_text = f"""  VIX9D: {vix_regime['vix9d']} | VIX(30D): {vix_regime['vix']} | VIX3M: {vix_regime['vix3m']}
  主要比率(VIX/VIX3M): {vix_regime['primary_ratio']:.4f} → 状态: {vix_regime['regime']}
  前导指标(VIX9D/VIX): {vix_regime['leading_ratio']:.4f} → {vix_regime['leading_regime']}
  5日SMA方向: {vix_regime['sma_direction']} | 日变动: {vix_regime['daily_delta']:+.4f} ({vix_regime['delta_magnitude']})
  VIX历史分位: {vix_regime.get('vix_percentile', 'N/A')}% | 比率历史分位: {vix_regime.get('ratio_percentile', 'N/A')}%
  5日走势: {trend_str}
  状态转换: {vix_regime['transition']} (确信度: {vix_regime['transition_conviction']}) | 从{vix_regime['prev_regime']}→{vix_regime['regime']}
  仓位建议乘数: {vix_regime['size_multiplier']:.0%}
  警报等级: {alert.get('level', 'N/A')}
  建议: {alert.get('action', 'N/A')}

  关键判断逻辑：
  - Contango(比率<0.95)=正常结构，远期>近期，最适合卖溢价，仓位100%
  - Flat(0.95-1.05)=过渡状态，方向比位置更重要，看SMA方向决定加减仓
  - Backwardation(>1.05)=恐慌，近期恐惧>远期，溢价看似肥但是陷阱，仓位0%
  - Golden Window=Backwardation消退中且前导已正常化，IV高但在回归，最佳卖出时机，仓位40-50%
  - 前导指标(VIX9D/VIX)领先主要比率1-3天，用来确认转换的真实性"""
    elif vix_term:
        vix_text = f"""  VIX 9天: {vix_term.get('vix_9d', 'N/A')} | VIX现货(30D): {vix_term['vix_spot']} | VIX 3个月: {vix_term['vix_3m']}
  比值(VIX/VIX3M): {vix_term['ratio']} → {vix_term['label']}
  风险等级: {vix_term['risk_level'].upper()}"""

    prompt = f"""你是一位资深宏观策略师和期权交易员。请用中文分析当前美股大盘，为CSP期权卖方提供可操作建议。
这是三层串联分析的第一层（大盘分析），你的结论将直接影响后续的板块分析和个股选择。

## VIX期限结构
{vix_text}

## 市场指数
{indices_text}

## 板块表现
{sectors_text}

## 近期新闻（含FinBERT情绪评分）
{news_text}

## 预测市场（Polymarket）
{poly_text if poly_text else "  暂无数据"}

## 分析要求
1. 判断整体市场状态
2. VIX期限结构推理：写出VIX现货=X vs VIX3M=Y，ratio=Z，是Contango还是Backwardation，对卖CSP的含义
3. SPY/QQQ关键技术位
4. **重点：推荐和回避哪些板块**（至少推荐3个板块，至少标注1个回避板块）
5. CSP策略参数建议（DTE、delta、仓位大小）
6. 新闻情绪综合分析

请严格按以下JSON格式返回（全部中文，不要markdown）：
{{
  "market_regime": "BULLISH|MILDLY_BULLISH|NEUTRAL|MILDLY_BEARISH|BEARISH|HIGH_VOLATILITY",
  "regime_confidence": 1-10,
  "summary": "3-4句中文市场概述，必须包含VIX期限结构推理过程",
  "spy_outlook": {{"direction": "UP|FLAT|DOWN", "support": number, "resistance": number, "commentary": "中文"}},
  "qqq_outlook": {{"direction": "UP|FLAT|DOWN", "support": number, "resistance": number, "commentary": "中文"}},
  "favorable_sectors": [
    {{"sector": "板块英文名", "etf": "ETF代码", "confidence": 1-10, "reasoning": "中文推荐理由"}}
  ],
  "avoid_sectors": [
    {{"sector": "板块英文名", "etf": "ETF代码", "reasoning": "中文回避理由"}}
  ],
  "risk_level": "LOW|MEDIUM|HIGH|EXTREME",
  "csp_parameters": {{
    "recommended_dte": number,
    "recommended_delta": number,
    "position_sizing": "conservative|normal|aggressive"
  }},
  "key_risks": ["风险1", "风险2", "风险3"],
  "key_catalysts": ["催化剂1", "催化剂2"],
  "news_sentiment_summary": "1-2句中文新闻情绪总结"
}}"""

    ai_result = _call_claude(prompt, max_tokens=5000)

    return {
        "ai": ai_result,
        "indices": indices,
        "sectors": sectors,
        "news": news,
        "news_sentiment": news_sentiment,
        "polymarket": polymarket,
        "vix_term": vix_term,
        "vix_regime": vix_regime,
    }


# ═══════════════════════════════════════════════════════════════
# TIER 2: 板块/子行业分析 (Sector & Sub-Industry Analysis)
# ═══════════════════════════════════════════════════════════════

def _tradingview_sector_scan(tv_sector_names: list[str]) -> list[dict]:
    """Scan TradingView for stocks in specific sectors."""
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {
        "filter": [
            {"left": "market_cap_basic", "operation": "greater", "right": 5_000_000_000},
            {"left": "average_volume_10d_calc", "operation": "greater", "right": 500_000},
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "is_primary", "operation": "equal", "right": True},
            {"left": "sector", "operation": "in_range", "right": tv_sector_names},
        ],
        "options": {"lang": "en"},
        "columns": TV_COLUMNS,
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 60],
    }
    try:
        resp = requests.post(TRADINGVIEW_URL, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        results = []
        for item in resp.json().get("data", []):
            parsed = _parse_tv_row(item)
            if parsed:
                results.append(parsed)
        return results
    except Exception as e:
        logger.error(f"TradingView sector scan failed: {e}")
        return []


def _fetch_sector_news(etf: str) -> list[dict]:
    """Fetch news for a sector ETF."""
    try:
        stock = yf.Ticker(etf)
        news = stock.news or []
        results = []
        for n in news[:6]:
            content = n.get("content", {})
            title = content.get("title", n.get("title", ""))
            if title:
                results.append({
                    "title": title,
                    "publisher": content.get("provider", {}).get("displayName", ""),
                    "date": content.get("pubDate", ""),
                })
        return results
    except Exception:
        return []


def _run_tier2(tier1_result: dict, progress_cb: Callable = None) -> dict:
    """Tier 2: Sector & sub-industry analysis based on Tier 1 conclusions.
    Scans ALL sectors and rates each one, not just Tier 1 favorites."""
    tier1_ai = tier1_result["ai"]
    favorable = tier1_ai.get("favorable_sectors", [])
    avoid_sectors = tier1_ai.get("avoid_sectors", [])

    # Build list of ALL sectors to scan (not just favorable ones)
    favorable_names = set(s.get("sector", "") for s in favorable)
    avoid_names = set(s.get("sector", "") for s in avoid_sectors)

    all_sectors_to_scan = []
    for sector_name, etf in SECTOR_ETF_MAP.items():
        all_sectors_to_scan.append({
            "sector": sector_name,
            "etf": etf,
            "tier1_stance": "推荐" if sector_name in favorable_names else "回避" if sector_name in avoid_names else "未提及",
        })

    if progress_cb:
        progress_cb(2, "fetching", f"扫描全部 {len(all_sectors_to_scan)} 个板块...")

    # For each favorable sector, gather data in parallel
    sector_data = {}

    def _gather_sector_data(sector_info):
        sector_name = sector_info.get("sector", "")
        etf = sector_info.get("etf", SECTOR_ETF_MAP.get(sector_name, ""))

        # Get TradingView sector names for this sector
        tv_names = TV_SECTOR_NAMES.get(sector_name, [sector_name])

        # Parallel: sector news + TradingView sub-industry scan
        with ThreadPoolExecutor(max_workers=2) as pool:
            news_f = pool.submit(_fetch_sector_news, etf)
            stocks_f = pool.submit(_tradingview_sector_scan, tv_names)

            sector_news = news_f.result(timeout=15)
            sector_stocks = stocks_f.result(timeout=15)

        # FinBERT on sector news
        try:
            sentiment = score_news_for_ticker(sector_news) if sector_news else None
        except Exception:
            sentiment = None

        # === NEW: Apply hard filters + soft scoring BEFORE grouping ===
        spy_data = tier1_result.get("indices", {}).get("SPY", {})
        spy_perf_1m = spy_data.get("perf_1m", 0) if spy_data else 0

        # Enrich stocks with SMA data for trend filter (already have RSI from TV scan)
        for s in sector_stocks:
            # TradingView scan gives us: ticker, name, price, rsi, perf_1m, volatility_m, market_cap, industry
            # We need sma50/sma200 for trend filter — approximate from TV data if available
            # (full SMA calc happens in Tier 3; here we use price vs simple thresholds)
            pass

        filter_result = tier2_filter_pipeline(
            sector_stocks,
            spy_perf_1m=spy_perf_1m,
            max_candidates=30,  # per sector, generous — Claude sees all sectors combined
        )
        filtered_stocks = filter_result["candidates"]
        filter_stats = filter_result["stats"]

        logger.info(
            f"Sector {sector_name}: {filter_stats['total_scanned']} scanned → "
            f"{filter_stats['hard_rejected']} rejected → "
            f"{filter_stats['sent_to_claude']} candidates"
        )

        # Group FILTERED stocks by sub-industry
        sub_industries = {}
        for s in filtered_stocks:
            ind = s.get("industry", "Other")
            if not ind:
                ind = "Other"
            if ind not in sub_industries:
                sub_industries[ind] = []
            sub_industries[ind].append(s)

        # Compute per-sub-industry metrics (only from filtered stocks)
        sub_industry_metrics = []
        for ind_name, stocks in sub_industries.items():
            if len(stocks) < 1:
                continue
            rsis = [s["rsi"] for s in stocks if s.get("rsi")]
            perfs = [s["perf_1m"] for s in stocks if s.get("perf_1m") is not None]
            vols = [s["volatility_m"] for s in stocks if s.get("volatility_m")]
            mcaps = [s["market_cap"] for s in stocks if s.get("market_cap")]
            scores = [s["soft_score"] for s in stocks if s.get("soft_score")]

            # Top stocks by soft score (not just market cap)
            top_stocks = sorted(stocks, key=lambda x: x.get("soft_score", 0), reverse=True)[:5]

            sub_industry_metrics.append({
                "name": ind_name,
                "stock_count": len(stocks),
                "avg_rsi": round(sum(rsis) / len(rsis), 1) if rsis else None,
                "avg_perf_1m": round(sum(perfs) / len(perfs), 2) if perfs else None,
                "avg_volatility": round(sum(vols) / len(vols), 2) if vols else None,
                "avg_soft_score": round(sum(scores) / len(scores), 1) if scores else None,
                "total_market_cap": sum(mcaps) if mcaps else 0,
                "top_stocks": [{"ticker": s["ticker"], "name": s["name"], "price": s["price"],
                                "rsi": s.get("rsi"), "perf_1m": s.get("perf_1m"),
                                "volatility_m": s.get("volatility_m"), "market_cap": s.get("market_cap"),
                                "soft_score": s.get("soft_score"), "trend_label": s.get("trend_label"),
                                "relative_strength_1m": s.get("relative_strength_1m")}
                               for s in top_stocks],
            })

        # Sort sub-industries by avg soft score (combines volatility, RSI, trend, sentiment)
        sub_industry_metrics.sort(key=lambda x: -(x.get("avg_soft_score") or 0))

        sector_perf = next((s.get("perf_1m", 0) for s in tier1_result.get("sectors", [])
                           if s.get("etf") == etf), 0)
        relative_strength = round((sector_perf or 0) - (spy_perf_1m or 0), 2)

        return {
            "sector": sector_name,
            "etf": etf,
            "news": sector_news,
            "news_sentiment": sentiment,
            "sub_industries": sub_industry_metrics,
            "relative_strength_vs_spy": relative_strength,
            "filter_stats": filter_stats,
            "stock_count": len(sector_stocks),
            "tier1_stance": sector_info.get("tier1_stance", "未提及"),
        }

    # Gather ALL sectors in parallel (not just favorable)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_gather_sector_data, s): s for s in all_sectors_to_scan}
        for future in futures:
            try:
                result = future.result(timeout=30)
                sector_data[result["sector"]] = result
            except Exception as e:
                logger.error(f"Sector data gather failed: {e}")

    if progress_cb:
        progress_cb(2, "analyzing", "AI分析板块和子行业投资价值...")

    # Build Tier 2 Claude prompt
    tier1_fav_list = ', '.join(s.get('sector','') for s in favorable)
    tier1_avoid_list = ', '.join(s.get('sector','') for s in avoid_sectors) if avoid_sectors else '无'
    tier1_summary = f"""Tier 1大盘结论:
  市场状态: {tier1_ai.get('market_regime', 'N/A')} (信心: {tier1_ai.get('regime_confidence', 'N/A')}/10)
  风险等级: {tier1_ai.get('risk_level', 'N/A')}
  VIX结构: {tier1_result.get('vix_term', {}).get('label', 'N/A')} (ratio={tier1_result.get('vix_term', {}).get('ratio', 'N/A')})
  CSP参数: DTE={tier1_ai.get('csp_parameters', {}).get('recommended_dte', 'N/A')} Delta={tier1_ai.get('csp_parameters', {}).get('recommended_delta', 'N/A')} 仓位={tier1_ai.get('csp_parameters', {}).get('position_sizing', 'N/A')}
  Tier1推荐板块: {tier1_fav_list}
  Tier1回避板块: {tier1_avoid_list}"""

    sector_details = ""
    for name, data in sector_data.items():
        # Mark Tier 1 stance
        stance = data.get("tier1_stance", "未提及")
        stance_tag = f" [Tier1: {stance}]" if stance != "未提及" else ""
        sector_details += f"\n### {name} ({data['etf']}){stance_tag}\n"
        sector_details += f"  相对SPY强度: {data['relative_strength_vs_spy']:+.2f}%\n"

        # News sentiment
        if data.get("news_sentiment") and data["news_sentiment"].get("aggregate"):
            agg = data["news_sentiment"]["aggregate"]
            sector_details += f"  新闻情绪: {agg['sentiment'].upper()} (均分: {agg['avg_score']:+.3f}, 共{agg['total']}条)\n"
            if data["news_sentiment"].get("articles"):
                for a in data["news_sentiment"]["articles"][:3]:
                    sector_details += f"    [{a['sentiment'].upper()} {a['score']:+.2f}] {a['headline']}\n"

        # Filter stats
        fs = data.get("filter_stats", {})
        if fs:
            sector_details += f"  过滤统计: 扫描{fs.get('total_scanned',0)}只 → 硬性过滤淘汰{fs.get('hard_rejected',0)}只 → {fs.get('sent_to_claude',0)}只候选\n"
            sector_details += f"  (已排除：市值<2B、RSI>80、价格<$10、确认下跌趋势的股票)\n"

        # Sub-industries (now sorted by avg_soft_score)
        sector_details += f"  子行业数量: {len(data['sub_industries'])}\n"
        for sub in data["sub_industries"][:8]:
            top_tickers = ", ".join(
                f"{s['ticker']}(评分{s.get('soft_score','?')}{'↑' if s.get('trend_label')=='UPTREND' else '↗' if s.get('trend_label')=='PULLBACK' else ''})"
                for s in sub["top_stocks"][:3]
            )
            sector_details += f"  - {sub['name']}: {sub['stock_count']}只 | "
            sector_details += f"RSI={sub.get('avg_rsi', 'N/A')} | 1M={sub.get('avg_perf_1m', 'N/A')}% | "
            sector_details += f"波动率={sub.get('avg_volatility', 'N/A')}% | "
            sector_details += f"CSP综合评分={sub.get('avg_soft_score', 'N/A')} | 代表: {top_tickers}\n"

    prompt = f"""你是一位资深板块分析师和期权策略师。这是三层串联分析的第二层（板块/子行业分析）。
基于第一层大盘分析的结论，对**全部11个板块**进行独立评级，找出最适合卖CSP的板块、子行业和代表性个股。

**重要：以下数据已经过硬性过滤（市值>2B、RSI<80、价格>$10、非下跌趋势），你看到的都是通过基本筛选的候选股。
每只股票附带CSP综合评分（满分120），评分越高越适合CSP操作。Tier 1的板块偏好仅供参考，你应该根据数据独立判断。**

## 第一层大盘分析结论
{tier1_summary}

## 全部板块详细数据（已过滤）
{sector_details}

## 分析要求
1. **对全部板块逐一评级**（STRONG_BUY/BUY/NEUTRAL/AVOID），即使Tier 1没有推荐，只要数据支持也可以给高评级
2. 重点分析每个板块内的**子行业**，结合CSP综合评分、新闻情绪、技术面排名
3. 优先选择CSP综合评分高、趋势向上(↑)或健康回调(↗)的子行业
4. 从每个STRONG_BUY和BUY板块的推荐子行业中选出2-3只评分最高的股票进入Tier 3个股分析
5. 说明回避哪些子行业及原因
6. 评级必须基于数据（相对强度、RSI、新闻情绪、候选股质量），不要仅因Tier 1推荐就自动给高评级

**重要：输出JSON必须紧凑，每个字段尽量简短。summary和reasoning控制在15字以内。**

请严格按以下JSON格式返回（全部中文，必须包含全部11个板块）：
{{
  "sector_analysis": [
    {{
      "sector": "板块英文名",
      "etf": "ETF代码",
      "rating": "STRONG_BUY|BUY|NEUTRAL|AVOID",
      "summary": "15字以内中文总评",
      "sub_industries": [
        {{
          "name": "子行业英文名",
          "rating": "STRONG_BUY|BUY|NEUTRAL|AVOID",
          "csp_attractiveness": 1-10,
          "recommended_stocks": ["TICKER1", "TICKER2"],
          "reasoning": "15字以内"
        }}
      ]
    }}
  ],
  "top_picks": [
    {{"rank": 1, "sector": "板块", "sub_industry": "子行业", "ticker": "TICKER", "reasoning": "15字以内"}}
  ],
  "avoid_sub_industries": [
    {{"sector": "板块", "sub_industry": "子行业", "reason": "15字以内"}}
  ]
}}

**注意：NEUTRAL和AVOID板块只需列出前2个子行业即可，STRONG_BUY和BUY板块列出前5个子行业。**"""

    ai_result = _call_claude(prompt, max_tokens=16000)

    return {
        "ai": ai_result,
        "sector_data": sector_data,
    }


# ═══════════════════════════════════════════════════════════════
# TIER 3: 个股CSP推荐 (Individual Stock Recommendations)
# ═══════════════════════════════════════════════════════════════

def _run_tier3(tier1_result: dict, tier2_result: dict, progress_cb: Callable = None) -> dict:
    """Tier 3: Individual stock CSP recommendations based on Tier 1+2."""
    tier2_ai = tier2_result["ai"]

    # Extract stock tickers with BALANCED SECTOR REPRESENTATION
    # Ensure each recommended sector gets fair representation in Tier 3
    top_picks = tier2_ai.get("top_picks", [])
    sector_analysis = tier2_ai.get("sector_analysis", [])

    # Build per-sector stock lists
    sector_stocks = {}  # sector_name -> [tickers]
    seen = set()

    # From top_picks
    for pick in top_picks:
        t = pick.get("ticker", "")
        sector = pick.get("sector", "Unknown")
        if t and t not in seen:
            sector_stocks.setdefault(sector, []).append(t)
            seen.add(t)

    # From sector_analysis recommended_stocks
    for sector in sector_analysis:
        sector_name = sector.get("sector", "Unknown")
        if sector.get("rating") == "AVOID":
            continue  # Skip AVOID sectors entirely
        for sub in sector.get("sub_industries", []):
            if sub.get("rating") in ("STRONG_BUY", "BUY"):
                for t in sub.get("recommended_stocks", []):
                    if t not in seen:
                        sector_stocks.setdefault(sector_name, []).append(t)
                        seen.add(t)

    # Include ALL stocks from STRONG_BUY and BUY sub-industries — no cap
    tickers = []
    for sector_name in sector_stocks:
        stocks = sector_stocks[sector_name]
        tickers.extend(stocks)
        logger.info(f"Tier 3 sector: {sector_name} → {len(stocks)} stocks: {stocks}")

    # Always include star stocks — high liquidity, popular for CSP
    STAR_STOCKS = ["NVDA", "TSLA", "META", "HOOD", "GOOGL", "AMZN"]
    star_added = []
    for t in STAR_STOCKS:
        if t not in seen:
            tickers.append(t)
            seen.add(t)
            star_added.append(t)
    if star_added:
        logger.info(f"Tier 3 star stocks added: {star_added}")

    logger.info(f"Tier 3 total candidates: {len(tickers)} ({len(tickers) - len(star_added)} from Tier 2 + {len(star_added)} star stocks)")

    if not tickers:
        return {"ai": {"error": "Tier 2未推荐任何个股"}, "stocks": []}

    if progress_cb:
        progress_cb(3, "fetching", f"获取{len(tickers)}只个股基本面、技术面和新闻数据...")

    # NO Moomoo batch here — option analysis is done per-stock on demand (separate endpoint)
    # Tier 3 focuses ONLY on: "Is this stock safe to hold for 30 days?"

    # For each stock, gather fundamental + technical + news data in parallel
    stock_results = {}

    def _gather_stock_data(ticker: str):
        """Gather all data for a single stock."""
        try:
            # Get basic info from yfinance
            yf_ticker = yf.Ticker(ticker)
            info = yf_ticker.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if not price:
                fast = yf_ticker.fast_info
                price = fast.get("lastPrice")
            if not price:
                return None

            avg_volume = info.get("averageVolume", 0) or 0

            stock_data = {
                "ticker": ticker,
                "name": info.get("shortName", info.get("longName", "")),
                "price": round(price, 2),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap"),
                "pe_ttm": info.get("trailingPE"),
                "eps_ttm": info.get("trailingEps"),
                "beta": info.get("beta"),
                "avg_volume": avg_volume,
            }

            # Option liquidity check (yfinance — free, no Moomoo needed)
            option_liquidity = "UNKNOWN"
            put_oi = 0
            try:
                exps = yf_ticker.options
                if exps:
                    chain = yf_ticker.option_chain(exps[0])
                    puts = chain.puts
                    put_oi = int(puts['openInterest'].sum()) if 'openInterest' in puts.columns else 0
                    put_vol = int(puts['volume'].sum()) if 'volume' in puts.columns else 0
                    stock_data["put_oi"] = put_oi
                    stock_data["put_volume"] = put_vol
                    stock_data["put_strikes"] = len(puts)
                    if put_oi >= 50000 and put_vol >= 1000:
                        option_liquidity = "HIGH"
                    elif put_oi >= 10000 and put_vol >= 200:
                        option_liquidity = "MEDIUM"
                    elif put_oi >= 3000:
                        option_liquidity = "LOW"
                    else:
                        option_liquidity = "ILLIQUID"
                else:
                    option_liquidity = "NO_OPTIONS"
            except Exception:
                pass
            stock_data["option_liquidity"] = option_liquidity

            # HARD FILTER: Skip stocks with low option liquidity
            # Require Put OI >= 3000 to ensure reasonable bid-ask spreads for CSP
            if option_liquidity in ("ILLIQUID", "NO_OPTIONS", "LOW"):
                logger.info(f"Tier 3 SKIP {ticker}: option_liquidity={option_liquidity} put_oi={put_oi} put_vol={put_vol}")
                return {"skipped": True, "ticker": ticker, "reason": f"期权流动性不足(Put OI={put_oi}, Vol={put_vol})", "option_liquidity": option_liquidity}

            # Technical indicators + drawdown from ONE history call (avoid duplicate request)
            try:
                hist = yf_ticker.history(period="6mo")
                if len(hist) >= 14:
                    closes = hist['Close'].values
                    # RSI
                    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                    gains = [max(d, 0) for d in deltas[-14:]]
                    losses = [-min(d, 0) for d in deltas[-14:]]
                    avg_gain = sum(gains) / 14
                    avg_loss = sum(losses) / 14
                    if avg_loss > 0:
                        rs = avg_gain / avg_loss
                        stock_data["rsi"] = round(100 - (100 / (1 + rs)), 1)
                    # SMA
                    if len(closes) >= 50:
                        stock_data["sma50"] = round(float(closes[-50:].mean()), 2)
                    if len(closes) >= 200:
                        stock_data["sma200"] = round(float(closes[-200:].mean()), 2)
                    elif len(closes) >= 120:
                        stock_data["sma200"] = round(float(closes.mean()), 2)
                    # Performance
                    if len(closes) >= 22:
                        stock_data["perf_1m"] = round((closes[-1] / closes[-22] - 1) * 100, 2)

                    # Max drawdown in last 3 months (reuse same hist data)
                    closes_3m = closes[-66:] if len(closes) >= 66 else closes
                    if len(closes_3m) >= 10:
                        peak = closes_3m[0]
                        max_dd = 0
                        for c in closes_3m:
                            if c > peak:
                                peak = c
                            dd = (c - peak) / peak * 100
                            if dd < max_dd:
                                max_dd = dd
                        stock_data["max_drawdown_3m"] = round(max_dd, 2)
                        returns = [(closes_3m[i] - closes_3m[i-1]) / closes_3m[i-1] for i in range(1, len(closes_3m))]
                        stock_data["daily_vol"] = round((sum(r**2 for r in returns) / len(returns)) ** 0.5 * 100, 2)
            except Exception:
                pass

            # Earnings distance
            try:
                cal = yf_ticker.calendar
                if cal is not None:
                    if isinstance(cal, dict):
                        ed = cal.get("Earnings Date")
                        if isinstance(ed, list) and ed:
                            from datetime import date
                            d = ed[0]
                            if hasattr(d, 'date'):
                                d = d.date()
                            days = (d - date.today()).days
                            stock_data["days_to_earnings"] = max(0, days)
            except Exception:
                pass

            # News (FinBERT runs AFTER all stocks are gathered — too CPU-heavy for parallel)
            news = _fetch_yahoo_news(ticker)
            sentiment = None  # Will be filled in post-processing

            # Support/resistance levels
            support = _fetch_support_levels(ticker, price)

            # Add trend label
            if stock_data.get("sma50") and stock_data.get("sma200"):
                if price > stock_data["sma50"] and price > stock_data["sma200"]:
                    stock_data["trend"] = "UPTREND"
                elif price > stock_data["sma200"]:
                    stock_data["trend"] = "PULLBACK"
                else:
                    stock_data["trend"] = "DOWNTREND"
            elif stock_data.get("sma50"):
                stock_data["trend"] = "UPTREND" if price > stock_data["sma50"] else "DOWNTREND"

            # EPS growth data
            try:
                eps_ttm = info.get("trailingEps")
                eps_forward = info.get("forwardEps")
                earnings_growth = info.get("earningsGrowth")  # QoQ
                revenue_growth = info.get("revenueGrowth")

                stock_data["eps_ttm"] = round(eps_ttm, 2) if eps_ttm else None
                stock_data["eps_forward"] = round(eps_forward, 2) if eps_forward else None
                stock_data["earnings_growth_qoq"] = round(earnings_growth * 100, 1) if earnings_growth else None
                stock_data["revenue_growth_qoq"] = round(revenue_growth * 100, 1) if revenue_growth else None

                # EPS growth rate (forward vs trailing)
                if eps_ttm and eps_forward and eps_ttm > 0:
                    stock_data["eps_growth_fwd"] = round((eps_forward - eps_ttm) / eps_ttm * 100, 1)

                # Recent earnings surprises
                try:
                    eh = yf_ticker.earnings_history
                    if eh is not None and not eh.empty:
                        recent = eh.tail(4)
                        beats = sum(1 for _, r in recent.iterrows() if (r.get("surprisePercent") or 0) > 0)
                        avg_surprise = recent["surprisePercent"].mean() * 100 if "surprisePercent" in recent.columns else 0
                        stock_data["earnings_beats_last4"] = beats
                        stock_data["avg_earnings_surprise"] = round(avg_surprise, 1)
                except Exception:
                    pass
            except Exception:
                pass

            # Institutional holdings (13F, ~45 day lag)
            institutional = None
            try:
                ih = yf_ticker.institutional_holders
                if ih is not None and not ih.empty:
                    top5 = []
                    for _, row in ih.head(5).iterrows():
                        pct_change = row.get("pctChange", 0) or 0
                        top5.append({
                            "holder": row.get("Holder", ""),
                            "pct_held": round(float(row.get("pctHeld", 0) or 0) * 100, 2),
                            "change": round(float(pct_change) * 100, 1),
                        })
                    # Summary: net institutional sentiment
                    changes = [h["change"] for h in top5 if h["change"] != 0]
                    net_buying = sum(1 for c in changes if c > 0)
                    net_selling = sum(1 for c in changes if c < 0)
                    mh = yf_ticker.major_holders
                    inst_pct = float(mh.iloc[1]["Value"] * 100) if mh is not None and len(mh) > 1 else None
                    institutional = {
                        "top5": top5,
                        "inst_pct": round(inst_pct, 1) if inst_pct else None,
                        "net_signal": "增持" if net_buying > net_selling else "减持" if net_selling > net_buying else "持平",
                        "buying_count": net_buying,
                        "selling_count": net_selling,
                    }
            except Exception:
                pass

            # Insider transactions (SEC Form 4, ~2 day lag)
            insider = None
            try:
                it = yf_ticker.insider_transactions
                if it is not None and not it.empty:
                    recent = it.head(10)
                    sales = recent[recent["Text"].str.contains("Sale", case=False, na=False)]
                    buys = recent[recent["Text"].str.contains("Purchase", case=False, na=False)]
                    total_sold = sales["Value"].sum() if not sales.empty else 0
                    total_bought = buys["Value"].sum() if not buys.empty else 0
                    insider = {
                        "recent_sales": len(sales),
                        "recent_buys": len(buys),
                        "total_sold_value": int(total_sold),
                        "total_bought_value": int(total_bought),
                        "net_signal": "内部人买入" if total_bought > total_sold else "内部人抛售" if total_sold > 0 else "无交易",
                        "notable": [],
                    }
                    # Add notable large transactions
                    for _, row in recent.head(3).iterrows():
                        val = row.get("Value", 0) or 0
                        if val > 0:
                            insider["notable"].append({
                                "who": row.get("Insider", ""),
                                "position": row.get("Position", ""),
                                "action": "卖出" if "Sale" in str(row.get("Text", "")) else "买入" if "Purchase" in str(row.get("Text", "")) else "授予",
                                "value": int(val),
                            })
            except Exception:
                pass

            return {
                "stock": stock_data,
                "news": news,
                "sentiment": sentiment,
                "support": support,
                "institutional": institutional,
                "insider": insider,
            }
        except Exception as e:
            logger.error(f"Stock data gather failed for {ticker}: {e}")
            return None

    # Parallel stock data gathering — batched to avoid yfinance rate-limiting
    # Process in batches of BATCH_SIZE with brief pauses between batches
    import time as _time
    BATCH_SIZE = 10
    skipped_stocks = []
    failed_tickers = []

    batches = [tickers[i:i+BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]
    logger.info(f"Tier 3: {len(tickers)} candidates in {len(batches)} batches of {BATCH_SIZE}")

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            _time.sleep(1.5)  # Pause between batches to avoid rate-limit
        if progress_cb and batch_idx > 0:
            progress_cb(3, "fetching", f"获取个股数据... 第{batch_idx+1}/{len(batches)}批 (已完成{len(stock_results)}只)")

        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as pool:
            futures = {pool.submit(_gather_stock_data, t): t for t in batch}
            for future in futures:
                ticker = futures[future]
                try:
                    result = future.result(timeout=60)
                    if result and result.get("skipped"):
                        skipped_stocks.append(result)
                        logger.info(f"Skipped {result['ticker']}: {result['reason']}")
                    elif result:
                        stock_results[ticker] = result
                    else:
                        failed_tickers.append(ticker)
                except Exception as e:
                    failed_tickers.append(ticker)
                    logger.error(f"Stock {ticker} data failed: {e}")

    # Retry failed tickers in smaller batches (often yfinance rate-limit recovers after pause)
    if failed_tickers:
        logger.info(f"Tier 3: Retrying {len(failed_tickers)} failed stocks: {failed_tickers}")
        if progress_cb:
            progress_cb(3, "retrying", f"重试{len(failed_tickers)}只获取失败的个股...")
        _time.sleep(3)  # Longer pause before retry

        retry_batches = [failed_tickers[i:i+8] for i in range(0, len(failed_tickers), 8)]
        still_failed = []
        for rb_idx, rb in enumerate(retry_batches):
            if rb_idx > 0:
                _time.sleep(2)
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_gather_stock_data, t): t for t in rb}
                for future in futures:
                    ticker = futures[future]
                    try:
                        result = future.result(timeout=60)
                        if result and result.get("skipped"):
                            skipped_stocks.append(result)
                        elif result:
                            stock_results[ticker] = result
                            logger.info(f"Retry succeeded for {ticker}")
                        else:
                            still_failed.append(ticker)
                    except Exception as e:
                        still_failed.append(ticker)
                        logger.error(f"Stock {ticker} retry also failed: {e}")

        if still_failed:
            logger.warning(f"Tier 3: {len(still_failed)} stocks permanently failed: {still_failed}")

    if skipped_stocks:
        logger.info(f"Tier 3: {len(skipped_stocks)} stocks skipped due to illiquid options: {[s['ticker'] for s in skipped_stocks]}")

    if not stock_results:
        return {"ai": {"error": "无法获取任何个股数据"}, "stocks": [], "skipped": skipped_stocks}

    # Run FinBERT sentiment SEQUENTIALLY after all data is gathered
    # FinBERT is CPU-bound (~7s per stock) — running it inside parallel threads causes timeouts
    stocks_with_news = [(tk, d) for tk, d in stock_results.items() if d.get("news")]
    if stocks_with_news:
        if progress_cb:
            progress_cb(3, "sentiment", f"FinBERT情绪分析{len(stocks_with_news)}只个股新闻...")
        logger.info(f"Tier 3: Running FinBERT on {len(stocks_with_news)} stocks sequentially")
        for tk, d in stocks_with_news:
            try:
                d["sentiment"] = score_news_for_ticker(d["news"])
            except Exception as e:
                logger.error(f"FinBERT failed for {tk}: {e}")

    if progress_cb:
        progress_cb(3, "analyzing", f"AI评估{len(stock_results)}只个股30天安全性...")

    # Build Tier 3 prompt — PURE STOCK SAFETY, NO OPTIONS
    tier1_ai = tier1_result["ai"]
    vix_term = tier1_result.get('vix_term', {})
    # Full regime data for Tier 3
    vix_regime = tier1_result.get('vix_regime', {})
    regime_text = ""
    if vix_regime and "error" not in vix_regime:
        vr_alert = vix_regime.get("alert", {})
        regime_text = f"""
VIX Regime详细分析:
  VIX9D={vix_regime.get('vix9d', 'N/A')} | VIX={vix_regime.get('vix', 'N/A')} | VIX3M={vix_regime.get('vix3m', 'N/A')}
  主要比率: {vix_regime.get('primary_ratio', 'N/A')} → {vix_regime.get('regime', 'N/A')}
  前导指标: {vix_regime.get('leading_ratio', 'N/A')} → {vix_regime.get('leading_regime', 'N/A')}
  5日趋势: {vix_regime.get('sma_direction', 'N/A')} | 日变动: {vix_regime.get('daily_delta', 'N/A')} ({vix_regime.get('delta_magnitude', 'N/A')})
  转换状态: {vix_regime.get('transition', 'N/A')} (确信度: {vix_regime.get('transition_conviction', 'N/A')})
  仓位乘数: {vix_regime.get('size_multiplier', 'N/A')}
  警报: {vr_alert.get('level', 'N/A')} — {vr_alert.get('action', 'N/A')}
  重要：仓位乘数={vix_regime.get('size_multiplier', 1.0)}意味着新仓位不应超过正常规模的{int(vix_regime.get('size_multiplier', 1.0)*100)}%"""
    else:
        regime_text = f"\nVIX: {vix_term.get('vix_spot', 'N/A')} ({vix_term.get('structure', 'N/A')}, 比值{vix_term.get('ratio', 'N/A')})"

    tier1_compact = f"""大盘状态: {tier1_ai.get('market_regime', 'N/A')} (信心: {tier1_ai.get('regime_confidence', 'N/A')}/10) | 风险等级: {tier1_ai.get('risk_level', 'N/A')}
{regime_text}
大盘总结: {tier1_ai.get('summary', 'N/A')}
SPY展望: {tier1_ai.get('spy_outlook', {}).get('analysis', 'N/A') if isinstance(tier1_ai.get('spy_outlook'), dict) else tier1_ai.get('spy_outlook', 'N/A')}
主要风险: {', '.join(tier1_ai.get('key_risks', [])) if isinstance(tier1_ai.get('key_risks'), list) else tier1_ai.get('key_risks', 'N/A')}
有利板块: {', '.join(s.get('sector', s) if isinstance(s, dict) else str(s) for s in tier1_ai.get('favorable_sectors', [])) if isinstance(tier1_ai.get('favorable_sectors'), list) else tier1_ai.get('favorable_sectors', 'N/A')}
回避板块: {', '.join(s.get('sector', s) if isinstance(s, dict) else str(s) for s in tier1_ai.get('avoid_sectors', [])) if isinstance(tier1_ai.get('avoid_sectors'), list) else tier1_ai.get('avoid_sectors', 'N/A')}"""

    tier2_compact = "推荐板块/子行业（基于板块技术面和资金流向）:\n"
    for pick in top_picks[:8]:
        tier2_compact += f"  #{pick.get('rank', '?')} {pick.get('sector', '')}/{pick.get('sub_industry', '')} → {pick.get('ticker', '')}\n"
    tier2_compact += "(注：以上排名仅供参考板块强度，个股安全性需独立评估)\n"

    stocks_text = ""
    for ticker, data in stock_results.items():
        s = data["stock"]
        sup = data.get("support") or {}
        sent = data.get("sentiment")

        stocks_text += f"\n### {ticker} - {s.get('name', '')}\n"
        stocks_text += f"  价格: ${s.get('price', 'N/A')} | 板块: {s.get('sector', '')} / {s.get('industry', '')}\n"
        stocks_text += f"  市值: ${(s.get('market_cap') or 0)/1e9:.1f}B | P/E: {s.get('pe_ttm', 'N/A')} | Beta: {s.get('beta', 'N/A')}\n"
        stocks_text += f"  RSI: {s.get('rsi', 'N/A')} | SMA50: ${s.get('sma50', 'N/A')} | SMA200: ${s.get('sma200', 'N/A')} | 趋势: {s.get('trend', 'N/A')}\n"
        stocks_text += f"  1M表现: {s.get('perf_1m', 'N/A')}% | 距财报: {s.get('days_to_earnings', '未知')}天\n"
        stocks_text += f"  3月最大回撤: {s.get('max_drawdown_3m', 'N/A')}% | 日均波动: {s.get('daily_vol', 'N/A')}%\n"
        stocks_text += f"  股票日均成交量: {s.get('avg_volume', 0):,} | 期权流动性: {s.get('option_liquidity', 'N/A')} (Put OI: {s.get('put_oi', 'N/A')})\n"

        # EPS growth data
        eps_parts = []
        if s.get('eps_ttm'): eps_parts.append(f"EPS(TTM): ${s['eps_ttm']}")
        if s.get('eps_forward'): eps_parts.append(f"EPS(预期): ${s['eps_forward']}")
        if s.get('eps_growth_fwd'): eps_parts.append(f"EPS增速: {s['eps_growth_fwd']:+.1f}%")
        if s.get('earnings_growth_qoq'): eps_parts.append(f"季度盈利增速: {s['earnings_growth_qoq']:+.1f}%")
        if s.get('revenue_growth_qoq'): eps_parts.append(f"收入增速: {s['revenue_growth_qoq']:+.1f}%")
        if eps_parts:
            stocks_text += f"  {' | '.join(eps_parts)}\n"
        if s.get('earnings_beats_last4') is not None:
            stocks_text += f"  近4季财报: {s['earnings_beats_last4']}/4次超预期 | 平均超预期幅度: {s.get('avg_earnings_surprise', 0):+.1f}%\n"

        if sup:
            stocks_text += f"  支撑位: ${sup.get('support_30d', 'N/A')} | 6月低点: ${sup.get('low_6m', 'N/A')} | 距52周高点: {sup.get('distance_from_high', 'N/A')}%\n"

        if sent and sent.get("aggregate"):
            agg = sent["aggregate"]
            stocks_text += f"  新闻情绪: {agg['sentiment'].upper()} (均分: {agg['avg_score']:+.3f})\n"

        # Institutional holdings
        inst = data.get("institutional")
        if inst:
            stocks_text += f"  机构持股: {inst.get('inst_pct', 'N/A')}% | 前5大机构动向: {inst['net_signal']} ({inst['buying_count']}家增持 vs {inst['selling_count']}家减持)\n"
            for h in inst.get("top5", [])[:3]:
                arrow = "↑" if h["change"] > 0 else "↓" if h["change"] < 0 else "→"
                stocks_text += f"    {arrow} {h['holder']}: 持有{h['pct_held']}% (变动{h['change']:+.1f}%)\n"

        # Insider transactions
        ins = data.get("insider")
        if ins:
            if ins.get("notable"):
                stocks_text += f"  内部人交易: {ins['net_signal']} (近期{ins['recent_sales']}笔卖出 vs {ins['recent_buys']}笔买入)\n"
                for n in ins["notable"][:2]:
                    stocks_text += f"    {n['action']}: {n['who']} ({n['position']}) ${n['value']:,}\n"
            elif ins["recent_sales"] > 0 or ins["recent_buys"] > 0:
                stocks_text += f"  内部人交易: {ins['net_signal']} ({ins['recent_sales']}笔卖出/${ins.get('total_sold_value',0):,} vs {ins['recent_buys']}笔买入/${ins.get('total_bought_value',0):,})\n"

    prompt = f"""你是一位资深股票分析师。这是三层串联分析的第三层（个股安全评估）。

**核心任务：评估每只股票未来30天内暴跌10%以上的概率。**

这一层只做股票基本面分析，不涉及任何期权相关内容。
只回答一个问题：**你有多大把握这只股票30天内不会暴跌10%？**

## 评估维度（按重要性排序）
1. **财报风险** — 距财报越近越危险（<21天=高危，财报可能导致单日暴跌10%+）
2. **技术面** — 趋势方向、RSI超买超卖、价格距支撑位远近、均线排列
3. **新闻面** — FinBERT情绪分数，是否有负面重大事件（诉讼、监管、财务造假等）
4. **资金面** — 机构增减持动向（13F数据，约45天延迟）、内部人买卖（SEC Form 4，2天延迟）
   - 多家机构同时减持 = 危险信号
   - 内部人大量抛售 = 高管可能知道坏消息
   - 机构增持 + 内部人买入 = 强烈看好信号
5. **波动性** — Beta高低、日均波动率、3月最大回撤历史（回撤>15%说明此股容易暴跌）
6. **盈利增长** — EPS增速（正增长=基本面健康，负增长=基本面恶化）、收入增速、近4季超预期次数（连续beat=管理层执行力强，miss=可能暴跌）
7. **基本面** — P/E是否合理（高P/E+高增速=OK，高P/E+低增速=泡沫风险）、市值大小（大市值更稳定）
8. **大盘环境** — 当前市场整体风险水平

## 特别关注：严重超跌股票
RSI < 30的股票如果基本面稳健（大市值、低Beta、机构增持、无重大利空），反而可能是最安全的选择：
- **超跌反弹概率高** — RSI<30的大盘股历史上30天内反弹概率>70%
- **下跌空间有限** — 已经跌了很多，继续暴跌10%的概率反而更低
- **关键判断标准**：超跌是因为板块轮动/市场情绪（安全）还是因为基本面恶化（危险）？
  - 安全的超跌：大盘普跌导致、板块轮动、短期利空已消化、机构在增持
  - 危险的超跌：财务造假、监管打击、行业结构性衰退、内部人大量抛售
对于安全的超跌股票，应该给予较高的safety_score（60-80），因为它们30天内继续暴跌10%的概率很低。

## 第一层大盘结论
{tier1_compact}

## 第二层板块结论
{tier2_compact}

## 候选个股数据
{stocks_text}

## 输出要求
1. 对每只股票给出**safety_score**: 0-100分 = 你有多大把握这只股票30天内不会暴跌10%
   - 90-100: 极度安全（大市值、低Beta、强支撑、远离财报）
   - 70-89: 安全（基本面稳健、技术面健康）
   - 50-69: 一般（有一些风险因素但整体可控）
   - 30-49: 危险（多个风险因素叠加）
   - 0-29: 极度危险（临近财报/重大利空/技术面崩坏）
2. 给出安全支撑位（30天内最可能的底部价格）
3. 按safety_score从高到低排名
4. **绝对禁止提及任何期权相关内容** — 禁止出现以下词汇：IV、implied volatility、隐含波动率、delta、premium、溢价、行权价、CSP、put、call、期权、ATM。如果数据中缺少某些字段，直接忽略不要提及。
5. 只分析：基本面(P/E/市值/EPS)、技术面(RSI/SMA/趋势)、新闻情绪、机构/内部人动向、波动性历史

请严格按以下JSON格式返回（全部中文）：
{{
  "recommendations": [
    {{
      "rank": 1,
      "ticker": "TICKER",
      "safety_score": 0-100,
      "summary": "2-3句中文：为什么这只股票30天内安全/危险",
      "safe_support": number_or_null,
      "max_loss_estimate": "如果暴跌，预计最大跌幅x%到$xx",
      "bull_case": "1句中文：支撑安全的理由",
      "bear_case": "1句中文：可能暴跌的风险",
      "risks": ["风险1", "风险2"]
    }}
  ],
  "portfolio_summary": "中文总结：哪些股最安全，哪些要避开，整体风险评估"
}}"""

    ai_result = _call_claude(prompt, max_tokens=10000)

    return {
        "ai": ai_result,
        "stocks": stock_results,
        "skipped": skipped_stocks,
    }


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATOR: Run all 3 tiers sequentially
# ═══════════════════════════════════════════════════════════════

def run_cascading_analysis_sync(progress_cb: Callable = None, force: bool = False) -> dict:
    """Run the full 3-tier cascading analysis. Blocking call."""
    start = time.time()

    # Check memory cache (skip if force=True — user explicitly wants fresh analysis)
    if not force:
        cached = _get_cached("cascading_analysis")
        if cached:
            return cached

    # Tier 1
    t1_start = time.time()
    tier1 = _run_tier1(progress_cb)
    t1_elapsed = round(time.time() - t1_start, 1)
    if progress_cb:
        progress_cb(1, "complete", f"大盘分析完成 ({t1_elapsed}s)")

    # Tier 2
    t2_start = time.time()
    tier2 = _run_tier2(tier1, progress_cb)
    t2_elapsed = round(time.time() - t2_start, 1)
    if progress_cb:
        progress_cb(2, "complete", f"板块分析完成 ({t2_elapsed}s)")

    # Tier 3
    t3_start = time.time()
    tier3 = _run_tier3(tier1, tier2, progress_cb)
    t3_elapsed = round(time.time() - t3_start, 1)
    if progress_cb:
        progress_cb(3, "complete", f"个股推荐完成 ({t3_elapsed}s)")

    total = round(time.time() - start, 1)

    result = {
        "generated_at": datetime.now().isoformat(),
        "total_seconds": total,
        "tier1": {
            "ai": tier1["ai"],
            "vix_term": tier1.get("vix_term"),
            "vix_regime": tier1.get("vix_regime"),
            "news_sentiment": tier1.get("news_sentiment"),
            "elapsed": t1_elapsed,
        },
        "tier2": {
            "ai": tier2["ai"],
            "sector_data": {
                name: {
                    "etf": d["etf"],
                    "relative_strength_vs_spy": d["relative_strength_vs_spy"],
                    "stock_count": d["stock_count"],
                    "news_sentiment": d.get("news_sentiment"),
                    "filter_stats": d.get("filter_stats"),
                    "sub_industries": d["sub_industries"][:6],
                }
                for name, d in tier2.get("sector_data", {}).items()
            },
            "elapsed": t2_elapsed,
        },
        "tier3": {
            "ai": tier3["ai"],
            "stocks": {
                ticker: {
                    "stock": data["stock"],
                    "sentiment": data.get("sentiment", {}).get("aggregate") if data.get("sentiment") else None,
                    "institutional": data.get("institutional"),
                    "insider": data.get("insider"),
                }
                for ticker, data in tier3.get("stocks", {}).items()
            },
            "elapsed": t3_elapsed,
        },
    }

    _set_cache("cascading_analysis", result)
    _save_to_disk(result)  # Persist to disk so it survives restarts
    return result


async def run_cascading_analysis() -> dict:
    """Async wrapper for the cascading analysis."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: run_cascading_analysis_sync())
