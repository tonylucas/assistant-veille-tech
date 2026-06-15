from __future__ import annotations

import pytest

from app.ingest.chroma_upsert import split_content
from app.ingest.news_api import NewsApiIngester
from tests.acceptance.ingest_helpers import assert_normalized_articles, assert_unique_urls
from tests.acceptance.news_api_fakes import mock_news_api


@pytest.fixture()
def news_api_mock():
    with mock_news_api() as mock:
        yield mock


def test_run_returns_list_of_normalized_articles(news_api_mock) -> None:
    ingester = NewsApiIngester()
    articles = ingester.run(["python", "ai-ml"])
    assert_normalized_articles(articles, source_type="news_article")


def test_run_tags_contain_category_and_keywords(news_api_mock) -> None:
    ingester = NewsApiIngester()
    articles = ingester.run(["python"])
    articles_with_tags = [a for a in articles if a["tags"]]
    assert len(articles_with_tags) > 0


def test_split_content_chunks_long_text() -> None:
    long_text = "Phrase de veille technologique. " * 400
    chunks = split_content(long_text)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_split_content_keeps_short_text_single_chunk() -> None:
    chunks = split_content("Un court article.")
    assert chunks == ["Un court article."]


def test_run_handles_empty_topics() -> None:
    ingester = NewsApiIngester()
    articles = ingester.run([])
    assert articles == []


def test_run_dedupes_across_topics(news_api_mock) -> None:
    ingester = NewsApiIngester()
    articles = ingester.run(["python", "python"])
    assert_unique_urls(articles)
