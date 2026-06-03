"""Metrics route — per-tenant stats."""

from fastapi import APIRouter

from ..database import get_db
from ..metrics import metrics_store
from ..models import MetricsResponse, TenantMetrics

router = APIRouter(tags=["Operations"])


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Service metrics",
    description=(
        "Exposes per-tenant request count, average latency, "
        "document count, and error rates."
    ),
)
def get_metrics() -> MetricsResponse:
    stats = metrics_store.get_stats()

    # Fetch document counts per tenant from DB
    with get_db() as conn:
        rows = conn.execute(
            "SELECT tenant_id, COUNT(*) AS cnt FROM documents GROUP BY tenant_id"
        ).fetchall()
    doc_counts = {row["tenant_id"]: row["cnt"] for row in rows}

    tenant_metrics = [
        TenantMetrics(
            tenant_id=tid,
            request_count=s.request_count,
            avg_response_time_ms=round(s.avg_response_time_ms, 2),
            document_count=doc_counts.get(tid, 0),
            error_count=s.error_count,
            error_rate=round(s.error_rate, 4),
        )
        for tid, s in stats.items()
    ]

    return MetricsResponse(
        uptime_seconds=round(metrics_store.uptime_seconds, 1),
        total_requests=metrics_store.total_requests,
        tenants=tenant_metrics,
    )
