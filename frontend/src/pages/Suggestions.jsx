import React, { useState, useEffect } from 'react';
import { fetchSuggestions } from '../api.js';
import { Zap, TrendingUp, TrendingDown, AlertTriangle, Shield, RefreshCw, ChevronDown, ChevronUp, DollarSign, Target, BarChart3 } from 'lucide-react';

const SIGNAL_COLORS = {
  BULLISH: 'text-emerald-600 bg-emerald-50',
  BEARISH: 'text-red-600 bg-red-50',
  CAUTION: 'text-yellow-600 bg-yellow-50',
};

const STRATEGY_STYLES = {
  CSP: { label: 'Cash-Secured Put', color: 'bg-blue-50 text-blue-600', icon: '🔵' },
  PUT_SPREAD: { label: 'Bull Put Spread', color: 'bg-emerald-50 text-emerald-600', icon: '🟢' },
  BEAR_CALL_SPREAD: { label: 'Bear Call Spread', color: 'bg-red-50 text-red-600', icon: '🔴' },
  HEDGE: { label: 'Hedge / Review', color: 'bg-yellow-50 text-yellow-600', icon: '⚠️' },
};

const ASSESSMENT_COLORS = {
  FAVORABLE: { bg: 'bg-emerald-50 border-emerald-200', text: 'text-emerald-600', icon: TrendingUp },
  NEUTRAL: { bg: 'bg-blue-50 border-blue-200', text: 'text-blue-600', icon: BarChart3 },
  CAUTIOUS: { bg: 'bg-yellow-50 border-yellow-200', text: 'text-yellow-600', icon: AlertTriangle },
  DEFENSIVE: { bg: 'bg-red-50 border-red-200', text: 'text-red-600', icon: Shield },
};

function MarketContext({ market }) {
  if (!market || market.error) return null;

  return (
    <div className="grid grid-cols-5 gap-3">
      <div className="card text-center">
        <p className="label">VIX</p>
        <p className={`text-2xl font-bold ${market.vix < 20 ? 'text-emerald-600' : market.vix < 30 ? 'text-yellow-600' : 'text-red-600'}`}>
          {market.vix}
        </p>
        <p className={`text-xs mt-1 ${market.vix_trend === 'RISING' ? 'text-red-500' : market.vix_trend === 'FALLING' ? 'text-emerald-500' : 'text-gray-500'}`}>
          {market.vix_trend === 'RISING' ? '↑ Rising' : market.vix_trend === 'FALLING' ? '↓ Falling' : '→ Stable'}
        </p>
      </div>
      <div className="card text-center">
        <p className="label">SPY</p>
        <p className="text-2xl font-bold">${market.spy_price}</p>
        <p className={`text-xs mt-1 ${market.spy_above_sma20 ? 'text-emerald-500' : 'text-red-500'}`}>
          {market.spy_above_sma20 ? '✓ Above' : '✗ Below'} 20 SMA (${market.spy_sma20})
        </p>
      </div>
      <div className="card text-center">
        <p className="label">QQQ</p>
        <p className="text-2xl font-bold">${market.qqq_price}</p>
        <p className={`text-xs mt-1 ${market.qqq_above_sma20 ? 'text-emerald-500' : 'text-red-500'}`}>
          {market.qqq_above_sma20 ? '✓ Above' : '✗ Below'} 20 SMA (${market.qqq_sma20})
        </p>
      </div>
      <div className="card text-center">
        <p className="label">SPY Trend</p>
        <p className={`text-2xl font-bold ${market.spy_trend === 'UP' ? 'text-emerald-600' : market.spy_trend === 'DOWN' ? 'text-red-600' : 'text-gray-600'}`}>
          {market.spy_trend}
        </p>
        <p className="text-xs mt-1 text-gray-500">
          {market.spy_above_sma50 ? '✓ Above 50 SMA' : '✗ Below 50 SMA'}
        </p>
      </div>
      <div className="card text-center">
        <p className="label">Regime</p>
        <p className={`text-lg font-bold ${
          market.regime === 'EXTREME_FEAR' ? 'text-purple-600' :
          market.regime === 'VERY_FEARFUL' ? 'text-blue-600' :
          market.regime === 'FEAR' ? 'text-emerald-600' :
          market.regime === 'SLIGHT_FEAR' ? 'text-emerald-500' :
          market.regime === 'GREED' ? 'text-orange-500' : 'text-red-500'
        }`}>
          {market.regime?.replace(/_/g, ' ')}
        </p>
      </div>
    </div>
  );
}

function AssessmentPanel({ assessment }) {
  if (!assessment) return null;
  const style = ASSESSMENT_COLORS[assessment.overall] || ASSESSMENT_COLORS.NEUTRAL;
  const Icon = style.icon;

  return (
    <div className={`rounded-xl border p-5 ${style.bg}`}>
      <div className="flex items-start gap-4">
        <div className="p-2 rounded-lg bg-white/60">
          <Icon size={24} className={style.text} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <h3 className={`text-lg font-bold ${style.text}`}>
              Market Outlook: {assessment.overall}
            </h3>
            <span className="text-sm text-gray-500">
              {assessment.slots_available} slot{assessment.slots_available !== 1 ? 's' : ''} available
              {assessment.max_new_capital > 0 && ` · $${assessment.max_new_capital.toLocaleString()} deployable`}
            </span>
          </div>
          <p className="text-sm text-gray-600 mb-3">{assessment.recommendation}</p>

          <div className="flex flex-wrap gap-2">
            {assessment.signals?.map((signal, i) => (
              <span key={i} className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${SIGNAL_COLORS[signal[1]] || 'text-gray-600 bg-gray-100'}`}>
                {signal[1] === 'BULLISH' ? '↑' : signal[1] === 'BEARISH' ? '↓' : '⚠'} {signal[0]}
              </span>
            ))}
          </div>

          {assessment.use_spreads && (
            <div className="mt-3 text-sm text-yellow-600 font-medium">
              ⚠ Spreads recommended in current regime. Delta range: {assessment.suggested_delta_range?.[0]} to {assessment.suggested_delta_range?.[1]}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SuggestionCard({ suggestion, index }) {
  const [expanded, setExpanded] = useState(index === 0);
  const s = suggestion;
  const style = STRATEGY_STYLES[s.strategy] || STRATEGY_STYLES.CSP;
  const isSpread = s.strategy === 'PUT_SPREAD' || s.strategy === 'BEAR_CALL_SPREAD';
  const isHedge = s.strategy === 'HEDGE';

  // Build strike display
  const strikeDisplay = isSpread
    ? `$${s.strike}/${s.strike_long}${s.strategy === 'BEAR_CALL_SPREAD' ? 'C' : 'P'}`
    : `$${s.strike}P`;

  // HEDGE cards — risk-level-aware with detailed instructions
  if (isHedge) {
    const riskColors = {
      CRITICAL: { border: 'border-red-500', bg: 'bg-red-50', label: 'bg-red-600 text-white', text: 'text-red-600', icon: '🚨' },
      DANGER: { border: 'border-orange-500', bg: 'bg-orange-50', label: 'bg-orange-500 text-white', text: 'text-orange-600', icon: '⚠️' },
      WARNING: { border: 'border-yellow-400', bg: 'bg-yellow-50', label: 'bg-yellow-500 text-white', text: 'text-yellow-600', icon: '⚡' },
      OK: { border: 'border-green-400', bg: 'bg-green-50', label: 'bg-green-600 text-white', text: 'text-green-600', icon: '✅' },
    };
    const rc = riskColors[s.risk_level] || riskColors.WARNING;

    return (
      <div className={`card border-l-4 ${rc.border} transition-shadow`}>
        <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded(!expanded)}>
          <div className="flex items-center gap-4">
            <div className="text-2xl">{rc.icon}</div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${rc.label}`}>{s.strategy_label}</span>
                <span className="text-lg font-bold text-gray-900">{s.ticker}</span>
                <span className="font-mono text-gray-600">${s.strike}P</span>
                <span className="text-sm text-gray-500">exp {s.expiry}</span>
                <span className="badge badge-blue">{s.dte} DTE</span>
              </div>
              <div className="flex items-center gap-4 mt-1 text-sm">
                <span className="text-gray-500">Stock: ${s.current_price}</span>
                <span className="text-gray-500">Sold: ${s.premium_received}</span>
                <span className="text-gray-500">Now: ${s.premium}</span>
                <span className={`font-bold ${s.unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                  P&L: ${s.unrealized_pnl?.toLocaleString()}
                </span>
                {s.loss_pct > 0 && (
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                    s.loss_pct >= 100 ? 'bg-red-50 text-red-600' :
                    s.loss_pct >= 50 ? 'bg-orange-50 text-orange-600' :
                    'bg-yellow-50 text-yellow-600'
                  }`}>
                    {s.loss_pct}% loss
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-sm text-gray-500">Cushion</p>
              <p className={`text-lg font-bold ${s.breakeven_distance_pct > 10 ? 'text-emerald-600' : s.breakeven_distance_pct > 5 ? 'text-yellow-600' : 'text-red-600'}`}>
                {s.breakeven_distance_pct}%
              </p>
            </div>
            {expanded ? <ChevronUp size={20} className="text-gray-500" /> : <ChevronDown size={20} className="text-gray-500" />}
          </div>
        </div>

        {expanded && s.instructions && (
          <div className={`mt-4 pt-4 border-t border-gray-200`}>
            {/* Position stats */}
            <div className="grid grid-cols-6 gap-3 mb-4">
              <div>
                <p className="label">Premium Sold</p>
                <p className="font-bold">${s.premium_received}</p>
              </div>
              <div>
                <p className="label">Current Value</p>
                <p className="font-bold text-red-600">${s.premium}</p>
              </div>
              <div>
                <p className="label">Unrealized P&L</p>
                <p className={`font-bold ${s.unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                  ${s.unrealized_pnl?.toLocaleString()}
                </p>
              </div>
              <div>
                <p className="label">Breakeven</p>
                <p className="font-bold">${s.breakeven}</p>
              </div>
              <div>
                <p className="label">Bid / Ask</p>
                <p className="font-mono text-sm">${s.bid} / ${s.ask}</p>
              </div>
              <div>
                <p className="label">Contracts</p>
                <p className="font-bold">{s.contracts}</p>
              </div>
            </div>

            {/* Action instructions */}
            <div className={`${rc.bg} rounded-lg p-4`}>
              <p className={`font-bold text-sm mb-2 ${rc.text}`}>
                {s.risk_level === 'CRITICAL' ? '🚨 IMMEDIATE ACTION REQUIRED' :
                 s.risk_level === 'DANGER' ? '⚠️ ACTION RECOMMENDED' :
                 s.risk_level === 'WARNING' ? '⚡ MONITOR & PREPARE' :
                 '✅ POSITION HEALTHY'}
              </p>
              <div className="space-y-1.5">
                {s.instructions.map((line, i) => (
                  <p key={i} className={`text-sm ${rc.text} ${
                    line.startsWith('RECOMMENDED') || line.startsWith('  Roll') ? 'font-medium' : ''
                  } ${line.startsWith('  Roll') ? 'ml-4 font-mono text-xs' : ''}`}>
                    {line.startsWith('RECOMMENDED') ? `📋 ${line}` :
                     line.startsWith('  Roll') ? line :
                     line.startsWith('Option') ? `🔹 ${line}` :
                     `• ${line}`}
                  </p>
                ))}
              </div>
            </div>

            {/* Breakeven bar */}
            <div className="mt-4">
              <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                <span>Breakeven ${s.breakeven}</span>
                <span>Strike ${s.strike}</span>
                <span>Current ${s.current_price}</span>
              </div>
              <div className="h-3 bg-gray-100 rounded-full relative overflow-hidden">
                <div
                  className={`absolute left-0 top-0 h-full rounded-l-full ${
                    s.breakeven_distance_pct > 10 ? 'bg-emerald-400' :
                    s.breakeven_distance_pct > 5 ? 'bg-yellow-400' : 'bg-red-400'
                  }`}
                  style={{ width: `${Math.min(s.breakeven_distance_pct * 5, 100)}%` }}
                />
              </div>
              <p className={`text-xs mt-1 font-medium ${
                s.breakeven_distance_pct > 10 ? 'text-emerald-600' :
                s.breakeven_distance_pct > 5 ? 'text-yellow-600' : 'text-red-600'
              }`}>{s.breakeven_distance_pct}% cushion remaining</p>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`card transition-shadow ${isSpread ? 'border-l-4' : ''} ${
      s.strategy === 'BEAR_CALL_SPREAD' ? 'border-red-400' : s.strategy === 'PUT_SPREAD' ? 'border-emerald-400' : ''
    }`}>
      <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-sm">
            {style.icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${style.color}`}>{style.label}</span>
              <span className="text-lg font-bold text-gray-900">{s.direction} {s.ticker}</span>
              <span className="font-mono text-gray-600">{strikeDisplay}</span>
              <span className="text-sm text-gray-500">exp {s.expiry}</span>
              <span className="badge badge-blue">{s.dte} DTE</span>
            </div>
            <p className="text-sm text-gray-500 mt-0.5">
              Current: ${s.current_price} · Breakeven: ${s.breakeven} ({s.breakeven_distance_pct}% cushion)
              {isSpread && <span className="ml-2 text-gray-500">· Width: ${s.spread_width}</span>}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <p className="text-sm text-gray-500">{isSpread ? 'Net Credit' : 'Premium'}</p>
            <p className="text-lg font-bold text-emerald-600">${s.premium}</p>
          </div>
          <div className="text-right">
            <p className="text-sm text-gray-500">Annualized</p>
            <p className="text-lg font-bold text-blue-600">{s.annualized_return}%</p>
          </div>
          {isSpread && (
            <div className="text-right">
              <p className="text-sm text-gray-500">Risk/Reward</p>
              <p className="text-lg font-bold text-blue-600">{s.risk_reward}x</p>
            </div>
          )}
          <div className="text-right">
            <p className="text-sm text-gray-500">Score</p>
            <p className={`text-lg font-bold ${s.score > 50 ? 'text-emerald-600' : s.score > 30 ? 'text-yellow-600' : 'text-gray-600'}`}>
              {s.score}
            </p>
          </div>
          {expanded ? <ChevronUp size={20} className="text-gray-500" /> : <ChevronDown size={20} className="text-gray-500" />}
        </div>
      </div>

      {s.warning && (
        <div className="mt-2 px-12">
          <p className="text-xs text-yellow-600 bg-yellow-50 rounded px-2 py-1 inline-block">
            {s.warning}
          </p>
        </div>
      )}

      {expanded && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          <div className="grid grid-cols-6 gap-4 mb-4">
            <div>
              <p className="label">Max Profit</p>
              <p className="font-bold text-emerald-600">${s.max_profit?.toLocaleString()}</p>
            </div>
            <div>
              <p className="label">Max Loss</p>
              <p className="font-bold text-red-600">${s.max_loss?.toLocaleString()}</p>
            </div>
            <div>
              <p className="label">Buying Power</p>
              <p className="font-bold">${s.buying_power?.toLocaleString()}</p>
            </div>
            <div>
              <p className="label">Position Size</p>
              <p className={`font-bold ${s.position_pct > 5 ? 'text-red-600' : 'text-gray-900'}`}>{s.position_pct}%</p>
            </div>
            <div>
              <p className="label">IV</p>
              <p className="font-bold">{s.iv}%</p>
            </div>
            <div>
              <p className="label">Est. Delta</p>
              <p className="font-bold">{s.estimated_delta}</p>
            </div>
          </div>

          <div className={`grid ${isSpread ? 'grid-cols-5' : 'grid-cols-4'} gap-4 mb-4`}>
            <div>
              <p className="label">{isSpread ? 'Short Bid / Long Ask' : 'Bid / Ask'}</p>
              <p className="font-mono text-sm">${s.bid} / ${s.ask}</p>
            </div>
            <div>
              <p className="label">Open Interest</p>
              <p className="font-mono text-sm">{s.open_interest?.toLocaleString()}</p>
            </div>
            <div>
              <p className="label">Volume</p>
              <p className="font-mono text-sm">{s.volume?.toLocaleString()}</p>
            </div>
            <div>
              <p className="label">Return on Capital</p>
              <p className="font-mono text-sm">{s.return_on_capital}%</p>
            </div>
            {isSpread && (
              <div>
                <p className="label">Spread Width</p>
                <p className="font-mono text-sm font-bold">${s.spread_width}</p>
              </div>
            )}
          </div>

          {/* Rationale */}
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="label mb-2">Trade Rationale</p>
            <div className="space-y-1">
              {s.rationale?.split(' | ').map((part, i) => (
                <p key={i} className="text-sm text-gray-600">
                  {i === 0 ? <span className="font-semibold text-blue-600">{part}</span> : `• ${part}`}
                </p>
              ))}
            </div>
          </div>

          {/* Visual: safety margin bar */}
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
              <span>Breakeven ${s.breakeven}</span>
              <span>{isSpread ? `Short Strike $${s.strike}` : `Strike $${s.strike}`}</span>
              <span>Current ${s.current_price}</span>
            </div>
            <div className="h-3 bg-gray-100 rounded-full relative overflow-hidden">
              <div
                className={`absolute left-0 top-0 h-full rounded-l-full ${
                  s.strategy === 'BEAR_CALL_SPREAD' ? 'bg-red-300' : 'bg-emerald-400'
                }`}
                style={{ width: `${Math.min(Math.abs(s.breakeven_distance_pct) * 5, 100)}%` }}
              />
              <div
                className="absolute top-0 h-full w-0.5 bg-red-500"
                style={{ left: `${Math.min(
                  s.strategy === 'BEAR_CALL_SPREAD'
                    ? (s.strike / s.current_price - 1) * 500
                    : (1 - s.strike / s.current_price) * 500
                , 95)}%` }}
                title={`Strike $${s.strike}`}
              />
            </div>
            <p className={`text-xs mt-1 font-medium ${s.strategy === 'BEAR_CALL_SPREAD' ? 'text-red-600' : 'text-emerald-600'}`}>
              {s.breakeven_distance_pct}% {s.strategy === 'BEAR_CALL_SPREAD' ? 'upside cushion' : 'safety cushion'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Suggestions() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadSuggestions = () => {
    setLoading(true);
    setError(null);
    fetchSuggestions()
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { loadSuggestions(); }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Zap size={24} className="text-yellow-500" /> Trade Suggestions
          </h1>
          <p className="text-gray-500 text-sm">Real-time market analysis — CSP, spreads, and bearish strategies</p>
        </div>
        <button
          onClick={loadSuggestions}
          disabled={loading}
          className="btn-primary flex items-center gap-2"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          {loading ? 'Scanning...' : 'Refresh Scan'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-600">
          <p className="font-medium">Error loading suggestions</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      )}

      {loading && !data && (
        <div className="flex flex-col items-center justify-center h-64 gap-3">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-400"></div>
          <p className="text-gray-500">Scanning market and analyzing {'>'}30 tickers...</p>
          <p className="text-gray-400 text-sm">This may take 15-30 seconds</p>
        </div>
      )}

      {data && (
        <>
          {/* Market Context */}
          <MarketContext market={data.market} />

          {/* Assessment */}
          <AssessmentPanel assessment={data.assessment} />

          {/* Portfolio state */}
          {data.portfolio && (
            <div className="grid grid-cols-4 gap-3">
              <div className="card text-center">
                <p className="label">Available Capital</p>
                <p className="text-xl font-bold">${data.portfolio.capital_available?.toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
              </div>
              <div className="card text-center">
                <p className="label">Utilization</p>
                <p className="text-xl font-bold">{data.portfolio.utilization_pct}%</p>
              </div>
              <div className="card text-center">
                <p className="label">Open Positions</p>
                <p className="text-xl font-bold">{data.portfolio.open_positions}</p>
              </div>
              <div className="card text-center">
                <p className="label">Already Holding</p>
                <p className="text-sm font-mono mt-1">{data.portfolio.open_tickers?.join(', ') || 'None'}</p>
              </div>
            </div>
          )}

          {/* Reason (if no suggestions) */}
          {data.reason && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-yellow-600">
              <p className="font-medium flex items-center gap-2">
                <Shield size={18} /> No trades recommended
              </p>
              <p className="text-sm mt-1">{data.reason}</p>
            </div>
          )}

          {/* Preferred strategies */}
          {data.assessment?.strategy_note && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 flex items-start gap-3">
              <Target size={18} className="text-blue-600 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-blue-600">{data.assessment.strategy_note}</p>
                {data.assessment.preferred_strategies && (
                  <div className="flex gap-2 mt-1.5">
                    {data.assessment.preferred_strategies.map(st => {
                      const ss = STRATEGY_STYLES[st];
                      return ss ? <span key={st} className={`text-xs px-2 py-0.5 rounded-full font-medium ${ss.color}`}>{ss.icon} {ss.label}</span> : null;
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Suggestions */}
          {data.suggestions?.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900">
                  Top {data.suggestions.length} Opportunities
                </h2>
                <span className="text-sm text-gray-500">
                  Scanned {data.total_scanned} tickers · {data.total_candidates} passed filters
                </span>
              </div>
              <div className="space-y-3">
                {data.suggestions.map((s, i) => (
                  <SuggestionCard key={`${s.ticker}-${s.strike}-${s.strategy}`} suggestion={s} index={i} />
                ))}
              </div>
            </div>
          )}

          {data.suggestions?.length === 0 && !data.reason && (
            <div className="card text-center py-12">
              <p className="text-gray-500 text-lg">No opportunities match your criteria right now</p>
              <p className="text-gray-400 text-sm mt-2">This could mean IV is low, or your portfolio is well-positioned</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
