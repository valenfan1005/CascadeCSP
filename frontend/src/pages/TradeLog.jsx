import React, { useState, useEffect } from 'react';
import { fetchTrades, deleteTrade } from '../api.js';
import { Trash2, Download, Filter } from 'lucide-react';

export default function TradeLog() {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ status: '', ticker: '', strategy: '' });
  const [showFilters, setShowFilters] = useState(false);

  const load = () => {
    setLoading(true);
    const params = {};
    if (filter.status) params.status = filter.status;
    if (filter.ticker) params.ticker = filter.ticker;
    if (filter.strategy) params.strategy = filter.strategy;
    fetchTrades(params).then(setTrades).catch(() => setTrades([])).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [filter.status, filter.strategy]);

  const handleTickerSearch = (e) => {
    if (e.key === 'Enter') load();
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this trade? This cannot be undone.')) return;
    try {
      await deleteTrade(id);
      load();
    } catch (err) {
      alert(err.message);
    }
  };

  const exportCSV = () => {
    window.open('/api/reports/export/trades' + (filter.status ? `?status=${filter.status}` : ''), '_blank');
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Trade Log</h1>
          <p className="text-gray-500 text-sm">{trades.length} trades</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowFilters(!showFilters)} className="btn-secondary flex items-center gap-2 text-sm">
            <Filter size={14} /> Filters
          </button>
          <button onClick={exportCSV} className="btn-secondary flex items-center gap-2 text-sm">
            <Download size={14} /> Export CSV
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="card flex items-center gap-4">
          <div>
            <label className="label">Status</label>
            <select value={filter.status} onChange={e => setFilter({ ...filter, status: e.target.value })} className="input-field w-32">
              <option value="">All</option>
              <option value="OPEN">Open</option>
              <option value="CLOSED">Closed</option>
            </select>
          </div>
          <div>
            <label className="label">Ticker</label>
            <input value={filter.ticker} onChange={e => setFilter({ ...filter, ticker: e.target.value })}
              onKeyDown={handleTickerSearch} className="input-field w-28 uppercase font-mono" placeholder="NVDA" />
          </div>
          <div>
            <label className="label">Strategy</label>
            <select value={filter.strategy} onChange={e => setFilter({ ...filter, strategy: e.target.value })} className="input-field w-40">
              <option value="">All</option>
              <option value="CSP">CSP</option>
              <option value="PUT_SPREAD">Put Spread</option>
              <option value="COVERED_CALL">Covered Call</option>
              <option value="IRON_CONDOR">Iron Condor</option>
            </select>
          </div>
          <div className="flex items-end">
            <button onClick={load} className="btn-primary text-sm">Apply</button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-navy-700"></div>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="py-2 px-2 text-left font-semibold text-gray-500 uppercase">Date</th>
                <th className="py-2 px-2 text-left font-semibold text-gray-500 uppercase">Ticker</th>
                <th className="py-2 px-2 text-left font-semibold text-gray-500 uppercase">Strategy</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">Strike</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">Expiry</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">Qty</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">Prem In</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">Prem Out</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">P&L</th>
                <th className="py-2 px-2 text-right font-semibold text-gray-500 uppercase">P&L %</th>
                <th className="py-2 px-2 text-left font-semibold text-gray-500 uppercase">Exit</th>
                <th className="py-2 px-2 text-left font-semibold text-gray-500 uppercase">Status</th>
                <th className="py-2 px-2"></th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2 px-2">{t.trade_date_open?.split('T')[0]}</td>
                  <td className="py-2 px-2 font-semibold">{t.ticker}</td>
                  <td className="py-2 px-2"><span className="badge badge-blue">{t.strategy}</span></td>
                  <td className="py-2 px-2 text-right font-mono">${t.strike}</td>
                  <td className="py-2 px-2 text-right">{t.expiry}</td>
                  <td className="py-2 px-2 text-right font-mono">{t.contracts}</td>
                  <td className="py-2 px-2 text-right font-mono">${t.premium_received?.toFixed(2)}</td>
                  <td className="py-2 px-2 text-right font-mono">{t.premium_close ? `$${t.premium_close.toFixed(2)}` : '—'}</td>
                  <td className={`py-2 px-2 text-right font-mono font-bold ${
                    t.pnl_dollars > 0 ? 'text-emerald-600' : t.pnl_dollars < 0 ? 'text-red-600' : ''
                  }`}>
                    {t.pnl_dollars != null ? `$${t.pnl_dollars.toFixed(0)}` : '—'}
                  </td>
                  <td className={`py-2 px-2 text-right font-mono ${
                    t.pnl_percent > 0 ? 'text-emerald-600' : t.pnl_percent < 0 ? 'text-red-600' : ''
                  }`}>
                    {t.pnl_percent != null ? `${t.pnl_percent.toFixed(1)}%` : '—'}
                  </td>
                  <td className="py-2 px-2 text-xs">{t.exit_reason?.replace(/_/g, ' ') || '—'}</td>
                  <td className="py-2 px-2">
                    <span className={`badge ${t.status === 'OPEN' ? 'badge-green' : 'badge-gray'}`}>{t.status}</span>
                  </td>
                  <td className="py-2 px-2">
                    <button onClick={() => handleDelete(t.id)} className="text-gray-400 hover:text-red-500 transition-colors">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-8">No trades found</p>
          )}
        </div>
      )}
    </div>
  );
}
