"""Data models for PanClip MCP Server."""

import time
from typing import Any

from pydantic import BaseModel, Field


class Clip(BaseModel):
    """Simple and efficient clip model."""

    id: str
    content: str
    embedding: list[float] | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Search result with similarity score."""

    id: str
    content: str
    tags: list[str]
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClipResponse(BaseModel):
    """Response for clip operations."""

    id: str
    status: str
    message: str | None = None
