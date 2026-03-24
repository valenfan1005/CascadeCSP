# VexFlow - AI-Powered US Options Trading Analysis Platform

## Project Overview
VexFlow is a full-stack AI-powered platform for US options trading analysis, focused on **Cash-Secured Put (CSP)** strategy. It uses Claude AI for multi-tier market analysis, FinBERT for news sentiment, and integrates with Moomoo OpenD for real-time options data.

**GitHub**: https://github.com/valenfan1005/VexFlow

## Tech Stack
- **Backend**: FastAPI (Python 3.9), port 8000, entry point `server/app.py`
- **Frontend**: React + Vite + TailwindCSS, port 3000
- **AI**: Claude API (`claude-sonnet-4-5-20250929`) via Anthropic SDK
- **Sentiment**: FinBERT (`ProsusAI/finbert`) - runs locally in offline mode (`TRANSFORMERS_OFFLINE=1`)
- **Market Data**: yfinance, TradingView scanner API, FMP SEC holdings
- **Real-time Options**: Moomoo OpenD (localhost:11111)
- **Database**: SQLAlchemy + SQLite (`server/database/optionscout.db`)
- **Node.js**: `/Users/valen.fan/.nvm/versions/node/v22.22.1/bin/node`

## How to Run
```bash
cd /Users/valen.fan/Documents/US Options Trading/optionscout-tracker

# Backend (with auto-reload)
ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY .env | cut -d= -f2) \
  /Users/valen.fan/Library/Python/3.9/bin/uvicorn server.app:app \
  --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &

# Frontend
cd frontend && npm run dev

# GitHub CLI
GH=/tmp/gh/gh_2.64.0_macOS_arm64/bin/gh
```

## Architecture

### 3-Tier Cascading Analysis (core feature)
```
Tier 1: Macro → VIX regime, market breadth, macro indicators
Tier 2: Sector → ALL 11 GICS sectors rated (STRONG_BUY/BUY/NEUTRAL/AVOID)
         Each sector: ETF relative strength, news sentiment, sub-industry ranking
         Top 8 sub-industries per sector sent to Claude
Tier 3: Stock → Individual stock 30-day safety assessment
         Candidates: Tier 2's BUY+ stocks + 6 star stocks
         Data: yfinance (info, history, options, earnings, institutional holders, news)
         FinBERT: runs AFTER all stock data gathered (not in parallel threads)
         Output: safety_score 0-100 for each stock
```

### Key Data Flows
- **Soft Score** (0-120): CSP attractiveness composite (volatility, RSI, trend, sentiment)
- **Hard Filters**: market_cap > 2B, RSI < 80, price > $10, non-downtrend, avg_volume > 500K, option_volume > 500
- **Sub-industry ranking**: sorted by `avg_soft_score` descending
- **VIX Regime**: 5 states based on VIX/VIX3M ratio (DEEP_CONTANGO, CONTANGO, FLAT, BACKWARDATION, DEEP_BACKWARDATION)

### Caching
- **Memory cache**: TTL 14400s (4 hours), in `_CACHE` dict
- **Disk cache**: `server/.cascading_cache.json`
- `run_cascading_analysis_sync(force=True)` bypasses both caches
- SSE endpoint passes `force=force` to the function

### Star Stocks (always in Tier 3)
`NVDA, TSLA, META, HOOD, GOOGL, AMZN`

### SECTOR_ETF_MAP (11 GICS sectors)
Technology=XLK, Financials=XLF, Healthcare=XLV, Consumer Discretionary=XLY,
Communication Services=XLC, Industrials=XLI, Consumer Staples=XLP,
Energy=XLE, Utilities=XLU, Real Estate=XLRE, Materials=XLB

## Key Files

### Backend
| File | Purpose |
|------|---------|
| `server/app.py` | FastAPI entry point, loads .env at startup |
| `server/routes/sync.py` | Main API routes (SSE streaming, stock-safety, portfolio analysis) |
| `server/services/cascading_analysis.py` | Core 3-tier analysis engine, Claude API calls, JSON parsing |
| `server/services/ai_signal.py` | Individual stock AI analysis, news fetching |
| `server/services/finbert_sentiment.py` | FinBERT model loading (offline mode), sentiment scoring |
| `server/services/flow_toxicity.py` | Flow toxicity detection (IVLD + PCCR), Phase 1 |
| `server/services/vix_regime.py` | VIX regime detection, 5-state classification |
| `server/services/stock_filters.py` | Hard filters + soft score computation |
| `server/services/trend_ribbon.py` | EMA crossover band calculation |
| `server/services/moomoo_client.py` | Moomoo OpenD integration |
| `server/services/moomoo_options.py` | Real-time option chain from Moomoo |
| `server/services/market_intel.py` | Market intelligence aggregation |
| `server/models.py` | SQLAlchemy models (Trade, PortfolioSnapshot, etc.) |

### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/pages/MarketIntel.jsx` | 3-Tier analysis display, VIX dashboard, sector cards |
| `frontend/src/pages/Dashboard.jsx` | Portfolio page, open positions, AI deep analysis |
| `frontend/src/pages/TickerAnalysis.jsx` | Individual stock analysis with safety score + debate |
| `frontend/src/pages/TrendRibbon.jsx` | EMA trend ribbon visualization (山海趋势图) |
| `frontend/src/pages/Analytics.jsx` | Performance analytics |
| `frontend/src/api.js` | API client functions |

## AI Analysis Details

### All AI output is in Chinese (中文)
Every Claude prompt includes instruction to respond in Chinese.

### Ticker Analysis - Devil's Advocate Debate System
```
Analyst Agent → safety assessment → Devil's Advocate Agent → challenges/finds risks
→ Arbiter Agent → final verdict with adjusted score
```
- Debate can raise OR lower the score (bidirectional)
- Located in `server/routes/sync.py` `/stock-safety/{ticker}` endpoint

### Portfolio Deep Analysis
- Endpoint: `/portfolio-deep-analysis`
- Loads 3-tier cached results for consistency
- Constraint: sector recommendations must align with 3-Tier conclusions

### Flow Toxicity (Phase 1)
- **IVLD** (Implied Volatility Local Distortion): detects IV spikes at specific strikes
- **PCCR** (Put-Call Concentration Ratio): detects unusual put concentration
- **Composite**: 50% IVLD + 50% PCCR
- Thresholds adjust by VIX regime (tighter in backwardation)
- Located in `server/services/flow_toxicity.py`

## Known Issues & Fixes

### macOS .env Permission
- macOS `com.apple.provenance` attribute blocks uvicorn from reading `.env`
- Fix: `app.py` loads `.env` at startup; all `_get_api_key()` functions have `PermissionError` handling
- Pass `ANTHROPIC_API_KEY` via env var when starting uvicorn

### FinBERT Offline Mode
- huggingface.co unreachable from this machine → 5 retries × exponential backoff = 23s timeout per stock
- Fix: `TRANSFORMERS_OFFLINE=1` + `local_files_only=True` in `finbert_sentiment.py`
- Model must be pre-downloaded to `~/.cache/huggingface/`

### Tier 3 Stock Data Gathering
- ~50 candidates, batched 10 at a time with 1.5s pause between batches
- FinBERT runs sequentially AFTER all yfinance data is collected
- Failed stocks get one retry pass in smaller batches of 8
- Success rate target: 85%+ (was 41% before batching + FinBERT fix)

### JSON Parsing from Claude
- `_parse_claude_json()` in `cascading_analysis.py` handles:
  - Markdown code fence removal
  - Truncated JSON repair (bracket/brace closing)
  - Progressive truncation from end to find valid JSON
- Tier 2 prompt uses `max_tokens=10000` (11 sectors = large response)

### buying_power_used
- Some trades had `buying_power_used=0` in DB
- Portfolio analysis showed 2.2% utilization instead of real 58.9%
- Fixed by correcting DB values to `strike × contracts × 100`
- Should add auto-calculation fallback when field is 0

## Pending Features / TODO
1. **Flow Toxicity in Ticker Analysis UI** - Show IVLD/PCCR composite on ticker page
2. **60-minute intraday + weekly chart** for Trend Ribbon page
3. **Tier 2 performance optimization** - 120s for 11 sectors; could split into quick rating + detailed analysis
4. **README.md** for GitHub (MiroFish-style with screenshots, architecture diagram, install steps)
5. **Docker support** - docker-compose.yml for one-click deployment
6. **LICENSE** file (MIT or Apache 2.0)

## User Context
- Trading capital: $177,000
- Strategy: Cash-Secured Puts (CSP)
- Position sizing: max 10% per position ($17,700 buying_power), 70% total deployment
- Current open positions: NEE, MCD, HOOD, AMZN, AAPL, NVDA, EQT
- All UI and AI analysis in Chinese
