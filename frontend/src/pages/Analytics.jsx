import React, { useState, useEffect } from 'react';
import { fetchPerformance, fetchEquityCurve, fetchMonthlyHeatmap, fetchPnLDistribution, fetchBreakdown } from '../api.js';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from 'recharts';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function StatRow({ label, value, color }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-gray-200">
      <span className="text-gray-500 text-sm">{label}</span>
      <span className={`font-mono font-bold text-sm ${color || ''}`}>{value}</span>
    </div>
  );
}

export default function Analytics() {
  const [performance, setPerformance] = useState(null);
  const [equityCurve, setEquityCurve] = useState([]);
  const [heatmap, setHeatmap] = useState([]);
  const [distribution, setDistribution] = useState(null);
  const [breakdown, setBreakdown] = useState(null);
  const [activeBreakdown, setActiveBreakdown] = useState('by_strategy');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchPerformance().catch(() => null),
      fetchEquityCurve().catch(() => []),
      fetchMonthlyHeatmap().catch(() => []),
      fetchPnLDistribution().catch(() => null),
      fetchBreakdown().catch(() => null),
    ]).then(([perf, curve, heat, dist, bd]) => {
      setPerformance(perf);
      setEquityCurve(curve);
      setHeatmap(heat);
      setDistribution(dist);
      setBreakdown(bd);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-navy-700"></div></div>;
  }

  const stats = performance?.stats || {};
  const risk = performance?.risk || {};
  const noData = !stats.total_trades;

  // Build heatmap grid by year
  const heatmapByYear = {};
  heatmap.forEach(h => {
    if (!heatmapByYear[h.year]) heatmapByYear[h.year] = {};
    heatmapByYear[h.year][h.month] = h.pnl;
  });

  const breakdownOptions = breakdown ? Object.keys(breakdown) : [];
  const activeData = breakdown?.[activeBreakdown] || {};

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
        <p className="text-gray-500 text-sm">Performance metrics and strategy analysis</p>
      </div>

      {noData ? (
        <div className="card shadow-sm text-center py-16">
          <p className="text-gray-500 text-lg">No closed trades yet. Analytics will appear after you close your first trade.</p>
        </div>
      ) : (
        <>
          {/* Overall stats + Risk metrics */}
          <div className="grid grid-cols-2 gap-4">
            <div className="card shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-3">Performance Stats</h3>
              <StatRow label="Total Trades" value={stats.total_trades} />
              <StatRow label="Win Rate" value={`${stats.win_rate}%`} color={stats.win_rate >= 70 ? 'text-emerald-600' : ''} />
              <StatRow label="Profit Factor" value={stats.profit_factor} color={stats.profit_factor >= 2 ? 'text-emerald-600' : ''} />
              <StatRow label="Expectancy" value={`$${stats.expectancy}`} />
              <StatRow label="Avg Winner" value={`$${stats.avg_win_dollars}`} color="text-emerald-600" />
              <StatRow label="Avg Loser" value={`$${stats.avg_loss_dollars}`} color="text-red-600" />
              <StatRow label="Total P&L" value={`$${stats.total_pnl?.toLocaleString()}`}
                color={stats.total_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'} />
              <StatRow label="Winners / Losers" value={`${stats.winners}W / ${stats.losers}L`} />
            </div>
            <div className="card shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-3">Risk Metrics</h3>
              <StatRow label="Sharpe Ratio" value={risk.sharpe_ratio} color={risk.sharpe_ratio >= 1.5 ? 'text-emerald-600' : ''} />
              <StatRow label="Sortino Ratio" value={risk.sortino_ratio} />
              <StatRow label="Max Drawdown" value={`$${risk.max_drawdown?.toLocaleString()}`} color="text-red-600" />
              <StatRow label="Max DD Duration" value={`${risk.max_drawdown_duration_days} trades`} />
              <StatRow label="Current Drawdown" value={`$${risk.current_drawdown?.toLocaleString()}`}
                color={risk.current_drawdown > 0 ? 'text-red-600' : ''} />
              <StatRow label="Max Win Streak" value={risk.max_win_streak} color="text-emerald-600" />
              <StatRow label="Max Loss Streak" value={risk.max_loss_streak} color="text-red-600" />
              <StatRow label="Current Streak" value={`${risk.current_streak} ${risk.current_streak_type}`} />
            </div>
          </div>

          {/* Equity Curve */}
          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-4">Equity Curve</h3>
            {equityCurve.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={equityCurve}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={{ stroke: '#D1D5DB' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={{ stroke: '#D1D5DB' }} tickFormatter={v => `$${v.toLocaleString()}`} />
                  <Tooltip formatter={(v) => [`$${v.toLocaleString()}`, 'Cumulative P&L']}
                    labelFormatter={l => `Date: ${l}`}
                    contentStyle={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: '8px', color: '#111' }} />
                  <Line type="monotone" dataKey="cumulative_pnl" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm text-center py-12">No data available</p>
            )}
          </div>

          {/* Monthly Returns Heatmap */}
          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-4">Monthly Returns</h3>
            {Object.keys(heatmapByYear).length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="py-2 px-3 text-left font-semibold text-gray-500">Year</th>
                      {MONTHS.map(m => <th key={m} className="py-2 px-3 text-center font-semibold text-gray-500">{m}</th>)}
                      <th className="py-2 px-3 text-center font-semibold text-gray-500">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(heatmapByYear).sort().map(([year, months]) => {
                      const total = Object.values(months).reduce((a, b) => a + b, 0);
                      return (
                        <tr key={year} className="border-t border-gray-200">
                          <td className="py-2 px-3 font-bold">{year}</td>
                          {Array.from({ length: 12 }, (_, i) => i + 1).map(m => {
                            const val = months[m];
                            const bg = val === undefined ? '' : val >= 0 ? `rgba(5,150,105,${Math.min(Math.abs(val) / 3000, 0.7)})` : `rgba(220,38,38,${Math.min(Math.abs(val) / 3000, 0.7)})`;
                            return (
                              <td key={m} className="py-2 px-3 text-center font-mono" style={{ backgroundColor: bg }}>
                                {val !== undefined ? `$${val.toLocaleString()}` : '—'}
                              </td>
                            );
                          })}
                          <td className={`py-2 px-3 text-center font-mono font-bold ${total >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                            ${total.toLocaleString()}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-gray-500 text-sm text-center py-8">No monthly data</p>
            )}
          </div>

          {/* P&L Distribution */}
          {distribution && distribution.pnls?.length > 0 && (
            <div className="card shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-4">P&L Distribution</h3>
              <div className="grid grid-cols-4 gap-4 mb-4 text-sm">
                <div><span className="label">Mean</span><p className="font-mono font-bold">${distribution.mean}</p></div>
                <div><span className="label">Std Dev</span><p className="font-mono font-bold">${distribution.stdev}</p></div>
                <div><span className="label">Skew</span><p className="font-mono font-bold">{distribution.skew}</p></div>
                <div><span className="label">Kurtosis</span><p className="font-mono font-bold">{distribution.kurtosis}</p></div>
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={distribution.pnls.map((p, i) => ({ idx: i, pnl: p }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                  <XAxis dataKey="idx" tick={false} axisLine={{ stroke: '#D1D5DB' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={{ stroke: '#D1D5DB' }} tickFormatter={v => `$${v}`} />
                  <Tooltip formatter={(v) => [`$${v}`, 'P&L']}
                    contentStyle={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: '8px', color: '#111' }} />
                  <Bar dataKey="pnl">
                    {distribution.pnls.map((p, i) => (
                      <Cell key={i} fill={p >= 0 ? '#059669' : '#dc2626'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Strategy Breakdown */}
          {breakdown && (
            <div className="card shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900">Strategy Breakdown</h3>
                <div className="flex gap-1">
                  {breakdownOptions.map(opt => (
                    <button key={opt} onClick={() => setActiveBreakdown(opt)}
                      className={`text-xs px-3 py-1 rounded-full transition-colors ${
                        activeBreakdown === opt ? 'bg-white text-gray-900 shadow-sm' : 'bg-gray-100 text-gray-600 hover:bg-gray-50'
                      }`}>
                      {opt.replace('by_', '').replace(/_/g, ' ')}
                    </button>
                  ))}
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="py-2 px-3 text-left font-semibold text-gray-500">Category</th>
                      <th className="py-2 px-3 text-right font-semibold text-gray-500">Trades</th>
                      <th className="py-2 px-3 text-right font-semibold text-gray-500">Win Rate</th>
                      <th className="py-2 px-3 text-right font-semibold text-gray-500">Profit Factor</th>
                      <th className="py-2 px-3 text-right font-semibold text-gray-500">Avg Win</th>
                      <th className="py-2 px-3 text-right font-semibold text-gray-500">Avg Loss</th>
                      <th className="py-2 px-3 text-right font-semibold text-gray-500">Total P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(activeData).sort((a, b) => b[1].total_pnl - a[1].total_pnl).map(([key, s]) => (
                      <tr key={key} className="border-b border-gray-200 hover:bg-gray-50">
                        <td className="py-2 px-3 font-semibold">{key}</td>
                        <td className="py-2 px-3 text-right font-mono">{s.total_trades}</td>
                        <td className="py-2 px-3 text-right font-mono">{s.win_rate}%</td>
                        <td className="py-2 px-3 text-right font-mono">{s.profit_factor}</td>
                        <td className="py-2 px-3 text-right font-mono text-emerald-600">${s.avg_win_dollars}</td>
                        <td className="py-2 px-3 text-right font-mono text-red-600">${s.avg_loss_dollars}</td>
                        <td className={`py-2 px-3 text-right font-mono font-bold ${s.total_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                          ${s.total_pnl?.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
