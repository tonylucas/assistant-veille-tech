# ---------------------------------------------------------------
# Flux d'appel des fonctions principales (call flow):
#
# TwitterIngester.run(topics)
#     └─> _fetch_articles_for_topics(topics)(async)
#         └─> _get_client()                 (async)
#             └─> _login()                  (async, si cookies invalides/absents)
#         └─> _fetch_topic_with_retry(client, topic) (async, retry 404 ×5)
#             └─> _fetch_topic(client, topic)        (async, par topic)
#             └─> parser.extract_article_id_from_quoted_status_result(tweet)
#             └─> _normalize(tweet, ...)    (static)
#                 └─> parser.article_url, parser.extract_article_title
#             └─> parser.quoted_tweet_url(tweet)
#             └─> _fetch_full_article(tweet_url)       (async, via md.genedai.me)
#         └─> ... (repeat for all topics)
#     └─> _upsert(articles)                 (static, si articles trouvés)
#         └─> _split_content(content)       (static, découpe le contenu en chunks)
#         └─> get_collection(), embed(), print_db_stats()
#
# Les fonctions statiques servent à la normalisation et l'extraction de données spécifiques.
# ---------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import ValidationError
from twikit import Client
from twikit.errors import NotFound, TwitterException

from app.config import Settings, get_settings
from . import parser
from app.rag.chroma_client import get_collection, print_db_stats
from app.rag.retrieval import embed
from app.schemas import Article

logger = logging.getLogger(__name__)

_LANGUAGE = "en"
_COUNT_PER_PAGE = 20
_MAX_PAGES = 5         # 5 × 20 = 100 tweets examinés par topic
_MAX_AGE_DAYS = 60     # filtre 2 mois
_SEARCH_TYPE = "Top"
_MAX_TOPIC_RETRIES = 5
_MD_GENEDAI_BASE = "https://md.genedai.me"
_CHUNK_SIZE = 2000  # ~400 mots / ~500 tokens en francais
_CHUNK_OVERLAP = 200  # ~10 % d'overlap


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
        """Fetch articles for the given topics and upsert them into the database."""
        if not topics:
            return []

        topics = list(dict.fromkeys(topics))
        self._seen_ids.clear()

        articles = asyncio.run(self._fetch_articles_for_topics(topics))

        if articles:
            self._upsert(articles)

        return [a.model_dump() for a in articles]

    # ── private ──────────────────────────────────────────────

    async def _fetch_articles_for_topics(self, topics: list[str]) -> list[Article]:
        """Fetch articles for the given topics and return them as a list of Article objects."""
        client = await self._get_client()
        articles: list[Article] = []

        for topic in topics:
            articles.extend(await self._fetch_topic_with_retry(client, topic))

        return articles

    async def _fetch_topic_with_retry(self, client: Client, topic: str) -> list[Article]:
        """Fetch a topic, retrying up to _MAX_TOPIC_RETRIES times on 404."""
        for attempt in range(1, _MAX_TOPIC_RETRIES + 1):
            try:
                return await self._fetch_topic(client, topic)
            except NotFound:
                if attempt < _MAX_TOPIC_RETRIES:
                    logger.warning(
                        "topic %r 404 (attempt %d/%d), retrying...",
                        topic, attempt, _MAX_TOPIC_RETRIES,
                    )
                    await asyncio.sleep(1)
                    continue
                logger.warning("topic %r failed after %d attempts: 404", topic, _MAX_TOPIC_RETRIES)
                return []
            except TwitterException as exc:
                logger.warning("topic %r failed: %s", topic, exc)
                return []
        return []

    async def _get_client(self) -> Client:
        """Get a client for the Twitter API."""
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
        """Login to the Twitter API."""
        assert self.settings is not None
        await client.login(
            auth_info_1=self.settings.twitter_username,
            auth_info_2=self.settings.twitter_email,
            password=self.settings.twitter_password,
        )
        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        client.save_cookies(str(cookies_path))

    async def _fetch_topic(self, client: Client, topic: str) -> list[Article]:
        """Fetch articles for the given topic and return them as a list of Article objects."""
        query = f"{topic} lang:{_LANGUAGE}"
        cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)

        articles: list[Article] = []
        result = await client.search_tweet(query, _SEARCH_TYPE, count=_COUNT_PER_PAGE)

        for page in range(_MAX_PAGES):
            page_articles = 0
            for tweet in result:
                if not parser.extract_article_id_from_quoted_status_result(tweet):
                    continue

                tweet_url = parser.quoted_tweet_url(tweet)
                if not tweet_url:
                    continue

                article = self._normalize(tweet, topic, cutoff)
                if article is None or article.id in self._seen_ids:
                    continue

                full_text = await self._fetch_full_article(tweet_url)
                if full_text:
                    article = article.model_copy(update={"content": full_text})

                if not article.content:
                    continue

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

    # ── static helpers ────────────────────────────────────────

    @staticmethod
    async def _fetch_full_article(tweet_url: str) -> str | None:
        """Fetch the full article content as markdown via md.genedai.me, or None if failed."""
        url = f"{_MD_GENEDAI_BASE}/{tweet_url}?raw=true"
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                response = await http.get(url)
                response.raise_for_status()
                return response.text.strip() or None
        except httpx.HTTPError as exc:
            logger.warning("_fetch_full_article(%s) failed: %s", tweet_url, exc)
            return None

    @staticmethod
    def _normalize(tweet: Any, topic: str, cutoff: datetime) -> Article | None:
        """Normalize a tweet into an Article, or None if failed."""
        article_url = parser.article_url(tweet)
        if not article_url:
            return None

        article_title = parser.extract_article_title(tweet)
        if not article_title:
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
                content="",
                url=article_url,
                tags=list(dict.fromkeys(tags)),
                lang=tweet.lang,
            )
        except ValidationError as exc:
            logger.warning("validation failed for %s: %s", article_url, exc)
            return None

    @staticmethod
    def _split_content(content: str) -> list[str]:
        """Split the content into chunks."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
        )
        return splitter.split_text(content)

    @staticmethod
    def _upsert(articles: list[Article]) -> None:
        """Upsert the given articles into the database."""
        print(f"upserting {len(articles)} articles into chroma...")
        collection = get_collection()
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for article in articles:
            chunks = TwitterIngester._split_content(article.content)
            print(f"chunks: {chunks}")
            base_meta = {
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
                "chunk_total": len(chunks),
            }
            for i, chunk in enumerate(chunks):
                ids.append(f"{article.id}_chunk_{i + 1}")
                documents.append(chunk)
                embeddings.append(embed(chunk))
                metadatas.append({**base_meta, "chunk_index": i})

        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("upserted %d chunks from %d articles", len(ids), len(articles))
        print(f"\nupserted {len(ids)} chunks from {len(articles)} articles into chroma")
        print_db_stats()
