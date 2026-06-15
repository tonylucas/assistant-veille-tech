# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Assistant Veille Tech** is a French internal tech monitoring assistant using RAG (Retrieval-Augmented Generation). It ingests articles from NewsAPI and Twitter/X, embeds them into ChromaDB, and answers natural language questions by retrieving relevant chunks and synthesizing with an LLM (Azure AI / Kimi-K2.6).

Stack: Python 3.11 + FastAPI backend, Next.js 15 frontend, ChromaDB vector store, Docker Compose orchestration.

## Commands

All Python commands use `uv`. All dev shortcuts are in the `Makefile`.

```bash
make install          # uv sync — install dependencies
make up               # docker compose up -d
make down             # docker compose down
make logs             # docker compose logs -f --tail=100
make test             # uv run pytest -v
make fmt              # ruff format + fix
make lint             # uv run ruff check .
make typecheck        # uv run mypy app
make ingest           # Run ingestion pipeline (requires Docker services up)
make delete-and-ingest  # Wipe Chroma collection then re-ingest
make chat-test        # curl smoke test of /chat endpoint
```

**Run a single test file:**
```bash
uv run pytest tests/acceptance/test_news_api_ingester.py -v
```

**Run a single test by name:**
```bash
uv run pytest -v -k "test_function_name"
```

**Ruff line length:** 100 chars. **Pytest asyncio mode:** auto (all async tests run without explicit decorator).

## Architecture

### Request Flow

`POST /chat` → `app/chat.py:handle_chat()`:
1. Expand query (question + topic slugs)
2. Semantic search in Chroma → top-8 chunks (`app/rag/retrieval.py`)
3. `enrich_retrieval()` — stub, raises `NotImplementedError`
4. `fresh_news.fetch()` — stub, raises `NotImplementedError`
5. LLM call → JSON `{answer, cards}` (`app/rag/llm.py`)
6. Graceful degradation if LLM unavailable → `status="degraded"`

### Ingestion Flow

`POST /topics` triggers ingestion per topic:
- **NewsAPI** (`app/ingest/news_api.py`): 2 pages × 10 articles, dedup by SHA1(url)
- **Twitter** (`app/ingest/twitter/ingester.py`): async twikit, 5 pages × 20 tweets, 60-day filter
- **Chroma upsert** (`app/ingest/chroma_upsert.py`): RecursiveCharacterTextSplitter (2000 chars, 200 overlap) → embed → upsert

### Key Modules

| Path | Role |
|------|------|
| `app/main.py` | FastAPI app, CORS, endpoints (`/health`, `/topics`, `/chat`) |
| `app/config.py` | Pydantic Settings from `.env` |
| `app/schemas.py` | `Article`, `ChatRequest`, `ChatResponse`, `ArticleCard`, `Topic` |
| `app/chat.py` | Chat orchestration |
| `app/rag/chroma_client.py` | ChromaDB HTTP client, collection management |
| `app/rag/retrieval.py` | Embedding + top-k semantic search |
| `app/rag/llm.py` | LangChain + Azure AI LLM, answer synthesis |
| `app/ingest/utils.py` | `stable_id()` — SHA1 of URL, used as document ID |
| `app/ingest/topics.py` | Topic persistence (`data/topics.json`) |
| `app/ingest/twitter/parser.py` | Parse raw twikit `tweet._data` structures |
| `scripts/ingest_cli.py` | Typer CLI wrapping the ingestion pipeline |

### Tests

All tests are acceptance-level in `tests/acceptance/`. HTTP calls are mocked with `respx`. Fakes/fixtures live in `news_api_fakes.py` and `twitter_fakes.py`.

### Frontend (`web/`)

Next.js 15 App Router. `lib/api.ts` calls the backend REST API. No separate state management library — React hooks only.

## Environment Variables

Required in `.env` (see `.env.example`):

```
AZURE_AI_INFERENCE_ENDPOINT / API_KEY / MODEL  # LLM (Kimi-K2.6)
NEWS_API_KEY
CHROMA_URL=http://chromadb:8000   # service-to-service in Docker; use http://localhost:8002 locally
EMBEDDING_MODEL=intfloat/multilingual-e5-small
```

Optional: `TWITTER_USERNAME`, `TWITTER_EMAIL`, `TWITTER_PASSWORD` (cached in `data/twitter_cookies.json`).

## Stubs to Be Aware Of

- `app/ingest/enrich.py:enrich_retrieval()` — raises `NotImplementedError`
- `app/runtime/fresh_news.py:fetch()` — raises `NotImplementedError`
- `app/ingest/cleaning.py` — several stubs (`dedupe`, `chunk`, `clean_html_to_markdown`, `strip_boilerplate`)

These are intentional placeholders for future implementation. The chat flow catches their errors and degrades gracefully.
