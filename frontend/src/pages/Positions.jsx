import React, { useState, useEffect } from 'react';
import { fetchOpenTrades, closeTrade } from '../api.js';
import { X, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';

export default function Positions({ onNavigate }) {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [closingId, setClosingId] = useState(null);
  const [closeForm, setCloseForm] = useState({ premium_close: '', exit_reason: 'TARGET_HIT', underlying_price_close: '', vix_at_close: '', notes: '' });
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    setLoading(true);
    fetchOpenTrades().then(setTrades).catch(() => setTrades([])).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleClose = async (id) => {
    setSubmitting(true);
    try {
      await closeTrade(id, {
        premium_close: parseFloat(closeForm.premium_close),
        exit_reason: closeForm.exit_reason,
        underlying_price_close: closeForm.underlying_price_close ? parseFloat(closeForm.underlying_price_close) : null,
        vix_at_close: closeForm.vix_at_close ? parseFloat(closeForm.vix_at_close) : null,
        notes: closeForm.notes || null,
      });
      setClosingId(null);
      setCloseForm({ premium_close: '', exit_reason: 'TARGET_HIT', underlying_price_close: '', vix_at_close: '', notes: '' });
      load();
    } catch (err) {
      alert(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-navy-700"></div></div>;
  }

  const EXIT_REASONS = ['TARGET_HIT', 'STOP_HIT', 'TIME_EXIT', 'EXPIRY_WORTHLESS', 'EXPIRY_ITM', 'MANUAL', 'ADJUSTMENT', 'REGIME_SHIFT'];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Open Positions</h1>
          <p className="text-gray-500 text-sm">{trades.length} active position{trades.length !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={() => onNavigate('new-trade')} className="btn-primary">+ New Trade</button>
      </div>

      {trades.length === 0 ? (
        <div className="card text-center py-16">
          <p className="text-gray-500 text-lg mb-4">No open positions</p>
          <button onClick={() => onNavigate('new-trade')} className="btn-primary">Open Your First Trade</button>
        </div>
      ) : (
        <div className="space-y-4">
          {trades.map(t => {
            const dte = t.expiry ? Math.ceil((new Date(t.expiry) - new Date()) / 86400000) : null;
            const profitTarget50 = t.premium_received ? (t.premium_received * 0.5).toFixed(2) : null;
            const isExpanding = closingId === t.id;

            return (
              <div key={t.id} className="card">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-6">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold">{t.ticker}</span>
                        <span className="badge badge-blue">{t.strategy}</span>
                        <span className="badge badge-gray">{t.sector}</span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1">{t.direction} {t.contracts}x ${t.strike} Put | Exp {t.expiry}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-8 text-sm">
                    <div className="text-right">
                      <p className="label">Premium</p>
                      <p className="font-mono font-bold">${t.premium_received?.toFixed(2)}</p>
                    </div>
                    <div className="text-right">
                      <p className="label">BP Used</p>
                      <p className="font-mono">${(t.buying_power_used || 0).toLocaleString()}</p>
                    </div>
                    <div className="text-right">
                      <p className="label">DTE</p>
                      <p className={`font-mono font-bold ${dte <= 21 ? 'text-red-600' : dte <= 30 ? 'text-yellow-600' : 'text-gray-900'}`}>{dte ?? '—'}</p>
                    </div>
                    <div className="text-right">
                      <p className="label">50% Target</p>
                      <p className="font-mono text-emerald-600">${profitTarget50 || '—'}</p>
                    </div>

                    <div className="flex gap-2">
                      <button
                        onClick={() => setClosingId(isExpanding ? null : t.id)}
                        className="btn-danger text-xs py-1.5 flex items-center gap-1"
                      >
                        Close {isExpanding ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Progress bar: % of profit target */}
                {t.premium_received > 0 && (
                  <div className="mt-3">
                    <div className="flex justify-between text-[10px] text-gray-500 mb-1">
                      <span>Open</span>
                      <span>50% Target (${(t.premium_received * 0.5).toFixed(2)})</span>
                      <span>Max Profit (${t.premium_received.toFixed(2)})</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className="bg-emerald-500 h-2 rounded-full" style={{ width: '0%' }}></div>
                    </div>
                  </div>
                )}

                {/* Close form */}
                {isExpanding && (
                  <div className="mt-4 pt-4 border-t border-gray-200">
                    <div className="grid grid-cols-5 gap-3">
                      <div>
                        <label className="label">Close Premium</label>
                        <input type="number" step="0.01" value={closeForm.premium_close}
                          onChange={e => setCloseForm({ ...closeForm, premium_close: e.target.value })}
                          className="input-field font-mono" placeholder="1.20" required />
                      </div>
                      <div>
                        <label className="label">Exit Reason</label>
                        <select value={closeForm.exit_reason}
                          onChange={e => setCloseForm({ ...closeForm, exit_reason: e.target.value })}
                          className="input-field">
                          {EXIT_REASONS.map(r => <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="label">Stock Price</label>
                        <input type="number" step="0.01" value={closeForm.underlying_price_close}
                          onChange={e => setCloseForm({ ...closeForm, underlying_price_close: e.target.value })}
                          className="input-field font-mono" placeholder="Optional" />
                      </div>
                      <div>
                        <label className="label">VIX at Close</label>
                        <input type="number" step="0.01" value={closeForm.vix_at_close}
                          onChange={e => setCloseForm({ ...closeForm, vix_at_close: e.target.value })}
                          className="input-field font-mono" placeholder="Optional" />
                      </div>
                      <div className="flex items-end">
                        <button
                          onClick={() => handleClose(t.id)}
                          disabled={!closeForm.premium_close || submitting}
                          className="btn-danger w-full flex items-center justify-center gap-2"
                        >
                          {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
                          Confirm Close
                        </button>
                      </div>
                    </div>
                    {closeForm.premium_close && (
                      <div className="mt-2 text-sm">
                        <span className="text-gray-500">Estimated P&L: </span>
                        <span className={`font-mono font-bold ${
                          (t.premium_received - parseFloat(closeForm.premium_close)) >= 0 ? 'text-emerald-600' : 'text-red-600'
                        }`}>
                          ${((t.premium_received - parseFloat(closeForm.premium_close)) * t.contracts * 100).toFixed(2)}
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {t.notes && (
                  <p className="mt-2 text-xs text-gray-500 italic">{t.notes}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
