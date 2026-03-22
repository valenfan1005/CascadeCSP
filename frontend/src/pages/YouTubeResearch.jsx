import React, { useState, useEffect, useRef } from 'react';
import { analyzeYouTubeVideo, getYouTubeChannels, addYouTubeChannel, removeYouTubeChannel, getYouTubeFeed, autoAnalyzeFeed, getSmartFeed } from '../api.js';
import { Loader2, TrendingUp, TrendingDown, Minus, AlertTriangle, Target, BookOpen, Shield, BarChart3, Play, Plus, Trash2, Rss, ExternalLink, Zap, ChevronDown, ChevronUp, StopCircle, Clock, Calendar } from 'lucide-react';

const SentimentBadge = ({ sentiment }) => {
  const colors = {
    BULLISH: 'bg-emerald-50 text-emerald-600',
    BEARISH: 'bg-red-50 text-red-600',
    MIXED: 'bg-yellow-50 text-yellow-600',
    NEUTRAL: 'bg-gray-100 text-gray-600',
  };
  const icons = {
    BULLISH: <TrendingUp size={14} />,
    BEARISH: <TrendingDown size={14} />,
    MIXED: <Minus size={14} />,
    NEUTRAL: <Minus size={14} />,
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${colors[sentiment] || colors.NEUTRAL}`}>
      {icons[sentiment]} {sentiment}
    </span>
  );
};

// Compact inline summary for feed cards
function InlineSummary({ result }) {
  const ai = result?.ai_summary;
  if (!ai || ai.error) return null;

  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-3 border-t border-gray-200 pt-3">
      {/* Summary header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-sm text-gray-600 leading-relaxed">{ai.summary}</p>
        <SentimentBadge sentiment={ai.market_outlook} />
      </div>

      {/* Tickers row */}
      {ai.tickers?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {ai.tickers.map((t, i) => (
            <span key={i} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-bold border ${
              t.sentiment === 'BULLISH' ? 'border-emerald-600 bg-emerald-50 text-emerald-600' :
              t.sentiment === 'BEARISH' ? 'border-red-600 bg-red-50 text-red-600' :
              'border-gray-200 bg-gray-50 text-gray-600'
            }`}>
              {t.sentiment === 'BULLISH' ? <TrendingUp size={10} /> : t.sentiment === 'BEARISH' ? <TrendingDown size={10} /> : <Minus size={10} />}
              {t.ticker}
              {t.price_targets?.length > 0 && <span className="font-normal ml-1">${t.price_targets[0]}</span>}
            </span>
          ))}
        </div>
      )}

      {/* CSP relevance */}
      {ai.relevance_to_csp && (
        <div className="p-2 bg-emerald-50 rounded text-xs text-emerald-600 border border-emerald-600 mb-2">
          <span className="font-semibold">CSP Takeaway:</span> {ai.relevance_to_csp}
        </div>
      )}

      {/* Expand for more details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-blue-600 hover:text-blue-500 flex items-center gap-1"
      >
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {expanded ? 'Less' : 'More details'}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {/* Key points */}
          {ai.key_points?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-gray-900 mb-1 flex items-center gap-1">
                <BookOpen size={12} className="text-blue-600" /> Key Points
              </h4>
              <ul className="space-y-1">
                {ai.key_points.map((point, i) => (
                  <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                    <span className="text-blue-600 font-bold">{i + 1}.</span> {point}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Ticker details */}
          {ai.tickers?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-gray-900 mb-1 flex items-center gap-1">
                <BarChart3 size={12} className="text-blue-600" /> Ticker Analysis
              </h4>
              {ai.tickers.map((t, i) => (
                <div key={i} className="p-2 bg-gray-50 rounded border border-gray-200 mb-1.5">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="font-mono font-bold text-xs text-gray-900">{t.ticker}</span>
                    <SentimentBadge sentiment={t.sentiment} />
                    {t.price_targets?.length > 0 && (
                      <span className="text-xs text-gray-500 ml-auto">
                        Targets: {t.price_targets.map(p => `$${p}`).join(', ')}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-600">{t.reasoning}</p>
                  {t.action && <p className="text-xs text-blue-600 font-medium mt-0.5">{t.action}</p>}
                </div>
              ))}
            </div>
          )}

          {/* VIX strategy */}
          {ai.vix_strategy && (
            <div className="p-2 bg-purple-50 rounded text-xs border border-purple-600">
              <span className="font-semibold text-purple-600">VIX Strategy:</span>{' '}
              <span className="text-purple-600">{ai.vix_strategy}</span>
            </div>
          )}

          {/* Options advice */}
          {ai.options_advice?.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-gray-900 mb-1 flex items-center gap-1">
                <Shield size={12} className="text-purple-400" /> Options Strategies
              </h4>
              {ai.options_advice.map((advice, i) => (
                <p key={i} className="text-xs text-gray-600 flex gap-1.5 mb-0.5">
                  <span className="text-purple-400">&#9679;</span> {advice}
                </p>
              ))}
            </div>
          )}

          {/* Risk warnings */}
          {ai.risk_warnings?.length > 0 && (
            <div className="p-2 bg-red-50 rounded text-xs border border-red-600">
              <h4 className="font-semibold text-red-600 mb-1 flex items-center gap-1">
                <AlertTriangle size={12} /> Risks
              </h4>
              {ai.risk_warnings.map((w, i) => (
                <p key={i} className="text-red-600 mb-0.5">&#9888; {w}</p>
              ))}
            </div>
          )}

          {/* Portfolio advice */}
          {ai.portfolio_advice && (
            <div className="p-2 bg-blue-50 rounded text-xs border border-blue-600">
              <span className="font-semibold text-blue-600">Portfolio:</span>{' '}
              <span className="text-blue-600">{ai.portfolio_advice}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Full analysis result display component (for Analyze tab)
function AnalysisResult({ result }) {
  const ai = result?.ai_summary;
  if (!ai || ai.error) return null;

  return (
    <div className="space-y-4">
      <div className="card bg-gradient-to-r from-navy-800 to-navy-900 text-white">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold">{ai.title_guess}</h2>
            <p className="text-navy-200 mt-1 text-sm">{result.duration_minutes} min | {result.word_count} words</p>
          </div>
          <SentimentBadge sentiment={ai.market_outlook} />
        </div>
        <p className="mt-3 text-navy-100">{ai.summary}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card shadow-sm">
          <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <BookOpen size={16} className="text-blue-600" /> Key Points
          </h3>
          <ul className="space-y-2">
            {ai.key_points?.map((point, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="text-blue-500 font-bold mt-0.5">{i + 1}.</span>
                <span className="text-gray-600">{point}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="card shadow-sm border-l-4 border-emerald-500">
          <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Target size={16} className="text-emerald-600" /> Relevance to Your CSP Strategy
          </h3>
          <p className="text-sm text-gray-600 leading-relaxed">{ai.relevance_to_csp}</p>
          {ai.vix_strategy && (
            <div className="mt-3 p-2 bg-purple-50 rounded text-sm">
              <span className="font-semibold text-purple-600">VIX Strategy: </span>
              <span className="text-purple-600">{ai.vix_strategy}</span>
            </div>
          )}
          {ai.portfolio_advice && (
            <div className="mt-2 p-2 bg-blue-50 rounded text-sm">
              <span className="font-semibold text-blue-600">Portfolio: </span>
              <span className="text-blue-600">{ai.portfolio_advice}</span>
            </div>
          )}
        </div>

        {ai.tickers?.length > 0 && (
          <div className="card shadow-sm lg:col-span-2">
            <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <BarChart3 size={16} className="text-blue-600" /> Ticker Analysis
            </h3>
            <div className="space-y-3">
              {ai.tickers.map((t, i) => (
                <div key={i} className="p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-gray-900">{t.ticker}</span>
                      <SentimentBadge sentiment={t.sentiment} />
                    </div>
                    {t.price_targets?.length > 0 && (
                      <span className="text-xs text-gray-500">
                        Targets: {t.price_targets.map(p => `$${p}`).join(', ')}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-600">{t.reasoning}</p>
                  {t.action && <p className="text-sm text-blue-600 font-medium mt-1">{t.action}</p>}
                </div>
              ))}
            </div>
          </div>
        )}

        {ai.options_advice?.length > 0 && (
          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <Shield size={16} className="text-purple-400" /> Options Strategies Mentioned
            </h3>
            <ul className="space-y-2">
              {ai.options_advice.map((advice, i) => (
                <li key={i} className="text-sm text-gray-600 flex gap-2">
                  <span className="text-purple-500">&#9679;</span> {advice}
                </li>
              ))}
            </ul>
          </div>
        )}

        {ai.risk_warnings?.length > 0 && (
          <div className="card shadow-sm border-l-4 border-red-400">
            <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <AlertTriangle size={16} className="text-red-500" /> Risk Warnings
            </h3>
            <ul className="space-y-2">
              {ai.risk_warnings.map((warning, i) => (
                <li key={i} className="text-sm text-red-600 flex gap-2">
                  <span className="text-red-600">&#9888;</span> {warning}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <details className="card shadow-sm">
        <summary className="cursor-pointer font-semibold text-gray-900">View Transcript Preview</summary>
        <p className="mt-3 text-sm text-gray-600 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
          {result.transcript_preview}
        </p>
      </details>
    </div>
  );
}

export default function YouTubeResearch() {
  const [tab, setTab] = useState('feed'); // 'feed' | 'analyze' | 'channels'
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  // Channel management
  const [channels, setChannels] = useState([]);
  const [channelUrl, setChannelUrl] = useState('');
  const [channelLoading, setChannelLoading] = useState(false);
  const [channelError, setChannelError] = useState(null);

  // Smart feed — market session aware
  const [feed, setFeed] = useState([]);       // videos with analysis attached
  const [session, setSession] = useState(null); // { window_start, expires_at, label }
  const [feedStats, setFeedStats] = useState(null);
  const [feedLoading, setFeedLoading] = useState(false);
  const [autoAnalyzing, setAutoAnalyzing] = useState(false);

  // Manual batch fallback
  const [analyses, setAnalyses] = useState({}); // { videoUrl: { status, result, error } }

  useEffect(() => {
    loadChannels();
    loadSmartFeed();
  }, []);

  const loadChannels = async () => {
    try {
      const data = await getYouTubeChannels();
      setChannels(data.channels || []);
    } catch {}
  };

  // Load smart feed (videos in market session window only)
  const loadSmartFeed = async () => {
    setFeedLoading(true);
    try {
      const data = await getSmartFeed();
      setFeed(data.videos || []);
      setSession(data.session || null);
    } catch {} finally {
      setFeedLoading(false);
    }
  };

  // Auto-analyze all videos in the session window (backend does the work)
  const handleAutoAnalyze = async () => {
    setAutoAnalyzing(true);
    try {
      const data = await autoAnalyzeFeed();
      // data.videos has analysis attached to each video
      setFeed(data.videos || []);
      setSession(data.session || null);
      setFeedStats(data.stats || null);
    } catch (err) {
      console.error('Auto-analyze failed:', err);
    } finally {
      setAutoAnalyzing(false);
    }
  };

  const handleAddChannel = async () => {
    if (!channelUrl.trim()) return;
    setChannelLoading(true);
    setChannelError(null);
    try {
      await addYouTubeChannel(channelUrl.trim());
      setChannelUrl('');
      await loadChannels();
      await loadSmartFeed();
    } catch (err) {
      setChannelError(err.message);
    } finally {
      setChannelLoading(false);
    }
  };

  const handleRemoveChannel = async (channelId) => {
    try {
      await removeYouTubeChannel(channelId);
      await loadChannels();
      await loadSmartFeed();
    } catch {}
  };

  // Single video analysis (for Analyze tab)
  const handleAnalyze = async (videoUrl) => {
    setUrl(videoUrl || url);
    const targetUrl = videoUrl || url;
    if (!targetUrl.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setTab('analyze');
    try {
      const data = await analyzeYouTubeVideo(targetUrl.trim());
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Analyze a single video inline in feed (manual fallback)
  const analyzeOne = async (videoUrl) => {
    setAnalyses(prev => ({ ...prev, [videoUrl]: { status: 'loading' } }));
    try {
      const data = await analyzeYouTubeVideo(videoUrl);
      setAnalyses(prev => ({ ...prev, [videoUrl]: { status: 'done', result: data } }));
    } catch (err) {
      const msg = err.message || 'Analysis failed';
      const skippable = /livestream|no caption|no transcript|unavailable|private/i.test(msg);
      setAnalyses(prev => ({ ...prev, [videoUrl]: { status: 'error', error: msg, skippable } }));
    }
  };

  // Count analyzed (from backend auto-analyze + manual)
  const analyzedFromFeed = feed.filter(v => v.analysis_status === 'done').length;
  const analyzedManual = Object.values(analyses).filter(a => a.status === 'done').length;
  const analyzedCount = analyzedFromFeed + analyzedManual;
  // Aggregate tickers and sentiment from both backend auto-analyzed and manual analyses
  const allTickers = [];
  const sentimentCounts = { BULLISH: 0, BEARISH: 0, MIXED: 0, NEUTRAL: 0 };

  const addTickersFromSummary = (ai) => {
    if (!ai) return;
    if (ai.market_outlook && sentimentCounts[ai.market_outlook] !== undefined) {
      sentimentCounts[ai.market_outlook]++;
    }
    (ai.tickers || []).forEach(t => {
      const existing = allTickers.find(x => x.ticker === t.ticker);
      if (existing) {
        existing.mentions++;
        if (t.sentiment === 'BULLISH') existing.bullish++;
        if (t.sentiment === 'BEARISH') existing.bearish++;
      } else {
        allTickers.push({
          ticker: t.ticker,
          mentions: 1,
          bullish: t.sentiment === 'BULLISH' ? 1 : 0,
          bearish: t.sentiment === 'BEARISH' ? 1 : 0,
        });
      }
    });
  };

  // From backend auto-analyzed feed
  feed.forEach(v => {
    if (v.analysis_status === 'done') {
      addTickersFromSummary(v.analysis?.ai_summary);
    }
  });
  // From manual analyses
  Object.values(analyses).forEach(a => {
    if (a.status === 'done') {
      addTickersFromSummary(a.result?.ai_summary);
    }
  });
  allTickers.sort((a, b) => b.mentions - a.mentions);

  return (
    <div className="space-y-6">
      <div className="sticky top-0 z-10 bg-white pb-3 -mt-2 pt-2">
        <div className="flex items-center gap-3 mb-2">
          <Play size={24} className="text-red-600 shrink-0" />
          <h1 className="text-xl font-bold text-gray-900">YouTube Research</h1>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
            {[
              { id: 'feed', label: 'Feed', icon: Rss },
              { id: 'analyze', label: 'Analyze', icon: Play },
              { id: 'channels', label: 'Channels', icon: Plus },
            ].map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  tab === t.id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-600'
                }`}
              >
                <t.icon size={14} /> {t.label}
              </button>
            ))}
          </div>
          <p className="text-gray-500 text-xs hidden sm:block">AI-powered financial video analysis</p>
        </div>
      </div>

      {/* === FEED TAB === */}
      {tab === 'feed' && (
        <div className="space-y-4">
          {/* Market session info */}
          {session && (
            <div className="flex items-center gap-2 px-3 py-2 bg-blue-50 border border-gray-200 rounded-lg text-xs">
              <Clock size={14} className="text-blue-600 shrink-0" />
              <span className="text-gray-600">{session.label}</span>
            </div>
          )}

          {/* Controls row */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <p className="text-sm text-gray-500">
              {channels.length} channels | {feed.length} videos in window | {analyzedCount} analyzed
            </p>
            <div className="flex items-center gap-2">
              <button onClick={loadSmartFeed} disabled={feedLoading} className="text-sm text-blue-600 hover:underline flex items-center gap-1 disabled:opacity-50">
                <Rss size={14} /> Refresh
              </button>
              {feed.length > 0 && !autoAnalyzing && (
                <button
                  onClick={handleAutoAnalyze}
                  className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5"
                >
                  <Zap size={14} /> Analyze All
                </button>
              )}
            </div>
          </div>

          {/* Auto-analyze progress */}
          {autoAnalyzing && (
            <div className="card shadow-sm bg-blue-50 border border-blue-600">
              <div className="flex items-center gap-3">
                <Loader2 size={18} className="animate-spin text-blue-600" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-blue-600">
                    Auto-analyzing all videos in session window...
                  </p>
                  <p className="text-xs text-blue-600">This may take a few minutes. Results are cached until next market close.</p>
                </div>
              </div>
            </div>
          )}

          {/* Stats after auto-analyze */}
          {feedStats && !autoAnalyzing && (
            <div className="flex items-center gap-3 text-xs text-gray-500 px-1">
              <span className="text-emerald-600 font-medium">{feedStats.analyzed} analyzed</span>
              {feedStats.errors > 0 && <span className="text-amber-400">{feedStats.errors} errors</span>}
              <span className="text-gray-400">Results cached until market close</span>
            </div>
          )}

          {/* Aggregate summary dashboard */}
          {analyzedCount > 0 && (
            <div className="card shadow-sm border border-gray-200 bg-gradient-to-r from-white to-white">
              <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2 text-sm">
                <BarChart3 size={16} className="text-blue-600" /> Market Consensus ({analyzedCount} videos)
              </h3>
              <div className="flex flex-wrap gap-4 mb-3">
                {sentimentCounts.BULLISH > 0 && (
                  <div className="flex items-center gap-1.5">
                    <TrendingUp size={14} className="text-emerald-600" />
                    <span className="text-sm font-medium text-emerald-600">{sentimentCounts.BULLISH} Bullish</span>
                  </div>
                )}
                {sentimentCounts.BEARISH > 0 && (
                  <div className="flex items-center gap-1.5">
                    <TrendingDown size={14} className="text-red-600" />
                    <span className="text-sm font-medium text-red-600">{sentimentCounts.BEARISH} Bearish</span>
                  </div>
                )}
                {sentimentCounts.MIXED > 0 && (
                  <div className="flex items-center gap-1.5">
                    <Minus size={14} className="text-yellow-400" />
                    <span className="text-sm font-medium text-yellow-400">{sentimentCounts.MIXED} Mixed</span>
                  </div>
                )}
                {sentimentCounts.NEUTRAL > 0 && (
                  <div className="flex items-center gap-1.5">
                    <Minus size={14} className="text-gray-400" />
                    <span className="text-sm font-medium text-gray-600">{sentimentCounts.NEUTRAL} Neutral</span>
                  </div>
                )}
              </div>
              {allTickers.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase mb-1.5">Most Mentioned Tickers</p>
                  <div className="flex flex-wrap gap-1.5">
                    {allTickers.slice(0, 15).map((t, i) => (
                      <span key={i} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-bold border ${
                        t.bullish > t.bearish ? 'border-emerald-600 bg-emerald-50 text-emerald-600' :
                        t.bearish > t.bullish ? 'border-red-600 bg-red-50 text-red-600' :
                        'border-gray-200 bg-gray-50 text-gray-600'
                      }`}>
                        {t.ticker}
                        <span className="font-normal text-gray-500">x{t.mentions}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {feedLoading && (
            <div className="card shadow-sm text-center py-8">
              <Loader2 size={24} className="animate-spin mx-auto text-gray-400" />
              <p className="text-sm text-gray-500 mt-2">Loading session feed...</p>
            </div>
          )}

          {!feedLoading && feed.length === 0 && channels.length > 0 && (
            <div className="card shadow-sm text-center py-8">
              <Calendar size={32} className="mx-auto text-gray-400 mb-2" />
              <p className="text-gray-500">No new videos since last market close</p>
              <p className="text-xs text-gray-400 mt-1">Videos will appear here when your channels post after the market closes</p>
            </div>
          )}

          {!feedLoading && feed.length === 0 && channels.length === 0 && (
            <div className="card shadow-sm text-center py-8">
              <Rss size={32} className="mx-auto text-gray-400 mb-2" />
              <p className="text-gray-500">No channels added yet</p>
              <button onClick={() => setTab('channels')} className="text-blue-600 text-sm hover:underline mt-1">
                Add your first channel
              </button>
            </div>
          )}

          {/* Video cards with inline analysis */}
          {feed.map((video, i) => {
            // Check both backend auto-analysis and manual analysis
            const backendDone = video.analysis_status === 'done';
            const backendError = video.analysis_status === 'error';
            const manual = analyses[video.url];
            const manualDone = manual?.status === 'done';
            const manualLoading = manual?.status === 'loading';
            const manualError = manual?.status === 'error';

            const isDone = backendDone || manualDone;
            const isError = (backendError || manualError) && !isDone;
            const isLoading = manualLoading;

            // Get the analysis result from whichever source
            const analysisResult = backendDone ? video.analysis : manual?.result;
            const errorMsg = backendError ? video.analysis_error : manual?.error;

            return (
              <div key={i} className={`card shadow-sm transition-shadow ${isDone ? 'border-l-4 border-emerald-400' : ''}`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                        {video.channel_name}
                      </span>
                      <span className="text-xs text-gray-500">
                        {video.published ? new Date(video.published).toLocaleDateString() : ''}
                      </span>
                      {isDone && analysisResult?.ai_summary?.market_outlook && (
                        <SentimentBadge sentiment={analysisResult.ai_summary.market_outlook} />
                      )}
                    </div>
                    <h3 className="font-semibold text-gray-900">{video.title}</h3>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <a
                      href={video.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gray-400 hover:text-gray-600 p-1"
                      title="Open on YouTube"
                    >
                      <ExternalLink size={16} />
                    </a>
                    {!isDone && !isLoading && (
                      <button
                        onClick={() => analyzeOne(video.url)}
                        className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1"
                      >
                        Analyze
                      </button>
                    )}
                  </div>
                </div>

                {/* Loading state */}
                {isLoading && (
                  <div className="mt-3 flex items-center gap-2 text-sm text-gray-500 border-t border-gray-200 pt-3">
                    <Loader2 size={14} className="animate-spin" />
                    Fetching transcript & analyzing with AI...
                  </div>
                )}

                {/* Error state */}
                {isError && (
                  <div className="mt-3 border-t border-gray-200 pt-3 flex items-center gap-2">
                    <AlertTriangle size={14} className="text-amber-500 shrink-0" />
                    <p className="text-xs text-gray-500 flex-1">{errorMsg}</p>
                    <button onClick={() => analyzeOne(video.url)} className="text-xs text-blue-600 hover:underline shrink-0">
                      Retry
                    </button>
                  </div>
                )}

                {/* Inline summary */}
                {isDone && <InlineSummary result={analysisResult} />}
              </div>
            );
          })}
        </div>
      )}

      {/* === ANALYZE TAB === */}
      {tab === 'analyze' && (
        <div className="space-y-4">
          {/* URL Input */}
          <div className="card shadow-sm">
            <div className="flex gap-3">
              <input
                type="text"
                value={url}
                onChange={e => setUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAnalyze()}
                placeholder="https://www.youtube.com/watch?v=... or youtu.be/..."
                className="input-field flex-1 font-mono text-sm bg-white text-gray-900 border-gray-200"
              />
              <button
                onClick={() => handleAnalyze()}
                disabled={loading || !url.trim()}
                className="btn-primary px-6 whitespace-nowrap disabled:opacity-50 flex items-center gap-2"
              >
                {loading ? <><Loader2 size={16} className="animate-spin" /> Analyzing...</> : 'Analyze Video'}
              </button>
            </div>
            {loading && (
              <p className="text-sm text-gray-500 mt-2">Fetching transcript and running AI analysis... this may take 10-20 seconds</p>
            )}
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
          </div>

          {result?.ai_summary?.error && (
            <div className="card shadow-sm border-l-4 border-red-400">
              <p className="text-red-600 font-semibold">AI Analysis Error</p>
              <p className="text-sm text-gray-600 mt-1">{result.ai_summary.error}</p>
            </div>
          )}

          <AnalysisResult result={result} />
        </div>
      )}

      {/* === CHANNELS TAB === */}
      {tab === 'channels' && (
        <div className="space-y-4">
          {/* Add Channel */}
          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-3">Add YouTube Channel</h3>
            <div className="flex gap-3">
              <input
                type="text"
                value={channelUrl}
                onChange={e => setChannelUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddChannel()}
                placeholder="@ChannelHandle or youtube.com/@handle"
                className="input-field flex-1 font-mono text-sm bg-white text-gray-900 border-gray-200"
              />
              <button
                onClick={handleAddChannel}
                disabled={channelLoading || !channelUrl.trim()}
                className="btn-primary px-4 whitespace-nowrap disabled:opacity-50 flex items-center gap-2"
              >
                {channelLoading ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                Add
              </button>
            </div>
            {channelError && <p className="text-sm text-red-600 mt-2">{channelError}</p>}
            <p className="text-xs text-gray-500 mt-2">
              Supports: @handle, youtube.com/@handle, youtube.com/channel/UCxxx, video URLs
            </p>
          </div>

          {/* Channel List */}
          <div className="card shadow-sm">
            <h3 className="font-semibold text-gray-900 mb-3">
              Followed Channels ({channels.length})
            </h3>
            {channels.length === 0 ? (
              <p className="text-sm text-gray-500 py-4 text-center">No channels added yet. Add a channel URL above.</p>
            ) : (
              <div className="space-y-2">
                {channels.map((ch, i) => (
                  <div key={i} className="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-red-50 flex items-center justify-center">
                        <Play size={14} className="text-red-600" />
                      </div>
                      <div>
                        <p className="font-medium text-gray-900 text-sm">{ch.name}</p>
                        <p className="text-xs text-gray-500 font-mono">{ch.channel_id}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleRemoveChannel(ch.channel_id)}
                      className="text-gray-400 hover:text-red-600 p-1 transition-colors"
                      title="Remove channel"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
