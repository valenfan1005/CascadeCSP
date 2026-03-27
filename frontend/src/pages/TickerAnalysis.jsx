import React, { useState, useEffect, useCallback, useRef } from 'react';
import { searchTickers, getTickerAnalysis, getTickerEarnings, getTickerPriceHistory, getStockSafety, getStockOptions, getStockDebate, getFlowToxicity } from '../api.js';
import {
  LineChart, Line, BarChart, Bar, ComposedChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell, ReferenceLine, Legend,
} from 'recharts';
import { Search, TrendingUp, DollarSign, BarChart3, Target, ChevronDown } from 'lucide-react';

// ─── Helpers ────────────────────────────────────────────────
const fmt = (n, decimals = 2) => n != null ? Number(n).toFixed(decimals) : '—';
const fmtB = (n) => {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString()}`;
};
const fmtPct = (n) => n != null ? `${(n * 100).toFixed(1)}%` : '—';
const priceColor = (cur, prev) => {
  if (cur == null || prev == null) return 'text-gray-900';
  return cur >= prev ? 'text-emerald-600' : 'text-red-600';
};

// ─── Metric Card ────────────────────────────────────────────
function MetricCard({ label, value, sub, color, glass }) {
  return (
    <div className={glass ? "bg-white/10 rounded-xl p-4 border border-white/20" : "bg-white rounded-xl p-4 border border-gray-200 shadow-sm"}>
      <p className={glass ? "text-white/70 text-xs font-medium uppercase tracking-wide" : "text-gray-500 text-xs font-medium uppercase tracking-wide"}>{label}</p>
      <p className={`text-xl font-bold mt-1 font-mono ${color || (glass ? 'text-white' : 'text-gray-900')}`}>{value}</p>
      {sub && <p className={glass ? "text-white/50 text-xs mt-0.5" : "text-gray-400 text-xs mt-0.5"}>{sub}</p>}
    </div>
  );
}

// ─── Custom Tooltip ─────────────────────────────────────────
function ChartTooltip({ active, payload, label, formatter }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-xl text-xs">
      <p className="text-gray-500 font-medium mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="font-mono text-gray-900 font-semibold">
          <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ backgroundColor: p.color || p.stroke || '#fff' }} />
          {p.name}: {formatter ? formatter(p.value) : p.value?.toLocaleString()}
        </p>
      ))}
    </div>
  );
}

// ─── EPS Bar Chart (like Earnings Hub) ──────────────────────
const EPS_RANGES = [
  { label: '4Y', quarters: 16 },
  { label: '10Y', quarters: 40 },
  { label: 'Max', quarters: 999 },
];

function EPSChart({ data, forecast }) {
  const [range, setRange] = useState(16);
  // Merge history + forecast into one array
  const allData = [...(data || []), ...(forecast || []).map(f => ({
    quarter: f.quarter,
    eps: f.eps_estimate, // use estimate as the bar value for forecasts
    eps_estimate: f.eps_estimate,
    eps_low: f.eps_low,
    eps_high: f.eps_high,
    is_forecast: true,
  }))];

  if (!allData?.length) return <EmptyChart label="No EPS data available" />;

  const sliced = range >= allData.length ? allData : allData.slice(-range);
  const hasEstimates = sliced.some(d => d.eps_estimate != null && !d.is_forecast);
  const allVals = sliced.flatMap(d => [d.eps || 0, d.eps_estimate || 0, d.eps_high || 0]);
  const maxEps = Math.max(...allVals);
  const minEps = Math.min(...allVals);
  const actuals = sliced.filter(d => !d.is_forecast);
  const beats = actuals.filter(d => d.eps != null && d.eps_estimate != null && d.eps >= d.eps_estimate).length;
  const total = actuals.filter(d => d.eps != null && d.eps_estimate != null).length;
  const hasForecast = sliced.some(d => d.is_forecast);

  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-gray-900 font-semibold">EPS History & Forecast</h3>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
          {EPS_RANGES.map(r => (
            <button
              key={r.label}
              onClick={() => setRange(r.quarters)}
              className={`px-2 py-0.5 text-xs font-medium rounded-md transition-colors ${
                range === r.quarters ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {total > 0 && (
        <p className="text-xs text-gray-500 mb-3">
          EPS beat estimates <span className="text-emerald-600 font-semibold">{beats}</span> times in <span className="text-gray-900 font-semibold">{total}</span> quarters
        </p>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={sliced} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <defs>
            <pattern id="forecastStripes" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="#60A5FA" strokeWidth="2" />
            </pattern>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
          <XAxis
            dataKey="quarter"
            tick={{ fill: '#6B7280', fontSize: 10 }}
            axisLine={{ stroke: '#D1D5DB' }}
            interval={sliced.length > 20 ? Math.floor(sliced.length / 10) : 0}
          />
          <YAxis
            tick={{ fill: '#6B7280', fontSize: 11 }}
            axisLine={{ stroke: '#D1D5DB' }}
            tickFormatter={v => `$${v.toFixed(2)}`}
            domain={[Math.min(0, minEps * 1.1), maxEps * 1.2]}
          />
          <Tooltip content={<ChartTooltip formatter={v => v != null ? `$${v.toFixed(2)}` : '—'} />} />
          <ReferenceLine y={0} stroke="#D1D5DB" strokeDasharray="3 3" />
          <Bar dataKey="eps" name="EPS" radius={[3, 3, 0, 0]} maxBarSize={sliced.length > 20 ? 16 : 40}>
            {sliced.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.is_forecast
                  ? 'url(#forecastStripes)'
                  : (entry.eps || 0) >= 0 ? '#10B981' : '#EF4444'
                }
                fillOpacity={entry.is_forecast ? 1 : 0.85}
                stroke={entry.is_forecast ? '#60A5FA' : 'none'}
                strokeWidth={entry.is_forecast ? 1.5 : 0}
                strokeDasharray={entry.is_forecast ? '4 2' : 'none'}
              />
            ))}
          </Bar>
          {hasEstimates && (
            <Line
              type="monotone"
              dataKey="eps_estimate"
              name="Estimate"
              stroke="#F59E0B"
              strokeWidth={2}
              dot={{ r: sliced.length > 20 ? 2 : 4, fill: '#F59E0B' }}
              connectNulls
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex gap-4 mt-2 justify-center text-xs">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-emerald-500 inline-block" /> Actual
        </span>
        {hasEstimates && (
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded bg-amber-500 inline-block" /> Estimate
          </span>
        )}
        {hasForecast && (
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded border-2 border-blue-400 border-dashed inline-block" /> Forecast
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Revenue Chart ──────────────────────────────────────────
function RevenueChart({ data, annualData }) {
  const [view, setView] = useState('quarterly');
  const chartData = view === 'annual' ? (annualData || []) : (data || []);
  if (!chartData?.length) return <EmptyChart label="No revenue data available" />;
  const hasForecast = chartData.some(d => d.is_forecast);

  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-gray-900 font-semibold">Revenue & Net Income</h3>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
          <button
            onClick={() => setView('quarterly')}
            className={`px-2 py-0.5 text-xs font-medium rounded-md transition-colors ${view === 'quarterly' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-900'}`}
          >Quarterly</button>
          <button
            onClick={() => setView('annual')}
            className={`px-2 py-0.5 text-xs font-medium rounded-md transition-colors ${view === 'annual' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-900'}`}
          >Annual</button>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <defs>
            <pattern id="revForecastStripes" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="#60A5FA" strokeWidth="2" />
            </pattern>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
          <XAxis
            dataKey="quarter"
            tick={{ fill: '#6B7280', fontSize: 11 }}
            axisLine={{ stroke: '#D1D5DB' }}
          />
          <YAxis
            tick={{ fill: '#6B7280', fontSize: 11 }}
            axisLine={{ stroke: '#D1D5DB' }}
            tickFormatter={v => fmtB(v)}
          />
          <Tooltip content={<ChartTooltip formatter={v => fmtB(v)} />} />
          <ReferenceLine y={0} stroke="#D1D5DB" strokeDasharray="3 3" />
          <Bar dataKey="revenue" name="Revenue" radius={[4, 4, 0, 0]} maxBarSize={40}>
            {chartData.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.is_forecast ? 'url(#revForecastStripes)' : '#3B82F6'}
                fillOpacity={entry.is_forecast ? 1 : 0.8}
                stroke={entry.is_forecast ? '#60A5FA' : 'none'}
                strokeWidth={entry.is_forecast ? 1.5 : 0}
                strokeDasharray={entry.is_forecast ? '4 2' : 'none'}
              />
            ))}
          </Bar>
          <Line
            type="monotone"
            dataKey="net_income"
            name="Net Income"
            stroke="#10B981"
            strokeWidth={2}
            dot={{ r: 3, fill: '#10B981' }}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex gap-4 mt-2 justify-center text-xs">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-blue-500 inline-block" /> Revenue
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-emerald-500 inline-block" /> Net Income
        </span>
        {hasForecast && (
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded border-2 border-blue-400 border-dashed inline-block" /> Forecast
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Price Chart ────────────────────────────────────────────
const PRICE_PERIODS = [
  { label: '1M', value: '1mo' },
  { label: '3M', value: '3mo' },
  { label: '6M', value: '6mo' },
  { label: '1Y', value: '1y' },
  { label: '2Y', value: '2y' },
  { label: '5Y', value: '5y' },
  { label: 'Max', value: 'max' },
];

function PriceChart({ ticker, priceData, period, setPeriod, loading }) {
  if (!priceData?.length && !loading) return <EmptyChart label="No price data available" />;

  const startPrice = priceData?.[0]?.close;
  const endPrice = priceData?.[priceData.length - 1]?.close;
  const changeAmt = startPrice && endPrice ? endPrice - startPrice : 0;
  const changePct = startPrice ? ((changeAmt / startPrice) * 100) : 0;
  const isUp = changeAmt >= 0;

  // Reduce data points for smoother rendering
  const chartData = priceData && priceData.length > 500
    ? priceData.filter((_, i) => i % Math.ceil(priceData.length / 500) === 0 || i === priceData.length - 1)
    : priceData || [];

  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h3 className="text-gray-900 font-semibold">{ticker} Price Chart</h3>
          {endPrice && (
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-bold text-gray-900 font-mono">${fmt(endPrice)}</span>
              <span className={`text-sm font-mono font-semibold ${isUp ? 'text-emerald-600' : 'text-red-600'}`}>
                {isUp ? '+' : ''}{fmt(changeAmt)} ({isUp ? '+' : ''}{fmt(changePct)}%)
              </span>
            </div>
          )}
        </div>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
          {PRICE_PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                period === p.value
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-[320px] flex items-center justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400" />
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
            <defs>
              <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={isUp ? '#10B981' : '#EF4444'} stopOpacity={0.3} />
                <stop offset="100%" stopColor={isUp ? '#10B981' : '#EF4444'} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
            <XAxis
              dataKey="date"
              tick={{ fill: '#6B7280', fontSize: 10 }}
              axisLine={{ stroke: '#D1D5DB' }}
              tickFormatter={d => {
                const dt = new Date(d);
                return period === '1mo' || period === '3mo'
                  ? dt.toLocaleDateString('en', { month: 'short', day: 'numeric' })
                  : dt.toLocaleDateString('en', { month: 'short', year: '2-digit' });
              }}
              minTickGap={50}
            />
            <YAxis
              tick={{ fill: '#6B7280', fontSize: 11 }}
              axisLine={{ stroke: '#D1D5DB' }}
              tickFormatter={v => `$${v.toLocaleString()}`}
              domain={['auto', 'auto']}
            />
            <Tooltip
              content={<ChartTooltip formatter={v => `$${v?.toFixed(2)}`} />}
            />
            <Line
              type="monotone"
              dataKey="close"
              name="Price"
              stroke={isUp ? '#10B981' : '#EF4444'}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ─── Empty Chart Placeholder ────────────────────────────────
function EmptyChart({ label }) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm h-[360px] flex items-center justify-center">
      <p className="text-gray-400 text-sm">{label}</p>
    </div>
  );
}

// ─── Ticker Search ──────────────────────────────────────────
function TickerSearch({ onSelect }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const doSearch = useCallback((q) => {
    if (!q || q.length < 1) { setResults([]); return; }
    setSearching(true);
    searchTickers(q)
      .then(r => { setResults(r || []); setShowDropdown(true); })
      .catch(() => setResults([]))
      .finally(() => setSearching(false));
  }, []);

  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 300);
  };

  const handleSelect = (ticker) => {
    setQuery(ticker.ticker);
    setShowDropdown(false);
    onSelect(ticker.ticker);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      setShowDropdown(false);
      if (query.trim()) onSelect(query.trim().toUpperCase());
    }
  };

  return (
    <div ref={wrapperRef} className="relative w-full max-w-md">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
        <input
          type="text"
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length && setShowDropdown(true)}
          placeholder="Search ticker (e.g. NVDA, TSLA, AAPL)..."
          className="w-full bg-white border border-gray-300 rounded-xl pl-10 pr-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
        />
        {searching && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-400" />
          </div>
        )}
      </div>

      {showDropdown && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-2xl max-h-64 overflow-y-auto">
          {results.map((r, i) => (
            <button
              key={i}
              onClick={() => handleSelect(r)}
              className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 transition-colors text-left"
            >
              <span className="text-blue-600 font-bold text-sm min-w-[60px]">{r.ticker}</span>
              <span className="text-gray-600 text-sm truncate">{r.name}</span>
              <span className="text-gray-400 text-xs ml-auto">{r.type}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Quick Ticker Chips (recently viewed / popular) ─────────
const POPULAR_TICKERS = ['NVDA', 'TSLA', 'AAPL', 'MSFT', 'SPY', 'QQQ', 'AMD', 'AMZN', 'GOOG', 'META'];

function QuickChips({ onSelect, activeTicker }) {
  return (
    <div className="flex flex-wrap gap-2">
      {POPULAR_TICKERS.map(t => (
        <button
          key={t}
          onClick={() => onSelect(t)}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
            activeTicker === t
              ? 'bg-blue-600 text-white'
              : 'bg-white text-gray-500 hover:bg-gray-50 hover:text-gray-900 border border-gray-200'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────
export default function TickerAnalysis() {
  const [ticker, setTicker] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [earnings, setEarnings] = useState(null);
  const [priceData, setPriceData] = useState([]);
  const [pricePeriod, setPricePeriod] = useState('5y');
  const [loading, setLoading] = useState(false);
  const [priceLoading, setPriceLoading] = useState(false);
  const [error, setError] = useState(null);
  const [safetyData, setSafetyData] = useState(null);
  const [safetyLoading, setSafetyLoading] = useState(false);
  const [optionsData, setOptionsData] = useState(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [debateData, setDebateData] = useState(null);
  const [debateLoading, setDebateLoading] = useState(false);
  const [toxicityData, setToxicityData] = useState(null);
  const [toxicityLoading, setToxicityLoading] = useState(false);

  // Load all data for a ticker
  const loadTicker = useCallback((t) => {
    if (!t) return;
    const sym = t.toUpperCase();
    setTicker(sym);
    setLoading(true);
    setError(null);
    setSafetyData(null);
    setOptionsData(null);

    Promise.all([
      getTickerAnalysis(sym).catch(e => ({ success: false, error: e.message })),
      getTickerEarnings(sym).catch(e => ({ success: false, error: e.message })),
      getTickerPriceHistory(sym, pricePeriod).catch(e => ({ success: false, error: e.message })),
    ]).then(([analysis, earn, price]) => {
      if (!analysis?.success && !analysis?.metrics) {
        setError(`Could not load data for ${sym}`);
        setMetrics(null);
        setEarnings(null);
        setPriceData([]);
      } else {
        setMetrics(analysis.metrics || null);
        setEarnings(earn || null);
        setPriceData(price?.prices || []);
        setError(null);
      }
      setLoading(false);
    });
  }, [pricePeriod]);

  // Reload price data when period changes
  useEffect(() => {
    if (!ticker) return;
    setPriceLoading(true);
    getTickerPriceHistory(ticker, pricePeriod)
      .then(r => setPriceData(r?.prices || []))
      .catch(() => {})
      .finally(() => setPriceLoading(false));
  }, [pricePeriod, ticker]);

  const m = metrics || {};

  // Build EPS chart data — prefer long eps_history (with estimates + actuals)
  const epsChartData = (earnings?.eps_history || []).map(e => ({
    quarter: e.quarter || e.date?.slice(0, 7),
    eps: e.eps_actual,
    eps_estimate: e.eps_estimate,
    surprise_pct: e.surprise_pct,
  }));

  // EPS forecast data
  const epsForecastData = (earnings?.eps_forecast || []);

  // Revenue: quarterly (short) + annual (longer) — include forecast flags
  const revenueChartData = (earnings?.revenue_quarterly || []).map(q => ({
    quarter: q.quarter,
    revenue: q.revenue,
    net_income: q.net_income,
    is_forecast: q.is_forecast || false,
  }));

  const revenueAnnualData = (earnings?.revenue_annual || [])
    .filter(r => r.revenue != null)
    .map(r => ({
      quarter: r.year,
      revenue: r.revenue,
      net_income: r.net_income,
      is_forecast: r.is_forecast || false,
    }));

  // Analyst forward estimates
  const earningsForecast = earnings?.earnings_forecast || [];
  const revenueForecast = earnings?.revenue_forecast || [];
  const growthEstimates = earnings?.growth_estimates || {};

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Ticker Analysis</h1>
        <p className="text-gray-500 text-sm mt-1">Fundamentals, earnings, and price charts</p>
      </div>

      {/* Search + Quick Chips */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 space-y-4">
        <TickerSearch onSelect={loadTicker} />
        <QuickChips onSelect={loadTicker} activeTicker={ticker} />
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500" />
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-600 text-sm">{error}</div>
      )}

      {/* Ticker Data */}
      {metrics && !loading && (
        <div className="space-y-6">
          {/* Ticker Header */}
          <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-xl p-6 text-white">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-3xl font-bold">{m.ticker}</h2>
                  {m.sector && (
                    <span className="bg-white/20 text-white text-xs font-medium px-2.5 py-1 rounded-full">{m.sector}</span>
                  )}
                </div>
                <p className="text-blue-100 text-sm mt-1">{m.name}</p>
                {m.industry && <p className="text-blue-200 text-xs mt-0.5">{m.industry}</p>}
              </div>
              <div className="text-right">
                <p className="text-3xl font-bold font-mono text-white">
                  ${fmt(m.current_price)}
                </p>
                {m.previous_close && m.current_price && (
                  <p className={`text-sm font-mono ${m.current_price >= m.previous_close ? 'text-emerald-300' : 'text-red-300'}`}>
                    {m.current_price >= m.previous_close ? '+' : ''}
                    {fmt(m.current_price - m.previous_close)} ({fmt(((m.current_price - m.previous_close) / m.previous_close) * 100)}%)
                  </p>
                )}
                {m.market_cap && <p className="text-blue-200 text-xs mt-1">Mkt Cap {fmtB(m.market_cap)}</p>}
              </div>
            </div>

            {/* Key Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 mt-5">
              <MetricCard glass label="P/E (TTM)" value={fmt(m.pe_ttm, 1)} color={m.pe_ttm > 40 ? 'text-amber-400' : 'text-emerald-400'} />
              <MetricCard glass label="P/E (Dynamic)" value={fmt(m.pe_dynamic ?? m.pe_forward, 1)} sub="动态市盈率" color={(m.pe_dynamic ?? m.pe_forward) && m.pe_ttm && (m.pe_dynamic ?? m.pe_forward) < m.pe_ttm ? 'text-emerald-400' : 'text-white'} />
              <MetricCard glass label="EPS (TTM)" value={m.eps_ttm != null ? `$${fmt(m.eps_ttm)}` : '—'} />
              <MetricCard glass label="EPS (FY Est)" value={m.eps_current_year != null ? `$${fmt(m.eps_current_year)}` : m.eps_forward != null ? `$${fmt(m.eps_forward)}` : '—'} />
              <MetricCard glass label="Rev Growth" value={fmtPct(m.revenue_growth)} color={m.revenue_growth > 0 ? 'text-emerald-400' : 'text-red-400'} />
              <MetricCard glass label="P/S Ratio" value={fmt(m.ps_ratio, 1)} />
            </div>

            {/* Secondary Metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 mt-3">
              <MetricCard glass label="Revenue (TTM)" value={fmtB(m.revenue_ttm)} />
              <MetricCard glass label="Profit Margin" value={fmtPct(m.profit_margin)} color={m.profit_margin > 0 ? 'text-emerald-400' : 'text-red-400'} />
              <MetricCard glass label="Gross Margin" value={fmtPct(m.gross_margin)} />
              <MetricCard glass label="Dividend Yield" value={m.dividend_yield != null ? fmtPct(m.dividend_yield) : '—'} />
              <MetricCard glass label="52W High" value={m.fifty_two_week_high != null ? `$${fmt(m.fifty_two_week_high)}` : '—'} />
              <MetricCard glass label="52W Low" value={m.fifty_two_week_low != null ? `$${fmt(m.fifty_two_week_low)}` : '—'} />
            </div>

            {/* Analyst Targets */}
            {m.target_mean && (
              <div className="mt-4 bg-white/10 rounded-lg p-3 flex items-center gap-6 text-sm">
                <div className="flex items-center gap-2">
                  <Target size={16} className="text-blue-200" />
                  <span className="text-blue-100">Analyst Target:</span>
                </div>
                <span className="font-mono text-white font-bold">${fmt(m.target_mean)}</span>
                <span className="text-blue-200 text-xs">
                  (Low ${fmt(m.target_low)} — High ${fmt(m.target_high)})
                </span>
                {m.recommendation && (
                  <span className={`ml-auto text-xs font-semibold px-2 py-0.5 rounded ${
                    m.recommendation === 'buy' || m.recommendation === 'strong_buy'
                      ? 'bg-emerald-500/30 text-emerald-200'
                      : m.recommendation === 'sell' || m.recommendation === 'strong_sell'
                        ? 'bg-red-500/30 text-red-200'
                        : 'bg-white/20 text-white/80'
                  }`}>
                    {m.recommendation?.replace(/_/g, ' ').toUpperCase()}
                  </span>
                )}
                {m.num_analysts && (
                  <span className="text-blue-200 text-xs">({m.num_analysts} analysts)</span>
                )}
              </div>
            )}
          </div>

          {/* Price Chart */}
          <PriceChart
            ticker={ticker}
            priceData={priceData}
            period={pricePeriod}
            setPeriod={setPricePeriod}
            loading={priceLoading}
          />

          {/* EPS + Revenue side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <EPSChart data={epsChartData} forecast={epsForecastData} />
            <RevenueChart data={revenueChartData} annualData={revenueAnnualData} />
          </div>

          {/* Analyst Forecast Summary */}
          {(earningsForecast.length > 0 || revenueForecast.length > 0) && (
            <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
              <h3 className="text-gray-900 font-semibold mb-4">Analyst Forecasts</h3>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* EPS Forecast Table */}
                {earningsForecast.length > 0 && (
                  <div>
                    <h4 className="text-gray-500 text-xs font-medium uppercase tracking-wide mb-2">EPS Estimates</h4>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-gray-500 text-xs border-b border-gray-200">
                          <th className="text-left py-1.5 px-2">Period</th>
                          <th className="text-right py-1.5 px-2">Avg</th>
                          <th className="text-right py-1.5 px-2">Low</th>
                          <th className="text-right py-1.5 px-2">High</th>
                          <th className="text-right py-1.5 px-2">YoY Growth</th>
                          <th className="text-right py-1.5 px-2">Analysts</th>
                        </tr>
                      </thead>
                      <tbody>
                        {earningsForecast.map((e, i) => (
                          <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                            <td className="py-1.5 px-2 text-gray-600 font-medium">
                              {e.period === '0q' ? 'Current Q' : e.period === '+1q' ? 'Next Q' : e.period === '0y' ? 'Current Y' : 'Next Y'}
                            </td>
                            <td className="py-1.5 px-2 text-right font-mono text-gray-900 font-semibold">${fmt(e.eps_avg)}</td>
                            <td className="py-1.5 px-2 text-right font-mono text-gray-500">${fmt(e.eps_low)}</td>
                            <td className="py-1.5 px-2 text-right font-mono text-gray-500">${fmt(e.eps_high)}</td>
                            <td className={`py-1.5 px-2 text-right font-mono font-semibold ${e.growth > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                              {e.growth != null ? `${e.growth > 0 ? '+' : ''}${(e.growth * 100).toFixed(1)}%` : '—'}
                            </td>
                            <td className="py-1.5 px-2 text-right text-gray-400">{e.num_analysts || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Revenue Forecast Table */}
                {revenueForecast.length > 0 && (
                  <div>
                    <h4 className="text-gray-500 text-xs font-medium uppercase tracking-wide mb-2">Revenue Estimates</h4>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-gray-500 text-xs border-b border-gray-200">
                          <th className="text-left py-1.5 px-2">Period</th>
                          <th className="text-right py-1.5 px-2">Avg</th>
                          <th className="text-right py-1.5 px-2">Low</th>
                          <th className="text-right py-1.5 px-2">High</th>
                          <th className="text-right py-1.5 px-2">YoY Growth</th>
                          <th className="text-right py-1.5 px-2">Analysts</th>
                        </tr>
                      </thead>
                      <tbody>
                        {revenueForecast.map((r, i) => (
                          <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                            <td className="py-1.5 px-2 text-gray-600 font-medium">
                              {r.period === '0q' ? 'Current Q' : r.period === '+1q' ? 'Next Q' : r.period === '0y' ? 'Current Y' : 'Next Y'}
                            </td>
                            <td className="py-1.5 px-2 text-right font-mono text-gray-900 font-semibold">{fmtB(r.revenue_avg)}</td>
                            <td className="py-1.5 px-2 text-right font-mono text-gray-500">{fmtB(r.revenue_low)}</td>
                            <td className="py-1.5 px-2 text-right font-mono text-gray-500">{fmtB(r.revenue_high)}</td>
                            <td className={`py-1.5 px-2 text-right font-mono font-semibold ${r.growth > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                              {r.growth != null ? `${r.growth > 0 ? '+' : ''}${(r.growth * 100).toFixed(1)}%` : '—'}
                            </td>
                            <td className="py-1.5 px-2 text-right text-gray-400">{r.num_analysts || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Growth Estimates */}
              {Object.keys(growthEstimates).length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-200">
                  <h4 className="text-gray-500 text-xs font-medium uppercase tracking-wide mb-2">Growth Estimates (EPS)</h4>
                  <div className="flex gap-4 flex-wrap">
                    {Object.entries(growthEstimates).map(([period, vals]) => (
                      <div key={period} className="bg-gray-50 rounded-lg px-3 py-2 text-center min-w-[80px]">
                        <p className="text-gray-500 text-xs">
                          {period === '0q' ? 'This Q' : period === '+1q' ? 'Next Q' : period === '0y' ? 'This Y' : period === '+1y' ? 'Next Y' : period}
                        </p>
                        <p className={`font-mono font-bold text-sm ${vals.stock > 0 ? 'text-emerald-600' : vals.stock != null ? 'text-red-600' : 'text-gray-400'}`}>
                          {vals.stock != null ? `${vals.stock > 0 ? '+' : ''}${(vals.stock * 100).toFixed(1)}%` : '—'}
                        </p>
                        <p className="text-gray-400 text-[10px]">vs S&P {vals.index != null ? `${(vals.index * 100).toFixed(1)}%` : ''}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Earnings History — hidden, data used by AI analysis */}
          {/* ─── AI Safety Analysis ─── */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-gray-900 font-semibold flex items-center gap-2">
                🛡️ AI 30天安全评估
              </h3>
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={() => {
                    setOptionsLoading(true);
                    setOptionsData(null);
                    getStockOptions(ticker)
                      .then(r => setOptionsData(r))
                      .catch(e => setOptionsData({ error: e.message }))
                      .finally(() => setOptionsLoading(false));
                  }}
                  disabled={optionsLoading}
                  className="bg-indigo-50 text-indigo-600 px-4 py-1.5 rounded-lg text-sm font-medium border border-indigo-200 hover:bg-indigo-100 transition-colors disabled:opacity-50"
                >
                  {optionsLoading ? '获取期权数据中...' : optionsData ? '🔄 刷新期权分析' : '📊 期权分析 (Moomoo)'}
                </button>
                <button
                  onClick={() => {
                    setToxicityLoading(true);
                    setToxicityData(null);
                    getFlowToxicity(ticker, 0, '')
                      .then(r => setToxicityData(r))
                      .catch(e => setToxicityData({ error: e.message }))
                      .finally(() => setToxicityLoading(false));
                  }}
                  disabled={toxicityLoading}
                  className="bg-gray-700 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors disabled:opacity-50"
                >
                  {toxicityLoading ? '🔬 检测中...' : toxicityData ? '🔬 重新检测' : '🔬 Flow Toxicity'}
                </button>
                <button
                  onClick={() => {
                    setSafetyLoading(true);
                    setSafetyData(null);
                    getStockSafety(ticker)
                      .then(r => setSafetyData(r))
                      .catch(e => setSafetyData({ error: e.message }))
                      .finally(() => setSafetyLoading(false));
                  }}
                  disabled={safetyLoading || debateLoading}
                  className="bg-indigo-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
                >
                  {safetyLoading ? '分析中...' : safetyData ? '🔄 重新分析' : '🧠 运行AI分析'}
                </button>
                <button
                  onClick={() => {
                    setDebateLoading(true);
                    setDebateData(null);
                    getStockDebate(ticker)
                      .then(r => setDebateData(r))
                      .catch(e => setDebateData({ error: e.message }))
                      .finally(() => setDebateLoading(false));
                  }}
                  disabled={debateLoading || safetyLoading}
                  className="bg-gradient-to-r from-purple-600 to-amber-500 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:opacity-90 transition-all disabled:opacity-50"
                >
                  {debateLoading ? '⚔️ Debate中...' : debateData ? '⚔️ 重新Debate' : '⚔️ AI Debate'}
                </button>
              </div>
            </div>

            {/* ─── Flow Toxicity Results ─── */}
            {toxicityLoading && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-400">
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-gray-400" />
                分析期权链流动性和信息流...
              </div>
            )}

            {toxicityData && !toxicityData.error && (() => {
              const t = toxicityData;
              const labelColor = { CLEAN: 'bg-emerald-100 text-emerald-700 border-emerald-300', CAUTION: 'bg-yellow-100 text-yellow-700 border-yellow-300', TOXIC: 'bg-red-100 text-red-700 border-red-300', HIGHLY_TOXIC: 'bg-red-200 text-red-800 border-red-400' }[t.label] || 'bg-gray-100 text-gray-700';
              const barColor = { CLEAN: 'bg-emerald-500', CAUTION: 'bg-yellow-500', TOXIC: 'bg-red-500', HIGHLY_TOXIC: 'bg-red-700' }[t.label] || 'bg-gray-500';
              const confColor = { HIGH: 'text-red-600', MEDIUM: 'text-yellow-600', LOW: 'text-gray-500' }[t.confidence] || 'text-gray-500';
              return (
                <div className="mt-3 bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-gray-700">🔬 Flow Toxicity</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${labelColor}`}>{t.label}</span>
                      <span className={`text-[10px] font-semibold ${confColor}`}>Conf: {t.confidence}</span>
                    </div>
                    <span className="text-[10px] text-gray-400">Strike ${t.strike} | {t.regime}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500 w-16">Composite</span>
                    <div className="flex-1 bg-gray-200 rounded-full h-2.5">
                      <div className={`h-2.5 rounded-full ${barColor} transition-all`} style={{width: `${Math.min(t.composite * 100, 100)}%`}} />
                    </div>
                    <span className="text-xs font-bold text-gray-700 w-10 text-right">{(t.composite * 100).toFixed(0)}%</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-white rounded p-2 border border-gray-100">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-gray-400 font-semibold">IV 局部扭曲</span>
                        <span className={`text-[10px] font-bold ${t.ivld >= 0.4 ? 'text-red-600' : t.ivld >= 0.15 ? 'text-yellow-600' : 'text-emerald-600'}`}>{t.ivld_label}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                          <div className={`h-1.5 rounded-full ${t.ivld >= 0.4 ? 'bg-red-400' : t.ivld >= 0.15 ? 'bg-yellow-400' : 'bg-emerald-400'}`} style={{width: `${Math.min(t.ivld * 100, 100)}%`}} />
                        </div>
                        <span className="text-[10px] font-mono text-gray-600">{t.ivld.toFixed(2)}</span>
                      </div>
                      {t.details && <p className="text-[9px] text-gray-400 mt-1">IV {t.details.iv_excess_pp > 0 ? '+' : ''}{t.details.iv_excess_pp}pp vs 邻近均值</p>}
                    </div>
                    <div className="bg-white rounded p-2 border border-gray-100">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-gray-400 font-semibold">Put/Call 集中度</span>
                        <span className={`text-[10px] font-bold ${t.pccr >= 0.5 ? 'text-red-600' : t.pccr >= 0.2 ? 'text-yellow-600' : 'text-emerald-600'}`}>{t.pccr_label}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                          <div className={`h-1.5 rounded-full ${t.pccr >= 0.5 ? 'bg-red-400' : t.pccr >= 0.2 ? 'bg-yellow-400' : 'bg-emerald-400'}`} style={{width: `${Math.min(t.pccr * 100, 100)}%`}} />
                        </div>
                        <span className="text-[10px] font-mono text-gray-600">{t.pccr.toFixed(2)}</span>
                      </div>
                      {t.details && <p className="text-[9px] text-gray-400 mt-1">P/C {t.details.zone_pcr}x vs 市场{t.details.market_pcr}x</p>}
                    </div>
                  </div>
                  {t.label !== 'CLEAN' && (
                    <div className={`text-xs rounded p-2 ${t.label === 'CAUTION' ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                      {t.label === 'CAUTION' && `⚠️ 建议减少仓位至 ${((t.position_multiplier || 0.5) * 100).toFixed(0)}%，premium可能含部分信息流`}
                      {t.label === 'TOXIC' && '🚫 建议跳过该行权价，多个信号指向信息流。寻找其他行权价或标的'}
                      {t.label === 'HIGHLY_TOXIC' && '🚫 强烈建议不要在该行权价卖出premium，高确信度信息流检测'}
                    </div>
                  )}
                  {t.label === 'CLEAN' && (
                    <p className="text-xs text-emerald-600">✅ 该行权价premium看起来是genuine fear premium，可正常卖出</p>
                  )}
                </div>
              );
            })()}

            {toxicityData?.error && (
              <p className="text-xs text-red-500 mt-2">Flow Toxicity 检测失败: {toxicityData.error}</p>
            )}

            {/* ─── Options Analysis Results (Moomoo) ─── */}
            {optionsLoading && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-400">
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-indigo-400" />
                正在从 Moomoo 获取实时期权链...
              </div>
            )}

            {optionsData && !optionsData.error && optionsData.ai_analysis && !optionsData.ai_analysis.error && (() => {
              const oai = optionsData.ai_analysis;
              const recColor = { 'STRONG_SELL': 'bg-emerald-500', 'SELL': 'bg-blue-500', 'HOLD': 'bg-yellow-500', 'AVOID': 'bg-red-500' }[oai.recommendation] || 'bg-gray-500';
              return (
                <div className="mt-3 bg-indigo-50/50 rounded-lg border border-indigo-200/50 p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-indigo-400 font-semibold">📊 期权AI分析</span>
                    <span className="text-[10px] text-gray-400">{optionsData.expiry} DTE={optionsData.dte} {optionsData.atm_iv ? `ATM IV=${(optionsData.atm_iv*100).toFixed(1)}%` : ''}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className={`${recColor} text-white text-xs font-bold px-2 py-0.5 rounded-full`}>{oai.recommendation}</span>
                    <p className="text-sm text-gray-700">{oai.summary}</p>
                  </div>
                  {oai.best_strike && (
                    <div className="bg-white rounded-lg p-3 border border-indigo-100 grid grid-cols-3 gap-3 text-xs">
                      <div><span className="text-gray-400 text-[10px]">推荐行权价</span><p className="font-bold text-indigo-700">${oai.best_strike}</p></div>
                      <div><span className="text-gray-400 text-[10px]">预期收入/手</span><p className="font-bold text-emerald-600">${oai.expected_income || (oai.best_premium * 100)?.toFixed(0)}</p></div>
                      <div><span className="text-gray-400 text-[10px]">IV评估</span><p className="font-bold text-gray-700 text-[10px]">{oai.iv_assessment}</p></div>
                    </div>
                  )}
                  {oai.action_plan && <p className="text-xs text-gray-700">📋 {oai.action_plan}</p>}
                  {oai.exit_strategy && <p className="text-xs text-gray-500">🎯 {oai.exit_strategy}</p>}
                  {oai.max_risk && <p className="text-xs text-red-500">⚠️ {oai.max_risk}</p>}
                  {(optionsData.candidates || []).length > 0 && (
                    <details>
                      <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">查看全部期权链 ({optionsData.candidates.length}个候选)</summary>
                      <div className="mt-1 space-y-1">
                        {optionsData.candidates.map((c, ci) => (
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

            {optionsData?.error && (
              <p className="text-xs text-red-500 mt-2">期权数据获取失败: {optionsData.error}</p>
            )}

            {safetyLoading && (
              <div className="flex items-center justify-center h-32">
                <div className="text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500 mx-auto mb-2" />
                  <p className="text-sm text-gray-400">AI正在分析 {ticker} 的基本面、技术面、新闻、机构持仓...</p>
                </div>
              </div>
            )}

            {safetyData && !safetyData.error && safetyData.ai_analysis && !safetyData.ai_analysis.error && (() => {
              const ai = safetyData.ai_analysis;
              const score = ai.safety_score ?? 50;
              const scoreColor = score >= 70 ? 'text-emerald-600 border-emerald-400' : score >= 50 ? 'text-blue-600 border-blue-400' : score >= 30 ? 'text-yellow-600 border-yellow-400' : 'text-red-600 border-red-400';
              const scoreBg = score >= 70 ? 'bg-emerald-50' : score >= 50 ? 'bg-blue-50' : score >= 30 ? 'bg-yellow-50' : 'bg-red-50';
              return (
                <div className="space-y-4">
                  {/* Score + Summary */}
                  <div className="flex items-start gap-4">
                    <div className={`w-16 h-16 rounded-full border-[3px] flex items-center justify-center font-bold text-xl flex-shrink-0 ${scoreColor}`}>
                      {score}
                    </div>
                    <div className="flex-1">
                      <p className="text-sm text-gray-700 leading-relaxed">{ai.summary}</p>
                    </div>
                  </div>

                  {/* Key Levels */}
                  {ai.key_levels && (
                    <div className={`${scoreBg} rounded-lg p-3 grid grid-cols-3 gap-4`}>
                      <div className="text-center">
                        <p className="text-[10px] text-gray-400 uppercase">强支撑</p>
                        <p className="font-bold text-emerald-700">${ai.key_levels.strong_support}</p>
                      </div>
                      <div className="text-center">
                        <p className="text-[10px] text-gray-400 uppercase">弱支撑</p>
                        <p className="font-bold text-yellow-700">${ai.key_levels.weak_support}</p>
                      </div>
                      <div className="text-center">
                        <p className="text-[10px] text-gray-400 uppercase">阻力位</p>
                        <p className="font-bold text-red-700">${ai.key_levels.resistance}</p>
                      </div>
                    </div>
                  )}

                  {/* Bull vs Bear */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-emerald-50 rounded-lg border border-emerald-200 p-3">
                      <p className="text-[10px] text-emerald-500 font-semibold mb-1">🟢 看多理由</p>
                      <p className="text-xs text-emerald-700">{ai.bull_case}</p>
                    </div>
                    <div className="bg-red-50 rounded-lg border border-red-200 p-3">
                      <p className="text-[10px] text-red-500 font-semibold mb-1">🔴 看空风险</p>
                      <p className="text-xs text-red-700">{ai.bear_case}</p>
                    </div>
                  </div>

                  {/* Max loss estimate */}
                  {ai.max_loss_estimate && (
                    <p className="text-xs text-gray-500 bg-gray-50 rounded-lg p-2">⚠️ 最大跌幅预估: {ai.max_loss_estimate}</p>
                  )}

                  {/* Risks + Catalysts */}
                  <div className="grid grid-cols-2 gap-3">
                    {ai.risks?.length > 0 && (
                      <div>
                        <p className="text-[10px] text-gray-400 font-semibold mb-1">风险因素</p>
                        <div className="flex flex-wrap gap-1">
                          {ai.risks.map((r, i) => (
                            <span key={i} className="text-[10px] bg-red-50 text-red-600 px-2 py-0.5 rounded-full border border-red-200">{r}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {ai.catalysts?.length > 0 && (
                      <div>
                        <p className="text-[10px] text-gray-400 font-semibold mb-1">正面催化剂</p>
                        <div className="flex flex-wrap gap-1">
                          {ai.catalysts.map((c, i) => (
                            <span key={i} className="text-[10px] bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-full border border-emerald-200">{c}</span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Data Sources */}
                  <div className="border-t border-gray-100 pt-3 grid grid-cols-3 gap-3 text-[10px]">
                    {safetyData.sentiment?.aggregate && (
                      <div>
                        <span className="text-gray-400">新闻情绪:</span>
                        <span className={`ml-1 font-semibold ${safetyData.sentiment.aggregate.avg_score > 0.1 ? 'text-emerald-600' : safetyData.sentiment.aggregate.avg_score < -0.1 ? 'text-red-600' : 'text-gray-600'}`}>
                          {safetyData.sentiment.aggregate.sentiment} ({safetyData.sentiment.aggregate.avg_score > 0 ? '+' : ''}{safetyData.sentiment.aggregate.avg_score?.toFixed(3)})
                        </span>
                      </div>
                    )}
                    {safetyData.institutional && (
                      <div>
                        <span className="text-gray-400">机构动向:</span>
                        <span className={`ml-1 font-semibold ${safetyData.institutional.net_signal === '增持' ? 'text-emerald-600' : safetyData.institutional.net_signal === '减持' ? 'text-red-600' : 'text-gray-600'}`}>
                          {safetyData.institutional.net_signal} ({safetyData.institutional.buying_count}↑ {safetyData.institutional.selling_count}↓)
                        </span>
                      </div>
                    )}
                    {safetyData.insider && (
                      <div>
                        <span className="text-gray-400">内部人:</span>
                        <span className={`ml-1 font-semibold ${safetyData.insider.net_signal === '内部人买入' ? 'text-emerald-600' : safetyData.insider.net_signal === '内部人抛售' ? 'text-red-600' : 'text-gray-600'}`}>
                          {safetyData.insider.net_signal}
                        </span>
                      </div>
                    )}
                  </div>

                </div>
              );
            })()}

            {safetyData?.error && (
              <p className="text-sm text-red-500">分析失败: {safetyData.error}</p>
            )}
            {safetyData?.ai_analysis?.error && (
              <p className="text-sm text-red-500">AI分析失败: {safetyData.ai_analysis.error}</p>
            )}

            {!safetyData && !safetyLoading && !debateLoading && !debateData && (
              <p className="text-xs text-gray-400 text-center py-4">点击"运行AI分析"获取快速评估，或"AI Debate"获取多空对抗深度分析</p>
            )}

            {/* ─── Debate Loading ─── */}
            {debateLoading && (
              <div className="flex items-center justify-center h-40 mt-4">
                <div className="text-center">
                  <div className="flex gap-2 justify-center mb-3">
                    <div className="animate-bounce delay-0 w-3 h-3 rounded-full bg-blue-500" />
                    <div className="animate-bounce delay-150 w-3 h-3 rounded-full bg-amber-500" style={{animationDelay:'0.15s'}} />
                    <div className="animate-bounce delay-300 w-3 h-3 rounded-full bg-purple-500" style={{animationDelay:'0.3s'}} />
                  </div>
                  <p className="text-sm text-gray-500">⚔️ AI Debate 进行中...</p>
                  <p className="text-xs text-gray-400 mt-1">分析师评估 → 质疑者反驳 → 首席投资官裁决 (约25秒)</p>
                </div>
              </div>
            )}

            {/* ─── Debate Results ─── */}
            {debateData && !debateData.error && debateData.debate && (() => {
              const { analyst, devil_advocate, arbiter } = debateData.debate;
              const scoreColor = (s) => s >= 70 ? 'text-emerald-600' : s >= 50 ? 'text-blue-600' : s >= 30 ? 'text-yellow-600' : 'text-red-600';
              const scoreBorder = (s) => s >= 70 ? 'border-emerald-400' : s >= 50 ? 'border-blue-400' : s >= 30 ? 'border-yellow-400' : 'border-red-400';
              return (
                <div className="mt-4 space-y-3">
                  {/* ── Phase 1: Analyst ── */}
                  {analyst && (
                    <div className="border-l-4 border-blue-400 bg-blue-50/50 rounded-r-lg p-4">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-semibold text-blue-800 text-sm flex items-center gap-1.5">📊 分析师观点</h4>
                        <div className={`w-10 h-10 rounded-full border-2 ${scoreBorder(analyst.safety_score)} flex items-center justify-center font-bold text-sm ${scoreColor(analyst.safety_score)}`}>
                          {analyst.safety_score}
                        </div>
                      </div>
                      <p className="text-xs text-gray-700 leading-relaxed mb-2">{analyst.summary}</p>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="bg-emerald-50 rounded p-2 border border-emerald-200">
                          <p className="text-[10px] text-emerald-500 font-semibold">🟢 看多</p>
                          <p className="text-xs text-emerald-700 mt-0.5">{analyst.bull_case}</p>
                        </div>
                        <div className="bg-red-50 rounded p-2 border border-red-200">
                          <p className="text-[10px] text-red-500 font-semibold">🔴 看空</p>
                          <p className="text-xs text-red-700 mt-0.5">{analyst.bear_case}</p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ── Phase 2: Devil's Advocate ── */}
                  {devil_advocate && (
                    <div className="border-l-4 border-amber-400 bg-amber-50/50 rounded-r-lg p-4">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-semibold text-amber-800 text-sm flex items-center gap-1.5">
                          😈 质疑者反驳
                          {devil_advocate.bias_direction && (
                            <span className={`text-[10px] px-2 py-0.5 rounded-full font-normal ${
                              devil_advocate.bias_direction?.includes('看多') ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                            }`}>
                              {devil_advocate.bias_direction?.includes('看多') ? '↑ 反向看多' : '↓ 反向看空'}
                            </span>
                          )}
                        </h4>
                        <div className={`w-10 h-10 rounded-full border-2 ${scoreBorder(devil_advocate.challenge_score)} flex items-center justify-center font-bold text-sm ${scoreColor(devil_advocate.challenge_score)}`}>
                          {devil_advocate.challenge_score}
                        </div>
                      </div>
                      <p className="text-xs text-gray-700 leading-relaxed mb-2">{devil_advocate.counter_arguments}</p>
                      {(devil_advocate.overlooked_factors || devil_advocate.overlooked_risks)?.length > 0 && (
                        <div className="mb-2">
                          <p className="text-[10px] text-amber-600 font-semibold mb-1">⚠️ 被忽略的因素</p>
                          <div className="flex flex-wrap gap-1">
                            {(devil_advocate.overlooked_factors || devil_advocate.overlooked_risks).map((r, i) => (
                              <span key={i} className="text-[10px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full border border-amber-300">{r}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {devil_advocate.historical_parallels && (
                        <div className="bg-amber-100/50 rounded p-2 border border-amber-200">
                          <p className="text-[10px] text-amber-600 font-semibold">📜 历史反例</p>
                          <p className="text-xs text-amber-800 mt-0.5">{devil_advocate.historical_parallels}</p>
                        </div>
                      )}
                      {devil_advocate.score_adjustment && (
                        <p className="text-xs text-amber-700 mt-2 italic">💯 {devil_advocate.score_adjustment}</p>
                      )}
                    </div>
                  )}

                  {/* ── Phase 3: Arbiter ── */}
                  {arbiter && (
                    <div className="border-l-4 border-purple-400 bg-purple-50/50 rounded-r-lg p-4">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-semibold text-purple-800 text-sm flex items-center gap-1.5">⚖️ 首席投资官裁决</h4>
                        <div className="flex items-center gap-2">
                          {arbiter.confidence_level && (
                            <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                              arbiter.confidence_level === 'HIGH' ? 'bg-emerald-100 text-emerald-700' :
                              arbiter.confidence_level === 'MEDIUM' ? 'bg-yellow-100 text-yellow-700' :
                              'bg-red-100 text-red-700'
                            }`}>
                              {arbiter.confidence_level === 'HIGH' ? '高确信' : arbiter.confidence_level === 'MEDIUM' ? '中确信' : '低确信'}
                            </span>
                          )}
                          <div className={`w-12 h-12 rounded-full border-[3px] ${scoreBorder(arbiter.final_safety_score)} flex items-center justify-center font-bold text-lg ${scoreColor(arbiter.final_safety_score)}`}>
                            {arbiter.final_safety_score}
                          </div>
                        </div>
                      </div>
                      <p className="text-xs text-gray-700 leading-relaxed mb-3">{arbiter.final_summary}</p>

                      {/* Who was right */}
                      <div className="grid grid-cols-2 gap-2 mb-3">
                        <div className="bg-blue-50 rounded p-2 border border-blue-200">
                          <p className="text-[10px] text-blue-500 font-semibold">✅ 分析师说对了</p>
                          <p className="text-xs text-blue-700 mt-0.5">{arbiter.analyst_strengths}</p>
                        </div>
                        <div className="bg-amber-50 rounded p-2 border border-amber-200">
                          <p className="text-[10px] text-amber-500 font-semibold">✅ 质疑者说对了</p>
                          <p className="text-xs text-amber-700 mt-0.5">{arbiter.advocate_strengths}</p>
                        </div>
                      </div>

                      {/* Final bull/bear */}
                      <div className="grid grid-cols-2 gap-2 mb-3">
                        <div className="bg-emerald-50 rounded p-2 border border-emerald-200">
                          <p className="text-[10px] text-emerald-500 font-semibold">🟢 最终看多</p>
                          <p className="text-xs text-emerald-700 mt-0.5">{arbiter.final_bull_case}</p>
                        </div>
                        <div className="bg-red-50 rounded p-2 border border-red-200">
                          <p className="text-[10px] text-red-500 font-semibold">🔴 最终看空</p>
                          <p className="text-xs text-red-700 mt-0.5">{arbiter.final_bear_case}</p>
                        </div>
                      </div>

                      {/* Key levels */}
                      {arbiter.key_levels && (
                        <div className="bg-purple-100/50 rounded-lg p-2 grid grid-cols-3 gap-3 mb-3">
                          <div className="text-center">
                            <p className="text-[10px] text-gray-400">强支撑</p>
                            <p className="font-bold text-sm text-emerald-700">${arbiter.key_levels.strong_support}</p>
                          </div>
                          <div className="text-center">
                            <p className="text-[10px] text-gray-400">弱支撑</p>
                            <p className="font-bold text-sm text-yellow-700">${arbiter.key_levels.weak_support}</p>
                          </div>
                          <div className="text-center">
                            <p className="text-[10px] text-gray-400">阻力位</p>
                            <p className="font-bold text-sm text-red-700">${arbiter.key_levels.resistance}</p>
                          </div>
                        </div>
                      )}

                      {/* Max loss */}
                      {arbiter.max_loss_estimate && (
                        <p className="text-xs text-gray-500 bg-gray-50 rounded p-2 mb-2">⚠️ 最大跌幅预估: {arbiter.max_loss_estimate}</p>
                      )}

                      {/* Risks + Catalysts */}
                      <div className="grid grid-cols-2 gap-2">
                        {arbiter.final_risks?.length > 0 && (
                          <div>
                            <p className="text-[10px] text-gray-400 font-semibold mb-1">风险因素</p>
                            <div className="flex flex-wrap gap-1">
                              {arbiter.final_risks.map((r, i) => (
                                <span key={i} className="text-[10px] bg-red-50 text-red-600 px-2 py-0.5 rounded-full border border-red-200">{r}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {arbiter.final_catalysts?.length > 0 && (
                          <div>
                            <p className="text-[10px] text-gray-400 font-semibold mb-1">正面催化剂</p>
                            <div className="flex flex-wrap gap-1">
                              {arbiter.final_catalysts.map((c, i) => (
                                <span key={i} className="text-[10px] bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-full border border-emerald-200">{c}</span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Score comparison */}
                      <div className="mt-3 pt-3 border-t border-purple-200">
                        <p className="text-[10px] text-gray-400 font-semibold mb-1">评分对比</p>
                        <div className="flex items-center gap-4 text-xs">
                          <span className="text-blue-600">📊 分析师: {analyst?.safety_score ?? '—'}</span>
                          <span className="text-gray-300">→</span>
                          <span className="text-amber-600">😈 质疑者: {devil_advocate?.challenge_score ?? '—'}</span>
                          <span className="text-gray-300">→</span>
                          <span className="text-purple-700 font-bold">⚖️ 最终: {arbiter.final_safety_score}</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {debateData?.error && (
              <p className="text-sm text-red-500 mt-2">Debate失败: {debateData.error}</p>
            )}
          </div>

        </div>
      )}

      {/* Welcome state */}
      {!ticker && !loading && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-12 text-center">
          <BarChart3 size={48} className="text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-700">Search for a ticker to get started</h3>
          <p className="text-gray-400 text-sm mt-1">View fundamentals, EPS history, revenue trends, and price charts</p>
        </div>
      )}
    </div>
  );
}
