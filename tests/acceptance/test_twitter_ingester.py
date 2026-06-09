from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ingest.twitter import TwitterIngester


class _FakeUser:
    def __init__(self, screen_name: str) -> None:
        self.screen_name = screen_name


class _FakeTweet:
    def __init__(
        self,
        tweet_id: str,
        text: str,
        screen_name: str,
        created_at_datetime: datetime,
        hashtags: list[str] | None = None,
    ) -> None:
        self.id = tweet_id
        self.text = text
        self.user = _FakeUser(screen_name)
        self.created_at_datetime = created_at_datetime
        self.hashtags = hashtags or []


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
        return [
            _FakeTweet("1001", f"Tweet sur {query} #python", "devuser", _recent(2), ["python"]),
            _FakeTweet("1002", f"Autre tweet {query}", "techuser", _recent(5)),
        ]


@pytest.fixture()
def twitter_mock(monkeypatch):
    """Patche _get_client et l'upsert Chroma pour isoler la normalisation."""
    async def fake_get_client(self):
        return _FakeClient()

    monkeypatch.setattr(TwitterIngester, "_get_client", fake_get_client)
    monkeypatch.setattr(TwitterIngester, "_upsert", staticmethod(lambda articles: None))
    yield


def test_run_returns_list_of_normalized_articles(twitter_mock) -> None:
    ingester = TwitterIngester()
    articles = ingester.run(["python", "rust"])
    print(f"articles: {articles}")
    assert isinstance(articles, list)
    assert len(articles) > 0
    for art in articles:
        assert "id" in art
        assert "title" in art
        assert "source_name" in art
        assert "source_type" in art
        assert "date_published" in art
        assert "date_collected" in art
        assert "url" in art
        assert "content" in art


def test_run_source_type_is_tweet(twitter_mock) -> None:
    ingester = TwitterIngester()
    articles = ingester.run(["python"])
    assert articles
    assert all(art["source_type"] == "tweet" for art in articles)


def test_run_filters_old_tweets(monkeypatch) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=90)

    class _OldClient(_FakeClient):
        async def search_tweet(self, query: str, product: str, count: int = 20):
            return [
                _FakeTweet("2001", "tweet recent", "u1", _recent(3)),
                _FakeTweet("2002", "tweet ancien", "u2", old),
            ]

    async def fake_get_client(self):
        return _OldClient()

    monkeypatch.setattr(TwitterIngester, "_get_client", fake_get_client)
    monkeypatch.setattr(TwitterIngester, "_upsert", staticmethod(lambda articles: None))

    ingester = TwitterIngester()
    articles = ingester.run(["python"])
    assert len(articles) == 1
    assert articles[0]["content"] == "tweet recent"


def test_run_dedupes_across_topics(twitter_mock) -> None:
    ingester = TwitterIngester()
    articles = ingester.run(["python", "rust"])
    ids = [a["id"] for a in articles]
    assert len(ids) == len(set(ids))


def test_run_handles_empty_topics() -> None:
    ingester = TwitterIngester()
    articles = ingester.run([])
    assert articles == []
