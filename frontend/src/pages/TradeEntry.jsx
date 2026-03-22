import React, { useState, useEffect } from 'react';
import { createTrade, fetchUniverse, fetchStockPrice, runPreTradeCheck, fetchPortfolioSummary } from '../api.js';
import { CheckCircle, XCircle, AlertTriangle, Loader2, Shield, TrendingDown, DollarSign } from 'lucide-react';

const STRATEGIES = ['CSP', 'PUT_SPREAD', 'IRON_CONDOR', 'COVERED_CALL', 'OTHER'];
const EXIT_REASONS = ['TARGET_HIT', 'STOP_HIT', 'TIME_EXIT', 'EXPIRY_WORTHLESS', 'EXPIRY_ITM', 'MANUAL', 'ADJUSTMENT', 'REGIME_SHIFT'];

export default function TradeEntry({ marketData, onSuccess }) {
  const [universe, setUniverse] = useState({});
  const [form, setForm] = useState({
    ticker: '', sector: '', strategy: 'CSP', direction: 'SELL',
    strike: '', strike_long: '', expiry: '', contracts: 1,
    premium_received: '', underlying_price_open: '',
    delta_at_entry: '', iv_at_entry: '', iv_rank_at_entry: '',
    vix_at_entry: marketData?.vix?.toFixed(2) || '',
    buying_power_used: '', market_regime: marketData?.regime || '',
    notes: '',
  });
  const [compliance, setCompliance] = useState(null);
  const [riskCheck, setRiskCheck] = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [priceLoading, setPriceLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  // Load universe
  useEffect(() => {
    fetchUniverse().then(setUniverse).catch(() => {});
  }, []);

  // Auto-detect sector from ticker
  useEffect(() => {
    if (form.ticker) {
      for (const [sector, tickers] of Object.entries(universe)) {
        const found = tickers.find(t => t.ticker === form.ticker.toUpperCase());
        if (found) {
          setForm(f => ({ ...f, sector }));
          break;
        }
      }
    }
  }, [form.ticker, universe]);

  // Auto-calculate buying power
  useEffect(() => {
    if (form.strike && form.contracts) {
      let bp;
      if (form.strategy === 'CSP') {
        bp = parseFloat(form.strike) * 100 * parseInt(form.contracts);
      } else if (form.strategy === 'PUT_SPREAD' && form.strike_long) {
        bp = Math.abs(parseFloat(form.strike) - parseFloat(form.strike_long)) * 100 * parseInt(form.contracts);
      }
      if (bp) setForm(f => ({ ...f, buying_power_used: bp.toFixed(0) }));
    }
  }, [form.strike, form.strike_long, form.contracts, form.strategy]);

  // Auto-calculate computed fields
  const dte = form.expiry ? Math.ceil((new Date(form.expiry) - new Date()) / 86400000) : null;
  const breakeven = form.strike && form.premium_received ? (parseFloat(form.strike) - parseFloat(form.premium_received)).toFixed(2) : null;
  const maxProfit = form.premium_received && form.contracts ? (parseFloat(form.premium_received) * parseInt(form.contracts) * 100).toFixed(0) : null;
  const maxLoss = form.strike && form.premium_received && form.contracts
    ? form.strategy === 'PUT_SPREAD' && form.strike_long
      ? ((Math.abs(parseFloat(form.strike) - parseFloat(form.strike_long)) - parseFloat(form.premium_received)) * parseInt(form.contracts) * 100).toFixed(0)
      : ((parseFloat(form.strike) - parseFloat(form.premium_received)) * parseInt(form.contracts) * 100).toFixed(0)
    : null;

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
    setCompliance(null);
  };

  const fetchPrice = async () => {
    if (!form.ticker) return;
    setPriceLoading(true);
    try {
      const data = await fetchStockPrice(form.ticker);
      if (data.price) {
        setForm(f => ({ ...f, underlying_price_open: data.price.toFixed(2) }));
      }
    } catch {} finally {
      setPriceLoading(false);
    }
  };

  const checkCompliance = async () => {
    const summary = await fetchPortfolioSummary().catch(() => ({ total_capital: 220000 }));
    setCompliance({ loading: true });
    try {
      const result = await runPreTradeCheck({
        ticker: form.ticker.toUpperCase(),
        strike: parseFloat(form.strike) || 0,
        strike_long: form.strike_long ? parseFloat(form.strike_long) : null,
        expiry: form.expiry,
        strategy: form.strategy,
        direction: form.direction,
        contracts: parseInt(form.contracts) || 1,
        premium: form.premium_received ? parseFloat(form.premium_received) : null,
      });
      setRiskCheck(result);

      // Auto-fill fields from live data
      if (result.position?.stock_price && !form.underlying_price_open) {
        setForm(f => ({ ...f, underlying_price_open: result.position.stock_price.toFixed(2) }));
      }
      if (result.position?.estimated_delta && !form.delta_at_entry) {
        setForm(f => ({ ...f, delta_at_entry: result.position.estimated_delta.toFixed(3) }));
      }
      if (result.position?.option?.iv && !form.iv_at_entry) {
        setForm(f => ({ ...f, iv_at_entry: result.position.option.iv.toFixed(1) }));
      }
      if (result.market?.vix) {
        setForm(f => ({ ...f, vix_at_entry: result.market.vix.toFixed(2) }));
      }
      if (result.market?.regime) {
        setForm(f => ({ ...f, market_regime: result.market.regime }));
      }
      if (result.position?.option?.mid && !form.premium_received) {
        setForm(f => ({ ...f, premium_received: result.position.option.mid.toFixed(2) }));
      }
      if (result.position?.volatility?.iv_rank != null && !form.iv_rank_at_entry) {
        setForm(f => ({ ...f, iv_rank_at_entry: String(result.position.volatility.iv_rank) }));
      }

      setCompliance(result);
    } catch (err) {
      setCompliance({ error: err.message });
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload = {
        ticker: form.ticker.toUpperCase(),
        sector: form.sector,
        strategy: form.strategy,
        direction: form.direction,
        strike: parseFloat(form.strike),
        strike_long: form.strike_long ? parseFloat(form.strike_long) : null,
        expiry: form.expiry,
        contracts: parseInt(form.contracts),
        premium_received: parseFloat(form.premium_received),
        underlying_price_open: form.underlying_price_open ? parseFloat(form.underlying_price_open) : null,
        delta_at_entry: form.delta_at_entry ? parseFloat(form.delta_at_entry) : null,
        iv_at_entry: form.iv_at_entry ? parseFloat(form.iv_at_entry) : null,
        iv_rank_at_entry: form.iv_rank_at_entry ? parseFloat(form.iv_rank_at_entry) : null,
        vix_at_entry: form.vix_at_entry ? parseFloat(form.vix_at_entry) : null,
        buying_power_used: form.buying_power_used ? parseFloat(form.buying_power_used) : null,
        market_regime: form.market_regime || null,
        notes: form.notes || null,
      };
      await createTrade(payload);
      setSuccess(true);
      setTimeout(() => onSuccess?.(), 1500);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // All tickers flat list for autocomplete
  const allTickers = Object.values(universe).flat().map(t => t.ticker);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">New Trade Entry</h1>
        <p className="text-gray-500 text-sm">Log a new options position</p>
      </div>

      {success && (
        <div className="bg-emerald-500/10 border border-emerald-200 rounded-lg p-4 flex items-center gap-3">
          <CheckCircle className="text-emerald-400" size={20} />
          <span className="text-emerald-800 font-medium">Trade created successfully!</span>
        </div>
      )}
      {error && (
        <div className="bg-red-500/10 border border-red-200 rounded-lg p-4 flex items-center gap-3">
          <XCircle className="text-red-400" size={20} />
          <span className="text-red-800">{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="grid grid-cols-3 gap-6">
        {/* Left: Core trade details */}
        <div className="col-span-2 space-y-6">
          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-4">Trade Details</h3>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="label">Ticker</label>
                <div className="flex gap-2">
                  <input name="ticker" value={form.ticker} onChange={handleChange} list="ticker-list"
                    className="input-field flex-1 font-mono uppercase bg-white text-gray-900 border-gray-300" placeholder="NVDA" required />
                  <datalist id="ticker-list">
                    {allTickers.map(t => <option key={t} value={t} />)}
                  </datalist>
                  <button type="button" onClick={fetchPrice} className="btn-secondary text-xs px-3" disabled={priceLoading}>
                    {priceLoading ? <Loader2 size={14} className="animate-spin" /> : '$'}
                  </button>
                </div>
              </div>
              <div>
                <label className="label">Sector</label>
                <select name="sector" value={form.sector} onChange={handleChange} className="input-field bg-white text-gray-900 border-gray-300" required>
                  <option value="">Select...</option>
                  {Object.keys(universe).map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Strategy</label>
                <select name="strategy" value={form.strategy} onChange={handleChange} className="input-field bg-white text-gray-900 border-gray-300">
                  {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Strike Price</label>
                <input name="strike" type="number" step="0.5" value={form.strike} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="180.00" required />
              </div>
              {(form.strategy === 'PUT_SPREAD' || form.strategy === 'IRON_CONDOR') && (
                <div>
                  <label className="label">Long Strike</label>
                  <input name="strike_long" type="number" step="0.5" value={form.strike_long} onChange={handleChange}
                    className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="175.00" />
                </div>
              )}
              <div>
                <label className="label">Expiry Date</label>
                <input name="expiry" type="date" value={form.expiry} onChange={handleChange} className="input-field bg-white text-gray-900 border-gray-300" required />
              </div>
              <div>
                <label className="label">Contracts</label>
                <input name="contracts" type="number" min="1" value={form.contracts} onChange={handleChange} className="input-field font-mono bg-white text-gray-900 border-gray-300" />
              </div>
              <div>
                <label className="label">Premium Received</label>
                <input name="premium_received" type="number" step="0.01" value={form.premium_received} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="2.50" required />
              </div>
              <div>
                <label className="label">Underlying Price</label>
                <input name="underlying_price_open" type="number" step="0.01" value={form.underlying_price_open} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="195.00" />
              </div>
            </div>
          </div>

          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-4">Greeks & Volatility</h3>
            <div className="grid grid-cols-4 gap-4">
              <div>
                <label className="label">Delta at Entry</label>
                <input name="delta_at_entry" type="number" step="0.01" min="-1" max="0" value={form.delta_at_entry} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="-0.20" />
              </div>
              <div>
                <label className="label">IV at Entry (%)</label>
                <input name="iv_at_entry" type="number" step="0.1" value={form.iv_at_entry} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="35.5" />
              </div>
              <div>
                <label className="label">IV Rank (0-100)</label>
                <input name="iv_rank_at_entry" type="number" step="0.1" min="0" max="100" value={form.iv_rank_at_entry} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="45" />
              </div>
              <div>
                <label className="label">VIX Level</label>
                <input name="vix_at_entry" type="number" step="0.01" value={form.vix_at_entry} onChange={handleChange}
                  className="input-field font-mono bg-white text-gray-900 border-gray-300" placeholder="18.5" />
              </div>
            </div>
          </div>

          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-4">Notes</h3>
            <textarea name="notes" value={form.notes} onChange={handleChange} rows={3}
              className="input-field bg-white text-gray-900 border-gray-300" placeholder="Trade thesis, market observations, catalysts..." />
          </div>
        </div>

        {/* Right sidebar: Computed fields + Risk Check */}
        <div className="space-y-6">
          {/* Auto-calculated */}
          <div className="card bg-gray-50 shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-4">Calculated</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">DTE</span>
                <span className={`font-mono font-bold ${dte && dte < 30 ? 'text-yellow-600' : ''}`}>{dte ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Breakeven</span>
                <span className="font-mono font-bold">{breakeven ? `$${breakeven}` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Max Profit</span>
                <span className="font-mono font-bold text-emerald-400">{maxProfit ? `$${parseInt(maxProfit).toLocaleString()}` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Max Loss</span>
                <span className="font-mono font-bold text-red-400">{maxLoss ? `$${parseInt(maxLoss).toLocaleString()}` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Buying Power</span>
                <span className="font-mono font-bold">{form.buying_power_used ? `$${parseInt(form.buying_power_used).toLocaleString()}` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Regime</span>
                <span className="font-mono text-xs">{form.market_regime || marketData?.regime || '—'}</span>
              </div>
            </div>
          </div>

          {/* Pre-trade risk check button */}
          <button
            type="button"
            onClick={checkCompliance}
            disabled={!form.ticker || !form.strike || !form.expiry || compliance?.loading}
            className="btn-primary w-full py-3 text-center flex items-center justify-center gap-2"
          >
            {compliance?.loading ? <Loader2 size={16} className="animate-spin" /> : <Shield size={16} />}
            {compliance?.loading ? 'Checking Live Data...' : 'Run Pre-Trade Risk Check'}
          </button>

          {/* Live option data (from risk check) */}
          {riskCheck?.position?.option && (
            <div className="card bg-blue-500/10 border border-gray-200">
              <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <DollarSign size={16} className="text-blue-400" /> Live Option Data
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Stock Price</span>
                  <span className="font-mono font-bold">${riskCheck.position.stock_price}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Bid / Ask</span>
                  <span className="font-mono">${riskCheck.position.option.bid} / ${riskCheck.position.option.ask}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Mid Price</span>
                  <span className="font-mono font-bold text-emerald-400">${riskCheck.position.option.mid}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">IV</span>
                  <span className="font-mono">{riskCheck.position.option.iv}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Est. Delta</span>
                  <span className="font-mono">{riskCheck.position.estimated_delta}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Open Interest</span>
                  <span className="font-mono">{riskCheck.position.option.open_interest?.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">OTM %</span>
                  <span className={`font-mono font-bold ${riskCheck.position.otm_pct > 10 ? 'text-emerald-400' : riskCheck.position.otm_pct > 5 ? 'text-yellow-600' : 'text-red-400'}`}>
                    {riskCheck.position.otm_pct}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Annualized Return</span>
                  <span className="font-mono font-bold text-blue-400">{riskCheck.position.annual_return}%</span>
                </div>
              </div>
            </div>
          )}

          {/* Volatility data */}
          {riskCheck?.position?.volatility && (
            <div className="card shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <TrendingDown size={16} className="text-purple-600" /> Volatility Analysis
              </h3>
              <div className="space-y-2 text-sm">
                {riskCheck.position.volatility.iv != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">Implied Vol (IV)</span>
                    <span className="font-mono font-bold">{riskCheck.position.volatility.iv}%</span>
                  </div>
                )}
                {riskCheck.position.volatility.hv_20 != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">HV (20-day)</span>
                    <span className="font-mono">{riskCheck.position.volatility.hv_20}%</span>
                  </div>
                )}
                {riskCheck.position.volatility.hv_60 != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">HV (60-day)</span>
                    <span className="font-mono">{riskCheck.position.volatility.hv_60}%</span>
                  </div>
                )}
                {riskCheck.position.volatility.iv_hv_ratio != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">IV/HV Ratio</span>
                    <span className={`font-mono font-bold ${
                      riskCheck.position.volatility.iv_hv_ratio >= 1.2 ? 'text-emerald-400' :
                      riskCheck.position.volatility.iv_hv_ratio >= 0.8 ? 'text-yellow-600' : 'text-red-400'
                    }`}>
                      {riskCheck.position.volatility.iv_hv_ratio}x
                    </span>
                  </div>
                )}
                {riskCheck.position.volatility.iv_rank != null && (
                  <div className="flex justify-between">
                    <span className="text-gray-600">IV Rank</span>
                    <span className={`font-mono font-bold ${
                      riskCheck.position.volatility.iv_rank >= 50 ? 'text-emerald-400' :
                      riskCheck.position.volatility.iv_rank >= 30 ? 'text-yellow-600' : 'text-red-400'
                    }`}>
                      {riskCheck.position.volatility.iv_rank}
                    </span>
                  </div>
                )}
                {riskCheck.position.volatility.iv_hv_ratio >= 1.2 && (
                  <p className="text-xs text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded mt-1">
                    IV &gt; HV — options are overpriced, good for selling premium
                  </p>
                )}
                {riskCheck.position.volatility.iv_hv_ratio < 0.8 && (
                  <p className="text-xs text-red-400 bg-red-500/10 px-2 py-1 rounded mt-1">
                    IV &lt; HV — options may be underpriced, not ideal for selling
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Market context (from risk check) */}
          {riskCheck?.market && (
            <div className="card shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <TrendingDown size={16} className="text-gray-600" /> Market Context
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">VIX</span>
                  <span className={`font-mono font-bold ${riskCheck.market.vix >= 30 ? 'text-red-400' : riskCheck.market.vix >= 20 ? 'text-yellow-600' : 'text-emerald-400'}`}>
                    {riskCheck.market.vix}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">SPY</span>
                  <span className="font-mono">${riskCheck.market.spy_price}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Regime</span>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                    riskCheck.market.regime === 'EXTREME_FEAR' ? 'bg-purple-100 text-purple-700' :
                    riskCheck.market.regime === 'VERY_FEARFUL' ? 'bg-blue-100 text-blue-700' :
                    riskCheck.market.regime === 'FEAR' ? 'bg-emerald-100 text-emerald-700' :
                    riskCheck.market.regime === 'SLIGHT_FEAR' ? 'bg-emerald-100 text-emerald-400' :
                    riskCheck.market.regime === 'GREED' ? 'bg-orange-100 text-orange-700' :
                    'bg-red-100 text-red-700'
                  }`}>{riskCheck.market.regime?.replace(/_/g, ' ')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Portfolio After</span>
                  <span className="font-mono">{riskCheck.portfolio.utilization_after}% utilized</span>
                </div>
              </div>
            </div>
          )}

          {/* Risk check results */}
          {riskCheck?.checks && (
            <div className="card shadow-sm">
              <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <Shield size={16} /> Risk Check Results
              </h3>
              <div className="space-y-2">
                {riskCheck.checks.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    {r.passed ? (
                      <CheckCircle size={14} className="text-emerald-500 mt-0.5 shrink-0" />
                    ) : (
                      <XCircle size={14} className={`mt-0.5 shrink-0 ${r.severity === 'CRITICAL' ? 'text-red-500' : 'text-yellow-500'}`} />
                    )}
                    <div>
                      <span className={`${r.passed ? 'text-gray-500' : 'text-gray-900 font-medium'}`}>{r.rule}</span>
                      <p className={`${r.passed ? 'text-gray-500' : r.severity === 'CRITICAL' ? 'text-red-400' : 'text-yellow-600'}`}>{r.message}</p>
                    </div>
                  </div>
                ))}
                <div className={`mt-3 p-2 rounded text-center text-xs font-bold ${
                  riskCheck.all_passed ? 'bg-emerald-100 text-emerald-800' :
                  riskCheck.critical_violations > 0 ? 'bg-red-100 text-red-800' :
                  'bg-yellow-100 text-yellow-800'
                }`}>
                  {riskCheck.all_passed ? 'ALL CHECKS PASSED — SAFE TO TRADE' :
                   riskCheck.critical_violations > 0 ? `${riskCheck.critical_violations} CRITICAL VIOLATION(S)` :
                   `${riskCheck.warning_count} WARNING(S) — PROCEED WITH CAUTION`}
                </div>
              </div>
            </div>
          )}

          {compliance?.error && (
            <div className="bg-red-500/10 border border-gray-200 rounded-lg p-3 text-red-400 text-sm">
              {compliance.error}
            </div>
          )}

          {!riskCheck && !compliance?.loading && !compliance?.error && (
            <p className="text-gray-500 text-xs text-center py-2">Enter ticker, strike & expiry, then click "Run Pre-Trade Risk Check"</p>
          )}

          {/* Submit */}
          <button type="submit" disabled={loading} className="btn-primary w-full py-3 text-center flex items-center justify-center gap-2">
            {loading ? <Loader2 size={16} className="animate-spin" /> : null}
            {loading ? 'Creating...' : 'Open Position'}
          </button>
        </div>
      </form>
    </div>
  );
}
