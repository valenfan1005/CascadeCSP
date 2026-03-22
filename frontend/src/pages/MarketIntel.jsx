import React, { useState, useCallback, useEffect } from 'react';
import { getMarketIntel, getMarketIntelQuick, getCSPSignal, runCascadingAnalysis, getCascadingAnalysisCached, getStockOptions, getVixRegime } from '../api.js';
import { Globe, RefreshCw, TrendingUp, TrendingDown, Minus, AlertTriangle, BarChart3, Newspaper, Activity, Zap, ChevronDown, ChevronUp, Brain, Search, Target, Shield } from 'lucide-react';

// ─── Helpers ────────────────────────────────────────────────
const fmt = (n, d = 2) => n != null ? Number(n).toFixed(d) : '—';
const pctColor = (n) => n > 0 ? 'text-emerald-600' : n < 0 ? 'text-red-600' : 'text-gray-500';
const pctSign = (n) => n != null ? `${n >= 0 ? '+' : ''}${Number(n).toFixed(2)}%` : '—';

// Regime colors
const REGIME_STYLES = {
  'BULLISH': { bg: 'bg-emerald-500', text: 'Bullish', emoji: '🟢' },
  'MILDLY_BULLISH': { bg: 'bg-green-600', text: 'Mildly Bullish', emoji: '🟢' },
  'NEUTRAL': { bg: 'bg-gray-500', text: 'Neutral', emoji: '⚪' },
  'MILDLY_BEARISH': { bg: 'bg-orange-500', text: 'Mildly Bearish', emoji: '🟡' },
  'BEARISH': { bg: 'bg-red-500', text: 'Bearish', emoji: '🔴' },
  'HIGH_VOLATILITY': { bg: 'bg-purple-500', text: 'High Volatility', emoji: '🟣' },
};

// Trend badge
function TrendBadge({ trend }) {
  const styles = {
    'bullish': 'bg-emerald-50 text-emerald-700',
    'mildly_bullish': 'bg-green-50 text-green-700',
    'neutral': 'bg-gray-100 text-gray-600',
    'mildly_bearish': 'bg-orange-50 text-orange-700',
    'bearish': 'bg-red-50 text-red-700',
  };
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase ${styles[trend] || styles.neutral}`}>
      {trend?.replace(/_/g, ' ') || 'N/A'}
    </span>
  );
}

// RSI gauge
function RSIGauge({ value }) {
  if (value == null) return <span className="text-gray-400 text-xs">—</span>;
  const v = Number(value);
  const color = v <= 30 ? 'text-emerald-600' : v >= 70 ? 'text-red-600' : v <= 40 ? 'text-green-600' : v >= 60 ? 'text-orange-600' : 'text-gray-600';
  const barColor = v <= 30 ? 'bg-emerald-500' : v >= 70 ? 'bg-red-500' : v <= 40 ? 'bg-green-500' : v >= 60 ? 'bg-orange-500' : 'bg-gray-500';
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 bg-gray-200 rounded-full h-1.5">
        <div className={`${barColor} rounded-full h-1.5 transition-all`} style={{ width: `${v}%` }} />
      </div>
      <span className={`font-mono text-xs font-semibold ${color}`}>{fmt(v, 0)}</span>
    </div>
  );
}

// Performance mini cell
function PerfCell({ label, value }) {
  return (
    <div className="text-center">
      <p className="text-gray-400 text-[9px] uppercase">{label}</p>
      <p className={`font-mono text-[11px] font-semibold ${pctColor(value)}`}>{pctSign(value)}</p>
    </div>
  );
}

// SMA indicator
function SMAIndicator({ label, above }) {
  if (above == null) return null;
  return (
    <span className={`text-[9px] px-1 py-0.5 rounded ${above ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
      {above ? '>' : '<'} {label}
    </span>
  );
}

// ─── Index Card ─────────────────────────────────────────────
function IndexCard({ idx }) {
  if (!idx) return null;
  const isVIX = idx.symbol === 'VIX' || idx.ticker === 'VIX' || idx.symbol === '^VIX';
  const symbol = idx.symbol || idx.ticker || '';
  const displaySymbol = symbol.replace('^', '');
  const price = idx.price || idx.last_price;
  const change = idx.change_pct || idx.daily_change_pct;
  const vixWarning = isVIX && price > 20;

  const cardBorder = isVIX
    ? (vixWarning ? 'border-red-300' : 'border-purple-200')
    : 'border-gray-200';
  const cardBg = isVIX
    ? (vixWarning ? 'bg-gradient-to-br from-red-50 to-purple-50' : 'bg-gradient-to-br from-purple-50 to-white')
    : 'bg-white';

  return (
    <div className={`${cardBg} rounded-xl border ${cardBorder} p-4 flex-1 min-w-[180px] shadow-sm`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-gray-900 font-bold text-sm">{displaySymbol}</span>
          <TrendBadge trend={idx.trend} />
        </div>
        {isVIX && vixWarning && <AlertTriangle size={14} className="text-red-600" />}
      </div>

      <div className="flex items-end gap-2 mb-2">
        <span className="text-gray-900 font-mono text-xl font-bold">
          {isVIX ? fmt(price, 2) : `$${fmt(price, 2)}`}
        </span>
        <span className={`font-mono text-sm font-semibold ${pctColor(change)}`}>
          {pctSign(change)}
        </span>
      </div>

      <RSIGauge value={idx.rsi} />

      <div className="flex gap-2 mt-2">
        <PerfCell label="1W" value={idx.perf_1w} />
        <PerfCell label="1M" value={idx.perf_1m} />
        <PerfCell label="3M" value={idx.perf_3m} />
        <PerfCell label="YTD" value={idx.perf_ytd} />
      </div>

      {idx.pct_from_high != null && (
        <p className="text-gray-400 text-[10px] mt-1.5">
          {fmt(Math.abs(idx.pct_from_high), 1)}% from 52w high
        </p>
      )}

      <div className="flex gap-1 mt-1.5">
        <SMAIndicator label="SMA50" above={idx.above_sma50} />
        <SMAIndicator label="SMA200" above={idx.above_sma200} />
      </div>
    </div>
  );
}

// ─── AI Analysis Section ────────────────────────────────────
function AIAnalysisSection({ ai }) {
  if (!ai) return null;
  const regime = REGIME_STYLES[ai.market_regime] || REGIME_STYLES['NEUTRAL'];

  return (
    <div className="bg-gradient-to-r from-indigo-50 via-purple-50 to-indigo-50 rounded-xl border border-indigo-200 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain size={22} className="text-indigo-500" />
          <h2 className="text-lg font-bold text-gray-900">AI Market Analysis</h2>
        </div>
        <span className={`${regime.bg} text-white text-sm font-bold px-3 py-1 rounded-full`}>
          {regime.emoji} {regime.text}
        </span>
      </div>

      {ai.summary && (
        <p className="text-gray-600 text-sm leading-relaxed">{ai.summary}</p>
      )}

      {/* SPY + QQQ Outlooks */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {['spy_outlook', 'qqq_outlook'].map((key) => {
          const outlook = ai[key];
          if (!outlook) return null;
          const label = key === 'spy_outlook' ? 'SPY' : 'QQQ';
          const dir = outlook.direction || outlook.bias;
          const isUp = dir && (dir.toLowerCase().includes('bull') || dir.toLowerCase().includes('up'));
          const isDown = dir && (dir.toLowerCase().includes('bear') || dir.toLowerCase().includes('down'));
          return (
            <div key={key} className="bg-gray-50 rounded-lg p-4 border border-gray-200">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-gray-900 font-bold">{label}</span>
                {isUp && <TrendingUp size={14} className="text-emerald-600" />}
                {isDown && <TrendingDown size={14} className="text-red-600" />}
                {!isUp && !isDown && <Minus size={14} className="text-gray-500" />}
                {dir && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${isUp ? 'bg-emerald-50 text-emerald-600' : isDown ? 'bg-red-50 text-red-600' : 'bg-gray-100 text-gray-500'}`}>
                    {dir}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs mb-2">
                {outlook.support && (
                  <div>
                    <span className="text-gray-500">Support: </span>
                    <span className="text-emerald-600 font-mono font-semibold">${outlook.support}</span>
                  </div>
                )}
                {outlook.resistance && (
                  <div>
                    <span className="text-gray-500">Resistance: </span>
                    <span className="text-red-600 font-mono font-semibold">${outlook.resistance}</span>
                  </div>
                )}
              </div>
              {outlook.commentary && (
                <p className="text-gray-500 text-xs leading-relaxed">{outlook.commentary}</p>
              )}
            </div>
          );
        })}
      </div>

      {/* CSP Strategy */}
      {ai.csp_strategy && (
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <h3 className="text-gray-900 font-semibold text-sm mb-2 flex items-center gap-2">
            <Activity size={14} className="text-yellow-500" />
            CSP Strategy Recommendation
          </h3>
          <div className="grid grid-cols-3 gap-3 text-xs mb-2">
            {ai.csp_strategy.dte && (
              <div>
                <span className="text-gray-500">Target DTE: </span>
                <span className="text-gray-900 font-mono font-semibold">{ai.csp_strategy.dte}</span>
              </div>
            )}
            {ai.csp_strategy.delta && (
              <div>
                <span className="text-gray-500">Target Delta: </span>
                <span className="text-gray-900 font-mono font-semibold">{ai.csp_strategy.delta}</span>
              </div>
            )}
            {ai.csp_strategy.sizing && (
              <div>
                <span className="text-gray-500">Sizing: </span>
                <span className="text-gray-900 font-mono font-semibold">{ai.csp_strategy.sizing}</span>
              </div>
            )}
          </div>
          {ai.csp_strategy.commentary && (
            <p className="text-gray-500 text-xs">{ai.csp_strategy.commentary}</p>
          )}
        </div>
      )}

      {/* Sector Picks */}
      {ai.sectors && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {ai.sectors.best_for_csp && (
            <div className="bg-emerald-50 rounded-lg p-3 border border-emerald-200">
              <p className="text-emerald-600 text-xs font-semibold mb-1.5">Best for CSP</p>
              <div className="flex flex-wrap gap-1.5">
                {(Array.isArray(ai.sectors.best_for_csp) ? ai.sectors.best_for_csp : [ai.sectors.best_for_csp]).map((s, i) => (
                  <span key={i} className="bg-emerald-50 text-emerald-700 text-[11px] px-2 py-0.5 rounded">{s}</span>
                ))}
              </div>
            </div>
          )}
          {ai.sectors.avoid && (
            <div className="bg-red-50 rounded-lg p-3 border border-red-200">
              <p className="text-red-600 text-xs font-semibold mb-1.5">Avoid</p>
              <div className="flex flex-wrap gap-1.5">
                {(Array.isArray(ai.sectors.avoid) ? ai.sectors.avoid : [ai.sectors.avoid]).map((s, i) => (
                  <span key={i} className="bg-red-50 text-red-700 text-[11px] px-2 py-0.5 rounded">{s}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Risks + Catalysts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {ai.risks?.length > 0 && (
          <div>
            <p className="text-gray-500 text-xs font-semibold mb-1.5">Key Risks</p>
            <div className="flex flex-wrap gap-1.5">
              {ai.risks.map((r, i) => (
                <span key={i} className="bg-red-50 text-red-700 text-[11px] px-2 py-0.5 rounded border border-red-200">{r}</span>
              ))}
            </div>
          </div>
        )}
        {ai.catalysts?.length > 0 && (
          <div>
            <p className="text-gray-500 text-xs font-semibold mb-1.5">Catalysts</p>
            <div className="flex flex-wrap gap-1.5">
              {ai.catalysts.map((c, i) => (
                <span key={i} className="bg-blue-50 text-blue-700 text-[11px] px-2 py-0.5 rounded border border-blue-200">{c}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sector Heatmap Card ────────────────────────────────────
function SectorCard({ sector }) {
  if (!sector) return null;
  const perf1m = sector.perf_1m || 0;
  // Card bg based on 1M performance
  const bgIntensity = Math.min(Math.abs(perf1m) * 4, 60);
  const cardBg = perf1m > 0
    ? `rgba(16, 185, 129, ${bgIntensity / 100})`
    : perf1m < 0
    ? `rgba(239, 68, 68, ${bgIntensity / 100})`
    : 'transparent';

  return (
    <div
      className="bg-white rounded-lg border border-gray-200 p-3 hover:border-gray-300 transition-all shadow-sm"
      style={{ backgroundColor: cardBg }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-gray-900 font-semibold text-sm">{sector.name || sector.sector}</span>
        <span className="text-gray-500 text-[10px] font-mono">{sector.etf || sector.symbol}</span>
      </div>

      <div className="flex items-center gap-2 mb-2">
        <span className={`font-mono text-sm font-bold ${pctColor(sector.change_1d || sector.daily_change)}`}>
          {pctSign(sector.change_1d || sector.daily_change)}
        </span>
        <span className="text-gray-400 text-[10px]">today</span>
      </div>

      <div className="flex gap-3 text-[10px] mb-1.5">
        <div>
          <span className="text-gray-400">1W </span>
          <span className={`font-mono font-semibold ${pctColor(sector.perf_1w)}`}>{pctSign(sector.perf_1w)}</span>
        </div>
        <div>
          <span className="text-gray-400">1M </span>
          <span className={`font-mono font-semibold ${pctColor(sector.perf_1m)}`}>{pctSign(sector.perf_1m)}</span>
        </div>
      </div>

      {/* Performance bars */}
      <div className="space-y-1">
        {[{ label: '1W', val: sector.perf_1w }, { label: '1M', val: sector.perf_1m }].map(({ label, val }) => {
          if (val == null) return null;
          const width = Math.min(Math.abs(val) * 5, 100);
          const barColor = val >= 0 ? 'bg-emerald-500' : 'bg-red-500';
          return (
            <div key={label} className="flex items-center gap-1">
              <span className="text-gray-400 text-[9px] w-4">{label}</span>
              <div className="flex-1 bg-gray-200 rounded-full h-1">
                <div
                  className={`${barColor} rounded-full h-1 transition-all`}
                  style={{ width: `${width}%`, marginLeft: val < 0 ? 'auto' : 0 }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {sector.rsi != null && (
        <div className="mt-1.5">
          <RSIGauge value={sector.rsi} />
        </div>
      )}
    </div>
  );
}

// ─── Polymarket Section ─────────────────────────────────────
function PolymarketSection({ predictions }) {
  const [expanded, setExpanded] = useState(false);
  if (!predictions || predictions.length === 0) return null;

  const visible = expanded ? predictions : predictions.slice(0, 4);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
          <BarChart3 size={20} className="text-blue-600" />
          Prediction Markets
        </h2>
        {predictions.length > 4 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-blue-600 text-xs hover:text-blue-700 flex items-center gap-1 transition"
          >
            {expanded ? 'Show less' : `Show all (${predictions.length})`}
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {visible.map((event, i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="text-gray-900 font-semibold text-sm mb-3">{event.title || event.event}</h3>
            <div className="space-y-2.5">
              {(event.markets || event.questions || []).map((mkt, j) => {
                const yesPct = mkt.yes_pct || mkt.yes_price || mkt.probability || 50;
                const noPct = 100 - yesPct;
                const barColor = yesPct > 60 ? 'bg-emerald-500' : yesPct < 40 ? 'bg-red-500' : 'bg-yellow-500';
                return (
                  <div key={j}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-gray-600 truncate flex-1 mr-2">{mkt.question || mkt.title || mkt.name}</span>
                      <span className={`font-mono font-bold ${yesPct > 60 ? 'text-emerald-600' : yesPct < 40 ? 'text-red-600' : 'text-yellow-600'}`}>
                        {fmt(yesPct, 0)}%
                      </span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className={`${barColor} rounded-full h-2 transition-all`} style={{ width: `${yesPct}%` }} />
                    </div>
                    <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
                      <span>Yes {fmt(yesPct, 0)}%</span>
                      <span>No {fmt(noPct, 0)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── News Section ───────────────────────────────────────────
function NewsSection({ news, sentiment }) {
  if (!news || news.length === 0) return null;

  // Build a map from headline → sentiment data for quick lookup
  const sentimentMap = {};
  if (sentiment?.articles) {
    sentiment.articles.forEach(a => {
      sentimentMap[a.headline] = a;
    });
  }
  const agg = sentiment?.aggregate;

  const getSentimentBadge = (score, label) => {
    if (score > 0.15) return { bg: 'bg-emerald-50 border-emerald-200', text: 'text-emerald-700', icon: '🟢' };
    if (score < -0.15) return { bg: 'bg-red-50 border-red-200', text: 'text-red-700', icon: '🔴' };
    return { bg: 'bg-gray-50 border-gray-200', text: 'text-gray-500', icon: '⚪' };
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
          <Newspaper size={20} className="text-amber-600" />
          Market News
        </h2>
        {agg && (
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400">FinBERT综合情绪</span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
              agg.sentiment === 'bullish' ? 'bg-emerald-50 text-emerald-700' :
              agg.sentiment === 'bearish' ? 'bg-red-50 text-red-700' :
              'bg-gray-100 text-gray-600'
            }`}>
              {agg.sentiment === 'bullish' ? '📈 看多' : agg.sentiment === 'bearish' ? '📉 看空' : '➡️ 中性'}
              {' '}{agg.avg_score >= 0 ? '+' : ''}{agg.avg_score?.toFixed(3)}
            </span>
            <span className="text-[10px] text-gray-400">
              🟢{agg.bullish_count} 🔴{agg.bearish_count} ⚪{agg.neutral_count}
            </span>
          </div>
        )}
      </div>
      <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 shadow-sm">
        {news.map((item, i) => {
          const title = item.title || item.headline;
          const s = sentimentMap[title];
          const score = s?.score ?? null;
          const badge = score !== null ? getSentimentBadge(score, s?.sentiment) : null;

          return (
            <div key={i} className="px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition">
              {/* Sentiment score pill */}
              {badge && (
                <div className={`shrink-0 mt-0.5 flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-mono font-bold ${badge.bg} ${badge.text}`}>
                  <span>{badge.icon}</span>
                  <span>{score >= 0 ? '+' : ''}{score?.toFixed(2)}</span>
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-gray-900 text-sm leading-snug">{title}</p>
                {item.summary && (
                  <p className="text-gray-400 text-xs mt-0.5 line-clamp-2">{item.summary}</p>
                )}
              </div>
              <div className="flex flex-col items-end shrink-0 gap-1">
                {item.publisher && (
                  <span className="bg-gray-100 text-gray-500 text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap">
                    {item.publisher}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Single Stock CSP Recommendation ─────────────────────────
const SIGNAL_STYLES = {
  'STRONG_SELL_CSP': { bg: 'bg-emerald-50 border-emerald-200', text: 'text-emerald-700', label: 'Strong Sell CSP', badge: 'bg-emerald-500 text-white' },
  'SELL_CSP': { bg: 'bg-blue-50 border-blue-200', text: 'text-blue-700', label: 'Sell CSP', badge: 'bg-blue-500 text-white' },
  'CAUTIOUS': { bg: 'bg-yellow-50 border-yellow-200', text: 'text-yellow-700', label: 'Cautious', badge: 'bg-yellow-500 text-white' },
  'AVOID': { bg: 'bg-red-50 border-red-200', text: 'text-red-700', label: 'Avoid', badge: 'bg-red-500 text-white' },
};

function CSPRecommendationSection() {
  const [ticker, setTicker] = useState('');
  const [signal, setSignal] = useState(null);
  const [cspLoading, setCspLoading] = useState(false);
  const [cspError, setCspError] = useState(null);

  const fetchSignal = async () => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setCspLoading(true);
    setCspError(null);
    setSignal(null);
    try {
      const result = await getCSPSignal(t);
      if (result.error) {
        setCspError(result.error);
      } else {
        setSignal(result);
      }
    } catch (err) {
      setCspError(err.message);
    } finally {
      setCspLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') fetchSignal();
  };

  const s = signal;
  const style = s ? (SIGNAL_STYLES[s.signal] || SIGNAL_STYLES['CAUTIOUS']) : null;

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
        <Target size={20} className="text-indigo-500" />
        Single Stock CSP Recommendation
      </h2>

      {/* Search bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            placeholder="Enter ticker (e.g. NVDA, AAPL)"
            className="input-field pl-9 pr-3"
            maxLength={5}
          />
        </div>
        <button
          onClick={fetchSignal}
          disabled={cspLoading || !ticker.trim()}
          className="btn-primary flex items-center gap-2"
        >
          {cspLoading ? <RefreshCw size={14} className="animate-spin" /> : <Zap size={14} />}
          {cspLoading ? 'Analyzing...' : 'Get Signal'}
        </button>
      </div>

      {/* Error */}
      {cspError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-600 text-sm">
          {cspError}
        </div>
      )}

      {/* Loading */}
      {cspLoading && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center">
          <RefreshCw size={28} className="mx-auto mb-3 text-indigo-400 animate-spin" />
          <p className="text-gray-900">Analyzing {ticker.trim().toUpperCase()}...</p>
          <p className="text-gray-400 text-sm mt-1">AI is evaluating fundamentals, technicals & options data</p>
        </div>
      )}

      {/* Result */}
      {s && !cspLoading && (
        <div className={`rounded-xl border p-5 space-y-4 shadow-sm ${style.bg}`}>
          {/* Header: ticker + price + signal */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-xl font-bold text-gray-900">{s.ticker}</span>
              <span className="text-lg font-mono text-gray-700">${fmt(s.price)}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-sm font-bold px-3 py-1 rounded-full ${style.badge}`}>
                {style.label}
              </span>
              <span className="text-sm text-gray-500">
                Confidence: <span className="font-bold text-gray-900">{s.confidence}/10</span>
              </span>
            </div>
          </div>

          {/* Summary */}
          {s.summary && (
            <p className="text-gray-600 text-sm leading-relaxed">{s.summary}</p>
          )}

          {/* Recommendation row */}
          {(s.recommended_strike || s.recommended_dte || s.recommended_premium) && (
            <div className="bg-white/70 rounded-lg p-4 border border-gray-200">
              <p className="text-gray-500 text-xs font-semibold uppercase tracking-wide mb-2">Recommended Trade</p>
              <div className="grid grid-cols-3 gap-4">
                {s.recommended_strike && (
                  <div>
                    <p className="text-gray-400 text-xs">Strike</p>
                    <p className="text-gray-900 font-mono font-bold text-lg">${s.recommended_strike}P</p>
                  </div>
                )}
                {s.recommended_dte && (
                  <div>
                    <p className="text-gray-400 text-xs">DTE</p>
                    <p className="text-gray-900 font-mono font-bold text-lg">{s.recommended_dte} days</p>
                  </div>
                )}
                {s.recommended_premium && (
                  <div>
                    <p className="text-gray-400 text-xs">Est. Premium</p>
                    <p className="text-emerald-600 font-mono font-bold text-lg">${s.recommended_premium}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Key Levels */}
          {s.key_levels && (s.key_levels.support || s.key_levels.resistance) && (
            <div className="flex gap-4">
              {s.key_levels.support && (
                <div className="bg-emerald-50 rounded-lg px-3 py-2 border border-emerald-200">
                  <p className="text-emerald-600 text-xs font-semibold">Support</p>
                  <p className="text-emerald-700 font-mono font-bold">${s.key_levels.support}</p>
                </div>
              )}
              {s.key_levels.resistance && (
                <div className="bg-red-50 rounded-lg px-3 py-2 border border-red-200">
                  <p className="text-red-600 text-xs font-semibold">Resistance</p>
                  <p className="text-red-700 font-mono font-bold">${s.key_levels.resistance}</p>
                </div>
              )}
              {s.key_levels.max_pain_strike && (
                <div className="bg-purple-50 rounded-lg px-3 py-2 border border-purple-200">
                  <p className="text-purple-600 text-xs font-semibold">Max Pain</p>
                  <p className="text-purple-700 font-mono font-bold">${s.key_levels.max_pain_strike}</p>
                </div>
              )}
            </div>
          )}

          {/* Bull / Bear case */}
          {(s.bull_case || s.bear_case) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {s.bull_case && (
                <div className="bg-emerald-50 rounded-lg p-3 border border-emerald-200">
                  <p className="text-emerald-600 text-xs font-semibold mb-1 flex items-center gap-1">
                    <TrendingUp size={12} /> Bull Case
                  </p>
                  <p className="text-emerald-700 text-sm">{s.bull_case}</p>
                </div>
              )}
              {s.bear_case && (
                <div className="bg-red-50 rounded-lg p-3 border border-red-200">
                  <p className="text-red-600 text-xs font-semibold mb-1 flex items-center gap-1">
                    <TrendingDown size={12} /> Bear Case
                  </p>
                  <p className="text-red-700 text-sm">{s.bear_case}</p>
                </div>
              )}
            </div>
          )}

          {/* Risks */}
          {s.risks?.length > 0 && (
            <div>
              <p className="text-gray-500 text-xs font-semibold mb-1.5 flex items-center gap-1">
                <Shield size={12} /> Key Risks
              </p>
              <div className="flex flex-wrap gap-1.5">
                {s.risks.map((r, i) => (
                  <span key={i} className="bg-red-50 text-red-700 text-[11px] px-2 py-0.5 rounded border border-red-200">{r}</span>
                ))}
              </div>
            </div>
          )}

          {/* News */}
          {s.news?.length > 0 && (
            <div>
              <p className="text-gray-500 text-xs font-semibold mb-1.5">Recent News</p>
              <div className="space-y-1">
                {s.news.slice(0, 4).map((n, i) => (
                  <p key={i} className="text-gray-600 text-xs truncate">• {typeof n === 'string' ? n : n.title || n.headline}</p>
                ))}
              </div>
            </div>
          )}

          {/* Timestamp */}
          {s.generated_at && (
            <p className="text-gray-400 text-[10px]">Generated: {new Date(s.generated_at).toLocaleString()}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 3-Tier Progress Stepper ─────────────────────────────────
const TIER_LABELS = { 1: '大盘分析', 2: '板块分析', 3: '个股推荐' };
const TIER_ICONS = { 1: '🌍', 2: '📊', 3: '🎯' };

function CascadingStepper({ currentTier, tierStatus, message }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-bold text-gray-900">🔬 3-Tier Deep Analysis</span>
        {message && <span className="text-xs text-gray-500 animate-pulse">{message}</span>}
      </div>
      <div className="flex items-center gap-2">
        {[1, 2, 3].map((tier) => {
          const status = tierStatus[tier] || 'pending';
          const isActive = currentTier === tier && status !== 'complete';
          const isDone = status === 'complete';
          return (
            <React.Fragment key={tier}>
              {tier > 1 && (
                <div className={`flex-1 h-0.5 ${isDone || currentTier > tier ? 'bg-emerald-400' : isActive ? 'bg-blue-300 animate-pulse' : 'bg-gray-200'}`} />
              )}
              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                isDone ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
                isActive ? 'bg-blue-50 text-blue-700 border border-blue-200 animate-pulse' :
                'bg-gray-50 text-gray-400 border border-gray-200'
              }`}>
                <span>{isDone ? '✅' : isActive ? '⏳' : TIER_ICONS[tier]}</span>
                <span>Tier {tier}: {TIER_LABELS[tier]}</span>
                {tierStatus[`${tier}_time`] && <span className="text-[10px] opacity-60">({tierStatus[`${tier}_time`]}s)</span>}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ─── Cascading Tier 2 Sector Results ─────────────────────────
function Tier2SectorResults({ tier2 }) {
  const ai = tier2?.ai;
  if (!ai || ai.error) return null;
  const sectors = ai.sector_analysis || [];
  const sectorData = tier2?.sector_data || {};

  // Aggregate filter stats across all sectors
  const totalScanned = Object.values(sectorData).reduce((sum, d) => sum + (d?.filter_stats?.total_scanned || 0), 0);
  const totalRejected = Object.values(sectorData).reduce((sum, d) => sum + (d?.filter_stats?.hard_rejected || 0), 0);
  const totalCandidates = Object.values(sectorData).reduce((sum, d) => sum + (d?.filter_stats?.sent_to_claude || 0), 0);

  // Sort: STRONG_BUY first, then BUY, NEUTRAL, AVOID
  const ratingOrder = { 'STRONG_BUY': 0, 'BUY': 1, 'NEUTRAL': 2, 'AVOID': 3 };
  const sorted = [...sectors].sort((a, b) => (ratingOrder[a.rating] ?? 9) - (ratingOrder[b.rating] ?? 9));
  // Always show top 5, collapse the rest
  const TOP_N = 5;
  const recommended = sorted.slice(0, TOP_N);
  const others = sorted.slice(TOP_N);

  const [showOthers, setShowOthers] = React.useState(false);

  const SectorCard = ({ sector, compact = false }) => (
    <div className={`bg-white rounded-xl border ${
      sector.rating === 'STRONG_BUY' ? 'border-emerald-200' :
      sector.rating === 'BUY' ? 'border-blue-200' :
      sector.rating === 'AVOID' ? 'border-red-200' :
      'border-gray-200'
    } p-4 shadow-sm`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-bold text-gray-900">{sector.sector}</span>
          <span className="text-gray-400 text-xs">{sector.etf}</span>
        </div>
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
          sector.rating === 'STRONG_BUY' ? 'bg-emerald-50 text-emerald-700' :
          sector.rating === 'BUY' ? 'bg-blue-50 text-blue-700' :
          sector.rating === 'AVOID' ? 'bg-red-50 text-red-700' :
          'bg-gray-100 text-gray-600'
        }`}>{sector.rating}</span>
      </div>
      {sector.summary && <p className="text-gray-600 text-sm mb-3">{sector.summary}</p>}
      {!compact && sector.news_impact && <p className="text-gray-500 text-xs mb-2 italic">📰 {sector.news_impact}</p>}

      {/* Sub-industries — show full for recommended, abbreviated for others */}
      {sector.sub_industries?.length > 0 && (
        <div className="border-t border-gray-100 pt-2 mt-2">
          <p className="text-gray-400 text-[10px] font-semibold mb-1.5">子行业排名</p>
          <div className="space-y-1.5">
            {(compact ? sector.sub_industries.slice(0, 3) : sector.sub_industries).map((sub, j) => (
              <div key={j} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold ${
                    sub.rating === 'STRONG_BUY' ? 'bg-emerald-100 text-emerald-700' :
                    sub.rating === 'BUY' ? 'bg-blue-100 text-blue-700' :
                    sub.rating === 'AVOID' ? 'bg-red-100 text-red-700' :
                    'bg-gray-100 text-gray-500'
                  }`}>{sub.csp_attractiveness || '?'}</span>
                  <span className="text-gray-900 font-medium">{sub.name}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  {sub.recommended_stocks?.map((t, k) => (
                    <span key={k} className="bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded text-[10px] font-mono">{t}</span>
                  ))}
                </div>
              </div>
            ))}
            {compact && sector.sub_industries.length > 3 && (
              <p className="text-[10px] text-gray-400">+{sector.sub_industries.length - 3} 更多子行业</p>
            )}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">📊 Tier 2: 全板块分析</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">
            {sectors.length} 个板块 | {recommended.length} 个推荐
          </span>
          {totalScanned > 0 && (
            <span className="text-xs text-gray-400">
              扫描 {totalScanned} 只 → 过滤 {totalRejected} 只 → {totalCandidates} 只候选
            </span>
          )}
        </div>
      </div>

      {/* Top 5 sectors — full display */}
      {recommended.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-gray-600">🏆 Top {recommended.length} 板块</p>
          <div className="grid grid-cols-1 gap-3">
            {recommended.map((sector, i) => <SectorCard key={i} sector={sector} />)}
          </div>
        </div>
      )}

      {/* Other sectors — collapsed by default */}
      {others.length > 0 && (
        <div className="space-y-2">
          <button
            onClick={() => setShowOthers(!showOthers)}
            className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
          >
            {showOthers ? '▼' : '▶'} 其他板块 ({others.length})：
            {others.map(s => (
              <span key={s.sector} className={`ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                s.rating === 'NEUTRAL' ? 'bg-gray-100 text-gray-500' :
                s.rating === 'AVOID' ? 'bg-red-50 text-red-600' : 'bg-gray-100 text-gray-500'
              }`}>{s.sector} {s.rating}</span>
            ))}
          </button>
          {showOthers && (
            <div className="grid grid-cols-1 gap-2">
              {others.map((sector, i) => <SectorCard key={i} sector={sector} compact />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Cascading Tier 3 Stock Results ──────────────────────────
function getSafetyColor(score) {
  if (score >= 90) return { bg: 'bg-emerald-50 border-emerald-300', ring: 'text-emerald-500', text: 'text-emerald-700' };
  if (score >= 70) return { bg: 'bg-blue-50 border-blue-200', ring: 'text-blue-500', text: 'text-blue-700' };
  if (score >= 50) return { bg: 'bg-yellow-50 border-yellow-200', ring: 'text-yellow-500', text: 'text-yellow-700' };
  if (score >= 30) return { bg: 'bg-orange-50 border-orange-200', ring: 'text-orange-500', text: 'text-orange-700' };
  return { bg: 'bg-red-50 border-red-200', ring: 'text-red-500', text: 'text-red-700' };
}

// Legacy signal colors fallback
const SIGNAL_COLORS_T3 = {
  'STRONG_SELL_CSP': { bg: 'bg-emerald-50 border-emerald-200', text: 'text-emerald-700', badge: 'bg-emerald-500 text-white' },
  'SELL_CSP': { bg: 'bg-blue-50 border-blue-200', text: 'text-blue-700', badge: 'bg-blue-500 text-white' },
  'CAUTIOUS': { bg: 'bg-yellow-50 border-yellow-200', text: 'text-yellow-700', badge: 'bg-yellow-500 text-white' },
  'AVOID': { bg: 'bg-red-50 border-red-200', text: 'text-red-700', badge: 'bg-red-500 text-white' },
};

function Tier3StockResults({ tier3 }) {
  const ai = tier3?.ai;
  if (!ai || ai.error) return null;
  const allRecs = (ai.recommendations || []).map(r => {
    // Normalize: convert old signal format to safety_score if missing
    if (r.safety_score === undefined && r.signal) {
      const scoreMap = { 'STRONG_SELL_CSP': 85, 'SELL_CSP': 75, 'CAUTIOUS': 55, 'AVOID': 25, 'DANGEROUS': 10 };
      r.safety_score = scoreMap[r.signal] ?? (r.confidence || 5) * 10;
    }
    return r;
  });
  // Sort by safety_score descending, show all — user can see which are safe vs risky
  const sortedRecs = [...allRecs].sort((a, b) => (b.safety_score ?? 0) - (a.safety_score ?? 0));
  // Split: safe (>=40) shown first, risky (<40) collapsed
  const recs = sortedRecs.filter(r => (r.safety_score ?? 0) >= 40);
  const dangerousRecs = sortedRecs.filter(r => (r.safety_score ?? 0) < 40);
  const stocks = tier3?.stocks || {};
  const [optionsData, setOptionsData] = React.useState({});
  const [loadingOptions, setLoadingOptions] = React.useState({});

  const handleGetOptions = async (ticker) => {
    setLoadingOptions(prev => ({ ...prev, [ticker]: true }));
    try {
      const data = await getStockOptions(ticker);
      setOptionsData(prev => ({ ...prev, [ticker]: data }));
    } catch (e) {
      setOptionsData(prev => ({ ...prev, [ticker]: { error: e.message } }));
    }
    setLoadingOptions(prev => ({ ...prev, [ticker]: false }));
  };

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">🛡️ Tier 3: 个股30天安全评估</h2>

      {ai.portfolio_summary && (
        <div className="bg-blue-50 rounded-lg border border-blue-200 p-3 text-blue-700 text-sm">
          💼 {ai.portfolio_summary}
        </div>
      )}

      {recs.length === 0 && (
        <div className="bg-yellow-50 rounded-lg border border-yellow-200 p-3 text-yellow-700 text-sm">
          当前市场环境下没有找到安全的CSP标的，建议等待更好的入场时机。
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {recs.map((rec, i) => {
          const score = rec.safety_score ?? rec.confidence * 10 ?? 50;
          const sc = getSafetyColor(score);
          const legacySc = SIGNAL_COLORS_T3[rec.signal];
          const cardBg = rec.safety_score !== undefined ? sc.bg : (legacySc?.bg || 'bg-gray-50 border-gray-200');
          const stockData = stocks[rec.ticker] || {};
          const opts = optionsData[rec.ticker];
          const isLoadingOpts = loadingOptions[rec.ticker];

          return (
            <div key={i} className={`rounded-xl border p-4 shadow-sm ${cardBg}`}>
              {/* Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="text-gray-400 text-sm font-medium">#{rec.rank}</span>
                  {/* Safety Score Circle */}
                  <div className={`w-11 h-11 rounded-full border-[3px] flex items-center justify-center font-bold text-sm ${
                    score >= 70 ? 'border-emerald-400 text-emerald-600' :
                    score >= 50 ? 'border-blue-400 text-blue-600' :
                    score >= 30 ? 'border-yellow-400 text-yellow-600' :
                    'border-red-400 text-red-600'
                  }`}>
                    {score}
                  </div>
                  <div>
                    <span className="text-xl font-bold text-gray-900">{rec.ticker}</span>
                    <p className="text-[10px] text-gray-400">{stockData?.stock?.name || ''}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-semibold ${sc.text}`}>
                    {score >= 90 ? '极度安全' : score >= 70 ? '安全' : score >= 50 ? '一般' : score >= 30 ? '危险' : '极危险'}
                  </p>
                  <p className="text-[10px] text-gray-400">30天不跌10%置信度</p>
                </div>
              </div>

              {/* Summary */}
              <p className="text-gray-700 text-sm mb-3">{rec.summary}</p>

              {/* Support & Max Loss */}
              <div className="grid grid-cols-2 gap-2 text-xs mb-2">
                {rec.safe_support && (
                  <div className="bg-white/70 rounded p-2">
                    <span className="text-gray-400">安全支撑位</span>
                    <p className="font-bold text-emerald-600">${rec.safe_support}</p>
                  </div>
                )}
                {rec.max_loss_estimate && (
                  <div className="bg-white/70 rounded p-2">
                    <span className="text-gray-400">最大跌幅预估</span>
                    <p className="font-bold text-red-600 text-[11px]">{rec.max_loss_estimate}</p>
                  </div>
                )}
              </div>

              {/* Bull/Bear */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                {rec.bull_case && (
                  <div className="bg-emerald-50/50 rounded p-2">
                    <span className="text-emerald-500 font-semibold">🟢 安全理由</span>
                    <p className="text-emerald-700 mt-0.5">{rec.bull_case}</p>
                  </div>
                )}
                {rec.bear_case && (
                  <div className="bg-red-50/50 rounded p-2">
                    <span className="text-red-500 font-semibold">🔴 暴跌风险</span>
                    <p className="text-red-700 mt-0.5">{rec.bear_case}</p>
                  </div>
                )}
              </div>

              {/* Risks */}
              {rec.risks?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {rec.risks.map((r, j) => (
                    <span key={j} className="text-[10px] bg-red-50 text-red-600 px-1.5 py-0.5 rounded border border-red-200">{r}</span>
                  ))}
                </div>
              )}

              {/* Option Analysis Button */}
              <div className="mt-3 border-t border-gray-200/50 pt-2">
                {!opts && (
                  <button
                    onClick={() => handleGetOptions(rec.ticker)}
                    disabled={isLoadingOpts}
                    className="text-xs bg-indigo-50 text-indigo-600 px-3 py-1.5 rounded-lg border border-indigo-200 hover:bg-indigo-100 transition-colors disabled:opacity-50"
                  >
                    {isLoadingOpts ? '获取期权数据...' : '📊 查看期权数据 (Moomoo)'}
                  </button>
                )}
                {opts && !opts.error && (
                  <div className="bg-white/80 rounded-lg border border-indigo-200/50 p-3 mt-1 space-y-2">
                    {/* Header: source + expiry */}
                    <div className="flex items-center justify-between">
                      <p className="text-[10px] text-indigo-500 font-semibold">
                        📊 期权分析 (Moomoo实时) — {opts.expiry} DTE={opts.dte}
                      </p>
                      {opts.atm_iv > 0 && <span className="text-[10px] text-gray-400">ATM IV: {(opts.atm_iv * 100).toFixed(1)}%</span>}
                    </div>

                    {/* AI Analysis — main content */}
                    {opts.ai_analysis && !opts.ai_analysis.error && (() => {
                      const ai = opts.ai_analysis;
                      const recColor = {
                        'STRONG_SELL': 'bg-emerald-500', 'SELL': 'bg-blue-500', 'HOLD': 'bg-yellow-500', 'AVOID': 'bg-red-500'
                      }[ai.recommendation] || 'bg-gray-500';
                      return (
                        <div className="space-y-2">
                          {/* Recommendation badge + summary */}
                          <div className="flex items-start gap-2">
                            <span className={`${recColor} text-white text-[10px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap`}>
                              {ai.recommendation}
                            </span>
                            <p className="text-xs text-gray-700">{ai.summary}</p>
                          </div>

                          {/* Best strike recommendation */}
                          {ai.best_strike && (
                            <div className="bg-indigo-50 rounded-lg p-2 border border-indigo-100">
                              <div className="grid grid-cols-3 gap-2 text-xs">
                                <div>
                                  <span className="text-gray-400 text-[10px]">推荐行权价</span>
                                  <p className="font-bold text-indigo-700">${ai.best_strike}</p>
                                </div>
                                <div>
                                  <span className="text-gray-400 text-[10px]">预期收入/手</span>
                                  <p className="font-bold text-emerald-600">${ai.expected_income || (ai.best_premium * 100)?.toFixed(0)}</p>
                                </div>
                                <div>
                                  <span className="text-gray-400 text-[10px]">IV评估</span>
                                  <p className="font-bold text-gray-700 text-[10px]">{ai.iv_assessment}</p>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Risk/reward + action plan */}
                          <div className="text-xs space-y-1">
                            {ai.risk_reward && <p className="text-gray-600">⚖️ {ai.risk_reward}</p>}
                            {ai.action_plan && <p className="text-gray-700">📋 {ai.action_plan}</p>}
                            {ai.exit_strategy && <p className="text-gray-500">🎯 {ai.exit_strategy}</p>}
                            {ai.max_risk && <p className="text-red-500 text-[10px]">⚠️ {ai.max_risk}</p>}
                          </div>

                          {/* Raw candidates (collapsible) */}
                          {(opts.candidates || []).length > 0 && (
                            <details className="mt-1">
                              <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">查看全部期权链数据 ({opts.candidates.length}个候选)</summary>
                              <div className="mt-1 space-y-1">
                                {opts.candidates.map((c, ci) => (
                                  <div key={ci} className="grid grid-cols-6 gap-1 text-[10px]">
                                    <span className="font-bold">${c.strike}</span>
                                    <span>Bid ${c.bid?.toFixed(2)}</span>
                                    <span>Ask ${c.ask?.toFixed(2)}</span>
                                    <span>Δ {c.delta?.toFixed(3)}</span>
                                    <span>IV {(c.iv * 100)?.toFixed(0)}%</span>
                                    <span className="text-emerald-600 font-bold">{(c.annualized_return * 100)?.toFixed(1)}%年化</span>
                                  </div>
                                ))}
                              </div>
                            </details>
                          )}
                        </div>
                      );
                    })()}

                    {/* AI analysis error fallback — show raw data */}
                    {opts.ai_analysis?.error && opts.best_csp && (
                      <div className="space-y-1">
                        <p className="text-[10px] text-yellow-500">AI分析失败，显示原始数据:</p>
                        {(opts.candidates || [opts.best_csp]).map((c, ci) => (
                          <div key={ci} className="grid grid-cols-6 gap-1 text-[10px]">
                            <span className="font-bold">${c.strike}</span>
                            <span>Bid ${c.bid}</span>
                            <span>Ask ${c.ask}</span>
                            <span>Δ {c.delta}</span>
                            <span>IV {(c.iv * 100).toFixed(0)}%</span>
                            <span className="text-emerald-600 font-bold">{(c.annualized_return * 100).toFixed(1)}%年化</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* No AI, no best_csp — minimal display */}
                    {!opts.ai_analysis && !opts.best_csp && (
                      <p className="text-xs text-gray-400">无可用的CSP候选期权</p>
                    )}
                  </div>
                )}
                {opts && opts.error && (
                  <p className="text-xs text-red-500 mt-1">期权数据获取失败: {opts.error}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Skipped stocks (illiquid options) */}
      {(tier3?.skipped || []).length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
            ⚠️ 期权流动性不足已排除 ({tier3.skipped.length}只) — 点击展开
          </summary>
          <div className="mt-1 flex flex-wrap gap-1">
            {tier3.skipped.map((s, i) => (
              <span key={i} className="text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                {s.ticker} ({s.reason})
              </span>
            ))}
          </div>
        </details>
      )}

      {/* Collapsed DANGEROUS section */}
      {dangerousRecs.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
            🚫 高危标的 ({dangerousRecs.length}只) — 点击展开
          </summary>
          <div className="mt-2 space-y-2">
            {dangerousRecs.map((rec, i) => (
              <div key={i} className="bg-red-50/50 rounded-lg border border-red-100 p-3 text-sm">
                <span className="font-bold text-gray-900">{rec.ticker}</span>
                <span className="text-[10px] bg-red-500 text-white px-1.5 py-0.5 rounded-full ml-2">DANGEROUS</span>
                <span className="text-gray-400 text-xs ml-2">暴跌概率: {rec.crash_probability}</span>
                <p className="text-gray-500 text-xs mt-1">{rec.summary}</p>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}


// ─── Main Component ─────────────────────────────────────────
export default function MarketIntel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadType, setLoadType] = useState(null);
  const [error, setError] = useState(null);

  // 3-tier cascading analysis state
  const [cascading, setCascading] = useState(null); // full result
  const [cascadingLoading, setCascadingLoading] = useState(false);
  const [cascadingTier, setCascadingTier] = useState(0);
  const [cascadingStatus, setCascadingStatus] = useState({});
  const [cascadingMessage, setCascadingMessage] = useState('');
  const [cascadingError, setCascadingError] = useState(null);

  const startCascadingAnalysis = useCallback(() => {
    setCascadingLoading(true);
    setCascadingTier(1);
    setCascadingStatus({});
    setCascadingMessage('启动三层分析...');
    setCascadingError(null);
    setCascading(null);

    const evtSource = runCascadingAnalysis({
      onProgress: (tier, step, message) => {
        setCascadingTier(tier);
        setCascadingMessage(message);
        if (step === 'complete') {
          setCascadingStatus(prev => ({ ...prev, [tier]: 'complete' }));
        } else {
          setCascadingStatus(prev => ({ ...prev, [tier]: 'active' }));
        }
      },
      onComplete: (result) => {
        setCascading(result);
        setCascadingLoading(false);
        setCascadingTier(3);
        setCascadingStatus({ 1: 'complete', 2: 'complete', 3: 'complete',
          '1_time': result?.tier1?.elapsed, '2_time': result?.tier2?.elapsed, '3_time': result?.tier3?.elapsed });
        setCascadingMessage(`分析完成 (${result?.total_seconds || '?'}s)`);
      },
      onError: (err) => {
        setCascadingError(err);
        setCascadingLoading(false);
      },
    });

    // Cleanup on unmount
    return () => evtSource.close();
  }, []);

  const load = useCallback(async (type) => {
    setLoading(true);
    setLoadType(type);
    setError(null);
    try {
      const result = type === 'quick' ? await getMarketIntelQuick() : await getMarketIntel();
      setData(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // VIX regime state
  const [vixRegime, setVixRegime] = useState(null);

  // Auto-load quick data + VIX regime + cached cascading results on mount
  useEffect(() => {
    load('quick');
    // Load VIX regime
    getVixRegime().then(setVixRegime).catch(() => {});
    // Load cached 3-tier results if available
    getCascadingAnalysisCached()
      .then(result => {
        if (result && result.total_seconds) {
          setCascading(result);
          setCascadingStatus({
            1: 'complete', 2: 'complete', 3: 'complete',
            '1_time': result?.tier1?.elapsed,
            '2_time': result?.tier2?.elapsed,
            '3_time': result?.tier3?.elapsed,
          });
          setCascadingTier(3);
          setCascadingMessage(`上次分析: ${new Date(result.generated_at).toLocaleString()}`);
        }
      })
      .catch(() => {});
  }, [load]);

  // indices can be an object keyed by symbol or an array
  const rawIndices = data?.indices || data?.index_data || {};
  const indices = Array.isArray(rawIndices)
    ? rawIndices
    : Object.entries(rawIndices).map(([sym, val]) => ({ ...val, symbol: sym }));
  const ai = data?.ai_analysis || null;
  const sectors = data?.sectors || data?.sector_heatmap || [];
  const predictions = data?.predictions || data?.polymarket || [];
  const news = data?.news || data?.market_news || [];
  const timestamp = data?.timestamp || data?.generated_at;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="bg-gradient-to-r from-purple-900 via-indigo-900 to-purple-900 rounded-2xl p-6 border border-purple-700/30">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Globe size={28} className="text-purple-400" />
              Market Intelligence
            </h1>
            <p className="text-purple-300 text-sm mt-1">
              Comprehensive market overview with index tracking, sector heatmaps, predictions & AI analysis
            </p>
          </div>

          <button
            onClick={startCascadingAnalysis}
            disabled={cascadingLoading}
            className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-sm px-5 py-2.5 rounded-lg transition disabled:opacity-50 flex items-center gap-2 shadow-lg shadow-blue-500/20"
          >
            {cascadingLoading ? <RefreshCw size={14} className="animate-spin" /> : <span>🔬</span>}
            {cascadingLoading ? '分析中...' : 'Run 3-Tier Analysis'}
          </button>
        </div>

        {timestamp && (
          <p className="text-purple-400/60 text-xs mt-2">
            Last updated: {new Date(timestamp).toLocaleString()}
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="text-center py-20">
          <RefreshCw size={32} className="mx-auto mb-4 text-purple-400 animate-spin" />
          <p className="text-gray-900 text-lg">
            {loadType === 'full' ? 'Running full market analysis with AI...' : 'Loading market data...'}
          </p>
          <p className="text-gray-400 text-sm mt-1">
            {loadType === 'full' ? 'This may take 30-60 seconds for AI analysis' : 'Fetching latest market data...'}
          </p>
        </div>
      )}

      {/* Loading overlay when refreshing with existing data */}
      {loading && data && (
        <div className="bg-purple-50 border border-purple-200 rounded-lg px-4 py-2 flex items-center gap-2 text-purple-600 text-sm">
          <RefreshCw size={14} className="animate-spin" />
          {loadType === 'full' ? 'Running AI analysis...' : 'Refreshing data...'}
        </div>
      )}

      {/* All raw data (indices, sectors, news, polymarket) is fetched by Quick Load
           and fed into the 3-Tier AI analysis. No standalone display needed. */}

      {/* ═══ VIX Regime Analysis ═══ */}
      {vixRegime && !vixRegime.error && (() => {
        const vr = vixRegime;
        const alert = vr.alert || {};
        const alertConfig = {
          'SAFE': { bg: 'from-emerald-50 to-green-50', border: 'border-emerald-200', badge: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500' },
          'INFO': { bg: 'from-emerald-50 to-green-50', border: 'border-emerald-200', badge: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500' },
          'WARNING': { bg: 'from-yellow-50 to-amber-50', border: 'border-yellow-200', badge: 'bg-yellow-100 text-yellow-700', dot: 'bg-yellow-500' },
          'DANGER': { bg: 'from-red-50 to-orange-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
          'CRISIS': { bg: 'from-red-50 to-red-100', border: 'border-red-300', badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
          'GOLDEN': { bg: 'from-purple-50 to-indigo-50', border: 'border-purple-200', badge: 'bg-purple-100 text-purple-700', dot: 'bg-purple-500' },
          'POSSIBLE_GOLDEN': { bg: 'from-purple-50 to-indigo-50', border: 'border-purple-200', badge: 'bg-purple-100 text-purple-700', dot: 'bg-purple-500' },
        };
        const cfg = alertConfig[alert.level] || alertConfig['SAFE'];
        const regimeLabels = { 'DEEP_CONTANGO': '深度Contango', 'CONTANGO': 'Contango', 'FLAT': '平坦 (过渡)', 'BACKWARDATION': 'Backwardation', 'DEEP_BACKWARDATION': '深度Backwardation' };
        const dirArrow = vr.sma_direction === 'RISING' ? '↑' : vr.sma_direction === 'FALLING' ? '↓' : '→';
        const dirLabel = vr.sma_direction === 'RISING' ? '恶化中' : vr.sma_direction === 'FALLING' ? '好转中' : '横盘';
        const sparkData = vr.sparkline || [];

        // SVG sparkline (two lines: primary_ratio + leading_ratio)
        const svgW = 400, svgH = 60;
        const vals = sparkData.map(d => d.primary_ratio);
        const leadVals = sparkData.map(d => d.leading_ratio).filter(v => v != null);
        const allVals = [...vals, ...leadVals];
        const sMin = Math.min(...allVals, 0.82), sMax = Math.max(...allVals, 1.18);
        const sRange = sMax - sMin || 0.1;
        const pts = vals.map((v, i) => `${(i/(vals.length-1))*svgW},${svgH - ((v-sMin)/sRange)*svgH}`).join(' ');
        const leadPts = leadVals.length > 0
          ? leadVals.map((v, i) => `${(i/(leadVals.length-1))*svgW},${svgH - ((v-sMin)/sRange)*svgH}`).join(' ')
          : '';
        const y095 = svgH - ((0.95-sMin)/sRange)*svgH;
        const y105 = svgH - ((1.05-sMin)/sRange)*svgH;

        return (
          <div className={`bg-gradient-to-r ${cfg.bg} rounded-xl border ${cfg.border} p-5 shadow-sm`}>
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Activity size={18} className="text-gray-700" />
                <span className="text-base font-bold text-gray-900">VIX 期限结构分析</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${cfg.badge}`}>
                  <span className={`inline-block w-2 h-2 rounded-full ${cfg.dot} mr-1.5 ${alert.level === 'CRISIS' ? 'animate-pulse' : ''}`} />
                  {alert.level}
                </span>
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${cfg.badge}`}>
                  {regimeLabels[vr.regime] || vr.regime}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-12 gap-4">
              {/* Left: VIX values + metrics */}
              <div className="col-span-5 space-y-3">
                {/* VIX 9D / 30D / 3M */}
                <div className="grid grid-cols-3 gap-2">
                  {[{label: 'VIX 9D', val: vr.vix9d}, {label: 'VIX 30D', val: vr.vix}, {label: 'VIX 3M', val: vr.vix3m}].map(({label, val}) => (
                    <div key={label} className="bg-white/60 rounded-lg p-2 text-center">
                      <div className="text-[10px] text-gray-500">{label}</div>
                      <div className="text-lg font-bold text-gray-900 font-mono">{val}</div>
                    </div>
                  ))}
                </div>

                {/* Key metrics */}
                <div className="space-y-1.5 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-500">主要比率 (VIX/VIX3M)</span>
                    <span className="font-mono font-bold text-gray-900">{vr.primary_ratio?.toFixed(4)} {dirArrow}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">前导指标 (VIX9D/VIX)</span>
                    <span className={`font-mono font-bold ${vr.leading_regime === 'SPIKING' ? 'text-red-600' : vr.leading_regime === 'ELEVATED' ? 'text-yellow-600' : 'text-gray-900'}`}>
                      {vr.leading_ratio?.toFixed(4)} ({vr.leading_regime})
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">5日趋势</span>
                    <span className={`font-bold ${vr.sma_direction === 'FALLING' ? 'text-emerald-600' : vr.sma_direction === 'RISING' ? 'text-red-600' : 'text-gray-600'}`}>
                      {dirArrow} {dirLabel}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">日变动</span>
                    <span className={`font-mono ${Math.abs(vr.daily_delta) >= 0.03 ? 'text-red-600 font-bold' : 'text-gray-700'}`}>
                      {vr.daily_delta > 0 ? '+' : ''}{vr.daily_delta?.toFixed(4)} ({vr.delta_magnitude})
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">VIX历史分位</span>
                    <span className="font-mono text-gray-900">{vr.vix_percentile}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">比率历史分位</span>
                    <span className="font-mono text-gray-900">{vr.ratio_percentile}%</span>
                  </div>
                </div>

                {/* Position size */}
                <div className="bg-white/60 rounded-lg p-3">
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium text-gray-700">建议仓位</span>
                    <span className={`text-2xl font-bold ${vr.size_multiplier >= 0.7 ? 'text-emerald-600' : vr.size_multiplier >= 0.4 ? 'text-yellow-600' : 'text-red-600'}`}>
                      {Math.round(vr.size_multiplier * 100)}%
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
                    <div className={`h-2 rounded-full ${vr.size_multiplier >= 0.7 ? 'bg-emerald-500' : vr.size_multiplier >= 0.4 ? 'bg-yellow-500' : 'bg-red-500'}`}
                         style={{width: `${vr.size_multiplier * 100}%`}} />
                  </div>
                </div>
              </div>

              {/* Right: Sparkline chart + action */}
              <div className="col-span-7">
                {/* Sparkline */}
                <div className="bg-white/60 rounded-lg p-3 mb-3">
                  <div className="text-xs text-gray-500 mb-1">VIX 期限结构比率 — 20日走势</div>
                  <svg width="100%" height={svgH + 35} viewBox={`0 -10 ${svgW} ${svgH + 35}`} preserveAspectRatio="none">
                    {/* Threshold zones */}
                    <rect x="0" y="0" width={svgW} height={y095} fill="#FEF2F2" opacity="0.5" />
                    <rect x="0" y={y095} width={svgW} height={y105 - y095 < 0 ? 0 : y105 - y095} fill="#FFFBEB" opacity="0.3" />
                    {/* Threshold lines */}
                    <line x1="0" y1={y095} x2={svgW} y2={y095} stroke="#F59E0B" strokeWidth="1" strokeDasharray="4,4" />
                    <line x1="0" y1={y105} x2={svgW} y2={y105} stroke="#EF4444" strokeWidth="1" strokeDasharray="4,4" />
                    {/* Labels */}
                    <text x={svgW - 2} y={y095 - 3} fill="#F59E0B" fontSize="9" textAnchor="end">0.95</text>
                    <text x={svgW - 2} y={y105 - 3} fill="#EF4444" fontSize="9" textAnchor="end">1.05</text>
                    {/* VIX9D/VIX leading ratio line (orange, behind primary) */}
                    {leadPts && (
                      <>
                        <polyline fill="none" stroke="#8B5CF6" strokeWidth="1.5" opacity="0.8" points={leadPts} />
                        {leadVals.length > 0 && (
                          <circle cx={svgW} cy={svgH - ((leadVals[leadVals.length-1]-sMin)/sRange)*svgH} r="3" fill="#8B5CF6" stroke="white" strokeWidth="1.5" />
                        )}
                      </>
                    )}
                    {/* VIX/VIX3M primary ratio line (blue, on top) */}
                    <polyline fill="none" stroke="#3B82F6" strokeWidth="2" points={pts} />
                    {/* Current point */}
                    {vals.length > 0 && (
                      <circle cx={svgW} cy={svgH - ((vals[vals.length-1]-sMin)/sRange)*svgH} r="4" fill="#3B82F6" stroke="white" strokeWidth="2" />
                    )}
                    {/* Date labels */}
                    {sparkData.length > 0 && (
                      <>
                        <text x="0" y={svgH + 18} fill="#6B7280" fontSize="11">{sparkData[0].date}</text>
                        <text x={svgW/2} y={svgH + 18} fill="#6B7280" fontSize="11" textAnchor="middle">{sparkData[Math.floor(sparkData.length/2)]?.date}</text>
                        <text x={svgW} y={svgH + 18} fill="#6B7280" fontSize="11" textAnchor="end">{sparkData[sparkData.length-1].date}</text>
                      </>
                    )}
                  </svg>
                  <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                    <span><span style={{color:'#3B82F6'}}>━</span> VIX/VIX3M (主要)</span>
                    <span><span style={{color:'#8B5CF6'}}>━</span> VIX9D/VIX (前导)</span>
                    <span>🟢 &lt;0.95 🟡 0.95-1.05 🔴 &gt;1.05</span>
                  </div>
                </div>

                {/* Action recommendation */}
                <div className={`rounded-lg p-3 border ${cfg.border} bg-white/80`}>
                  <div className="text-sm font-bold text-gray-800 mb-1">📋 操作建议</div>
                  <p className="text-sm text-gray-600 leading-relaxed">{alert.message}</p>
                  <p className="text-xs text-gray-500 mt-2 font-medium">{alert.action}</p>
                </div>
              </div>
            </div>

            {/* Current reading interpretation */}
            <div className="mt-4 bg-white/60 rounded-lg p-4 border border-gray-200/50">
              <div className="text-sm font-bold text-gray-800 mb-2">📖 当前读数解读</div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs text-gray-600">
                <div>
                  <span className="font-medium text-gray-800">VIX/VIX3M = {vr.primary_ratio?.toFixed(3)} {dirArrow}</span>
                  <span className="ml-1">
                    {vr.primary_ratio < 0.85 ? '→ 深度Contango：市场极度自满，波动率极低，安全卖premium但收益也低'
                     : vr.primary_ratio < 0.95 ? '→ Contango：短期恐惧低于长期预期，正常状态，适合卖premium'
                     : vr.primary_ratio < 1.05 ? '→ Flat：短期和长期恐惧接近，市场在过渡中，方向比位置更重要'
                     : vr.primary_ratio < 1.15 ? '→ Backwardation：短期恐惧超过长期预期，市场恐慌中，不宜开新仓'
                     : '→ 深度Backwardation：极端恐慌（如COVID），应资金保全'}
                  </span>
                </div>
                <div>
                  <span className="font-medium text-gray-800">VIX9D/VIX = {vr.leading_ratio?.toFixed(3)}</span>
                  <span className="ml-1">
                    {vr.leading_ratio < 0.95 ? '→ 前导正常：极短期（9天）恐惧低于30天恐惧，无急性压力'
                     : vr.leading_ratio < 1.05 ? '→ 前导偏高：极短期恐惧接近30天恐惧，需密切关注，可能是主要比率恶化的前兆'
                     : '→ 前导飙升：极短期恐惧已超过30天恐惧，市场正在经历急性冲击，主要比率可能1-3天内跟上'}
                  </span>
                </div>
                <div>
                  <span className="font-medium text-gray-800">5日趋势: {dirArrow} {dirLabel}</span>
                  <span className="ml-1">
                    {vr.sma_direction === 'RISING' ? '→ VIX/VIX3M比率（上方图表的蓝线）的5日均线在上升，说明短期恐惧相对长期在加剧。即使当前仍在Contango区间，趋势方向不利，应考虑减仓或暂停开新仓'
                     : vr.sma_direction === 'FALLING' ? '→ VIX/VIX3M比率（上方图表的蓝线）的5日均线在下降，说明短期恐惧正在消退、回归正常。如果是从Flat/Backwardation高位回落到当前位置，这可能是"黄金窗口"——此时IV仍然偏高（期权premium肥），但恐慌已在消退（被行权风险降低），是卖CSP收益风险比最佳的时机'
                     : '→ VIX/VIX3M比率（上方图表的蓝线）的5日均线走平，短期恐惧相对长期没有明显变化。维持当前仓位，等待明确的上升（减仓信号）或下降（加仓信号）再调整'}
                  </span>
                </div>
                <div>
                  <span className="font-medium text-gray-800">日变动: {vr.daily_delta > 0 ? '+' : ''}{vr.daily_delta?.toFixed(4)} ({vr.delta_magnitude})</span>
                  <span className="ml-1">
                    {vr.delta_magnitude === 'noise' ? '→ 噪音级别（<0.01），无实际意义，可忽略'
                     : vr.delta_magnitude === 'meaningful' ? '→ 有意义的变动（0.01-0.03），趋势正在形成，关注后续方向确认'
                     : '→ 快速变动（>0.03），状态可能在1-2天内转换，需要立即评估仓位'}
                  </span>
                </div>
              </div>

              {/* Core principle */}
              <div className="mt-3 pt-3 border-t border-gray-200/50 text-xs text-gray-500 italic">
                💡 核心原则：绝对水平告诉你在哪里，变动方向和速度告诉你要去哪里。决策基于你要去哪里，而不是你在哪里。同样VIX=25，从20涨到25（恶化）和从35降到25（好转）的操作完全不同。
              </div>
            </div>
          </div>
        );
      })()}

      {/* ═══ 3-Tier Cascading Analysis ═══ */}
      {(cascadingLoading || cascading) && (
        <div className="border-t-2 border-dashed border-indigo-200 pt-5 mt-5 space-y-4">
          {/* Progress Stepper */}
          <CascadingStepper
            currentTier={cascadingTier}
            tierStatus={cascadingStatus}
            message={cascadingMessage}
          />

          {cascadingError && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-600 text-sm">
              分析出错: {cascadingError}
            </div>
          )}

          {/* Tier 1 Results - use existing AIAnalysisSection for macro */}
          {cascading?.tier1?.ai && (
            <div className="space-y-3">
              <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">🌍 Tier 1: 大盘分析</h2>
              <AIAnalysisSection ai={{
                ...cascading.tier1.ai,
                sectors: cascading.tier1.ai.sector_picks || { best_for_csp: cascading.tier1.ai.favorable_sectors?.map(s => s.sector), avoid: cascading.tier1.ai.avoid_sectors?.map(s => s.sector) },
                csp_strategy: cascading.tier1.ai.csp_parameters ? {
                  dte: cascading.tier1.ai.csp_parameters.recommended_dte,
                  delta: cascading.tier1.ai.csp_parameters.recommended_delta,
                  sizing: cascading.tier1.ai.csp_parameters.position_sizing,
                  commentary: cascading.tier1.ai.news_sentiment_summary || '',
                } : {},
                risks: cascading.tier1.ai.key_risks,
                catalysts: cascading.tier1.ai.key_catalysts,
              }} />

              {/* Favorable sectors badges */}
              {cascading.tier1.ai.favorable_sectors?.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-gray-500 font-semibold">→ Tier 2 推荐板块:</span>
                  {cascading.tier1.ai.favorable_sectors.map((s, i) => (
                    <span key={i} className="bg-emerald-50 text-emerald-700 text-xs px-2 py-0.5 rounded-full border border-emerald-200 font-medium">
                      {s.sector} ({s.confidence}/10)
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Tier 2 Results */}
          {cascading?.tier2 && <Tier2SectorResults tier2={cascading.tier2} />}

          {/* Tier 3 Results */}
          {cascading?.tier3 && <Tier3StockResults tier3={cascading.tier3} />}
        </div>
      )}

      {/* Empty state */}
      {!data && !loading && !error && (
        <div className="text-center py-20 text-gray-400">
          <Globe size={48} className="mx-auto mb-4 opacity-30" />
          <p className="text-lg">Loading market intelligence...</p>
        </div>
      )}
    </div>
  );
}
