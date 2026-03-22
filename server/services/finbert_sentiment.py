"""
FinBERT News Sentiment Analysis Service
Uses ProsusAI/finbert to score financial news headlines.
Sentiment scores are fed into Claude's AI signal for better CSP recommendations.
"""
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-loaded model (heavy imports deferred until first use)
_tokenizer = None
_model = None
_model_loaded = False
_model_load_error: Optional[str] = None

# Cache sentiment results for 30 minutes
_sentiment_cache: dict = {}
_SENTIMENT_TTL = 1800


def _load_model():
    """Lazy-load FinBERT model on first use."""
    global _tokenizer, _model, _model_loaded, _model_load_error

    if _model_loaded:
        return _model is not None
    if _model_load_error:
        return False

    try:
        logger.info("Loading FinBERT model (first time, may take a moment)...")
        import os
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        # Use local cache only — avoid slow/failing huggingface.co DNS lookups
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        _tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert", local_files_only=True)
        _model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert", local_files_only=True)
        _model.eval()  # Set to inference mode
        _model_loaded = True
        logger.info("FinBERT model loaded successfully (local cache)")
        return True
    except Exception as e:
        _model_load_error = str(e)
        _model_loaded = True  # Don't retry
        logger.error(f"Failed to load FinBERT model: {e}")
        return False


def score_headline(headline: str) -> dict:
    """
    Score a single news headline using FinBERT.

    Returns:
        {
            "headline": str,
            "sentiment": "positive" | "negative" | "neutral",
            "score": float (-1.0 to 1.0),
            "confidence": float (0.0 to 1.0),
            "probabilities": {"positive": float, "negative": float, "neutral": float}
        }
    """
    if not headline or not headline.strip():
        return {"headline": headline, "sentiment": "neutral", "score": 0.0, "confidence": 0.0}

    if not _load_model():
        return {
            "headline": headline,
            "sentiment": "neutral",
            "score": 0.0,
            "confidence": 0.0,
            "error": _model_load_error or "Model not available",
        }

    try:
        import torch

        inputs = _tokenizer(
            headline, return_tensors="pt", truncation=True, max_length=512, padding=True
        )

        with torch.no_grad():
            outputs = _model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]

        # FinBERT labels: positive=0, negative=1, neutral=2
        pos_prob = float(probs[0])
        neg_prob = float(probs[1])
        neu_prob = float(probs[2])

        # Composite score: -1 (bearish) to +1 (bullish)
        score = pos_prob - neg_prob

        # Determine label
        max_idx = int(probs.argmax())
        labels = ["positive", "negative", "neutral"]
        sentiment = labels[max_idx]
        confidence = float(probs[max_idx])

        return {
            "headline": headline,
            "sentiment": sentiment,
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "probabilities": {
                "positive": round(pos_prob, 4),
                "negative": round(neg_prob, 4),
                "neutral": round(neu_prob, 4),
            },
        }
    except Exception as e:
        logger.error(f"FinBERT scoring failed for headline: {e}")
        return {"headline": headline, "sentiment": "neutral", "score": 0.0, "confidence": 0.0, "error": str(e)}


def score_headlines(headlines: list[str]) -> list[dict]:
    """
    Batch-score multiple headlines efficiently.
    Uses batch inference for better performance.
    """
    if not headlines:
        return []

    if not _load_model():
        return [
            {"headline": h, "sentiment": "neutral", "score": 0.0, "confidence": 0.0, "error": _model_load_error}
            for h in headlines
        ]

    try:
        import torch

        # Batch tokenize
        inputs = _tokenizer(
            headlines, return_tensors="pt", truncation=True, max_length=512, padding=True
        )

        with torch.no_grad():
            outputs = _model(**inputs)
            all_probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

        labels = ["positive", "negative", "neutral"]
        results = []

        for i, headline in enumerate(headlines):
            probs = all_probs[i]
            pos_prob = float(probs[0])
            neg_prob = float(probs[1])
            neu_prob = float(probs[2])

            score = pos_prob - neg_prob
            max_idx = int(probs.argmax())

            results.append({
                "headline": headline,
                "sentiment": labels[max_idx],
                "score": round(score, 4),
                "confidence": round(float(probs[max_idx]), 4),
                "probabilities": {
                    "positive": round(pos_prob, 4),
                    "negative": round(neg_prob, 4),
                    "neutral": round(neu_prob, 4),
                },
            })

        return results
    except Exception as e:
        logger.error(f"Batch FinBERT scoring failed: {e}")
        return [{"headline": h, "sentiment": "neutral", "score": 0.0, "confidence": 0.0, "error": str(e)} for h in headlines]


def score_news_for_ticker(news: list[dict]) -> dict:
    """
    Score a list of news items (from Yahoo Finance format) and return
    individual scores plus an aggregate sentiment summary.

    Input: list of {"title": str, "publisher": str, "date": str}
    Returns:
        {
            "articles": [scored articles],
            "aggregate": {
                "avg_score": float,
                "sentiment": str,
                "bullish_count": int,
                "bearish_count": int,
                "neutral_count": int,
                "total": int
            }
        }
    """
    if not news:
        return {
            "articles": [],
            "aggregate": {
                "avg_score": 0.0,
                "sentiment": "neutral",
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "total": 0,
            },
        }

    # Check cache
    cache_key = "|".join(n.get("title", "") for n in news)
    cached = _sentiment_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < _SENTIMENT_TTL:
        return cached["data"]

    # Extract headlines and score in batch
    headlines = [n.get("title", "") for n in news if n.get("title")]
    scored = score_headlines(headlines)

    # Merge back with original news metadata
    articles = []
    for i, s in enumerate(scored):
        article = {**s}
        if i < len(news):
            article["publisher"] = news[i].get("publisher", "")
            article["date"] = news[i].get("date", "")
        articles.append(article)

    # Compute aggregate
    scores = [a["score"] for a in articles if "error" not in a]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    bullish = sum(1 for a in articles if a["sentiment"] == "positive")
    bearish = sum(1 for a in articles if a["sentiment"] == "negative")
    neutral = sum(1 for a in articles if a["sentiment"] == "neutral")

    if avg_score > 0.15:
        agg_sentiment = "bullish"
    elif avg_score < -0.15:
        agg_sentiment = "bearish"
    else:
        agg_sentiment = "neutral"

    result = {
        "articles": articles,
        "aggregate": {
            "avg_score": round(avg_score, 4),
            "sentiment": agg_sentiment,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "total": len(articles),
        },
    }

    # Cache
    _sentiment_cache[cache_key] = {"data": result, "ts": time.time()}

    return result
