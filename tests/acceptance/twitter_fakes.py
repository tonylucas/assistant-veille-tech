"""Fakes Twikit/Twitter pour les tests d'ingestion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.ingest.twitter import TwitterIngester


class FakeUser:
    def __init__(self, screen_name: str) -> None:
        self.screen_name = screen_name


class FakeSearchResult:
    next_cursor: str | None = None

    def __init__(self, tweets: list[FakeTweet]) -> None:
        self._tweets = tweets

    def __iter__(self):
        return iter(self._tweets)

    def __len__(self) -> int:
        return len(self._tweets)


class FakeTweet:
    def __init__(
        self,
        tweet_id: str,
        title: str,
        screen_name: str,
        created_at_datetime: datetime,
        hashtags: list[str] | None = None,
    ) -> None:
        self.id = tweet_id
        self.user = FakeUser(screen_name)
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


def recent(days: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class FakeTwikitClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def load_cookies(self, path: str) -> None:
        pass

    def save_cookies(self, path: str) -> None:
        pass

    async def login(self, **kwargs) -> None:
        pass

    async def search_tweet(self, query: str, product: str, count: int = 20):
        return FakeSearchResult(
            [
                FakeTweet("1001", f"Article {query}", "devuser", recent(2), ["python"]),
                FakeTweet("1002", f"Autre article {query}", "techuser", recent(5)),
            ]
        )


class FakeTwikitClientOldArticle(FakeTwikitClient):
    async def search_tweet(self, query: str, product: str, count: int = 20):
        old = datetime.now(timezone.utc) - timedelta(days=90)
        return FakeSearchResult(
            [
                FakeTweet("2001", "Article recent", "u1", recent(3)),
                FakeTweet("2002", "Article ancien", "u2", old),
            ]
        )


class FakeTwikitClientDuplicateArticle(FakeTwikitClient):
    async def search_tweet(self, query: str, product: str, count: int = 20):
        shared = FakeTweet("1001", "Article partagé", "devuser", recent(2))
        return FakeSearchResult([shared])


async def fake_fetch_full_article(article_url: str) -> str | None:
    return f"Contenu pour {article_url}"


def patch_twitter_io(monkeypatch, *, client_factory: type[FakeTwikitClient]) -> None:
    """Stub auth, article fetch and Chroma upsert for isolated ingester tests."""
    async def fake_get_client(self):
        return client_factory()

    monkeypatch.setattr(TwitterIngester, "_get_client", fake_get_client)
    monkeypatch.setattr(
        TwitterIngester,
        "_fetch_full_article",
        staticmethod(fake_fetch_full_article),
    )
    monkeypatch.setattr("app.ingest.twitter.ingester.upsert_articles", lambda articles: None)
