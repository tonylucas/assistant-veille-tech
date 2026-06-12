from __future__ import annotations

from typing import Any

REQUIRED_ARTICLE_FIELDS = (
    "id",
    "title",
    "source_name",
    "source_type",
    "date_published",
    "date_collected",
    "url",
    "content",
)


def assert_normalized_articles(
    articles: list[dict[str, Any]],
    *,
    source_type: str,
) -> None:
    """Assert run() returned a non-empty list of Article-shaped dicts."""
    assert isinstance(articles, list)
    assert len(articles) > 0
    for art in articles:
        for field in REQUIRED_ARTICLE_FIELDS:
            assert field in art
        assert art["source_type"] == source_type


def assert_unique_urls(articles: list[dict[str, Any]]) -> None:
    urls = [art["url"] for art in articles]
    assert len(urls) == len(set(urls))
