from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings

_COL_W = 28
_NUM_W = 7
_META_W = 20


@lru_cache(maxsize=1)
def get_client() -> chromadb.HttpClient:
    settings = get_settings()
    parsed = urlparse(settings.chroma_url)
    host = parsed.hostname or "chromadb"
    port = parsed.port or 8000
    return chromadb.HttpClient(host=host, port=port)


def get_collection() -> Collection:
    settings = get_settings()
    client = get_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


def print_db_stats() -> None:
    """Affiche un tableau récapitulatif de toutes les collections ChromaDB."""
    client = get_client()
    collections = client.list_collections()

    title = " ChromaDB — état de la base "
    total_w = _COL_W + _NUM_W + _META_W + 8  # separators + padding

    top    = f"╔{'═' * (total_w)}╗"
    mid_h  = f"╠{'═' * (_COL_W + 2)}╦{'═' * (_NUM_W + 2)}╦{'═' * (_META_W + 2)}╣"
    sep    = f"╠{'═' * (_COL_W + 2)}╬{'═' * (_NUM_W + 2)}╬{'═' * (_META_W + 2)}╣"
    bot    = f"╚{'═' * (_COL_W + 2)}╩{'═' * (_NUM_W + 2)}╩{'═' * (_META_W + 2)}╝"

    def row(col: str, num: str, meta: str) -> str:
        return (
            f"║ {col:<{_COL_W}} ║ {num:>{_NUM_W}} ║ {meta:<{_META_W}} ║"
        )

    print(top)
    print(f"║{title:^{total_w}}║")
    print(mid_h)
    print(row("Collection", "Items", "Métrique (hnsw)"))
    print(sep)

    if not collections:
        print(row("(aucune collection)", "", ""))
    else:
        for col in collections:
            count = col.count()
            metric = (col.metadata or {}).get("hnsw:space", "—")
            name = col.name[:_COL_W] if len(col.name) > _COL_W else col.name
            print(row(name, str(count), metric))

    print(bot)
    print(f"  {len(collections)} collection(s) • {get_settings().chroma_url}")
