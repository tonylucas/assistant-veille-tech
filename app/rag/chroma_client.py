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

def delete_documents(where: dict[str, str]) -> None:
    """Delete all documents from the collection where the metadata matches the given where clause."""
    settings = get_settings()
    client = get_client()
    collection = client.get_collection(settings.chroma_collection)
    collection.delete(
        where=where
    )

def print_db_stats() -> None:
    """Affiche un tableau récapitulatif de toutes les collections ChromaDB
    avec répartition des items par source_type."""
    client = get_client()
    collections = client.list_collections()

    # Largeur supplémentaire pour le détail par source_type
    _SRC_W = 34
    total_w = _COL_W + _NUM_W + _META_W + _SRC_W + 11  # 11 pour séparateurs

    title = " ChromaDB — état de la base "
    top    = f"╔{'═' * (total_w)}╗"
    mid_h  = f"╠{'═' * (_COL_W + 2)}╦{'═' * (_NUM_W + 2)}╦{'═' * (_META_W + 2)}╦{'═' * (_SRC_W + 2)}╣"
    sep    = f"╠{'═' * (_COL_W + 2)}╬{'═' * (_NUM_W + 2)}╬{'═' * (_META_W + 2)}╬{'═' * (_SRC_W + 2)}╣"
    bot    = f"╚{'═' * (_COL_W + 2)}╩{'═' * (_NUM_W + 2)}╩{'═' * (_META_W + 2)}╩{'═' * (_SRC_W + 2)}╝"

    def row(col: str, num: str, meta: str, per_source: str) -> str:
        return (
            f"║ {col:<{_COL_W}} ║ {num:>{_NUM_W}} ║ {meta:<{_META_W}} ║ {per_source:<{_SRC_W}} ║"
        )

    print(top)
    print(f"║{title:^{total_w}}║")
    print(mid_h)
    print(row("Collection", "Items", "Métrique (hnsw)", "Items par source_type"))
    print(sep)

    if not collections:
        print(row("(aucune collection)", "", "", ""))
    else:
        for col in collections:
            count = col.count()
            metric = (col.metadata or {}).get("hnsw:space", "—")
            name = col.name[:_COL_W] if len(col.name) > _COL_W else col.name

            # Statistiques détaillées par source_type
            try:
                # Extraction jusqu'à 1000 docs suffit pour l'affichage
                MAX_SAMPLE = 1000
                docs = col.get(
                    include=["metadatas"], 
                    limit=MAX_SAMPLE,
                )
                source_counts = {}
                metadatas = docs.get("metadatas", [])
                for meta in metadatas:
                    if not meta:
                        continue
                    st = meta.get("source_type", "—")
                    source_counts[st] = source_counts.get(st, 0) + 1
                per_source = ", ".join(f"{k}:{v}" for k, v in sorted(source_counts.items())) or "—"
                if count > MAX_SAMPLE and per_source != "—":
                    per_source += " …"
            except Exception as e:
                per_source = f"[erreur: {e}]"

            print(row(name, str(count), metric, per_source))

    print(bot)
    print(f"  {len(collections)} collection(s) • {get_settings().chroma_url}")
