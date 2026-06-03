"""
Document routes — ingestion (POST) and search (GET).
"""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import verify_tenant_access
from ..database import get_db
from ..models import (
    DocumentCreate,
    DocumentCreatedResponse,
    SearchResponse,
    SearchResult,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Documents"])


@router.post(
    "/tenants/{tenant_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentCreatedResponse,
    summary="Ingest a document",
    description=(
        "Store a document for the given tenant. "
        "The document is immediately indexed for full-text search."
    ),
)
def create_document(
    body: DocumentCreate,
    tenant_ctx: dict = Depends(verify_tenant_access),
) -> DocumentCreatedResponse:
    tenant_id = tenant_ctx["tenant_id"]
    doc_id = str(uuid.uuid4())

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, tenant_id, title, content, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (doc_id, tenant_id, body.title, body.content, json.dumps(body.tags)),
        )
        # Audit log
        conn.execute(
            """
            INSERT INTO audit_log (tenant_id, actor, action, resource_id, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                f"tenant:{tenant_id}",
                "document.created",
                doc_id,
                json.dumps({"title": body.title, "tags": body.tags}),
            ),
        )

    logger.info("Document %s created for tenant %s", doc_id, tenant_id)
    return DocumentCreatedResponse(id=doc_id, tenant_id=tenant_id)


@router.get(
    "/tenants/{tenant_id}/documents/search",
    response_model=SearchResponse,
    summary="Search documents",
    description=(
        "Full-text search across tenant documents using BM25 ranking. "
        "Results are strictly isolated to the requesting tenant."
    ),
)
def search_documents(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    limit: int = Query(10, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    tenant_ctx: dict = Depends(verify_tenant_access),
) -> SearchResponse:
    tenant_id = tenant_ctx["tenant_id"]

    with get_db() as conn:
        # FTS5 bm25() returns negative scores; negate so higher = more relevant
        rows = conn.execute(
            """
            SELECT
                d.id,
                d.tenant_id,
                d.title,
                d.content,
                d.tags,
                d.created_at,
                (-bm25(documents_fts)) AS score
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.id
            WHERE documents_fts MATCH ?
              AND documents_fts.tenant_id = ?
            ORDER BY score DESC
            LIMIT ? OFFSET ?
            """,
            (q, tenant_id, limit, offset),
        ).fetchall()

        # Count total matches for pagination
        total_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM documents_fts
            WHERE documents_fts MATCH ?
              AND documents_fts.tenant_id = ?
            """,
            (q, tenant_id),
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

    results = [
        SearchResult(
            id=row["id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            content_snippet=row["content"][:200],
            tags=json.loads(row["tags"]),
            relevance_score=round(float(row["score"]), 4),
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return SearchResponse(
        query=q,
        total=total,
        limit=limit,
        offset=offset,
        results=results,
    )
