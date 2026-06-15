from app.ingest.chroma_upsert import _CHUNK_SIZE, split_content


def test_split_content_splits_long_text() -> None:
    text = "phrase. " * 500
    chunks = split_content(text)
    assert all(len(c) <= _CHUNK_SIZE * 1.1 for c in chunks)
    assert len(chunks) >= 2
