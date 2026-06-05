from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.rag.chroma_client import get_collection, print_db_stats
from app.rag.retrieval import embed
from app.schemas import Article

logger = logging.getLogger(__name__)

_ENDPOINT = "latest"
_LANGUAGE = "fr"
_PAGE_SIZE = 10
_MAX_PAGES = 5
_TOPICS_PATH = Path("data/topics.json")
_REMOVE_DUPLICATE = 1
_SORT = "relevancy"
_EXCLUDE_FIELD = "sentiment,sentiment_stats,ai_tag,ai_region,ai_org,ai_summary,content"

def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


@dataclass
class NewsApiIngester:
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

        self._save_topics(topics)
        self._seen_ids.clear()
        articles: list[Article] = []

        with httpx.Client(timeout=30) as client:
            for topic in topics:
                try:
                    articles.extend(self._fetch_topic(client, topic))
                except httpx.HTTPError as exc:
                    logger.warning("topic %r failed: %s", topic, exc)

        if articles:
            self._upsert(articles)

        return [a.model_dump() for a in articles]
 

    # ── private ──────────────────────────────────────────────

    def _fetch_topic(self, client: httpx.Client, topic: str) -> list[Article]:
        assert self.settings is not None
        articles: list[Article] = []
        fetched = 0

        for page in range(1, _MAX_PAGES + 1):
            data = self._fetch_page(client, topic, page)
            raw_articles: list[dict[str, Any]] = data.get("results", [])
            total_results: int = data.get("totalResults", 0)
            for raw in raw_articles:
                article = self._normalize(raw, topic)
                if article and article.id not in self._seen_ids:
                    self._seen_ids.add(article.id)
                    articles.append(article)

            fetched += len(raw_articles)
            if fetched >= total_results or len(raw_articles) < _PAGE_SIZE:
                break

        return articles

    def _fetch_page(self, client: httpx.Client, topic: str, page: int) -> dict[str, Any]:
        """
        Si le fichier local 'mock/news.json' existe, retourne son contenu JSON.
        Sinon, effectue la requête HTTP normale.
        """
        mock_path = Path("mock/news.json")
        if mock_path.exists():
            with mock_path.open(encoding="utf-8") as f:
                return json.load(f)

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
            },
            headers={"X-ACCESS-KEY": self.settings.news_api_key},
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _normalize(raw: dict[str, Any], topic: str) -> Article | None:
        url = raw.get("link") or ""
        if not url:
            return None

        description = raw.get("description") or ""
        body = raw.get("content") or ""
        content = f"{description} {body}".strip()
        if not content:
            return None

        try:
            return Article(
                id=_stable_id(url),
                title=raw.get("title") or "",
                source=raw.get("source_name") or "unknown",
                date=raw.get("pubDate"),
                content=content,
                url=url,
                tags=[topic],
            )
        except ValidationError as exc:
            logger.warning("validation failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _upsert(articles: list[Article]) -> None:
        print(f"upserting {len(articles)} articles into chroma...")
        collection = get_collection()
        ids = [a.id for a in articles]
        documents = [a.content for a in articles]
        embeddings = [embed(doc) for doc in documents]
        metadatas = [
            {
                "title": a.title,
                "source": a.source,
                "date": a.date.isoformat() if a.date else "",
                "url": str(a.url),
                "tags": ",".join(a.tags),
            }
            for a in articles
        ]
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("upserted %d articles into chroma", len(ids))
        print(f"\nupserted {len(ids)} articles into chroma")
        print_db_stats()

    @staticmethod
    def _save_topics(topics: list[str]) -> None:
        _TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "topics": topics,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _TOPICS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info("saved topics to %s", _TOPICS_PATH)
