"""
Pydantic models for request/response validation.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
import json


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Document title")
    content: str = Field(..., min_length=1, description="Document text content")
    tags: List[str] = Field(default_factory=list, description="Searchable tags")

    @field_validator("tags")
    @classmethod
    def tags_max_20(cls, v: List[str]) -> List[str]:
        if len(v) > 20:
            raise ValueError("Maximum 20 tags allowed")
        return [t.strip().lower() for t in v if t.strip()]


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    content: str
    tags: List[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "DocumentResponse":
        return cls(
            id=row["id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            content=row["content"],
            tags=json.loads(row["tags"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class DocumentCreatedResponse(BaseModel):
    id: str
    tenant_id: str
    message: str = "Document created successfully"


class SearchResult(BaseModel):
    id: str
    tenant_id: str
    title: str
    content_snippet: str = Field(description="First 200 chars of content")
    tags: List[str]
    relevance_score: float = Field(ge=0.0, description="BM25 relevance score")
    created_at: str


class SearchResponse(BaseModel):
    query: str
    total: int
    limit: int
    offset: int
    results: List[SearchResult]


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str = "1.0.0"
    timestamp: str


class TenantMetrics(BaseModel):
    tenant_id: str
    request_count: int
    avg_response_time_ms: float
    document_count: int
    error_count: int
    error_rate: float


class MetricsResponse(BaseModel):
    uptime_seconds: float
    total_requests: int
    tenants: List[TenantMetrics]
