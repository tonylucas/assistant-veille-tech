from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "news.json"


@pytest.fixture()
def news_api_mock():
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
