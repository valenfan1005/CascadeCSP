import React, { useState, useCallback } from 'react';
import { runCSPScan, runCSPScanQuick, getCSPSignal } from '../api.js';
import { Radar, RefreshCw, ChevronDown, ChevronUp, Filter, Zap, Shield, TrendingUp, BarChart3, Activity } from 'lucide-react';

// ─── Helpers ────────────────────────────────────────────────
const fmt = (n, d = 2) => n != null ? Number(n).toFixed(d) : '—';
const fmtPct = (n) => n != null ? `${(n * 100).toFixed(1)}%` : '—';
const fmtB = (n) => {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${Number(n).toLocaleString()}`;
};
const fmtK = (n) => {
  if (n == null) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toString();
};

// ─── Score Badge ────────────────────────────────────────────
function ScoreBadge({ score, size = 'md' }) {
  const color = score >= 70 ? 'bg-emerald-500' : score >= 50 ? 'bg-yellow-500' : score >= 30 ? 'bg-orange-500' : 'bg-red-500';
  const sz = size === 'lg' ? 'w-12 h-12 text-lg' : 'w-9 h-9 text-sm';
  return (
    <div className={`${color} ${sz} rounded-full flex items-center justify-center font-bold text-white shadow-lg`}>
      {Math.round(score)}
    </div>
  );
}

// ─── Score Breakdown Bar ────────────────────────────────────
function ScoreBar({ label, score, max, icon: Icon }) {
  const pct = Math.min((score / max) * 100, 100); // cap at 100% to prevent bar overflow
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 50 ? 'bg-yellow-500' : pct >= 30 ? 'bg-orange-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2 text-xs">
      {Icon && <Icon size={12} className="text-gray-500 shrink-0" />}
      <span className="text-gray-500 w-20 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-200 rounded-full h-2 overflow-hidden">
        <div className={`${color} rounded-full h-2 transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-900 font-mono w-10 text-right">{fmt(Math.min(score, max), 0)}/{max}</span>
    </div>
  );
}

// ─── CSP Detail Row ─────────────────────────────────────────
function CSPDetail({ csp, label }) {
  if (!csp) return null;
  return (
    <div className="bg-gray-50 rounded-lg p-2.5 text-xs">
      <p className="text-gray-500 font-medium mb-1.5">{label}</p>
      <div className="grid grid-cols-4 gap-2">
        <div>
          <p className="text-gray-400">Strike</p>
          <p className="text-gray-900 font-mono font-semibold">${fmt(csp.strike, 0)}</p>
        </div>
        <div>
          <p className="text-gray-400">Premium</p>
          <p className="text-emerald-600 font-mono font-semibold">${fmt(csp.mid)}</p>
        </div>
        <div>
          <p className="text-gray-400">Delta</p>
          <p className="text-gray-900 font-mono">{fmt(csp.delta, 2)}</p>
        </div>
        <div>
          <p className="text-gray-400">Annual Ret</p>
          <p className="text-yellow-600 font-mono font-semibold">{fmtPct(csp.annualized_return)}</p>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2 mt-1.5">
        <div>
          <p className="text-gray-400">Expiry</p>
          <p className="text-gray-900 font-mono">{csp.expiry}</p>
        </div>
        <div>
          <p className="text-gray-400">DTE</p>
          <p className="text-gray-900 font-mono">{csp.dte}</p>
        </div>
        <div>
          <p className="text-gray-400">OI</p>
          <p className="text-gray-900 font-mono">{fmtK(csp.open_interest)}</p>
        </div>
        <div>
          <p className="text-gray-400">Spread</p>
          <p className="text-gray-900 font-mono">{fmtPct(csp.spread_pct)}</p>
        </div>
      </div>
    </div>
  );
}

// ─── AI Signal Panel ────────────────────────────────────────
function AISignalPanel({ signal, loading }) {
  if (loading) {
    return (
      <div className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-lg p-4 border border-indigo-200 animate-pulse">
        <div className="flex items-center gap-2 text-indigo-600 text-sm">
          <RefreshCw size={14} className="animate-spin" />
          Analyzing with Claude AI...
        </div>
      </div>
    );
  }
  if (!signal) return null;
  if (signal.error) {
    return (
      <div className="bg-red-50 rounded-lg p-3 border border-red-200 text-red-600 text-xs">
        AI Signal Error: {signal.error}
      </div>
    );
  }

  const signalColors = {
    'STRONG_SELL_CSP': { bg: 'from-emerald-50 to-green-50', border: 'border-emerald-200', badge: 'bg-emerald-500', text: '🟢 Strong Sell CSP' },
    'SELL_CSP': { bg: 'from-green-50 to-teal-50', border: 'border-green-200', badge: 'bg-green-600', text: '🟢 Sell CSP' },
    'CAUTIOUS': { bg: 'from-yellow-50 to-amber-50', border: 'border-yellow-200', badge: 'bg-yellow-600', text: '🟡 Cautious' },
    'AVOID': { bg: 'from-red-50 to-rose-50', border: 'border-red-200', badge: 'bg-red-500', text: '🔴 Avoid' },
  };
  const sc = signalColors[signal.signal] || signalColors['CAUTIOUS'];

  return (
    <div className={`bg-gradient-to-r ${sc.bg} rounded-lg p-4 border ${sc.border}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`${sc.badge} text-white text-xs font-bold px-2.5 py-1 rounded-full`}>
            {sc.text}
          </span>
          <span className="text-gray-500 text-xs">Confidence: {signal.confidence}/10</span>
        </div>
        <span className="text-gray-400 text-[10px]">
          {signal.generated_at ? new Date(signal.generated_at).toLocaleTimeString() : ''}
        </span>
      </div>

      <p className="text-gray-900 text-sm mb-3">{signal.summary}</p>

      {/* Recommended Trade */}
      {signal.recommended_strike && (
        <div className="bg-gray-50 rounded-lg p-2.5 mb-3 text-xs">
          <p className="text-gray-500 font-medium mb-1">Recommended CSP</p>
          <div className="flex gap-4">
            <span className="text-gray-900">Strike: <span className="text-emerald-600 font-mono font-bold">${signal.recommended_strike}</span></span>
            {signal.recommended_dte && <span className="text-gray-900">DTE: <span className="text-indigo-500 font-mono">{signal.recommended_dte}</span></span>}
            {signal.recommended_premium && <span className="text-gray-900">Premium: <span className="text-yellow-600 font-mono">${signal.recommended_premium}</span></span>}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 mb-3 text-xs">
        <div className="bg-emerald-50 rounded p-2">
          <p className="text-emerald-500 font-medium mb-0.5">Bull Case</p>
          <p className="text-gray-600">{signal.bull_case}</p>
        </div>
        <div className="bg-red-50 rounded p-2">
          <p className="text-red-500 font-medium mb-0.5">Bear Case</p>
          <p className="text-gray-600">{signal.bear_case}</p>
        </div>
      </div>

      {/* Risks */}
      {signal.risks?.length > 0 && (
        <div className="text-xs">
          <p className="text-gray-500 font-medium mb-1">⚠️ Risks</p>
          <div className="flex flex-wrap gap-1.5">
            {signal.risks.map((r, i) => (
              <span key={i} className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-[11px]">{r}</span>
            ))}
          </div>
        </div>
      )}

      {/* Key Levels */}
      {signal.key_levels && (signal.key_levels.support || signal.key_levels.resistance) && (
        <div className="flex gap-3 mt-2 text-[11px] text-gray-400">
          {signal.key_levels.support && <span>Support: <span className="text-emerald-600 font-mono">${signal.key_levels.support}</span></span>}
          {signal.key_levels.resistance && <span>Resistance: <span className="text-red-600 font-mono">${signal.key_levels.resistance}</span></span>}
        </div>
      )}

      {/* FinBERT News Sentiment */}
      {signal.sentiment?.articles?.length > 0 ? (
        <div className="mt-3 text-xs">
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-gray-500 font-medium">📰 News Sentiment <span className="text-gray-400 font-normal">(FinBERT)</span></p>
            {signal.sentiment.aggregate && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                signal.sentiment.aggregate.sentiment === 'bullish' ? 'bg-emerald-50 text-emerald-700' :
                signal.sentiment.aggregate.sentiment === 'bearish' ? 'bg-red-50 text-red-700' :
                'bg-gray-100 text-gray-600'
              }`}>
                {signal.sentiment.aggregate.sentiment === 'bullish' ? '📈' : signal.sentiment.aggregate.sentiment === 'bearish' ? '📉' : '➖'}
                {' '}{signal.sentiment.aggregate.sentiment.toUpperCase()} ({signal.sentiment.aggregate.avg_score > 0 ? '+' : ''}{signal.sentiment.aggregate.avg_score.toFixed(2)})
              </span>
            )}
          </div>
          <div className="space-y-1">
            {signal.sentiment.articles.map((a, i) => (
              <div key={i} className="flex items-start gap-2 text-[11px]">
                <span className={`shrink-0 w-10 text-center font-mono font-bold rounded px-1 py-0.5 ${
                  a.sentiment === 'positive' ? 'bg-emerald-50 text-emerald-700' :
                  a.sentiment === 'negative' ? 'bg-red-50 text-red-700' :
                  'bg-gray-50 text-gray-500'
                }`}>
                  {a.score > 0 ? '+' : ''}{a.score.toFixed(2)}
                </span>
                <span className="text-gray-600 flex-1">{a.headline}</span>
                {a.publisher && <span className="text-gray-400 shrink-0 ml-auto whitespace-nowrap">{a.publisher}</span>}
              </div>
            ))}
          </div>
        </div>
      ) : signal.news?.length > 0 && (
        <div className="mt-3 text-xs">
          <p className="text-gray-500 font-medium mb-1.5">📰 Recent News</p>
          <div className="space-y-1">
            {signal.news.map((n, i) => (
              <div key={i} className="flex items-start gap-2 text-[11px]">
                <span className="text-gray-400 shrink-0">•</span>
                <span className="text-gray-600">{n.title}</span>
                {n.publisher && <span className="text-gray-400 shrink-0 ml-auto whitespace-nowrap">{n.publisher}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Stock Card (expanded view) ─────────────────────────────
function StockCard({ stock, rank }) {
  const [expanded, setExpanded] = useState(false);
  const [aiSignal, setAiSignal] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const s = stock.score_breakdown || {};
  const opts = stock.options_data || {};
  const earningsDays = stock.days_to_earnings;
  const earningsWarning = earningsDays != null && earningsDays <= 14;

  const handleAISignal = async () => {
    setAiLoading(true);
    setExpanded(true);
    try {
      const data = await getCSPSignal(stock.ticker);
      setAiSignal(data);
    } catch (err) {
      setAiSignal({ error: err.message });
    } finally {
      setAiLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 hover:border-gray-300 transition-all overflow-hidden shadow-sm">
      {/* Main row */}
      <div
        className="flex items-center px-4 py-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Rank */}
        <span className="text-gray-400 font-mono text-sm w-8 shrink-0">#{rank}</span>

        {/* Score */}
        <div className="shrink-0 mr-3">
          <ScoreBadge score={stock.csp_score || 0} />
        </div>

        {/* Ticker + Name */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-gray-900 font-bold text-lg">{stock.ticker}</span>
            {earningsWarning && (
              <span className="bg-red-50 text-red-600 text-[10px] px-1.5 py-0.5 rounded font-medium">
                ER {earningsDays}d
              </span>
            )}
            {stock.sector && (
              <span className="bg-gray-100 text-gray-500 text-[10px] px-1.5 py-0.5 rounded">
                {stock.sector}
              </span>
            )}
          </div>
          <p className="text-gray-400 text-xs truncate">{stock.name}</p>
        </div>

        {/* Key metrics */}
        <div className="hidden md:grid grid-cols-5 gap-4 text-xs mr-4">
          <div className="text-center">
            <p className="text-gray-400">Price</p>
            <p className="text-gray-900 font-mono font-semibold">${fmt(stock.price, 2)}</p>
          </div>
          <div className="text-center">
            <p className="text-gray-400">ATM IV</p>
            <p className="text-yellow-600 font-mono font-semibold">
              {opts.atm_iv ? fmtPct(opts.atm_iv) : fmtPct(stock.volatility_m / 100 * Math.sqrt(12))}
            </p>
          </div>
          <div className="text-center">
            <p className="text-gray-400">Vol.M</p>
            <p className="text-gray-900 font-mono">{fmt(stock.volatility_m, 1)}%</p>
          </div>
          <div className="text-center">
            <p className="text-gray-400">RSI</p>
            <p className={`font-mono ${stock.rsi < 40 ? 'text-emerald-600' : stock.rsi > 70 ? 'text-red-600' : 'text-gray-900'}`}>
              {fmt(stock.rsi, 0)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-gray-400">Best Ret</p>
            <p className="text-emerald-600 font-mono font-semibold">
              {opts.best_csp_return ? fmtPct(opts.best_csp_return.annualized_return) : '—'}
            </p>
          </div>
        </div>

        {/* AI Signal button */}
        <button
          onClick={(e) => { e.stopPropagation(); handleAISignal(); }}
          disabled={aiLoading}
          className="bg-indigo-100 hover:bg-indigo-200 text-indigo-600 text-[11px] px-2.5 py-1 rounded-lg transition disabled:opacity-50 flex items-center gap-1 shrink-0 mr-2"
          title="Get AI Analysis"
        >
          {aiLoading ? <RefreshCw size={11} className="animate-spin" /> : '🤖'}
          AI
        </button>

        {/* Expand arrow */}
        {expanded ? <ChevronUp size={16} className="text-gray-500" /> : <ChevronDown size={16} className="text-gray-500" />}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-gray-200 px-4 py-3 space-y-3">
          {/* AI Signal */}
          {(aiSignal || aiLoading) && (
            <AISignalPanel signal={aiSignal} loading={aiLoading} />
          )}

          {/* Score breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <p className="text-gray-600 text-xs font-semibold uppercase tracking-wide">Score Breakdown</p>
              <ScoreBar label="IV" score={s.iv_score || 0} max={30} icon={Activity} />
              <ScoreBar label="Liquidity" score={s.liquidity_score || 0} max={20} icon={BarChart3} />
              <ScoreBar label="Return" score={s.return_score || 0} max={20} icon={TrendingUp} />
              <ScoreBar label="Technical" score={s.technical_score || 0} max={15} icon={Zap} />
              <ScoreBar label="Safety" score={s.safety_score || 0} max={15} icon={Shield} />
            </div>

            <div className="space-y-2">
              <p className="text-gray-600 text-xs font-semibold uppercase tracking-wide">Fundamentals</p>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className="bg-gray-50 rounded p-2">
                  <p className="text-gray-400">Mkt Cap</p>
                  <p className="text-gray-900 font-mono">{fmtB(stock.market_cap)}</p>
                </div>
                <div className="bg-gray-50 rounded p-2">
                  <p className="text-gray-400">P/E</p>
                  <p className="text-gray-900 font-mono">{stock.pe_ttm ? fmt(stock.pe_ttm, 1) : '—'}</p>
                </div>
                <div className="bg-gray-50 rounded p-2">
                  <p className="text-gray-400">Beta</p>
                  <p className={`font-mono ${stock.beta > 2 ? 'text-red-600' : stock.beta > 1.5 ? 'text-yellow-600' : 'text-gray-900'}`}>
                    {fmt(stock.beta, 2)}
                  </p>
                </div>
                <div className="bg-gray-50 rounded p-2">
                  <p className="text-gray-400">1M Perf</p>
                  <p className={`font-mono ${stock.perf_1m >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                    {stock.perf_1m != null ? `${stock.perf_1m >= 0 ? '+' : ''}${fmt(stock.perf_1m, 1)}%` : '—'}
                  </p>
                </div>
                <div className="bg-gray-50 rounded p-2">
                  <p className="text-gray-400">Avg Vol</p>
                  <p className="text-gray-900 font-mono">{fmtK(stock.avg_volume)}</p>
                </div>
                <div className="bg-gray-50 rounded p-2">
                  <p className="text-gray-400">Earnings</p>
                  <p className={`font-mono ${earningsWarning ? 'text-red-600' : 'text-gray-900'}`}>
                    {earningsDays != null ? `${earningsDays}d` : '—'}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* CSP Recommendations */}
          {opts.best_csp_16d || opts.best_csp_return ? (
            <div className="space-y-2">
              <p className="text-gray-600 text-xs font-semibold uppercase tracking-wide">CSP Recommendations</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <CSPDetail csp={opts.best_csp_16d} label="Best ~16 Delta (1 Std Dev)" />
                <CSPDetail csp={opts.best_csp_return} label="Best Annualized Return" />
              </div>
            </div>
          ) : (
            <p className="text-gray-500 text-xs italic">Options data not available — run full scan for IV enrichment</p>
          )}

          {/* All candidate strikes */}
          {opts.all_candidates?.length > 0 && (
            <div>
              <p className="text-gray-600 text-xs font-semibold uppercase tracking-wide mb-2">All OTM Put Candidates</p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-400 border-b border-gray-200">
                      <th className="text-left py-1 px-2">Strike</th>
                      <th className="text-right py-1 px-2">OTM%</th>
                      <th className="text-right py-1 px-2">Bid</th>
                      <th className="text-right py-1 px-2">Ask</th>
                      <th className="text-right py-1 px-2">Mid</th>
                      <th className="text-right py-1 px-2">IV</th>
                      <th className="text-right py-1 px-2">Delta</th>
                      <th className="text-right py-1 px-2">OI</th>
                      <th className="text-right py-1 px-2">Annual Ret</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opts.all_candidates.map((c, i) => (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="py-1.5 px-2 text-gray-900 font-mono">${fmt(c.strike, 0)}</td>
                        <td className="py-1.5 px-2 text-right text-gray-500 font-mono">{fmtPct(c.otm_pct)}</td>
                        <td className="py-1.5 px-2 text-right text-gray-900 font-mono">${fmt(c.bid)}</td>
                        <td className="py-1.5 px-2 text-right text-gray-900 font-mono">${fmt(c.ask)}</td>
                        <td className="py-1.5 px-2 text-right text-emerald-600 font-mono font-semibold">${fmt(c.mid)}</td>
                        <td className="py-1.5 px-2 text-right text-yellow-600 font-mono">{fmtPct(c.iv)}</td>
                        <td className="py-1.5 px-2 text-right text-gray-900 font-mono">{fmt(c.delta, 2)}</td>
                        <td className="py-1.5 px-2 text-right text-gray-500 font-mono">{fmtK(c.open_interest)}</td>
                        <td className="py-1.5 px-2 text-right text-emerald-600 font-mono font-semibold">{fmtPct(c.annualized_return)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Filter Controls ────────────────────────────────────────
const SECTORS = [
  'All', 'Technology Services', 'Electronic Technology', 'Health Technology',
  'Finance', 'Retail Trade', 'Consumer Non-Durables', 'Energy Minerals',
  'Communications', 'Producer Manufacturing', 'Industrial Services',
];
const SORT_OPTIONS = [
  { value: 'score', label: 'CSP Score' },
  { value: 'iv', label: 'Highest IV' },
  { value: 'return', label: 'Best Return' },
  { value: 'safety', label: 'Safest' },
  { value: 'volatility', label: 'Volatility' },
];

// ─── Main Component ─────────────────────────────────────────
export default function CSPScanner() {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanType, setScanType] = useState('full'); // 'full' or 'quick'
  const [error, setError] = useState(null);
  const [sortBy, setSortBy] = useState('score');
  const [sectorFilter, setSectorFilter] = useState('All');
  const [minScore, setMinScore] = useState(0);
  const [hideEarnings, setHideEarnings] = useState(false);

  const runScan = useCallback(async (type) => {
    setLoading(true);
    setError(null);
    try {
      const data = type === 'quick' ? await runCSPScanQuick() : await runCSPScan();
      setResults(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Apply filters and sorting
  const filtered = (results?.results || [])
    .filter(s => sectorFilter === 'All' || s.sector === sectorFilter)
    .filter(s => (s.csp_score || 0) >= minScore)
    .filter(s => !hideEarnings || s.days_to_earnings == null || s.days_to_earnings > 14)
    .sort((a, b) => {
      switch (sortBy) {
        case 'iv': {
          const aIv = a.options_data?.atm_iv || a.volatility_m || 0;
          const bIv = b.options_data?.atm_iv || b.volatility_m || 0;
          return bIv - aIv;
        }
        case 'return': {
          const aRet = a.options_data?.best_csp_return?.annualized_return || 0;
          const bRet = b.options_data?.best_csp_return?.annualized_return || 0;
          return bRet - aRet;
        }
        case 'safety':
          return (b.score_breakdown?.safety_score || 0) - (a.score_breakdown?.safety_score || 0);
        case 'volatility':
          return (b.volatility_m || 0) - (a.volatility_m || 0);
        default:
          return (b.csp_score || 0) - (a.csp_score || 0);
      }
    });

  const scanTime = results?.scan_time ? new Date(results.scan_time).toLocaleString() : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-indigo-900 via-purple-900 to-indigo-900 rounded-2xl p-6 border border-indigo-700/30">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <Radar size={28} className="text-indigo-400" />
              CSP Scanner
            </h1>
            <p className="text-indigo-300 text-sm mt-1">
              Scans 200+ liquid stocks for the best Cash-Secured Put opportunities based on IV, liquidity, technicals & safety
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => { setScanType('quick'); runScan('quick'); }}
              disabled={loading}
              className="bg-gray-200 hover:bg-gray-300 text-gray-900 text-sm px-4 py-2 rounded-lg transition disabled:opacity-50 flex items-center gap-1.5"
            >
              <Zap size={14} />
              Quick Scan
            </button>
            <button
              onClick={() => { setScanType('full'); runScan('full'); }}
              disabled={loading}
              className="bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-4 py-2 rounded-lg transition disabled:opacity-50 flex items-center gap-1.5"
            >
              {loading ? <RefreshCw size={14} className="animate-spin" /> : <Radar size={14} />}
              {loading ? (scanType === 'full' ? 'Scanning (1-2 min)...' : 'Scanning...') : 'Full Scan + IV'}
            </button>
          </div>
        </div>

        {scanTime && (
          <p className="text-indigo-400/60 text-xs mt-2">
            Last scan: {scanTime} | {results?.total_scanned || 0} stocks scanned | {results?.results?.length || 0} candidates
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* Filters */}
      {results && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Filter size={14} className="text-gray-500" />

          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value)}
            className="bg-white border border-gray-300 text-gray-900 text-xs rounded-lg px-3 py-1.5"
          >
            {SORT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>Sort: {o.label}</option>
            ))}
          </select>

          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="bg-white border border-gray-300 text-gray-900 text-xs rounded-lg px-3 py-1.5"
          >
            {SECTORS.map(s => (
              <option key={s} value={s}>{s === 'All' ? 'All Sectors' : s}</option>
            ))}
          </select>

          <div className="flex items-center gap-1.5">
            <span className="text-gray-500 text-xs">Min Score:</span>
            <input
              type="range"
              min={0}
              max={80}
              step={5}
              value={minScore}
              onChange={e => setMinScore(Number(e.target.value))}
              className="w-20 accent-indigo-500"
            />
            <span className="text-gray-900 text-xs font-mono w-5">{minScore}</span>
          </div>

          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
            <input
              type="checkbox"
              checked={hideEarnings}
              onChange={e => setHideEarnings(e.target.checked)}
              className="accent-indigo-500"
            />
            Hide ER &lt;14d
          </label>

          <span className="text-gray-500 text-xs ml-auto">
            Showing {filtered.length} of {results?.results?.length || 0}
          </span>
        </div>
      )}

      {/* Results */}
      {!results && !loading && (
        <div className="text-center py-20 text-gray-500">
          <Radar size={48} className="mx-auto mb-4 opacity-30" />
          <p className="text-lg">Click "Full Scan + IV" to find the best CSP opportunities</p>
          <p className="text-sm mt-1">Quick Scan uses TradingView data only (faster, no options data)</p>
          <p className="text-sm mt-1">Full Scan adds Yahoo Finance options chains for IV & strike recommendations</p>
        </div>
      )}

      {loading && (
        <div className="text-center py-20">
          <RefreshCw size={32} className="mx-auto mb-4 text-indigo-400 animate-spin" />
          <p className="text-gray-900 text-lg">
            {scanType === 'full' ? 'Running full scan with IV enrichment...' : 'Running quick scan...'}
          </p>
          <p className="text-gray-500 text-sm mt-1">
            {scanType === 'full' ? 'Scanning 200+ stocks + fetching options chains for top 30. This takes 1-2 minutes.' : 'Fetching TradingView data...'}
          </p>
        </div>
      )}

      {results && !loading && (
        <div className="space-y-2">
          {filtered.map((stock, i) => (
            <StockCard key={stock.ticker} stock={stock} rank={i + 1} />
          ))}
          {filtered.length === 0 && (
            <p className="text-center text-gray-500 py-10">No stocks match current filters</p>
          )}
        </div>
      )}
    </div>
  );
}
