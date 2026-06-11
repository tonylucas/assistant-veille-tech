from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json

from pydantic import ValidationError
from twikit import Client
from twikit.errors import TwitterException

from app.config import Settings, get_settings
from app.rag.chroma_client import get_collection, print_db_stats
from app.rag.retrieval import embed
from app.schemas import Article

logger = logging.getLogger(__name__)

_LANGUAGE = "en"
_COUNT_PER_PAGE = 20
_MAX_PAGES = 5         # 5 × 20 = 100 tweets examinés par topic
_MAX_AGE_DAYS = 60     # filtre 2 mois
_SEARCH_TYPE = "Top"
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
        cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)

        articles: list[Article] = []
        result = await client.search_tweet(query, _SEARCH_TYPE, count=_COUNT_PER_PAGE)

        for page in range(_MAX_PAGES):
            page_articles = 0
            for tweet in result:
                if getattr(tweet, "lang", None) not in (None, _LANGUAGE):
                    continue
                article = self._normalize(tweet, topic, cutoff)
                if article is None or article.id in self._seen_ids:
                    continue

                full_text = await self._fetch_full_article(client, tweet.id)

                if full_text:
                    article = article.model_copy(update={"content": full_text})

                self._seen_ids.add(article.id)
                articles.append(article)
                page_articles += 1

            print(
                f"topic={topic} page={page + 1} tweets={len(result)} articles_found={page_articles}",
            )

            if page < _MAX_PAGES - 1 and result.next_cursor:
                result = await result.next()
            else:
                break

        logger.info("topic=%r total_articles=%d", topic, len(articles))
        return articles

    @staticmethod
    def _article_url(tweet: Any) -> str | None:
        """
        Retourne l'URL x.com/{user}/article/... si le tweet est un article X, sinon None.
        Nouvelle version : cherche dans quoted_status_result > article > article_results > result > rest_id
        et remonte l'URL canonique de l'article si possible.

        Cette méthode est adaptée au format observé dans article.json (tweet data logué à la main).
        """
        data = getattr(tweet, "_data", {})
        rest_id = data.get("legacy", {}).get("quoted_status_id_str", "")
        if rest_id:
            # On va tenter de retrouver le nom d'utilisateur original pour le coller dans l'URL canonique
            qsr_core_user = (
                data.get("quoted_status_result", {})
                .get("result", {})
                .get("core", {})
                .get("user_results", {})
                .get("result", {})
                .get("legacy", {})
            )
            screen_name = qsr_core_user.get("screen_name", "unknown")
            return f"https://x.com/{screen_name}/article/{rest_id}"

        # Si on ne trouve pas, fallback sur l'ancien comportement (par sécurité)
        urls = (
            data
            .get("legacy", {})
            .get("entities", {})
            .get("urls", [])
        )
        for u in urls:
            expanded = u.get("expanded_url", "")
            if ("x.com" in expanded or "twitter.com" in expanded) and "/article/" in expanded:
                return expanded
        return None

    @staticmethod
    async def _fetch_full_article(client: Client, tweet_id: str) -> str | None:
        """Second appel avec fieldToggles article pour récupérer le contenu complet."""
        try:
            tweet = await client.get_tweet_by_id(tweet_id)
            article_data = (
                tweet._data
                .get("article", {})
                .get("article_results", {})
                .get("result", {})
            )
            return article_data.get("plain_text") or article_data.get("preview_text") or None
        except Exception as exc:
            logger.warning("_fetch_full_article(%s) failed: %s", tweet_id, exc)
            return None

    @staticmethod
    def _extract_article_title(tweet: Any) -> str | None:
        """Extract the title of an article from a tweet. Return None if tweet is not an article."""
        try:
            data = getattr(tweet, "_data", {})
            return (
                data.get("quoted_status_result", {})
                .get("result", {})
                .get("article", {})
                .get("article_results", {})
                .get("result", {})
                .get("title", "")
            )
        except (AttributeError, KeyError, TypeError):
            return None

    @staticmethod
    def _normalize(tweet: Any, topic: str, cutoff: datetime) -> Article | None:
        article_title = TwitterIngester._extract_article_title(tweet)

        if not article_title:
            return None

        article_url = TwitterIngester._article_url(tweet)
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
        tags = [topic] + list(tweet.hashtags or [])

        try:
            return Article(
                id=_stable_id(article_url),
                title=article_title,
                source_name=screen_name,
                source_type="x-article",
                date_published=date_published,
                date_collected=datetime.now(timezone.utc),
                content=content,
                url=article_url,
                tags=list(dict.fromkeys(tags)),
                lang=tweet.lang,
            )
        except ValidationError as exc:
            logger.warning("validation failed for %s: %s", article_url, exc)
            return None

    @staticmethod
    def _upsert(articles: list[Article]) -> None:
        print(f"upserting {len(articles)} tweets into chroma...")
        collection = get_collection()
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        print(f"articles[0]: {articles[0].model_dump()}")
        for article in articles:
            if article is None:
                continue
            print(f"title: {article.title[:100]}..., url: {article.url}, lang: {article.lang}")
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
