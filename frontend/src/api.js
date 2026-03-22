const BASE_URL = '/api';

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const config = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };

  const res = await fetch(url, config);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

// --- Trades ---
export const fetchTrades = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/trades/?${qs}`);
};
export const fetchOpenTrades = () => request('/trades/open');
export const fetchTrade = (id) => request(`/trades/${id}`);
export const createTrade = (data) => request('/trades/', { method: 'POST', body: JSON.stringify(data) });
export const updateTrade = (id, data) => request(`/trades/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const closeTrade = (id, data) => request(`/trades/${id}/close`, { method: 'POST', body: JSON.stringify(data) });
export const deleteTrade = (id) => request(`/trades/${id}`, { method: 'DELETE' });
export const fetchUniverse = () => request('/trades/tickers/universe');

// --- Portfolio ---
export const fetchPortfolioSummary = () => request('/portfolio/summary');
export const fetchSnapshots = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/portfolio/snapshots?${qs}`);
};
export const fetchMonthlyReturns = (year) => request(`/portfolio/monthly-returns${year ? `?year=${year}` : ''}`);

// --- Analytics ---
export const fetchPerformance = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/analytics/performance?${qs}`);
};
export const fetchMTDPerformance = () => request('/analytics/performance/mtd');
export const fetchYTDPerformance = () => request('/analytics/performance/ytd');
export const fetchBreakdown = () => request('/analytics/breakdown');
export const fetchEquityCurve = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/analytics/equity-curve?${qs}`);
};
export const fetchMonthlyHeatmap = () => request('/analytics/monthly-heatmap');
export const fetchPnLDistribution = () => request('/analytics/pnl-distribution');
export const fetchCapitalUtilization = () => request('/analytics/capital-utilization');
export const fetchAlerts = () => request('/analytics/alerts');
export const runComplianceCheck = (data) => request('/analytics/compliance-check', { method: 'POST', body: JSON.stringify(data) });

// --- Sync ---
export const checkMoomooStatus = () => request('/sync/moomoo/status');
export const fetchMarketData = () => request('/sync/market-data');
export const fetchStockPrice = (ticker) => request(`/sync/stock-price/${ticker}`);
export const syncPositions = () => request('/sync/positions', { method: 'POST' });
export const syncAccount = () => request('/sync/account', { method: 'POST' });
export const fetchSuggestions = () => request('/sync/suggestions');
export const runPreTradeCheck = (data) => request('/sync/pre-trade-check', { method: 'POST', body: JSON.stringify(data) });

// --- YouTube Analysis ---
export const analyzeYouTubeVideo = (url) => request('/sync/youtube/analyze', { method: 'POST', body: JSON.stringify({ url }) });
export const getYouTubeChannels = () => request('/sync/youtube/channels');
export const addYouTubeChannel = (url) => request('/sync/youtube/channels', { method: 'POST', body: JSON.stringify({ url }) });
export const removeYouTubeChannel = (channelId) => request(`/sync/youtube/channels/${channelId}`, { method: 'DELETE' });
export const getYouTubeFeed = () => request('/sync/youtube/feed');
export const getSmartFeed = () => request('/sync/youtube/smart-feed');
export const autoAnalyzeFeed = () => request('/sync/youtube/auto-analyze', { method: 'POST' });
export const getSessionInfo = () => request('/sync/youtube/session');

// --- Ticker Analysis ---
export const searchTickers = (q) => request(`/sync/ticker/search?q=${encodeURIComponent(q)}`);
export const getTickerAnalysis = (ticker) => request(`/sync/ticker/${ticker}/analysis`);
export const getTickerEarnings = (ticker) => request(`/sync/ticker/${ticker}/earnings`);
export const getTickerPriceHistory = (ticker, period = '5y') => request(`/sync/ticker/${ticker}/price-history?period=${period}`);

// --- CSP Scanner ---
export const runCSPScan = () => request('/sync/csp-scanner');
export const runCSPScanQuick = () => request('/sync/csp-scanner/quick');
export const getCSPSignal = (ticker) => request(`/sync/csp-scanner/signal/${ticker}`);

// --- Market Intelligence ---
export const getMarketIntel = () => request('/sync/market-intel');
export const getMarketIntelQuick = () => request('/sync/market-intel/quick');

// --- 3-Tier Cascading Analysis ---
export const getCascadingAnalysisCached = () => request('/sync/cascading-analysis/cached');

// --- Per-stock Option Analysis (Moomoo) ---
export const getStockOptions = (ticker, dte = 35) => request(`/sync/stock-options/${ticker}?dte=${dte}`);

// --- Single Stock Safety Analysis (same as Tier 3) ---
export const getStockSafety = (ticker) => request(`/sync/stock-safety/${ticker}`);
export const getStockDebate = (ticker) => request(`/sync/stock-safety/${ticker}/debate`);

// --- Flow Toxicity ---
export const getFlowToxicity = (ticker, strike, expiry) =>
  request(`/sync/flow-toxicity/${ticker}?strike=${strike || 0}&expiry=${expiry || ''}`);

// VIX Regime
export const getVixRegime = (force = false) => request(`/sync/vix-regime${force ? '?force=true' : ''}`);

// Trend Ribbon
export const getTrendRibbon = (ticker = 'QQQ', period = '1y', emaFast = 13, emaSlow = 34, emaLong = 120, interval = '1d') =>
  request(`/sync/trend-ribbon/${ticker}?period=${period}&interval=${interval}&ema_fast=${emaFast}&ema_slow=${emaSlow}&ema_long=${emaLong}`);

/**
 * Run 3-tier cascading analysis with SSE streaming progress.
 * @param {Object} callbacks - { onProgress(tier, step, message), onTierComplete(tier, result), onComplete(result), onError(error) }
 * @returns {EventSource} - call .close() to cancel
 */
export const runCascadingAnalysis = (callbacks) => {
  // Always force=true when user clicks the button — bypass cache
  const evtSource = new EventSource(`${BASE_URL}/sync/cascading-analysis?force=true`);

  evtSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    callbacks.onProgress?.(data.tier, data.step, data.message);
  });

  evtSource.addEventListener('cached', (e) => {
    const result = JSON.parse(e.data);
    callbacks.onComplete?.(result);
    evtSource.close();
  });

  evtSource.addEventListener('complete', (e) => {
    const result = JSON.parse(e.data);
    callbacks.onComplete?.(result);
    evtSource.close();
  });

  evtSource.addEventListener('error', (e) => {
    if (e.data) {
      const data = JSON.parse(e.data);
      callbacks.onError?.(data.error);
    } else {
      callbacks.onError?.('SSE connection lost');
    }
    evtSource.close();
  });

  evtSource.onerror = () => {
    // Connection error — could be server restarting or analysis complete
    // EventSource auto-reconnects; we close it after 'complete' event
  };

  return evtSource;
};

// --- Portfolio Deep Analysis ---
export const getPortfolioDeepAnalysis = () => request('/sync/portfolio-deep-analysis');

// --- Config ---
export const fetchConfig = () => request('/config');
