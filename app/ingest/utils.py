from __future__ import annotations

import hashlib


def stable_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()
