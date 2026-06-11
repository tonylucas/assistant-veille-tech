from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import Topic

logger = logging.getLogger(__name__)

_TOPICS_PATH = Path("data/topics.json")


def save_topics(topics: list[str]) -> list[Topic]:
    """Persist the current topic list to disk (single source of truth)."""
    _TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized_topics = [
        {
            "slug": re.sub(r"[^a-zA-Z0-9]", " ", topic).lower().replace(" ", "-"),
            "label": topic,
        }
        for topic in topics
    ]
    print(f"normalized_topics: {normalized_topics}")
    payload = {
        "topics": normalized_topics,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _TOPICS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("saved %d topic(s) to %s", len(normalized_topics), _TOPICS_PATH)
    return normalized_topics


def load_topics() -> list[Topic]:
    """Load the persisted topic list from disk; returns [] if absent."""
    if not _TOPICS_PATH.exists():
        return []
    try:
        data = json.loads(_TOPICS_PATH.read_text())
        return data.get("topics", [])
    except Exception as exc:
        logger.warning("could not read %s: %s", _TOPICS_PATH, exc)
        return []
