from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Article(BaseModel):
    id: str
    title: str
    source_name: str
    source_type: str = "news_article"
    date_published: datetime | None = None
    date_collected: datetime | None = None
    content: str
    url: HttpUrl | str
    tags: list[str] = Field(default_factory=list)


class ArticleCard(BaseModel):
    title: str
    source: str
    date: str | None = None
    snippet: str
    url: str
    tags: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    slug: str
    label: str


class ChatRequest(BaseModel):
    question: str
    topics: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    cards: list[ArticleCard]
    status: Literal["ok", "empty", "degraded"] = "ok"
