from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
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
_REMOVE_DUPLICATE = 1
_SORT = "relevancy"
_EXCLUDE_FIELD = "sentiment,sentiment_stats,ai_tag,ai_region,ai_org,ai_summary,content"
_CHUNK_SIZE = 2000  # ~400 mots / ~500 tokens en francais
_CHUNK_OVERLAP = 200  # ~10 % d'overlap

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
                article = self._normalize(raw)
                if article and article.id not in self._seen_ids:
                    self._seen_ids.add(article.id)
                    articles.append(article)

            fetched += len(raw_articles)
            if fetched >= total_results or len(raw_articles) < _PAGE_SIZE:
                break

        return articles

    def _fetch_page(self, client: httpx.Client, topic: str, page: int) -> dict[str, Any]:
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
    def _normalize(raw: dict[str, Any]) -> Article | None:
        url = raw.get("link") or ""
        if not url:
            return None

        description = raw.get("description") or ""
        body = raw.get("content") or ""
        content = f"{description} {body}".strip()
        if not content:
            return None

        tags = (raw.get("category") or []) + (raw.get("keywords") or [])

        try:
            return Article(
                id=_stable_id(url),
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

    @staticmethod
    def _split_content(content: str) -> list[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
        )
        return splitter.split_text(content)

    @staticmethod
    def _upsert(articles: list[Article]) -> None:
        print(f"upserting {len(articles)} articles into chroma...")
        collection = get_collection()
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for article in articles:
            chunks = NewsApiIngester._split_content(article.content)
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
