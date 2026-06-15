from __future__ import annotations

import logging
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chroma_client import get_collection, print_db_stats
from app.rag.retrieval import embed
from app.schemas import Article

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 2000  # ~400 mots / ~500 tokens en francais
_CHUNK_OVERLAP = 200  # ~10 % d'overlap


def split_content(content: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
    )
    return splitter.split_text(content)


def upsert_articles(articles: list[Article]) -> None:
    """Chunk, embed and upsert articles into Chroma."""
    print(f"upserting {len(articles)} articles into chroma...")
    collection = get_collection()
    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []

    for article in articles:
        chunks = split_content(article.content)
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
            "lang": article.lang or "",
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
