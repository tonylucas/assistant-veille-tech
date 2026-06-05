from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_azure_ai.embeddings import AzureAIOpenAIApiEmbeddingsModel

from app.config import get_settings
from app.rag.chroma_client import get_collection

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embedder() -> AzureAIOpenAIApiEmbeddingsModel:
    settings = get_settings()
    return AzureAIOpenAIApiEmbeddingsModel(
        endpoint=settings.azure_ai_embedding_endpoint,
        credential=settings.azure_ai_embedding_api_key,
        model=settings.azure_ai_embedding_model,
    )


def embed(text: str) -> list[float]:
    return get_embedder().embed_query(text)


def retrieve(query: str, k: int = 8) -> list[dict[str, Any]]:
    try:
        collection = get_collection()
        query_vec = embed(query)
        result = collection.query(query_embeddings=[query_vec], n_results=k)
    except Exception as exc:
        logger.warning("retrieval failed: %s", exc)
        return []

    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    chunks: list[dict[str, Any]] = []
    for doc_id, doc, meta, dist in zip(ids, docs, metas, distances, strict=False):
        chunks.append(
            {
                "id": doc_id,
                "content": doc,
                "metadata": meta or {},
                "distance": dist,
            }
        )
    return chunks
