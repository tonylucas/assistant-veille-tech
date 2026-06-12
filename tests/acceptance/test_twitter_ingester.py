from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.ingest.twitter import TwitterIngester
from tests.acceptance.ingest_helpers import assert_normalized_articles, assert_unique_urls


class _FakeUser:
    def __init__(self, screen_name: str) -> None:
        self.screen_name = screen_name


class _FakeSearchResult:
    next_cursor: str | None = None

    def __init__(self, tweets: list[_FakeTweet]) -> None:
        self._tweets = tweets

    def __iter__(self):
        return iter(self._tweets)

    def __len__(self) -> int:
        return len(self._tweets)


class _FakeTweet:
    def __init__(
        self,
        tweet_id: str,
        title: str,
        screen_name: str,
        created_at_datetime: datetime,
        hashtags: list[str] | None = None,
    ) -> None:
        self.id = tweet_id
        self.user = _FakeUser(screen_name)
        self.created_at_datetime = created_at_datetime
        self.hashtags = hashtags or []
        self.lang = "en"
        self._data = _article_data(tweet_id, title, screen_name)


def _article_data(tweet_id: str, title: str, screen_name: str) -> dict[str, Any]:
    return {
        "quoted_status_result": {
            "result": {
                "rest_id": tweet_id,
                "article": {
                    "article_results": {
                        "result": {
                            "rest_id": f"article-{tweet_id}",
                            "title": title,
                        }
                    }
                },
                "core": {
                    "user_results": {
                        "result": {"legacy": {"screen_name": screen_name}}
                    }
                },
            }
        }
    }


def _recent(days: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def load_cookies(self, path: str) -> None:
        pass

    def save_cookies(self, path: str) -> None:
        pass

    async def login(self, **kwargs) -> None:
        pass

    async def search_tweet(self, query: str, product: str, count: int = 20):
        return _FakeSearchResult(
            [
                _FakeTweet("1001", f"Article {query}", "devuser", _recent(2), ["python"]),
                _FakeTweet("1002", f"Autre article {query}", "techuser", _recent(5)),
            ]
        )


async def _fake_fetch_full_article(article_url: str) -> str | None:
    return f"Contenu pour {article_url}"


def _patch_twitter_io(monkeypatch, *, client_factory: type[_FakeClient]) -> None:
    """Stub auth, article fetch and Chroma upsert for isolated ingester tests."""
    async def fake_get_client(self):
        return client_factory()

    monkeypatch.setattr(TwitterIngester, "_get_client", fake_get_client)
    monkeypatch.setattr(
        TwitterIngester,
        "_fetch_full_article",
        staticmethod(_fake_fetch_full_article),
    )
    monkeypatch.setattr("app.ingest.twitter.ingester.upsert_articles", lambda articles: None)


@pytest.fixture()
def twitter_mock(monkeypatch):
    """Patche client, fetch article et upsert Chroma pour isoler l'ingestion."""
    _patch_twitter_io(monkeypatch, client_factory=_FakeClient)
    yield


def test_run_returns_list_of_normalized_articles(twitter_mock) -> None:
    ingester = TwitterIngester()
    articles = ingester.run(["python", "rust"])
    assert_normalized_articles(articles, source_type="x-article")


def test_run_filters_old_tweets(monkeypatch) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=90)

    class _OldClient(_FakeClient):
        async def search_tweet(self, query: str, product: str, count: int = 20):
            return _FakeSearchResult(
                [
                    _FakeTweet("2001", "Article recent", "u1", _recent(3)),
                    _FakeTweet("2002", "Article ancien", "u2", old),
                ]
            )

    _patch_twitter_io(monkeypatch, client_factory=_OldClient)

    ingester = TwitterIngester()
    articles = ingester.run(["python"])
    assert len(articles) == 1
    assert articles[0]["title"] == "Article recent"
    assert articles[0]["content"].startswith("Contenu pour")


def test_run_dedupes_same_article_url_across_topics(monkeypatch) -> None:
    """Two topic searches return the same article URL; run() keeps it once."""
    shared = _FakeTweet("1001", "Article partagé", "devuser", _recent(2))

    class _DuplicateClient(_FakeClient):
        async def search_tweet(self, query: str, product: str, count: int = 20):
            return _FakeSearchResult([shared])

    _patch_twitter_io(monkeypatch, client_factory=_DuplicateClient)

    ingester = TwitterIngester()
    articles = ingester.run(["python", "rust"])

    assert len(articles) == 1
    assert articles[0]["url"] == "https://x.com/i/article/article-1001"
    assert_unique_urls(articles)


def test_run_handles_empty_topics() -> None:
    ingester = TwitterIngester()
    articles = ingester.run([])
    assert articles == []
