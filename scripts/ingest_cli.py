from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer

from app.rag.chroma_client import delete_documents
from app.ingest.topics import load_topics, save_topics
from app.ingest.news_api import NewsApiIngester
from app.ingest.twitter import TwitterIngester

app = typer.Typer(help="Ingestion CLI for the veille tech index.")

@app.command()
def ingest(
    topics: list[str] = typer.Option(
        None, "--topic", "-t", help="Topic to ingest (repeatable). Falls back to saved topics."
    ),
) -> None:
    """Save topics then run all ingesters (NewsAPI + Twitter)."""
    resolved = list(dict.fromkeys(topics)) if topics else [topic['slug'] for topic in load_topics()]
    if not resolved:
        typer.echo("No topics provided and none saved. Use --topic.", err=True)
        raise typer.Exit(code=1)

    if topics:
        save_topics(resolved)
    typer.echo(f"Topics: {resolved}")

    typer.echo("=== NewsAPI ===")
    news_results = NewsApiIngester().run(resolved)
    typer.echo(f"  {len(news_results)} article(s) ingested")

    typer.echo("=== Twitter ===")
    twitter_results = TwitterIngester().run(resolved)
    typer.echo(f"  {len(twitter_results)} tweet(s) ingested")


@app.command()
def delete_and_ingest(
    topics: list[str] = typer.Option(
        None, "--topic", "-t", help="Topic to ingest (repeatable). Falls back to saved topics."
    ),
) -> None:
    """Delete the collection and ingest the topics."""
    delete_documents(where={"source_type": "news_article"})
    delete_documents(where={"source_type": "x-article"})
    typer.echo("Documents deleted successfully.")

    ingest(topics)
    typer.echo("Documents deleted and ingested successfully.")

if __name__ == "__main__":
    app()
