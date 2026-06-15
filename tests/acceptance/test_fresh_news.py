from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.runtime import fresh_news
from app.schemas import Article


@pytest.mark.asyncio
async def test_fetch_returns_list_of_articles() -> None:
    out = await fresh_news.fetch(topics=["python"], since=None)
    assert isinstance(out, list)
    for art in out:
        assert isinstance(art, Article)
        assert art.title
        assert art.url
        assert art.source_name


@pytest.mark.asyncio
async def test_fetch_filters_by_since() -> None:
    since = datetime.now(timezone.utc) - timedelta(days=2)
    articles = await fresh_news.fetch(topics=["ai"], since=since)
    assert isinstance(articles, list)
    for art in articles:
        if art.date_published is None:
            continue
        pub = art.date_published
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        assert pub >= since


@pytest.mark.asyncio
async def test_fetch_empty_topics_returns_empty() -> None:
    out = await fresh_news.fetch(topics=[], since=None)
    assert out == []
