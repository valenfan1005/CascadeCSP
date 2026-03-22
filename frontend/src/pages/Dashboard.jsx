import React, { useState, useEffect, useCallback } from 'react';
import { fetchPortfolioSummary, fetchPerformance, fetchAlerts, fetchOpenTrades, fetchEquityCurve, syncAccount, syncPositions, getPortfolioDeepAnalysis } from '../api.js';
import { TrendingUp, TrendingDown, AlertTriangle, DollarSign, Activity, Target, Briefcase, RefreshCw, Brain, Shield, ChevronDown, ChevronUp } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';

const COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#6366f1'];

const YEAR_TABS = [
  { label: 'All Time', value: 'all' },
  { label: '2025', value: '2025' },
  { label: '2026', value: '2026' },
];

function MetricCard({ label, value, sublabel, icon: Icon, color = 'text-gray-900', trend }) {
  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <p className="label">{label}</p>
          <p className={`metric-value ${color}`}>{value}</p>
          {sublabel && <p className="text-xs text-gray-500 mt-1">{sublabel}</p>}
        </div>
        {Icon && (
          <div className={`p-2 rounded-lg ${trend === 'up' ? 'bg-emerald-50' : trend === 'down' ? 'bg-red-50' : 'bg-blue-50'}`}>
            <Icon size={20} className={trend === 'up' ? 'text-emerald-600' : trend === 'down' ? 'text-red-600' : 'text-gray-500'} />
          </div>
        )}
      </div>
    </div>
  );
}

function YearTabBar({ selected, onChange }) {
  return (
    <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
      {YEAR_TABS.map(tab => (
        <button
          key={tab.value}
          onClick={() => onChange(tab.value)}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
            selected === tab.value
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export default function Dashboard({ onNavigate }) {
  const [summary, setSummary] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [equityCurve, setEquityCurve] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [openTrades, setOpenTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [perfLoading, setPerfLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedYear, setSelectedYear] = useState('all');
  const [refreshKey, setRefreshKey] = useState(0);
  const [deepAnalysis, setDeepAnalysis] = useState(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const [expandedPositions, setExpandedPositions] = useState({});

  const getDateParams = useCallback((year) => {
    if (year === 'all') return {};
    return { start_date: `${year}-01-01`, end_date: `${year}-12-31` };
  }, []);

  useEffect(() => {
    Promise.all([
      fetchPortfolioSummary().catch(() => null),
      fetchAlerts().catch(() => []),
      fetchOpenTrades().catch(() => []),
    ]).then(([sum, al, trades]) => {
      setSummary(sum);
      setAlerts(al || []);
      setOpenTrades(trades || []);
    });
  }, [refreshKey]);

  useEffect(() => {
    setPerfLoading(true);
    const params = getDateParams(selectedYear);
    Promise.all([
      fetchPerformance(params).catch(() => null),
      fetchEquityCurve(params).catch(() => []),
    ]).then(([perf, curve]) => {
      setPerformance(perf);
      setEquityCurve(curve || []);
      setPerfLoading(false);
      setLoading(false);
      setRefreshing(false);
    });
  }, [selectedYear, getDateParams, refreshKey]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([
      syncAccount().catch(() => null),
      syncPositions().catch(() => null),
    ]);
    setRefreshKey(k => k + 1);
  };

  const handleDeepAnalysis = async () => {
    setDeepLoading(true);
    try {
      const result = await getPortfolioDeepAnalysis();
      if (result.error === 'no_positions') {
        setDeepAnalysis({ empty: true });
      } else if (result.error) {
        setDeepAnalysis({ error: result.error });
      } else {
        setDeepAnalysis(result);
      }
    } catch (e) {
      setDeepAnalysis({ error: e.message });
    }
    setDeepLoading(false);
  };

  const togglePosition = (ticker) => {
    setExpandedPositions(prev => ({ ...prev, [ticker]: !prev[ticker] }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
      </div>
    );
  }

  const stats = performance?.stats || {};
  const risk = performance?.risk || {};

  const sectorData = summary?.sector_exposure_pct
    ? Object.entries(summary.sector_exposure_pct).map(([name, value]) => ({ name, value: Math.round(value * 10) / 10 }))
    : [];

  const severityColors = {
    CRITICAL: 'border-red-500 bg-red-50',
    HIGH: 'border-orange-500 bg-orange-50',
    WARNING: 'border-yellow-500 bg-yellow-50',
    MEDIUM: 'border-blue-500 bg-blue-50',
    INFO: 'border-gray-200 bg-gray-50',
  };

  const chartData = equityCurve.map((d, i) => ({
    date: d.date ? d.date.slice(5) : `#${i}`,
    pnl: d.cumulative_pnl,
    ticker: d.ticker,
  }));

  const yearLabel = selectedYear === 'all' ? 'All Time' : selectedYear;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Portfolio Dashboard</h1>
          <p className="text-gray-500 text-sm">Systematic CSP Strategy Overview</p>
        </div>
        <div className="flex items-center gap-3">
          <YearTabBar selected={selectedYear} onChange={setSelectedYear} />
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-50"
            title="Refresh all data"
          >
            <RefreshCw size={16} className={`text-gray-500 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={() => onNavigate('new-trade')} className="btn-primary flex items-center gap-2">
            <Target size={16} /> New Trade
          </button>
        </div>
      </div>

      {/* Top metrics */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard
          label="Total Capital"
          value={`$${(summary?.total_capital || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}`}
          sublabel={`SGD ${Math.round((summary?.total_capital || 0) * 1.35).toLocaleString()}`}
          icon={DollarSign}
        />
        <MetricCard
          label="Capital Deployed"
          value={`${summary?.capital_utilization_pct?.toFixed(1) || 0}%`}
          sublabel={`$${(summary?.capital_deployed || 0).toLocaleString(undefined, {maximumFractionDigits: 0})} in use`}
          icon={Briefcase}
          trend={summary?.capital_utilization_pct > 70 ? 'down' : 'up'}
        />
        <MetricCard
          label={`${yearLabel} P&L`}
          value={`$${stats.total_pnl >= 0 ? '+' : ''}${(stats.total_pnl || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}`}
          sublabel={`${stats.total_trades || 0} trades closed`}
          icon={stats.total_pnl >= 0 ? TrendingUp : TrendingDown}
          color={stats.total_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}
          trend={stats.total_pnl >= 0 ? 'up' : 'down'}
        />
        <MetricCard
          label="Open Positions"
          value={summary?.open_positions_count || openTrades.length || 0}
          sublabel={`VIX: ${summary?.vix_level?.toFixed(1) || '—'} | ${summary?.regime?.replace(/_/g, ' ') || '—'}`}
          icon={Activity}
        />
      </div>

      {/* Performance stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900">Performance ({yearLabel})</h3>
            {perfLoading && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-400"></div>}
          </div>
          <div className="grid grid-cols-4 gap-4">
            <div>
              <p className="label">Win Rate</p>
              <p className={`text-2xl font-bold ${stats.win_rate >= 70 ? 'text-emerald-600' : stats.win_rate >= 50 ? 'text-gray-900' : 'text-red-600'}`}>
                {stats.win_rate || 0}%
              </p>
              <p className="text-xs text-gray-500">{stats.winners || 0}W / {stats.losers || 0}L</p>
            </div>
            <div>
              <p className="label">Profit Factor</p>
              <p className={`text-2xl font-bold ${stats.profit_factor >= 2 ? 'text-emerald-600' : stats.profit_factor >= 1 ? 'text-gray-900' : 'text-red-600'}`}>
                {stats.profit_factor >= 100 ? '∞' : stats.profit_factor || 0}
              </p>
              <p className="text-xs text-gray-500">Wins / Losses</p>
            </div>
            <div>
              <p className="label">Total Trades</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total_trades || 0}</p>
              <p className="text-xs text-gray-500">{stats.breakevens || 0} breakeven</p>
            </div>
            <div>
              <p className="label">Expectancy</p>
              <p className={`text-2xl font-bold ${stats.expectancy >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                ${stats.expectancy || 0}
              </p>
              <p className="text-xs text-gray-500">Per trade</p>
            </div>
            <div>
              <p className="label">Avg Win</p>
              <p className="text-lg font-bold text-emerald-600">${stats.avg_win_dollars || 0}</p>
            </div>
            <div>
              <p className="label">Avg Loss</p>
              <p className="text-lg font-bold text-red-600">${stats.avg_loss_dollars || 0}</p>
            </div>
            <div>
              <p className="label">Sharpe</p>
              <p className="text-lg font-bold text-gray-900">{risk.sharpe_ratio || 0}</p>
            </div>
            <div>
              <p className="label">Max Drawdown</p>
              <p className="text-lg font-bold text-red-600">${risk.max_drawdown || 0}</p>
            </div>
          </div>

          {/* Gross P&L bar */}
          <div className="mt-4 pt-4 border-t border-gray-200">
            <div className="flex items-center justify-between text-sm">
              <div>
                <span className="text-gray-400">Gross Wins: </span>
                <span className="font-bold text-emerald-600">+${(stats.gross_wins || 0).toLocaleString()}</span>
              </div>
              <div>
                <span className="text-gray-400">Gross Losses: </span>
                <span className="font-bold text-red-600">-${(stats.gross_losses || 0).toLocaleString()}</span>
              </div>
              <div>
                <span className="text-gray-400">Net: </span>
                <span className={`font-bold text-lg ${stats.total_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                  ${stats.total_pnl >= 0 ? '+' : ''}{(stats.total_pnl || 0).toLocaleString()}
                </span>
              </div>
            </div>
            <div className="mt-2 flex h-3 rounded-full overflow-hidden bg-gray-100">
              {stats.gross_wins > 0 && (
                <div className="bg-emerald-500 rounded-l-full transition-all duration-500"
                  style={{ width: `${(stats.gross_wins / (stats.gross_wins + stats.gross_losses)) * 100}%` }} />
              )}
              {stats.gross_losses > 0 && (
                <div className="bg-red-500 rounded-r-full transition-all duration-500"
                  style={{ width: `${(stats.gross_losses / (stats.gross_wins + stats.gross_losses)) * 100}%` }} />
              )}
            </div>
          </div>
        </div>

        {/* Sector exposure pie */}
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">Sector Exposure</h3>
          {sectorData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={sectorData} cx="50%" cy="50%" outerRadius={70} dataKey="value" label={({ name, value }) => `${name} ${value}%`}>
                  {sectorData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => `${value}%`} contentStyle={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: '8px', color: '#111' }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-500 text-sm text-center py-12">No open positions</p>
          )}
        </div>
      </div>

      {/* Equity Curve */}
      {chartData.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">Equity Curve ({yearLabel})</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={{ stroke: '#D1D5DB' }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={{ stroke: '#D1D5DB' }} tickFormatter={(v) => `$${v.toLocaleString()}`} />
              <Tooltip
                formatter={(value) => [`$${value.toLocaleString()}`, 'Cumulative P&L']}
                labelFormatter={(label) => `Date: ${label}`}
                contentStyle={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: '8px', color: '#111' }}
              />
              <Line type="monotone" dataKey="pnl" stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: '#3b82f6' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <AlertTriangle size={18} className="text-yellow-400" /> Active Alerts ({alerts.length})
          </h3>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {alerts.map((alert, i) => (
              <div key={i} className={`border-l-4 rounded-r-lg px-4 py-3 ${severityColors[alert.severity] || severityColors.INFO}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <span className={`badge ${alert.severity === 'CRITICAL' ? 'badge-red' : alert.severity === 'HIGH' ? 'badge-yellow' : 'badge-blue'} mr-2`}>
                      {alert.severity}
                    </span>
                    <span className="text-sm font-medium text-gray-700">{alert.message}</span>
                  </div>
                  {alert.ticker && <span className="font-mono text-xs text-gray-500">{alert.ticker}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Open positions table */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">Open Positions</h3>
          <button onClick={() => onNavigate('positions')} className="text-sm text-blue-600 hover:text-blue-500">View All →</button>
        </div>
        {openTrades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase">Ticker</th>
                  <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase">Strategy</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 uppercase">Strike</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 uppercase">Expiry</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 uppercase">DTE</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 uppercase">Premium</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 uppercase">Max Profit</th>
                  <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 uppercase">BP Used</th>
                </tr>
              </thead>
              <tbody>
                {openTrades.map(t => {
                  const dte = t.expiry ? Math.ceil((new Date(t.expiry) - new Date()) / 86400000) : null;
                  return (
                    <tr key={t.id} className="border-b border-gray-200 hover:bg-gray-50">
                      <td className="py-2.5 px-3 font-semibold text-gray-900">{t.ticker}</td>
                      <td className="py-2.5 px-3"><span className="badge badge-blue">{t.strategy}</span></td>
                      <td className="py-2.5 px-3 text-right font-mono text-gray-600">${t.strike}</td>
                      <td className="py-2.5 px-3 text-right text-gray-600">{t.expiry}</td>
                      <td className={`py-2.5 px-3 text-right font-mono ${dte && dte <= 21 ? 'text-red-600 font-bold' : dte && dte <= 45 ? 'text-yellow-600' : 'text-gray-600'}`}>
                        {dte || '—'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-gray-600">${t.premium_received?.toFixed(2)}</td>
                      <td className="py-2.5 px-3 text-right font-mono text-emerald-600">${t.max_profit?.toLocaleString()}</td>
                      <td className="py-2.5 px-3 text-right font-mono text-gray-600">${(t.buying_power_used || 0).toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-sm text-center py-8">No open positions. Click "New Trade" to get started.</p>
        )}
      </div>

      {/* ═══ Deep Portfolio Analysis ═══ */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <Brain size={18} className="text-purple-500" /> 持仓深度分析与建议
          </h3>
          <button
            onClick={handleDeepAnalysis}
            disabled={deepLoading || openTrades.length === 0}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all bg-gradient-to-r from-purple-500 to-indigo-500 text-white hover:from-purple-600 hover:to-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          >
            {deepLoading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
                AI 分析中...
              </>
            ) : (
              <>
                <Brain size={16} /> 开始 AI 深度分析
              </>
            )}
          </button>
        </div>

        {deepLoading && (
          <div className="flex flex-col items-center justify-center py-12 space-y-3">
            <div className="animate-spin rounded-full h-10 w-10 border-3 border-purple-200 border-t-purple-500"></div>
            <p className="text-sm text-gray-500">正在分析 {openTrades.length} 个持仓的实时数据...</p>
            <p className="text-xs text-gray-400">获取股价、技术指标、新闻情绪、VIX环境...</p>
          </div>
        )}

        {deepAnalysis && !deepLoading && deepAnalysis.empty && (
          <p className="text-gray-500 text-sm text-center py-8">当前没有持仓需要分析</p>
        )}

        {deepAnalysis && !deepLoading && deepAnalysis.error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            分析失败: {deepAnalysis.error}
          </div>
        )}

        {deepAnalysis && !deepLoading && deepAnalysis.analysis && (() => {
          const a = deepAnalysis.analysis;
          const ps = a.portfolio_summary || {};
          const positions = a.positions || [];
          const recs = a.recommendations || [];

          const riskColors = {
            '低': 'bg-emerald-100 text-emerald-700',
            '中': 'bg-yellow-100 text-yellow-700',
            '高': 'bg-orange-100 text-orange-700',
            '极高': 'bg-red-100 text-red-700',
          };
          const healthColors = {
            '健康': 'bg-emerald-100 text-emerald-700',
            '一般': 'bg-yellow-100 text-yellow-700',
            '需关注': 'bg-orange-100 text-orange-700',
            '危险': 'bg-red-100 text-red-700',
          };
          const actionColors = {
            '继续持有': 'text-emerald-600',
            '提前平仓': 'text-blue-600',
            '止损平仓': 'text-red-600',
            '滚仓': 'text-purple-600',
          };
          const urgencyBadge = {
            '立即': 'bg-red-100 text-red-700',
            '本周': 'bg-orange-100 text-orange-700',
            '可以等待': 'bg-gray-100 text-gray-600',
          };

          return (
            <div className="space-y-5">
              {/* Portfolio Summary Cards */}
              <div className="grid grid-cols-4 gap-3">
                <div className="bg-gray-50 rounded-lg px-4 py-3">
                  <p className="text-xs text-gray-500 mb-1">整体风险</p>
                  <span className={`inline-block px-2 py-0.5 rounded text-sm font-bold ${riskColors[ps.overall_risk] || 'bg-gray-100 text-gray-600'}`}>
                    {ps.overall_risk || 'N/A'}
                  </span>
                </div>
                <div className="bg-gray-50 rounded-lg px-4 py-3">
                  <p className="text-xs text-gray-500 mb-1">组合健康度</p>
                  <span className={`inline-block px-2 py-0.5 rounded text-sm font-bold ${healthColors[ps.overall_health] || 'bg-gray-100 text-gray-600'}`}>
                    {ps.overall_health || 'N/A'}
                  </span>
                </div>
                <div className="bg-gray-50 rounded-lg px-4 py-3">
                  <p className="text-xs text-gray-500 mb-1">资金效率</p>
                  <span className="text-sm font-bold text-gray-900">{ps.capital_efficiency || 'N/A'}</span>
                </div>
                <div className="bg-gray-50 rounded-lg px-4 py-3">
                  <p className="text-xs text-gray-500 mb-1">极端情景</p>
                  <p className="text-xs text-red-600 font-medium leading-tight">{ps.max_loss_scenario || 'N/A'}</p>
                </div>
              </div>

              {/* Key Concerns */}
              {ps.key_concerns && ps.key_concerns.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                  <p className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1">
                    <AlertTriangle size={14} /> 主要关注点
                  </p>
                  <ul className="space-y-1">
                    {ps.key_concerns.map((c, i) => (
                      <li key={i} className="text-sm text-amber-800 flex items-start gap-2">
                        <span className="text-amber-400 mt-0.5">•</span> {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Per-Position Analysis */}
              <div>
                <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                  <Shield size={16} className="text-blue-500" /> 逐仓分析
                </h4>
                <div className="space-y-2">
                  {positions.map((p, i) => {
                    const expanded = expandedPositions[p.ticker];
                    return (
                      <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
                        <button
                          onClick={() => togglePosition(p.ticker)}
                          className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                        >
                          <div className="flex items-center gap-3">
                            <span className="font-bold text-gray-900 text-sm">{p.ticker}</span>
                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${riskColors[p.risk_level] || 'bg-gray-100 text-gray-600'}`}>
                              风险{p.risk_level}
                            </span>
                            <span className={`text-sm font-medium ${actionColors[p.action] || 'text-gray-600'}`}>
                              → {p.action}
                            </span>
                            {p.urgency && (
                              <span className={`px-1.5 py-0.5 rounded text-xs ${urgencyBadge[p.urgency] || 'bg-gray-100 text-gray-600'}`}>
                                {p.urgency}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-500">{p.status}</span>
                            {expanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
                          </div>
                        </button>
                        {expanded && (
                          <div className="px-4 pb-3 border-t border-gray-100 bg-gray-50">
                            <div className="mt-2 space-y-2">
                              <div className="text-sm text-gray-600">
                                <span className="font-medium text-gray-700">安全边际:</span> {p.safety_margin}
                              </div>
                              <div className="text-sm text-gray-700 leading-relaxed">{p.reasoning}</div>
                              {p.profit_potential && (
                                <div className="text-sm text-gray-600">
                                  <span className="font-medium text-gray-700">收益预期:</span> {p.profit_potential}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Recommendations */}
              {recs.length > 0 && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
                  <p className="text-xs font-semibold text-blue-700 mb-2">📋 操作建议</p>
                  <ul className="space-y-2">
                    {recs.map((r, i) => (
                      <li key={i} className="text-sm text-blue-900 flex items-start gap-2">
                        <span className="bg-blue-200 text-blue-700 rounded-full w-5 h-5 flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5">{i + 1}</span>
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Hedge & Sector Advice */}
              <div className="grid grid-cols-2 gap-3">
                {a.hedge_suggestion && (
                  <div className="bg-purple-50 border border-purple-200 rounded-lg px-4 py-3">
                    <p className="text-xs font-semibold text-purple-700 mb-1">🛡️ 对冲建议</p>
                    <p className="text-sm text-purple-900">{a.hedge_suggestion}</p>
                  </div>
                )}
                {a.sector_advice && (
                  <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3">
                    <p className="text-xs font-semibold text-indigo-700 mb-1">📊 板块调仓</p>
                    <p className="text-sm text-indigo-900">{a.sector_advice}</p>
                  </div>
                )}
              </div>

              {/* Timestamp */}
              {deepAnalysis.timestamp && (
                <p className="text-xs text-gray-400 text-right">
                  分析时间: {new Date(deepAnalysis.timestamp).toLocaleString('zh-CN')}
                </p>
              )}
            </div>
          );
        })()}

        {!deepAnalysis && !deepLoading && openTrades.length > 0 && (
          <div className="text-center py-8 text-gray-400 text-sm">
            点击上方按钮，AI 将分析每个持仓的实时数据并给出操作建议
          </div>
        )}
      </div>
    </div>
  );
}
