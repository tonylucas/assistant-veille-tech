from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.ingest.news_api import NewsApiIngester
from app.ingest.twitter.ingester import TwitterIngester
from app.ingest.twitter import parser
from app.schemas import Article

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_HOURS = 48
_FRESH_NEWS_PAGE_SIZE = 5
_FRESH_TWITTER_COUNT = 20  # 1 page de 20 tweets


# ── helpers ──────────────────────────────────────────────────


def _resolve_cutoff(since: datetime | None) -> datetime:
    if since is None:
        return datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_LOOKBACK_HOURS)
    return since if since.tzinfo else since.replace(tzinfo=timezone.utc)


# ── sources ──────────────────────────────────────────────────


async def _fetch_from_newsapi(
    topics: list[str], cutoff: datetime, seen_ids: set[str]
) -> list[Article]:
    ingester = NewsApiIngester()
    from_date = cutoff.strftime("%Y-%m-%d")
    results: list[Article] = []

    async with httpx.AsyncClient(timeout=15) as client:
        for topic in topics:
            try:
                data = await ingester._fetch_page(
                    client, topic, page=1,
                    page_size=_FRESH_NEWS_PAGE_SIZE, from_date=from_date,
                )
                for raw in data.get("results", []):
                    article = NewsApiIngester._normalize(raw)
                    if article and article.id not in seen_ids:
                        seen_ids.add(article.id)
                        results.append(article)
            except httpx.HTTPError as exc:
                logger.warning("fresh_news newsapi topic %r: %s", topic, exc)

    return results


async def _fetch_from_twitter(
    topics: list[str], cutoff: datetime, seen_ids: set[str]
) -> list[Article]:
    ingester = TwitterIngester()
    try:
        client = await ingester._get_client()
    except Exception as exc:
        logger.warning("fresh_news twitter login failed: %s", exc)
        return []

    results: list[Article] = []

    for topic in topics:
        try:
            tweets = await client.search_tweet(
                f"{topic} lang:en", "Top", count=_FRESH_TWITTER_COUNT
            )
            for tweet in tweets:
                if not parser.extract_article_id_from_quoted_status_result(tweet):
                    continue
                tweet_url = parser.quoted_tweet_url(tweet)
                if not tweet_url:
                    continue
                article = TwitterIngester._normalize(tweet, topic, cutoff)
                if article is None or article.id in seen_ids:
                    continue
                full_text = await TwitterIngester._fetch_full_article(tweet_url)
                if full_text:
                    article = article.model_copy(update={"content": full_text})
                if not article.content:
                    continue
                seen_ids.add(article.id)
                results.append(article)
        except Exception as exc:
            logger.warning("fresh_news twitter topic %r: %s", topic, exc)

    return results


# ── public ───────────────────────────────────────────────────


async def fetch(
    topics: list[str],
    since: datetime | None = None,
) -> list[Article]:
    if not topics:
        return []

    topics = list(dict.fromkeys(topics))
    cutoff = _resolve_cutoff(since)
    seen_ids: set[str] = set()

    newsapi_results, twitter_results = await asyncio.gather(
        _fetch_from_newsapi(topics, cutoff, seen_ids),
        _fetch_from_twitter(topics, cutoff, seen_ids),
        return_exceptions=True,
    )

    results: list[Article] = []
    for batch in (newsapi_results, twitter_results):
        if isinstance(batch, list):
            results.extend(batch)
        else:
            logger.warning("fresh_news source failed: %s", batch)

    return results
