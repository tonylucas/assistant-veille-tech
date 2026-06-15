from __future__ import annotations

import pytest

from app.ingest.twitter import TwitterIngester
from tests.acceptance.ingest_helpers import assert_normalized_articles, assert_unique_urls
from tests.acceptance.twitter_fakes import (
    FakeTwikitClient,
    FakeTwikitClientDuplicateArticle,
    FakeTwikitClientOldArticle,
    patch_twitter_io,
)


@pytest.fixture()
def twitter_mock(monkeypatch):
    """Patche client, fetch article et upsert Chroma pour isoler l'ingestion."""
    patch_twitter_io(monkeypatch, client_factory=FakeTwikitClient)
    yield


def test_run_returns_list_of_normalized_articles(twitter_mock) -> None:
    ingester = TwitterIngester()
    articles = ingester.run(["python", "rust"])
    assert_normalized_articles(articles, source_type="x-article")


def test_run_filters_old_tweets(monkeypatch) -> None:
    patch_twitter_io(monkeypatch, client_factory=FakeTwikitClientOldArticle)

    ingester = TwitterIngester()
    articles = ingester.run(["python"])
    assert len(articles) == 1
    assert articles[0]["title"] == "Article recent"
    assert articles[0]["content"].startswith("Contenu pour")


def test_run_dedupes_same_article_url_across_topics(monkeypatch) -> None:
    """Two topic searches return the same article URL; run() keeps it once."""
    patch_twitter_io(monkeypatch, client_factory=FakeTwikitClientDuplicateArticle)

    ingester = TwitterIngester()
    articles = ingester.run(["python", "rust"])

    assert len(articles) == 1
    assert articles[0]["url"] == "https://x.com/i/article/article-1001"
    assert_unique_urls(articles)


def test_run_handles_empty_topics() -> None:
    ingester = TwitterIngester()
    articles = ingester.run([])
    assert articles == []
