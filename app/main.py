from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.chat import handle_chat
from app.ingest.topics import save_topics
from app.ingest.news_api import NewsApiIngester
from app.ingest.twitter import TwitterIngester
from app.schemas import ChatRequest, ChatResponse, Topic

POPULAR_TOPICS: list[Topic] = [
    Topic(slug="python", label="Python"),
    Topic(slug="javascript", label="JavaScript"),
    Topic(slug="ai-ml", label="AI/ML"),
    Topic(slug="devops", label="DevOps"),
    Topic(slug="web", label="Web"),
]


app = FastAPI(
    title="Nauda Palisse — Veille Tech",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class IngestRequest(BaseModel):
    topics: list[str]


class IngestResponse(BaseModel):
    topics: list[str]
    news_count: int
    twitter_count: int


@app.get("/topics", response_model=list[Topic])
def topics() -> list[Topic]:
    return POPULAR_TOPICS


@app.post("/topics", response_model=IngestResponse)
def ingest_topics(req: IngestRequest) -> IngestResponse:
    resolved = list(dict.fromkeys(req.topics))
    save_topics(resolved)
    news_results = NewsApiIngester().run(resolved)
    twitter_results = TwitterIngester().run(resolved)
    return IngestResponse(
        topics=resolved,
        news_count=len(news_results),
        twitter_count=len(twitter_results),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    return await handle_chat(req)
