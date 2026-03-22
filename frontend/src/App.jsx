import React, { useState, useEffect } from 'react';
import Dashboard from './pages/Dashboard.jsx';
import TradeEntry from './pages/TradeEntry.jsx';
import Positions from './pages/Positions.jsx';
import Analytics from './pages/Analytics.jsx';
import TradeLog from './pages/TradeLog.jsx';
import YouTubeResearch from './pages/YouTubeResearch.jsx';
import TickerAnalysis from './pages/TickerAnalysis.jsx';
import CSPScanner from './pages/CSPScanner.jsx';
import MarketIntel from './pages/MarketIntel.jsx';
import TrendRibbon from './pages/TrendRibbon.jsx';
import { getVixRegime } from './api.js';
import { LayoutDashboard, PlusCircle, Briefcase, BarChart3, ScrollText, Play, Search, Radar, Globe, Activity, TrendingUp } from 'lucide-react';

const NAV_ITEMS = [
  { id: 'market-intel', label: 'Market Intel', icon: Globe },
  { id: 'trend-ribbon', label: 'Trend Ribbon', icon: Activity },
  { id: 'ticker-analysis', label: 'Ticker Analysis', icon: Search },
  { id: 'dashboard', label: 'Portfolio', icon: LayoutDashboard },
  { id: 'analytics', label: 'Performance', icon: BarChart3 },
  { id: 'trade-log', label: 'Trade Log', icon: ScrollText },
{ id: 'youtube', label: 'YT Research', icon: Play },
];

// Mini sparkline SVG component
function VixSparkline({ data, width = 140, height = 32 }) {
  if (!data || data.length < 2) return null;
  const values = data.map(d => d.primary_ratio);
  const min = Math.min(...values, 0.85);
  const max = Math.max(...values, 1.15);
  const range = max - min || 0.1;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  // Reference lines at 0.95 and 1.05
  const y095 = height - ((0.95 - min) / range) * height;
  const y105 = height - ((1.05 - min) / range) * height;

  return (
    <svg width={width} height={height} className="mt-1">
      <line x1="0" y1={y095} x2={width} y2={y095} stroke="#F59E0B" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.5" />
      <line x1="0" y1={y105} x2={width} y2={y105} stroke="#EF4444" strokeWidth="0.5" strokeDasharray="2,2" opacity="0.5" />
      <polyline fill="none" stroke="#60A5FA" strokeWidth="1.5" points={points} />
      {/* Current point */}
      {values.length > 0 && (
        <circle cx={width} cy={height - ((values[values.length-1] - min) / range) * height} r="2.5" fill="#60A5FA" />
      )}
    </svg>
  );
}

export default function App() {
  const [activePage, setActivePage] = useState('dashboard');
  const [marketData, setMarketData] = useState(null);
  const [vixRegime, setVixRegime] = useState(null);

  useEffect(() => {
    fetch('/api/sync/market-data')
      .then(r => r.ok ? r.json() : null)
      .then(data => setMarketData(data))
      .catch(() => {});

    // Fetch VIX regime
    getVixRegime().then(setVixRegime).catch(() => {});
  }, []);

  const renderPage = () => {
    switch (activePage) {
      case 'market-intel': return <MarketIntel />;
      case 'trend-ribbon': return <TrendRibbon />;
      case 'dashboard': return <Dashboard onNavigate={setActivePage} />;
      case 'new-trade': return <TradeEntry marketData={marketData} onSuccess={() => setActivePage('positions')} />;
      case 'positions': return <Positions onNavigate={setActivePage} />;
      case 'analytics': return <Analytics />;
      case 'trade-log': return <TradeLog />;
      case 'csp-scanner': return <CSPScanner />;
      case 'ticker-analysis': return <TickerAnalysis />;
      case 'youtube': return <YouTubeResearch />;
      default: return <Dashboard onNavigate={setActivePage} />;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-64 bg-navy-900 text-white flex flex-col fixed h-full">
        <div className="p-6 border-b border-navy-700">
          <h1 className="text-xl font-bold tracking-tight">OptionScout</h1>
          <p className="text-navy-300 text-xs mt-1">Trading Tracker v1.0</p>
        </div>

        {/* Compact VIX + SPY sidebar summary */}
        <div className="px-4 py-3 border-b border-navy-700 space-y-1.5">
          {vixRegime && !vixRegime.error ? (() => {
            const alert = vixRegime.alert || {};
            const dotColor = { 'SAFE': 'bg-emerald-400', 'INFO': 'bg-emerald-400', 'WARNING': 'bg-yellow-400', 'DANGER': 'bg-red-400', 'CRISIS': 'bg-red-400', 'GOLDEN': 'bg-purple-400', 'POSSIBLE_GOLDEN': 'bg-purple-400' };
            const textColor = { 'SAFE': 'text-emerald-400', 'INFO': 'text-emerald-400', 'WARNING': 'text-yellow-400', 'DANGER': 'text-red-400', 'CRISIS': 'text-red-400', 'GOLDEN': 'text-purple-400', 'POSSIBLE_GOLDEN': 'text-purple-400' };
            const regimeShort = { 'DEEP_CONTANGO': 'Deep C', 'CONTANGO': 'Contango', 'FLAT': 'Flat', 'BACKWARDATION': 'Backwd', 'DEEP_BACKWARDATION': 'Crisis' };
            const dirArrow = vixRegime.sma_direction === 'RISING' ? '↑' : vixRegime.sma_direction === 'FALLING' ? '↓' : '→';
            return (
              <>
                <div className="flex justify-between text-xs items-center">
                  <span className="text-navy-300">VIX</span>
                  <span className={`font-mono font-bold ${vixRegime.vix >= 30 ? 'text-red-400' : vixRegime.vix >= 20 ? 'text-yellow-400' : 'text-emerald-400'}`}>
                    {vixRegime.vix}
                  </span>
                </div>
                <div className="flex justify-between text-xs items-center">
                  <span className="text-navy-300">Regime</span>
                  <div className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${dotColor[alert.level] || 'bg-gray-400'} ${alert.level === 'CRISIS' ? 'animate-pulse' : ''}`} />
                    <span className={`font-mono text-[11px] font-bold ${textColor[alert.level] || 'text-gray-400'}`}>
                      {regimeShort[vixRegime.regime] || vixRegime.regime} {dirArrow}
                    </span>
                  </div>
                </div>
                <div className="flex justify-between text-xs items-center">
                  <span className="text-navy-300">仓位</span>
                  <span className={`font-mono font-bold text-[11px] ${vixRegime.size_multiplier >= 0.7 ? 'text-emerald-400' : vixRegime.size_multiplier >= 0.4 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {Math.round(vixRegime.size_multiplier * 100)}%
                  </span>
                </div>
              </>
            );
          })() : marketData && (
            <>
              <div className="flex justify-between text-xs">
                <span className="text-navy-300">VIX</span>
                <span className={`font-mono font-bold ${marketData.vix >= 30 ? 'text-red-400' : marketData.vix >= 20 ? 'text-yellow-400' : 'text-emerald-400'}`}>
                  {marketData.vix?.toFixed(1) || '—'}
                </span>
              </div>
            </>
          )}
          {marketData && (
            <div className="flex justify-between text-xs">
              <span className="text-navy-300">SPY</span>
              <span className="font-mono text-white">${marketData.spy_price?.toFixed(2) || '—'}</span>
            </div>
          )}
        </div>

        <nav className="flex-1 py-4">
          {NAV_ITEMS.map(item => {
            const Icon = item.icon;
            const isActive = activePage === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActivePage(item.id)}
                className={`w-full flex items-center gap-3 px-6 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-navy-700 text-white border-r-2 border-blue-400'
                    : 'text-navy-300 hover:bg-navy-800 hover:text-white'
                }`}
              >
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="p-4 border-t border-navy-700 text-xs text-navy-400">
          Systematic CSP Portfolio
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 ml-64 p-8">
        {renderPage()}
      </main>
    </div>
  );
}
