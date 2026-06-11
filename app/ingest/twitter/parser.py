"""Pure functions for parsing X/Twitter tweet._data structures."""

from __future__ import annotations

from typing import Any


def quoted_article_result(tweet: Any) -> dict[str, Any]:
    """Return the quoted article result from the tweet, or {} if absent."""
    try:
        data = getattr(tweet, "_data", {})
        return (
            data.get("quoted_status_result", {})
            .get("result", {})
            .get("article", {})
            .get("article_results", {})
            .get("result", {})
        ) or {}
    except (AttributeError, TypeError):
        return {}


def extract_article_id_from_quoted_status_result(tweet: Any) -> str | None:
    """Return the tweet's article ID, or None if not an article tweet."""
    try:
        data = getattr(tweet, "_data", {})
        qsr_result = data.get("quoted_status_result", {}).get("result", {})
        if not qsr_result.get("article"):
            return None
        return qsr_result.get("rest_id") or None
    except (AttributeError, KeyError, TypeError):
        return None


def extract_article_title(tweet: Any) -> str | None:
    """Return the title of the article quoted in the tweet, or None."""
    return quoted_article_result(tweet).get("title") or None


def quoted_tweet_url(tweet: Any) -> str | None:
    """Return the URL of the quoted article tweet, or None."""
    try:
        data = getattr(tweet, "_data", {})
        qsr_result = data.get("quoted_status_result", {}).get("result", {})
        if not qsr_result.get("article"):
            return None
        tweet_id = qsr_result.get("rest_id")
        if not tweet_id:
            return None
        screen_name = (
            qsr_result.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("legacy", {})
            .get("screen_name", "i")
        )
        return f"https://x.com/{screen_name}/status/{tweet_id}"
    except (AttributeError, TypeError):
        return None


def article_url(tweet: Any) -> str | None:
    """Return the URL of the article, or None."""
    article_entity_id = quoted_article_result(tweet).get("rest_id")
    if article_entity_id:
        return f"https://x.com/i/article/{article_entity_id}"
    # Fallback: URL present in the quoted tweet's entities
    try:
        data = getattr(tweet, "_data", {})
        urls = (
            data.get("quoted_status_result", {})
            .get("result", {})
            .get("legacy", {})
            .get("entities", {})
            .get("urls", [])
        )
        for u in urls:
            if "/article/" in u.get("expanded_url", ""):
                return u["expanded_url"]
    except (AttributeError, TypeError):
        pass
    return None
