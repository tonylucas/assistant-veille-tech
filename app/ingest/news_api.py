# ---------------------------------------------------------------
# Flux d'appel des fonctions principales (call flow):
#
# NewsApiIngester.run(topics)
#     └─> _fetch_topic(client, topic)             (par topic)
#         └─> _fetch_page(client, topic, page)    (par page)
#         └─> _normalize(raw)                     (static, normalise chaque article brut)
#     └─> upsert_articles(articles)               (si articles trouvés)
#         └─> get_collection(), embed(), print_db_stats()
#
# Les fonctions statiques servent à la normalisation et à la découpe du contenu.
# ---------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.ingest.chroma_upsert import upsert_articles
from app.ingest.utils import stable_id
from app.schemas import Article

logger = logging.getLogger(__name__)

_ENDPOINT = "latest"
_LANGUAGE = "fr"
_PAGE_SIZE = 10
_MAX_PAGES = 2
_REMOVE_DUPLICATE = 1
_SORT = "relevancy"
_EXCLUDE_FIELD = "sentiment,sentiment_stats,ai_tag,ai_region,ai_org,ai_summary,content"
_CATEGORIES = ["technology"]


@dataclass
class NewsApiIngester:
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
        articles: list[Article] = []

        with httpx.Client(timeout=30) as client:
            for topic in topics:
                try:
                    articles.extend(self._fetch_topic(client, topic))
                except httpx.HTTPError as exc:
                    logger.warning("topic %r failed: %s", topic, exc)

        if articles:
            upsert_articles(articles)

        return [a.model_dump() for a in articles]
 

    # ── private ──────────────────────────────────────────────

    def _fetch_topic(self, client: httpx.Client, topic: str) -> list[Article]:
        """Fetch a topic and return a list of Article objects."""
        assert self.settings is not None
        articles: list[Article] = []
        fetched = 0

        for page in range(1, _MAX_PAGES + 1):
            data = self._fetch_page(client, topic, page)
            raw_articles: list[dict[str, Any]] = data.get("results", [])
            total_results: int = data.get("totalResults", 0)
            for raw in raw_articles:
                article = self._normalize(raw)
                if article and article.id not in self._seen_ids:
                    self._seen_ids.add(article.id)
                    articles.append(article)

            fetched += len(raw_articles)
            if fetched >= total_results or len(raw_articles) < _PAGE_SIZE:
                break

        return articles

    def _fetch_page(self, client: httpx.Client, topic: str, page: int) -> dict[str, Any]:
        """Fetch a page of articles and return a dictionary of results."""
        assert self.settings is not None
        resp = client.get(
            f"{self.settings.news_api_base_url}/{_ENDPOINT}",
            params={
                "q": topic,
                "size": _PAGE_SIZE,
                "page": page,
                "sort": _SORT,
                "language": _LANGUAGE,
                "removeDuplicate": _REMOVE_DUPLICATE,
                "excludefield": _EXCLUDE_FIELD,
                "category": _CATEGORIES,
            },
            headers={"X-ACCESS-KEY": self.settings.news_api_key},
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> Article | None:
        """Normalize a raw article and return an Article object."""
        url = raw.get("link") or ""
        if not url:
            return None

        description = raw.get("description") or ""
        content = description.strip()
        if not content:
            return None

        tags = (raw.get("category") or []) + (raw.get("keywords") or [])

        try:
            return Article(
                id=stable_id(url),
                title=raw.get("title") or "",
                source_name=raw.get("source_name") or "unknown",
                source_type="news_article",
                date_published=raw.get("pubDate"),
                date_collected=raw.get("fetched_at"),
                content=content,
                url=url,
                tags=list(dict.fromkeys(tags)),
            )
        except ValidationError as exc:
            logger.warning("validation failed for %s: %s", url, exc)
            return None
