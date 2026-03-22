"""
YouTube Financial Video Scraper
Extracts transcripts from YouTube videos and uses Claude AI to summarize
financial advice with actionable trading insights.

Market-session-aware smart feed:
  - US market closes ~4:00 AM SGT (UTC+8)
  - Crawl window: last market close → now
  - Auto-expire analyses after next market close
  - Weekend: Friday close (Sat 4am SGT) → Monday 9:30pm SGT
"""
from __future__ import annotations

import os
import re
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_api_key() -> str | None:
    """Get Anthropic API key from environment or .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # Try loading from .env
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY=") and not line.endswith("="):
                        return line.split("=", 1)[1].strip()
        except PermissionError:
            pass
    return None


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    if not url:
        return None

    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/").split("/")[0]

    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/v/", "/shorts/")):
            return parsed.path.split("/")[2]

    if re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        return url

    return None


def get_transcript(video_id: str) -> dict:
    """Fetch transcript for a YouTube video. Tries multiple languages."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt_api = YouTubeTranscriptApi()

        # Try common languages first, then fall back to whatever is available
        _PREFERRED_LANGS = [
            "en", "zh-Hans", "zh-Hant", "zh", "zh-CN", "zh-TW",
            "ja", "ko", "es", "de", "fr", "pt",
        ]

        transcript = None
        lang_used = None
        try:
            transcript = ytt_api.fetch(video_id, languages=_PREFERRED_LANGS)
        except Exception:
            # Preferred languages not found — list all and grab the first one
            try:
                transcript_list = ytt_api.list(video_id)
                for t in transcript_list:
                    lang_used = t.language_code
                    transcript = t.fetch()
                    break
            except Exception:
                raise  # re-raise so the outer handler catches it

        if transcript is None:
            return {
                "success": False,
                "video_id": video_id,
                "error": "No transcripts available for this video",
                "error_type": "no_transcript",
            }

        segments = []
        full_text = []
        for snippet in transcript:
            text = snippet.text
            start = snippet.start
            segments.append({
                "text": text,
                "start": round(start, 1),
                "timestamp": _format_timestamp(start),
            })
            full_text.append(text)

        return {
            "success": True,
            "video_id": video_id,
            "language": lang_used,
            "segments": segments,
            "full_text": " ".join(full_text),
            "word_count": len(" ".join(full_text).split()),
            "duration_minutes": round(segments[-1]["start"] / 60, 1) if segments else 0,
        }
    except Exception as e:
        error_str = str(e)
        # Classify common errors into user-friendly messages
        if "live event" in error_str.lower():
            friendly = "Upcoming livestream — no transcript available yet"
            error_type = "livestream"
        elif "subtitles are disabled" in error_str.lower() or "no transcripts" in error_str.lower():
            friendly = "No captions/transcript available for this video"
            error_type = "no_transcript"
        elif "video is unavailable" in error_str.lower() or "video unavailable" in error_str.lower():
            friendly = "Video is unavailable or private"
            error_type = "unavailable"
        elif "too many requests" in error_str.lower():
            friendly = "Rate limited by YouTube — try again in a minute"
            error_type = "rate_limit"
        else:
            friendly = "Could not fetch transcript"
            error_type = "unknown"

        return {
            "success": False,
            "video_id": video_id,
            "error": friendly,
            "error_type": error_type,
            "error_detail": error_str[:200],
        }


def summarize_with_claude(transcript_text: str) -> dict | None:
    """Use Claude to generate intelligent financial summary."""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("No Anthropic API key found, skipping AI summary")
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        # Truncate very long transcripts to stay within token limits
        max_chars = 50000
        text = transcript_text[:max_chars] if len(transcript_text) > max_chars else transcript_text

        prompt = f"""You are a financial analyst assistant. Analyze this YouTube video transcript and provide a structured summary for an options trader who sells cash-secured puts (CSP) and credit spreads.

Return a JSON object with this exact structure:
{{
  "title_guess": "Best guess for video title based on content",
  "summary": "2-3 sentence overall summary of the video",
  "market_outlook": "BULLISH" or "BEARISH" or "MIXED" or "NEUTRAL",
  "key_points": ["point 1", "point 2", ...],
  "tickers": [
    {{
      "ticker": "NVDA",
      "sentiment": "BULLISH" or "BEARISH" or "NEUTRAL",
      "reasoning": "Why the creator is bullish/bearish",
      "price_targets": [180, 200],
      "action": "What the creator suggests doing"
    }}
  ],
  "options_advice": [
    "Any specific options strategy advice mentioned"
  ],
  "risk_warnings": ["Any risks or warnings mentioned"],
  "vix_strategy": "Any VIX-based or volatility-based advice",
  "portfolio_advice": "Any portfolio allocation or position sizing advice",
  "relevance_to_csp": "How this applies to a CSP/wheel strategy trader — specific actionable takeaways"
}}

Important:
- Only include tickers that are explicitly discussed (not just briefly mentioned)
- Price targets should be actual numbers mentioned, not guesses
- Be specific about options strategies if mentioned
- The "relevance_to_csp" field should translate the advice into actionable CSP/spread trade ideas
- If the video discusses VIX levels or volatility strategy for capital deployment, detail that in vix_strategy
- LANGUAGE: Respond in the SAME language as the transcript. If the transcript is in Chinese, write all text fields in Chinese. If English, write in English. Ticker symbols should always be in English (e.g. NVDA, TSLA). The JSON keys must stay in English.

Transcript:
{text}"""

        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Extract JSON from response (handle markdown code blocks)
        json_str = response_text.strip()
        # Strip markdown code fences
        if json_str.startswith('```'):
            # Remove opening fence (```json or ```)
            first_newline = json_str.index('\n') if '\n' in json_str else len(json_str)
            json_str = json_str[first_newline + 1:]
        if json_str.endswith('```'):
            json_str = json_str[:-3]
        json_str = json_str.strip()
        # Fallback: try to find { ... } in the response
        if not json_str.startswith('{'):
            brace_start = json_str.find('{')
            brace_end = json_str.rfind('}')
            if brace_start != -1 and brace_end != -1:
                json_str = json_str[brace_start:brace_end + 1]

        # Try to find JSON object boundaries
        if not json_str.startswith('{'):
            start = json_str.find('{')
            end = json_str.rfind('}')
            if start >= 0 and end > start:
                json_str = json_str[start:end + 1]

        return json.loads(json_str)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        return {"error": "Failed to parse AI response", "raw": response_text[:500]}
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return {"error": str(e)}


def scrape_and_analyze(url: str) -> dict:
    """Full pipeline: extract video ID, get transcript, analyze with Claude."""
    video_id = extract_video_id(url)
    if not video_id:
        return {"success": False, "error": "Could not extract video ID from URL"}

    transcript = get_transcript(video_id)
    if not transcript["success"]:
        return transcript

    # AI-powered summary
    ai_summary = summarize_with_claude(transcript["full_text"])

    return {
        "success": True,
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "word_count": transcript["word_count"],
        "duration_minutes": transcript["duration_minutes"],
        "ai_summary": ai_summary,
        "transcript_preview": transcript["full_text"][:2000] + "..." if len(transcript["full_text"]) > 2000 else transcript["full_text"],
    }


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to MM:SS format."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


# --- Channel Management ---

CHANNELS_FILE = os.path.join(BASE_DIR, "youtube_channels.json")


def _load_channels() -> list[dict]:
    """Load saved channels from file."""
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE) as f:
            return json.load(f)
    return []


def _save_channels(channels: list[dict]):
    """Save channels to file."""
    with open(CHANNELS_FILE, "w") as f:
        json.dump(channels, f, indent=2)


def resolve_channel_id(url: str) -> dict | None:
    """Resolve a YouTube URL to a channel ID and name.
    Supports: /channel/ID, /@handle, /c/name, video URLs (extracts channel), direct channel ID"""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        path = parsed.path.rstrip("/")

        # /channel/UCxxxx format - already have ID
        if path.startswith("/channel/"):
            channel_id = path.split("/channel/")[1].split("/")[0]
            name = _fetch_channel_name(channel_id)
            return {"channel_id": channel_id, "name": name or channel_id}

        # /@handle, /c/name, or /watch - scrape page for channel ID
        if path == "/watch" or path.startswith("/@") or path.startswith("/c/"):
            return _resolve_from_page(url)

    # youtu.be short links - resolve via the video page
    if hostname == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0]
        return _resolve_from_page(f"https://www.youtube.com/watch?v={video_id}")

    # Maybe it's just a raw channel ID
    if re.match(r"^UC[a-zA-Z0-9_-]{22}$", url):
        name = _fetch_channel_name(url)
        return {"channel_id": url, "name": name or url}

    # Bare @handle (e.g. "@OptionsWithRyan") — convert to full URL
    stripped = url.strip().lstrip("/")
    if stripped.startswith("@"):
        return _resolve_from_page(f"https://www.youtube.com/{stripped}")

    # Try as a bare handle without @ (e.g. "OptionsWithRyan")
    if re.match(r"^[a-zA-Z0-9_.-]+$", stripped) and not stripped.startswith("UC"):
        return _resolve_from_page(f"https://www.youtube.com/@{stripped}")

    return None


def _resolve_from_page(url: str) -> dict | None:
    """Resolve channel ID by scraping a YouTube page."""
    result = _scrape_page_for_channel(url)
    if result:
        return result

    # Fallback: if it's a handle URL, try YouTube search
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/")
    if path.startswith("/@"):
        handle = path[2:]  # strip /@
        return _search_youtube_channel(handle)

    return None


def _scrape_page_for_channel(url: str) -> dict | None:
    """Scrape a YouTube page for channel ID."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Try multiple patterns — YouTube varies the escaping
        match = (
            re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]+)"', html)
            or re.search(r'channel_id=(UC[a-zA-Z0-9_-]+)', html)
            or re.search(r'"externalId"\s*:\s*"(UC[a-zA-Z0-9_-]+)"', html)
            or re.search(r'externalId.{0,5}(UC[a-zA-Z0-9_-]{22,})', html)
        )
        if match:
            channel_id = match.group(1)
            name = _fetch_channel_name(channel_id)
            if not name:
                name_match = re.search(r'"name":"([^"]+)"', html)
                name = name_match.group(1) if name_match else channel_id
            return {"channel_id": channel_id, "name": name}
    except Exception as e:
        logger.error(f"Failed to resolve channel from {url}: {e}")
    return None


def _search_youtube_channel(query: str) -> dict | None:
    """Search YouTube for a channel by name/handle and return the first match."""
    import urllib.request
    import urllib.parse
    try:
        # sp=EgIQAg%3D%3D filters for channels only
        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote('@' + query)}&sp=EgIQAg%3D%3D"
        req = urllib.request.Request(search_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Get the first channel ID from search results
        match = re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]+)"', html)
        if match:
            channel_id = match.group(1)
            name = _fetch_channel_name(channel_id)
            return {"channel_id": channel_id, "name": name or query}
    except Exception as e:
        logger.error(f"YouTube channel search failed for '{query}': {e}")
    return None


def _fetch_channel_name(channel_id: str) -> str | None:
    """Fetch channel name from RSS feed."""
    try:
        import feedparser
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        return feed.feed.get("title", None)
    except Exception:
        return None


def add_channel(url: str) -> dict:
    """Add a YouTube channel to the followed list."""
    channels = _load_channels()

    info = resolve_channel_id(url)
    if not info:
        return {"success": False, "error": "Could not resolve channel. Use a URL like youtube.com/@handle or youtube.com/channel/UCxxx"}

    # Check duplicate
    for ch in channels:
        if ch["channel_id"] == info["channel_id"]:
            return {"success": False, "error": f"Channel '{info['name']}' is already in your list"}

    channel = {
        "channel_id": info["channel_id"],
        "name": info["name"],
        "url": url,
        "added_at": __import__("datetime").datetime.now().isoformat(),
    }
    channels.append(channel)
    _save_channels(channels)

    return {"success": True, "channel": channel}


def remove_channel(channel_id: str) -> dict:
    """Remove a channel from the followed list."""
    channels = _load_channels()
    original_len = len(channels)
    channels = [ch for ch in channels if ch["channel_id"] != channel_id]
    if len(channels) == original_len:
        return {"success": False, "error": "Channel not found"}
    _save_channels(channels)
    return {"success": True}


def get_channels() -> list[dict]:
    """Get all followed channels."""
    return _load_channels()


_LIVE_KEYWORDS = re.compile(
    r'\blive\b|\blivestream\b|\bstreaming\b|\b直播\b|\b實況\b',
    re.IGNORECASE,
)


def _is_likely_live(entry: dict) -> bool:
    """Heuristic: detect upcoming/live streams from RSS entry."""
    title = entry.get("title", "")
    # Check title for live keywords
    if _LIVE_KEYWORDS.search(title):
        return True
    # If the video has 0 views it's likely upcoming (media_statistics)
    stats = entry.get("media_statistics", {})
    views = stats.get("views", None)
    if views is not None and str(views) == "0":
        return True
    # If published date is in the future, it's scheduled
    pub = entry.get("published_parsed")
    if pub:
        from time import mktime
        from datetime import datetime as _dt
        try:
            pub_ts = mktime(pub)
            if pub_ts > _dt.now().timestamp() + 300:  # >5min in future
                return True
        except Exception:
            pass
    return False


def fetch_latest_videos(channel_id: str, max_results: int = 3) -> list[dict]:
    """Fetch latest videos from a channel via RSS feed.
    Skips likely livestreams and scheduled premieres."""
    try:
        import feedparser
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")

        videos = []
        for entry in feed.entries:
            if len(videos) >= max_results:
                break
            # Skip livestreams
            if _is_likely_live(entry):
                logger.debug(f"Skipping likely live/stream: {entry.get('title', '')[:50]}")
                continue
            video_id = entry.get("yt_videoid", "")
            published = entry.get("published", "")
            videos.append({
                "video_id": video_id,
                "title": entry.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published": published,
                "channel_name": feed.feed.get("title", ""),
            })
        return videos
    except Exception as e:
        logger.error(f"Failed to fetch RSS for {channel_id}: {e}")
        return []


def fetch_all_latest(max_per_channel: int = 1) -> list[dict]:
    """Fetch latest video from all followed channels."""
    channels = _load_channels()
    all_videos = []
    for ch in channels:
        videos = fetch_latest_videos(ch["channel_id"], max_per_channel)
        for v in videos:
            v["channel_name"] = ch["name"]
        all_videos.extend(videos)

    # Sort by published date (newest first)
    all_videos.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_videos


# ============================================================
# Smart Feed — Market-session-aware video crawling & analysis
# ============================================================

SGT = timezone(timedelta(hours=8))
MARKET_CLOSE_HOUR = 4   # 4:00 AM SGT = ~4 PM ET (approx)
ANALYSES_FILE = os.path.join(BASE_DIR, "youtube_analyses.json")


def _now_sgt() -> datetime:
    return datetime.now(SGT)


def get_market_session_window() -> dict:
    """Calculate the crawl window based on US market sessions in SGT.

    Returns:
        {
            "window_start": datetime,   # last market close
            "window_end": datetime,     # now (capped at next session open ~9:30pm SGT)
            "expires_at": datetime,     # next market close (when to delete)
            "label": str,               # human-readable description
        }
    """
    now = _now_sgt()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Market close time today at 4am SGT
    close_today = today.replace(hour=MARKET_CLOSE_HOUR)

    # Determine the *last* market close
    # US market doesn't trade Sat/Sun, so:
    #   Mon 4am = Sunday session? No — Mon 4am = Friday session close (Mon morning SGT = Mon in US)
    #   Actually: US Mon session closes Tue 4am SGT
    #
    # Day of week (0=Mon): market sessions that close at 4am SGT:
    #   Tue 4am  = Mon session close
    #   Wed 4am  = Tue session close
    #   Thu 4am  = Wed session close
    #   Fri 4am  = Thu session close
    #   Sat 4am  = Fri session close
    #   (No close on Sun 4am or Mon 4am — no Sat/Sun sessions)

    dow = now.weekday()  # 0=Mon, 6=Sun

    if now.hour < MARKET_CLOSE_HOUR:
        # Before 4am — the "close" hasn't happened yet today
        # The last close was yesterday's 4am (if it was a trading day)
        candidate_close = close_today - timedelta(days=1)
    else:
        candidate_close = close_today

    # Adjust for weekends: walk back to find a real trading close
    # Close at 4am only happens Tue-Sat (Mon-Fri sessions)
    cd = candidate_close.weekday()  # day of the candidate close
    if cd == 6:  # Sunday — last close was Saturday 4am (Fri session)
        candidate_close -= timedelta(days=1)
    elif cd == 0:  # Monday — last close was Saturday 4am (Fri session)
        candidate_close -= timedelta(days=2)

    window_start = candidate_close

    # Next market close = next Tue-Sat 4am after now
    # Find the next trading close after now
    next_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
    if next_close <= now:
        next_close += timedelta(days=1)
    # Skip Sun/Mon 4am (no sessions close then)
    while next_close.weekday() in (0, 6):  # Mon=0, Sun=6
        next_close += timedelta(days=1)

    expires_at = next_close

    # Label
    start_str = window_start.strftime("%a %b %d %I:%M%p SGT")
    expires_str = expires_at.strftime("%a %b %d %I:%M%p SGT")
    label = f"Videos since {start_str} (expires {expires_str})"

    return {
        "window_start": window_start,
        "window_end": now,
        "expires_at": expires_at,
        "label": label,
    }


def _load_analyses() -> dict:
    """Load cached analyses from file."""
    if os.path.exists(ANALYSES_FILE):
        try:
            with open(ANALYSES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_analyses(data: dict):
    """Save analyses cache to file."""
    with open(ANALYSES_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _cleanup_expired_analyses():
    """Remove analyses that have expired (past market close)."""
    data = _load_analyses()
    now = _now_sgt()
    cleaned = {}
    for url, entry in data.items():
        expires = entry.get("expires_at", "")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=SGT)
                if exp_dt > now:
                    cleaned[url] = entry
                    continue
            except (ValueError, TypeError):
                pass
        # No valid expiry or expired — drop it
    if len(cleaned) != len(data):
        _save_analyses(cleaned)
        logger.info(f"Cleaned up {len(data) - len(cleaned)} expired analyses")
    return cleaned


def _parse_published_date(pub_str: str) -> datetime | None:
    """Parse RSS published date string to datetime."""
    from email.utils import parsedate_to_datetime
    try:
        # RSS dates are RFC 2822 format
        dt = parsedate_to_datetime(pub_str)
        return dt.astimezone(SGT)
    except Exception:
        pass
    # Try ISO format
    try:
        dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        return dt.astimezone(SGT)
    except Exception:
        pass
    return None


def fetch_smart_feed() -> dict:
    """Fetch videos within the current market session window from all channels.

    Returns videos posted between last market close and now, with up to 5
    recent videos per channel to ensure we catch everything.
    """
    session = get_market_session_window()
    window_start = session["window_start"]
    channels = _load_channels()

    # Clean up expired analyses first
    _cleanup_expired_analyses()

    all_videos = []
    for ch in channels:
        # Fetch more videos per channel to catch all within window
        videos = fetch_latest_videos(ch["channel_id"], max_results=5)
        for v in videos:
            v["channel_name"] = ch["name"]
            pub_dt = _parse_published_date(v.get("published", ""))
            if pub_dt and pub_dt >= window_start:
                v["published_sgt"] = pub_dt.isoformat()
                all_videos.append(v)

    # Sort by published date (newest first)
    all_videos.sort(key=lambda x: x.get("published_sgt", ""), reverse=True)

    return {
        "videos": all_videos,
        "session": {
            "window_start": session["window_start"].isoformat(),
            "window_end": session["window_end"].isoformat(),
            "expires_at": session["expires_at"].isoformat(),
            "label": session["label"],
        },
    }


def analyze_and_cache(url: str) -> dict:
    """Analyze a video and cache the result with market session expiry."""
    # Check cache first
    analyses = _load_analyses()
    if url in analyses:
        cached = analyses[url]
        # Check if still valid
        expires = cached.get("expires_at", "")
        try:
            exp_dt = datetime.fromisoformat(expires)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=SGT)
            if exp_dt > _now_sgt():
                cached_result = cached.get("result", {})
                # Skip cache if failure was from English-only bug or parse error
                error_detail = cached_result.get("error_detail", "")
                ai_summary = cached_result.get("ai_summary", {})
                was_lang_bug = not cached_result.get("success") and "('en',)" in error_detail
                was_parse_bug = cached_result.get("success") and isinstance(ai_summary, dict) and "error" in ai_summary
                if not was_lang_bug and not was_parse_bug:
                    return cached_result
        except (ValueError, TypeError):
            pass

    # Not cached or expired — analyze
    result = scrape_and_analyze(url)

    # Cache with expiry
    session = get_market_session_window()
    analyses[url] = {
        "result": result,
        "analyzed_at": _now_sgt().isoformat(),
        "expires_at": session["expires_at"].isoformat(),
    }
    _save_analyses(analyses)

    return result


def auto_analyze_feed() -> dict:
    """Fetch smart feed and auto-analyze all videos in the window.

    Returns the feed with analysis results attached to each video.
    """
    feed_data = fetch_smart_feed()
    videos = feed_data["videos"]
    analyses = _load_analyses()
    session = get_market_session_window()

    results = []
    analyzed_count = 0
    skipped_count = 0
    error_count = 0

    for video in videos:
        url = video["url"]
        entry = {**video, "analysis_status": "pending"}

        # Check cache
        if url in analyses:
            cached = analyses[url]
            expires = cached.get("expires_at", "")
            try:
                exp_dt = datetime.fromisoformat(expires)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=SGT)
                if exp_dt > _now_sgt():
                    cached_result = cached.get("result", {})
                    # Retry if previous failure was due to English-only language bug
                    error_detail = cached_result.get("error_detail", "")
                    was_lang_bug = (
                        not cached_result.get("success")
                        and "('en',)" in error_detail
                    )
                    # Also retry if AI parsing failed (truncated JSON)
                    ai_summary = cached_result.get("ai_summary", {})
                    was_parse_bug = (
                        cached_result.get("success")
                        and isinstance(ai_summary, dict)
                        and "error" in ai_summary
                    )
                    if not was_lang_bug and not was_parse_bug:
                        if cached_result.get("success"):
                            entry["analysis"] = cached_result
                            entry["analysis_status"] = "done"
                            analyzed_count += 1
                        else:
                            entry["analysis_error"] = cached_result.get("error", "Previous analysis failed")
                            entry["analysis_status"] = "error"
                            error_count += 1
                        results.append(entry)
                        continue
                    # Fall through to re-analyze
                    logger.info(f"Re-analyzing {url} (previous failure was language/parse bug)")
            except (ValueError, TypeError):
                pass

        # Not cached — analyze now
        try:
            result = scrape_and_analyze(url)
            # Cache it
            analyses[url] = {
                "result": result,
                "analyzed_at": _now_sgt().isoformat(),
                "expires_at": session["expires_at"].isoformat(),
            }

            if result.get("success"):
                entry["analysis"] = result
                entry["analysis_status"] = "done"
                analyzed_count += 1
            else:
                entry["analysis_error"] = result.get("error", "Analysis failed")
                entry["analysis_status"] = "error"
                error_count += 1
        except Exception as e:
            entry["analysis_error"] = str(e)
            entry["analysis_status"] = "error"
            error_count += 1

        results.append(entry)

    # Save all analyses
    _save_analyses(analyses)

    return {
        "videos": results,
        "session": feed_data["session"],
        "stats": {
            "total": len(results),
            "analyzed": analyzed_count,
            "errors": error_count,
            "skipped": skipped_count,
        },
    }
