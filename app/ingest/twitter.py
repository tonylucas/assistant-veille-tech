from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from twikit import Client
from twikit.errors import TwitterException

from app.config import Settings, get_settings
from app.rag.chroma_client import get_collection, print_db_stats
from app.rag.retrieval import embed
from app.schemas import Article

logger = logging.getLogger(__name__)

_LANGUAGE = "en"
_MAX_TWEETS_PER_TOPIC = 20
_MAX_AGE_DAYS = 60  # filtre 2 mois
_SEARCH_TYPE = "Latest"
_TITLE_MAX_LEN = 100
def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


@dataclass
class TwitterIngester:
    settings: Settings | None = None
    _seen_ids: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()

    # ── public ───────────────────────────────────────────────

    def run(self, topics: list[str]) -> list[dict[str, Any]]:
        if not topics:
            return []

        topics = list(dict.fromkeys(topics))

        self._seen_ids.clear()

        articles = asyncio.run(self._async_run(topics))

        if articles:
            self._upsert(articles)

        return [a.model_dump() for a in articles]

    # ── private ──────────────────────────────────────────────

    async def _async_run(self, topics: list[str]) -> list[Article]:
        client = await self._get_client()
        articles: list[Article] = []

        for topic in topics:
            try:
                articles.extend(await self._fetch_topic(client, topic))
            except TwitterException as exc:
                logger.warning("topic %r failed: %s", topic, exc)

        return articles

    async def _get_client(self) -> Client:
        assert self.settings is not None
        client = Client(language=_LANGUAGE)
        cookies_path = Path(self.settings.twitter_cookies_path)

        if cookies_path.exists():
            try:
                client.load_cookies(str(cookies_path))
                return client
            except Exception as exc:
                logger.warning("cookies invalides (%s), nouveau login", exc)

        await self._login(client, cookies_path)
        return client

    async def _login(self, client: Client, cookies_path: Path) -> None:
        assert self.settings is not None
        await client.login(
            auth_info_1=self.settings.twitter_username,
            auth_info_2=self.settings.twitter_email,
            password=self.settings.twitter_password,
        )
        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        client.save_cookies(str(cookies_path))

    async def _fetch_topic(self, client: Client, topic: str) -> list[Article]:
        query = f"{topic} lang:{_LANGUAGE}"
        tweets = await client.search_tweet(query, _SEARCH_TYPE, count=_MAX_TWEETS_PER_TOPIC)
        cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)

        articles: list[Article] = []
        for tweet in tweets:
            if getattr(tweet, "lang", None) not in (None, _LANGUAGE):
                continue
            article = self._normalize(tweet, topic, cutoff)
            if article and article.id not in self._seen_ids:
                self._seen_ids.add(article.id)
                articles.append(article)

        return articles

    @staticmethod
    def _normalize(tweet: Any, topic: str, cutoff: datetime) -> Article | None:
        content = (tweet.text or "").strip()
        if not content:
            return None

        try:
            date_published = tweet.created_at_datetime
        except (ValueError, TypeError):
            date_published = None

        if date_published is not None and date_published < cutoff:
            return None

        screen_name = getattr(tweet.user, "screen_name", "") or "unknown"
        url = f"https://x.com/{screen_name}/status/{tweet.id}"
        tags = [topic] + list(tweet.hashtags or [])

        try:
            return Article(
                id=_stable_id(url),
                title=content[:_TITLE_MAX_LEN],
                source_name=screen_name,
                source_type="tweet",
                date_published=date_published,
                date_collected=datetime.now(timezone.utc),
                content=content,
                url=url,
                tags=list(dict.fromkeys(tags)),
                lang=tweet.lang,
            )
        except ValidationError as exc:
            logger.warning("validation failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _upsert(articles: list[Article]) -> None:
        print(f"upserting {len(articles)} tweets into chroma...")
        collection = get_collection()
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for article in articles:
            print(f"title: {article.title[:30]}..., url: {article.url}, lang: {article.lang}")
            ids.append(article.id)
            documents.append(article.content)
            embeddings.append(embed(article.content))
            metadatas.append(
                {
                    "source_type": article.source_type,
                    "source_name": article.source_name,
                    "date_published": article.date_published.isoformat()
                    if article.date_published
                    else "",
                    "date_collected": article.date_collected.isoformat()
                    if article.date_collected
                    else "",
                    "tags": ",".join(article.tags),
                    "url": str(article.url),
                    "title": article.title,
                    "lang": article.lang,
                }
            )

        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("upserted %d tweets", len(ids))
        print(f"\nupserted {len(ids)} tweets into chroma")
        print_db_stats()
