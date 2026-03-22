import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getTrendRibbon } from '../api.js';
import { RefreshCw, TrendingUp, TrendingDown, Activity, Settings } from 'lucide-react';

// ═══════════════════════════════════════════════════
// Custom Candlestick + Trend Ribbon Chart (SVG-based)
// ═══════════════════════════════════════════════════

const CHART_PADDING = { top: 30, right: 80, bottom: 40, left: 10 };
const CANDLE_GAP = 0.3; // fraction of candle width for gap

function TrendRibbonChart({ data, width = 1200, height = 600 }) {
  const svgRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [visibleRange, setVisibleRange] = useState(null); // { start, end }

  const candles = data?.candles || [];
  if (!candles.length) return null;

  // Default: show last 120 candles
  const maxVisible = 120;
  const start = visibleRange?.start ?? Math.max(0, candles.length - maxVisible);
  const end = visibleRange?.end ?? candles.length;
  const visible = candles.slice(start, end);

  const chartW = width - CHART_PADDING.left - CHART_PADDING.right;
  const chartH = height - CHART_PADDING.top - CHART_PADDING.bottom;
  const candleW = chartW / visible.length;
  const bodyW = candleW * (1 - CANDLE_GAP);

  // Price range
  const allPrices = visible.flatMap(c => [c.high, c.low, c.ema_fast, c.ema_slow, c.ema_long].filter(Boolean));
  const priceMin = Math.min(...allPrices) * 0.998;
  const priceMax = Math.max(...allPrices) * 1.002;
  const priceRange = priceMax - priceMin || 1;

  const yScale = (price) => CHART_PADDING.top + chartH - ((price - priceMin) / priceRange) * chartH;
  const xCenter = (i) => CHART_PADDING.left + i * candleW + candleW / 2;

  // Build ribbon path (filled area between ema_fast and ema_slow)
  const ribbonSegments = [];
  let segStart = 0;
  let segTrend = visible[0]?.trend;

  for (let i = 1; i <= visible.length; i++) {
    if (i === visible.length || visible[i]?.trend !== segTrend) {
      // Close segment
      const seg = visible.slice(segStart, i);
      const topLine = seg.map((c, j) => `${xCenter(segStart + j)},${yScale(c.ema_fast)}`).join(' ');
      const botLine = seg.map((c, j) => `${xCenter(segStart + j)},${yScale(c.ema_slow)}`).reverse().join(' ');

      ribbonSegments.push({
        trend: segTrend,
        points: topLine + ' ' + botLine,
        startIdx: segStart,
        endIdx: i - 1,
      });

      if (i < visible.length) {
        segStart = i - 1; // overlap by 1 for continuity
        segTrend = visible[i].trend;
      }
    }
  }

  // EMA long line path
  const emaLongPath = visible.map((c, i) => `${i === 0 ? 'M' : 'L'}${xCenter(i)},${yScale(c.ema_long)}`).join(' ');

  // Price grid lines
  const gridStep = Math.pow(10, Math.floor(Math.log10(priceRange / 5)));
  const niceStep = priceRange / 5 > gridStep * 5 ? gridStep * 5 : priceRange / 5 > gridStep * 2 ? gridStep * 2 : gridStep;
  const gridLines = [];
  let gl = Math.ceil(priceMin / niceStep) * niceStep;
  while (gl < priceMax) {
    gridLines.push(gl);
    gl += niceStep;
  }

  // Scroll handler
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 5 : -5;
    setVisibleRange(prev => {
      const s = (prev?.start ?? Math.max(0, candles.length - maxVisible));
      const en = (prev?.end ?? candles.length);
      const newStart = Math.max(0, Math.min(s + delta, candles.length - 20));
      const newEnd = Math.min(candles.length, Math.max(newStart + 20, en + delta));
      return { start: newStart, end: newEnd };
    });
  }, [candles.length]);

  // Mouse move for tooltip
  const handleMouseMove = useCallback((e) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left - CHART_PADDING.left;
    const idx = Math.floor(x / candleW);
    if (idx >= 0 && idx < visible.length) {
      const c = visible[idx];
      setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, candle: c });
    }
  }, [visible, candleW]);

  // Block ALL touch/gesture/wheel events on the chart — only allow mouse interactions
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const preventAll = (e) => e.preventDefault();
    // Block all touch events (pinch, two-finger scroll, etc.)
    svg.addEventListener('touchstart', preventAll, { passive: false });
    svg.addEventListener('touchmove', preventAll, { passive: false });
    svg.addEventListener('touchend', preventAll, { passive: false });
    // Block trackpad gestures (pinch-zoom)
    svg.addEventListener('gesturestart', preventAll);
    svg.addEventListener('gesturechange', preventAll);
    svg.addEventListener('gestureend', preventAll);
    // Block trackpad scroll/wheel on the chart (prevents the big shift you saw)
    svg.addEventListener('wheel', preventAll, { passive: false });
    return () => {
      svg.removeEventListener('touchstart', preventAll);
      svg.removeEventListener('touchmove', preventAll);
      svg.removeEventListener('touchend', preventAll);
      svg.removeEventListener('gesturestart', preventAll);
      svg.removeEventListener('gesturechange', preventAll);
      svg.removeEventListener('gestureend', preventAll);
      svg.removeEventListener('wheel', preventAll);
    };
  }, []);

  return (
    <div className="relative" style={{ touchAction: 'none' }}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="select-none"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTooltip(null)}
      >
        {/* Background */}
        <rect width={width} height={height} fill="#0f172a" rx="8" />

        {/* Grid lines */}
        {gridLines.map(g => (
          <g key={g}>
            <line
              x1={CHART_PADDING.left} y1={yScale(g)}
              x2={width - CHART_PADDING.right} y2={yScale(g)}
              stroke="#1e293b" strokeWidth="1"
            />
            <text x={width - CHART_PADDING.right + 5} y={yScale(g) + 4} fill="#64748b" fontSize="10" fontFamily="monospace">
              ${g.toFixed(0)}
            </text>
          </g>
        ))}

        {/* Date labels */}
        {visible.map((c, i) => {
          if (i % Math.max(1, Math.floor(visible.length / 8)) !== 0) return null;
          return (
            <text key={i} x={xCenter(i)} y={height - 8} fill="#64748b" fontSize="9" textAnchor="middle" fontFamily="monospace">
              {c.date.substring(5)} {/* MM-DD */}
            </text>
          );
        })}

        {/* Ribbon segments */}
        {ribbonSegments.map((seg, i) => (
          <polygon
            key={i}
            points={seg.points}
            fill={seg.trend === 'bullish' ? '#7c3aed' : '#f97316'}
            opacity="0.45"
          />
        ))}

        {/* EMA fast line */}
        <polyline
          fill="none"
          stroke="#fbbf24"
          strokeWidth="1.5"
          points={visible.map((c, i) => `${xCenter(i)},${yScale(c.ema_fast)}`).join(' ')}
        />

        {/* EMA slow line */}
        <polyline
          fill="none"
          stroke="#fbbf24"
          strokeWidth="1.5"
          opacity="0.6"
          points={visible.map((c, i) => `${xCenter(i)},${yScale(c.ema_slow)}`).join(' ')}
        />

        {/* EMA long (white line) */}
        <polyline
          fill="none"
          stroke="white"
          strokeWidth="1.5"
          opacity="0.7"
          points={emaLongPath}
        />

        {/* Candlesticks */}
        {visible.map((c, i) => {
          const isUp = c.close >= c.open;
          // Candle color: yellow=overbought, blue=oversold, normal green/red
          const color = c.candle_state === 'overbought' ? '#eab308'
            : c.candle_state === 'oversold' ? '#3b82f6'
            : isUp ? '#22c55e' : '#ef4444';
          const bodyTop = yScale(Math.max(c.open, c.close));
          const bodyBot = yScale(Math.min(c.open, c.close));
          const bodyH = Math.max(bodyBot - bodyTop, 1);

          return (
            <g key={i}>
              {/* Wick */}
              <line
                x1={xCenter(i)} y1={yScale(c.high)}
                x2={xCenter(i)} y2={yScale(c.low)}
                stroke={color} strokeWidth="1"
              />
              {/* Body */}
              <rect
                x={xCenter(i) - bodyW / 2}
                y={bodyTop}
                width={bodyW}
                height={bodyH}
                fill={isUp ? color : color}
                stroke={color}
                strokeWidth="0.5"
              />
              {/* Crossover marker */}
              {c.crossover && (
                <g>
                  <circle
                    cx={xCenter(i)} cy={yScale(c.high) - 15}
                    r="10" fill={c.crossover === 'golden_cross' ? '#7c3aed' : '#f97316'}
                    opacity="0.9"
                  />
                  <text
                    x={xCenter(i)} y={yScale(c.high) - 11}
                    fill="white" fontSize="10" textAnchor="middle" fontWeight="bold"
                  >
                    变
                  </text>
                </g>
              )}
              {/* Phase markers: 蓄势 / 落势 / 🔔底部 */}
              {c.phase === 'accumulation' && (
                <text
                  x={xCenter(i)} y={yScale(c.low) + 16}
                  fill="#a78bfa" fontSize="9" textAnchor="middle" fontWeight="bold"
                >
                  蓄势
                </text>
              )}
              {c.phase === 'declining' && (
                <text
                  x={xCenter(i)} y={yScale(c.high) - 20}
                  fill="#fb923c" fontSize="9" textAnchor="middle" fontWeight="bold"
                >
                  落势
                </text>
              )}
              {c.phase === 'bottom_signal' && (
                <text
                  x={xCenter(i)} y={yScale(c.low) + 18}
                  fill="#fbbf24" fontSize="14" textAnchor="middle"
                >
                  🔔
                </text>
              )}
            </g>
          );
        })}

        {/* Latest price label */}
        {visible.length > 0 && (() => {
          const last = visible[visible.length - 1];
          const y = yScale(last.close);
          return (
            <g>
              <line x1={width - CHART_PADDING.right} y1={y} x2={width - CHART_PADDING.right + 5} y2={y} stroke="#3b82f6" strokeWidth="2" />
              <rect x={width - CHART_PADDING.right + 6} y={y - 10} width={65} height={20} fill="#3b82f6" rx="3" />
              <text x={width - CHART_PADDING.right + 10} y={y + 4} fill="white" fontSize="11" fontWeight="bold" fontFamily="monospace">
                ${last.close.toFixed(2)}
              </text>
            </g>
          );
        })()}
      </svg>

      {/* Tooltip */}
      {tooltip && tooltip.candle && (
        <div
          className="absolute pointer-events-none bg-gray-900/95 border border-gray-600 rounded-lg px-3 py-2 text-xs z-50"
          style={{ left: Math.min(tooltip.x + 15, width - 220), top: tooltip.y - 100 }}
        >
          <div className="text-gray-400 mb-1">{tooltip.candle.date}</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-white font-mono">
            <span className="text-gray-500">O</span><span>${tooltip.candle.open}</span>
            <span className="text-gray-500">H</span><span>${tooltip.candle.high}</span>
            <span className="text-gray-500">L</span><span>${tooltip.candle.low}</span>
            <span className="text-gray-500">C</span><span className={tooltip.candle.close >= tooltip.candle.open ? 'text-green-400' : 'text-red-400'}>${tooltip.candle.close}</span>
          </div>
          <div className="border-t border-gray-700 mt-1.5 pt-1.5 space-y-0.5">
            <div className="flex justify-between">
              <span className="text-gray-500">EMA{data.summary.ema_params.fast}</span>
              <span className="text-yellow-400 font-mono">${tooltip.candle.ema_fast}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">EMA{data.summary.ema_params.slow}</span>
              <span className="text-yellow-300 font-mono">${tooltip.candle.ema_slow}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">趋势</span>
              <span className={tooltip.candle.trend === 'bullish' ? 'text-purple-400' : 'text-orange-400'}>
                {tooltip.candle.trend === 'bullish' ? '🟣 多头' : '🟠 空头'}
              </span>
            </div>
            {tooltip.candle.rsi && (
              <div className="flex justify-between">
                <span className="text-gray-500">RSI</span>
                <span className={`font-mono ${tooltip.candle.rsi > 70 ? 'text-red-400' : tooltip.candle.rsi < 30 ? 'text-green-400' : 'text-gray-300'}`}>
                  {tooltip.candle.rsi}
                </span>
              </div>
            )}
            {tooltip.candle.candle_state && tooltip.candle.candle_state !== 'normal' && (
              <div className={`text-center mt-1 font-bold ${tooltip.candle.candle_state === 'overbought' ? 'text-yellow-300' : 'text-blue-400'}`}>
                {tooltip.candle.candle_state === 'overbought' ? '⚠️ 超买' : '💎 超卖'}
              </div>
            )}
            {tooltip.candle.crossover && (
              <div className="text-center mt-1 font-bold text-yellow-300">
                ⚡ {tooltip.candle.crossover === 'golden_cross' ? '金叉 — 转多' : '死叉 — 转空'}
              </div>
            )}
            {tooltip.candle.phase && (
              <div className={`text-center mt-1 font-bold ${
                tooltip.candle.phase === 'accumulation' ? 'text-purple-300' :
                tooltip.candle.phase === 'declining' ? 'text-orange-300' : 'text-yellow-300'
              }`}>
                {tooltip.candle.phase === 'accumulation' ? '📦 蓄势' :
                 tooltip.candle.phase === 'declining' ? '📉 落势' : '🔔 底部信号'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════
// Main Page Component
// ═══════════════════════════════════════════════════

const PRESETS = [
  { label: 'NASDAQ (QQQ)', ticker: 'QQQ' },
  { label: 'S&P 500 (SPY)', ticker: 'SPY' },
  { label: 'Dow Jones (DIA)', ticker: 'DIA' },
  { label: 'Russell 2000 (IWM)', ticker: 'IWM' },
  { label: 'NVDA', ticker: 'NVDA' },
  { label: 'TSLA', ticker: 'TSLA' },
  { label: 'AAPL', ticker: 'AAPL' },
  { label: 'META', ticker: 'META' },
];

// Timeframe labels
const TIMEFRAME_LABELS = {
  '1d': '日线',
  '60m': '60分钟',
  '1wk': '周线',
};

// Mini summary for sub-charts
function MiniSummary({ summary, label }) {
  if (!summary) return null;
  const trendColor = summary.current_trend === 'bullish' ? 'text-purple-400' : 'text-orange-400';
  const trendIcon = summary.current_trend === 'bullish' ? '🟣' : '🟠';
  const unit = summary.interval === '60m' ? '根K线' : summary.interval === '1wk' ? '周' : '天';
  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-gray-800/50 rounded-t-xl text-sm">
      <span className="text-white font-bold">{label}</span>
      <span className={trendColor}>{trendIcon} {summary.current_trend === 'bullish' ? '多头' : '空头'}</span>
      <span className="text-gray-400">连续{summary.consecutive_trend_days}{unit}</span>
      <span className="text-gray-400">带宽 {summary.ribbon_width > 0 ? '+' : ''}{summary.ribbon_width?.toFixed(2)}%</span>
      <span className={`${summary.rsi > 70 ? 'text-red-400' : summary.rsi < 30 ? 'text-green-400' : 'text-gray-400'}`}>
        RSI {summary.rsi}
      </span>
      {summary.last_crossover && (
        <span className={summary.last_crossover.type === 'golden_cross' ? 'text-purple-400' : 'text-orange-400'}>
          上次{summary.last_crossover.type === 'golden_cross' ? '金叉' : '死叉'} {summary.last_crossover.date}
        </span>
      )}
    </div>
  );
}

export default function TrendRibbon() {
  const [ticker, setTicker] = useState('QQQ');
  const [customTicker, setCustomTicker] = useState('');
  const [period, setPeriod] = useState('1y');
  const [emaFast, setEmaFast] = useState(13);
  const [emaSlow, setEmaSlow] = useState(34);
  const [emaLong, setEmaLong] = useState(120);
  const [data, setData] = useState(null);          // daily
  const [data60m, setData60m] = useState(null);     // 60-min
  const [dataWeekly, setDataWeekly] = useState(null); // weekly
  const [loading, setLoading] = useState(false);
  const [loading60m, setLoading60m] = useState(false);
  const [loadingWeekly, setLoadingWeekly] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showMultiTF, setShowMultiTF] = useState(true); // show all 3 timeframes
  const [chartWidth, setChartWidth] = useState(1200);
  const containerRef = useRef(null);

  // Measure container width
  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        setChartWidth(containerRef.current.offsetWidth);
      }
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  const loadData = useCallback(async (t = ticker) => {
    setLoading(true);
    try {
      const result = await getTrendRibbon(t, period, emaFast, emaSlow, emaLong, '1d');
      if (result && !result.error) {
        setData(result);
        setTicker(t);
      }
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [period, emaFast, emaSlow, emaLong]);

  const load60m = useCallback(async (t = ticker) => {
    setLoading60m(true);
    try {
      const result = await getTrendRibbon(t, '60d', emaFast, emaSlow, emaLong, '60m');
      if (result && !result.error) {
        setData60m(result);
      }
    } catch (e) {
      console.error('60m load error:', e);
    }
    setLoading60m(false);
  }, [emaFast, emaSlow, emaLong]);

  const loadWeekly = useCallback(async (t = ticker) => {
    setLoadingWeekly(true);
    try {
      const result = await getTrendRibbon(t, period, emaFast, emaSlow, emaLong, '1wk');
      if (result && !result.error) {
        setDataWeekly(result);
      }
    } catch (e) {
      console.error('weekly load error:', e);
    }
    setLoadingWeekly(false);
  }, [period, emaFast, emaSlow, emaLong]);

  // Load all timeframes
  const loadAll = useCallback(async (t = ticker) => {
    loadData(t);
    if (showMultiTF) {
      load60m(t);
      loadWeekly(t);
    }
  }, [loadData, load60m, loadWeekly, showMultiTF]);

  useEffect(() => {
    loadAll('QQQ');
  }, []);

  const summary = data?.summary;

  return (
    <div className="space-y-4" ref={containerRef}>
      {/* Header */}
      <div className="bg-gradient-to-r from-indigo-900 via-purple-900 to-indigo-900 rounded-xl p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Activity size={24} />
              <h1 className="text-2xl font-bold">趋势通道 Trend Ribbon</h1>
            </div>
            <p className="text-indigo-200 text-sm">EMA变色趋势带 — 紫色=多头 橙色=空头 "变"=趋势转换 | 多周期联动分析</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setShowMultiTF(!showMultiTF); }}
              className={`px-3 py-2 rounded-lg text-sm transition-colors ${showMultiTF ? 'bg-purple-500/40 text-purple-200' : 'bg-white/10 text-white/70 hover:bg-white/20'}`}
            >
              {showMultiTF ? '📊 三周期' : '📊 单周期'}
            </button>
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="bg-white/10 hover:bg-white/20 px-3 py-2 rounded-lg text-sm transition-colors"
            >
              <Settings size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Ticker selection */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          {PRESETS.map(p => (
            <button
              key={p.ticker}
              onClick={() => loadAll(p.ticker)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                ticker === p.ticker
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {p.label}
            </button>
          ))}
          <div className="flex items-center gap-1 ml-2">
            <input
              value={customTicker}
              onChange={e => setCustomTicker(e.target.value.toUpperCase())}
              onKeyDown={e => {
                if (e.key === 'Enter' && customTicker) {
                  loadAll(customTicker);
                  setCustomTicker('');
                }
              }}
              placeholder="自定义..."
              className="w-24 bg-gray-50 border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
            />
          </div>
          <div className="flex items-center gap-1 ml-auto">
            {['3mo', '6mo', '1y', '2y'].map(p => (
              <button
                key={p}
                onClick={() => { setPeriod(p); setTimeout(() => loadAll(ticker), 50); }}
                className={`px-2 py-1 rounded text-xs font-medium ${period === p ? 'bg-indigo-100 text-indigo-700' : 'text-gray-500 hover:bg-gray-100'}`}
              >
                {p}
              </button>
            ))}
            <button
              onClick={() => loadAll(ticker)}
              className="ml-2 bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-indigo-700 flex items-center gap-1"
              disabled={loading}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              刷新
            </button>
          </div>
        </div>

        {/* EMA Settings (collapsible) */}
        {showSettings && (
          <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-4 text-sm">
            <label className="text-gray-500">EMA快线:
              <input type="number" value={emaFast} onChange={e => setEmaFast(+e.target.value)}
                className="w-16 ml-1 border border-gray-300 rounded px-1.5 py-0.5 text-center" />
            </label>
            <label className="text-gray-500">EMA慢线:
              <input type="number" value={emaSlow} onChange={e => setEmaSlow(+e.target.value)}
                className="w-16 ml-1 border border-gray-300 rounded px-1.5 py-0.5 text-center" />
            </label>
            <label className="text-gray-500">长期均线:
              <input type="number" value={emaLong} onChange={e => setEmaLong(+e.target.value)}
                className="w-16 ml-1 border border-gray-300 rounded px-1.5 py-0.5 text-center" />
            </label>
            <button onClick={() => loadAll(ticker)} className="text-indigo-600 hover:text-indigo-800 font-medium">
              应用
            </button>
          </div>
        )}
      </div>

      {/* Summary card (daily) */}
      {summary && (
        <div className="grid grid-cols-6 gap-3">
          <div className={`col-span-2 rounded-xl p-4 border shadow-sm ${summary.current_trend === 'bullish' ? 'bg-purple-50 border-purple-200' : 'bg-orange-50 border-orange-200'}`}>
            <div className="flex items-center gap-2">
              {summary.current_trend === 'bullish' ? <TrendingUp size={20} className="text-purple-600" /> : <TrendingDown size={20} className="text-orange-600" />}
              <span className={`text-lg font-bold ${summary.current_trend === 'bullish' ? 'text-purple-700' : 'text-orange-700'}`}>
                {summary.ticker} — {summary.current_trend === 'bullish' ? '🟣 多头趋势' : '🟠 空头趋势'}
              </span>
            </div>
            <div className="mt-2 text-sm text-gray-600">
              连续 <span className="font-bold text-gray-900">{summary.consecutive_trend_days}</span> 天 |
              带宽 <span className={`font-bold ${summary.ribbon_strength === 'strong' ? 'text-red-600' : summary.ribbon_strength === 'moderate' ? 'text-yellow-600' : 'text-gray-600'}`}>
                {summary.ribbon_strength === 'strong' ? '强' : summary.ribbon_strength === 'moderate' ? '中等' : '弱'}
              </span> ({summary.ribbon_width > 0 ? '+' : ''}{summary.ribbon_width?.toFixed(2)}%)
            </div>
            {/* Multi-TF trend alignment */}
            {showMultiTF && (data60m?.summary || dataWeekly?.summary) && (
              <div className="mt-2 pt-2 border-t border-gray-200/50 flex items-center gap-3 text-xs">
                <span className="text-gray-500">多周期:</span>
                {data60m?.summary && (
                  <span className={data60m.summary.current_trend === 'bullish' ? 'text-purple-600' : 'text-orange-600'}>
                    60分 {data60m.summary.current_trend === 'bullish' ? '🟣多' : '🟠空'}
                  </span>
                )}
                <span className={summary.current_trend === 'bullish' ? 'text-purple-600' : 'text-orange-600'}>
                  日线 {summary.current_trend === 'bullish' ? '🟣多' : '🟠空'}
                </span>
                {dataWeekly?.summary && (
                  <span className={dataWeekly.summary.current_trend === 'bullish' ? 'text-purple-600' : 'text-orange-600'}>
                    周线 {dataWeekly.summary.current_trend === 'bullish' ? '🟣多' : '🟠空'}
                  </span>
                )}
                {/* Alignment indicator */}
                {data60m?.summary && dataWeekly?.summary && (() => {
                  const trends = [data60m.summary.current_trend, summary.current_trend, dataWeekly.summary.current_trend];
                  const allBull = trends.every(t => t === 'bullish');
                  const allBear = trends.every(t => t === 'bearish');
                  if (allBull) return <span className="text-purple-700 font-bold ml-1">✅ 三线共振多</span>;
                  if (allBear) return <span className="text-orange-700 font-bold ml-1">⚠️ 三线共振空</span>;
                  return <span className="text-gray-500 ml-1">⚡ 多空分歧</span>;
                })()}
              </div>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm text-center">
            <div className="text-xs text-gray-500">当前价格</div>
            <div className="text-xl font-bold text-gray-900 font-mono">${summary.price}</div>
            <div className={`text-xs font-medium ${summary.price_vs_long_ema === 'above' ? 'text-emerald-600' : 'text-red-600'}`}>
              {summary.price_vs_long_ema === 'above' ? '▲ 长期均线上方' : '▼ 长期均线下方'}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm text-center">
            <div className="text-xs text-gray-500">RSI(14)</div>
            <div className={`text-xl font-bold font-mono ${summary.rsi > 70 ? 'text-red-600' : summary.rsi < 30 ? 'text-emerald-600' : 'text-gray-900'}`}>
              {summary.rsi}
            </div>
            <div className="text-xs text-gray-500">
              {summary.rsi > 70 ? '超买' : summary.rsi < 30 ? '超卖' : '正常'}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm text-center">
            <div className="text-xs text-gray-500">EMA{summary.ema_params.fast}/{summary.ema_params.slow}</div>
            <div className="text-sm font-mono mt-1">
              <span className="text-yellow-600">{summary.ema_fast}</span>
              <span className="text-gray-400 mx-1">/</span>
              <span className="text-yellow-500">{summary.ema_slow}</span>
            </div>
            <div className="text-xs text-gray-500 mt-1">EMA{summary.ema_params.long}: {summary.ema_long}</div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm text-center">
            <div className="text-xs text-gray-500">上次转换</div>
            {summary.last_crossover ? (
              <>
                <div className={`text-sm font-bold ${summary.last_crossover.type === 'golden_cross' ? 'text-purple-600' : 'text-orange-600'}`}>
                  {summary.last_crossover.type === 'golden_cross' ? '金叉' : '死叉'}
                </div>
                <div className="text-xs text-gray-500 font-mono">{summary.last_crossover.date}</div>
                <div className="text-xs text-gray-500">${summary.last_crossover.price}</div>
              </>
            ) : <div className="text-sm text-gray-400">无</div>}
          </div>
        </div>
      )}

      {/* ═══ DAILY CHART ═══ */}
      <div>
        <MiniSummary summary={data?.summary} label="📈 日线 Daily" />
        {loading && !data ? (
          <div className="bg-gray-900 rounded-b-xl h-[500px] flex items-center justify-center">
            <RefreshCw size={24} className="animate-spin text-gray-500" />
          </div>
        ) : data?.candles?.length > 0 ? (
          <TrendRibbonChart data={data} width={chartWidth} height={showMultiTF ? 450 : 600} />
        ) : null}
      </div>

      {/* ═══ 60-MINUTE CHART ═══ */}
      {showMultiTF && (
        <div>
          <MiniSummary summary={data60m?.summary} label="⏱️ 60分钟 Intraday" />
          {loading60m ? (
            <div className="bg-gray-900 rounded-b-xl h-[350px] flex items-center justify-center">
              <RefreshCw size={24} className="animate-spin text-gray-500" />
            </div>
          ) : data60m?.candles?.length > 0 ? (
            <TrendRibbonChart data={data60m} width={chartWidth} height={350} />
          ) : data60m?.error ? (
            <div className="bg-gray-900 rounded-b-xl h-[100px] flex items-center justify-center text-gray-500 text-sm">
              60分钟数据不可用: {data60m.error}
            </div>
          ) : !loading60m ? (
            <div className="bg-gray-900 rounded-b-xl h-[100px] flex items-center justify-center text-gray-500 text-sm">
              加载中...
            </div>
          ) : null}
        </div>
      )}

      {/* ═══ WEEKLY CHART ═══ */}
      {showMultiTF && (
        <div>
          <MiniSummary summary={dataWeekly?.summary} label="📅 周线 Weekly" />
          {loadingWeekly ? (
            <div className="bg-gray-900 rounded-b-xl h-[350px] flex items-center justify-center">
              <RefreshCw size={24} className="animate-spin text-gray-500" />
            </div>
          ) : dataWeekly?.candles?.length > 0 ? (
            <TrendRibbonChart data={dataWeekly} width={chartWidth} height={350} />
          ) : dataWeekly?.error ? (
            <div className="bg-gray-900 rounded-b-xl h-[100px] flex items-center justify-center text-gray-500 text-sm">
              周线数据不可用: {dataWeekly.error}
            </div>
          ) : !loadingWeekly ? (
            <div className="bg-gray-900 rounded-b-xl h-[100px] flex items-center justify-center text-gray-500 text-sm">
              加载中...
            </div>
          ) : null}
        </div>
      )}

      {/* Legend */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <h3 className="text-sm font-bold text-gray-900 mb-2">图例说明</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm text-gray-600">
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-purple-500 opacity-50" />
            紫色带 = 多头（EMA快线 &gt; 慢线）
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-orange-500 opacity-50" />
            橙色带 = 空头（EMA快线 &lt; 慢线）
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-3 rounded bg-yellow-400" />
            EMA快线/慢线
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-0.5 bg-white border border-gray-300" />
            长期均线 (EMA{emaLong})
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded-full bg-purple-600 text-white text-[8px] flex items-center justify-center font-bold">变</span>
            金叉 = 多头转换
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded-full bg-orange-500 text-white text-[8px] flex items-center justify-center font-bold">变</span>
            死叉 = 空头转换
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-green-500" />
            阳线（收盘 &gt; 开盘）
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-red-500" />
            阴线（收盘 &lt; 开盘）
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-yellow-500" />
            超买K线（RSI&gt;70 或 触及布林上轨）
          </div>
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-blue-500" />
            超卖K线（RSI&lt;30 或 触及布林下轨）
          </div>
          <div className="flex items-center gap-2">
            <span className="text-purple-400 font-bold text-xs">蓄势</span>
            带宽收窄+成交萎缩=蓄力中
          </div>
          <div className="flex items-center gap-2">
            <span className="text-orange-400 font-bold text-xs">落势</span>
            空头+带宽扩大=趋势性下跌
          </div>
          <div className="flex items-center gap-2">
            🔔 底部信号（RSI超卖+放量）
          </div>
        </div>
        <p className="text-xs text-gray-400 mt-3">
          💡 带宽越宽=趋势越强。带宽收窄=趋势减弱，可能即将转换。"变"出现时应谨慎操作。价格在龙门线(白线)下方=大趋势向下。黄色K线=超买警告，蓝色K线=超卖机会。
        </p>
      </div>
    </div>
  );
}
