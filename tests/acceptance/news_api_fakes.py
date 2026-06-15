"""Fakes NewsAPI pour les tests d'ingestion."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx
import respx

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "news.json"


@contextmanager
def mock_news_api() -> Iterator[respx.MockRouter]:
    """
    Intercepte les appels httpx vers newsdata.io avec des données stables.
    ChromaDB et Azure Embeddings sont appelés réellement (tests d'acceptance).
    """
    fixture_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"^https://newsdata\.io.*").mock(
            return_value=httpx.Response(200, json=fixture_data)
        )
        mock.route().pass_through()
        yield mock
