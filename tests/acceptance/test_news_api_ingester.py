from __future__ import annotations

from app.ingest.news_api import NewsApiIngester


def test_run_returns_list_of_normalized_articles() -> None:
    ingester = NewsApiIngester()
    articles = ingester.run(["python", "ai-ml"])
    assert isinstance(articles, list)
    for art in articles:
        assert "id" in art
        assert "title" in art
        assert "source_name" in art
        assert "source_type" in art
        assert "date_published" in art
        assert "date_collected" in art
        assert "url" in art
        assert "content" in art


def test_split_content_chunks_long_text() -> None:
    long_text = "Phrase de veille technologique. " * 400
    chunks = NewsApiIngester._split_content(long_text)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_split_content_keeps_short_text_single_chunk() -> None:
    chunks = NewsApiIngester._split_content("Un court article.")
    assert chunks == ["Un court article."]


def test_run_handles_empty_topics() -> None:
    ingester = NewsApiIngester()
    articles = ingester.run([])
    assert articles == [] or isinstance(articles, list)


def test_run_dedupes_across_topics() -> None:
    ingester = NewsApiIngester()
    articles = ingester.run(["python", "python"])
    ids = [a["id"] for a in articles]
    assert len(ids) == len(set(ids))
