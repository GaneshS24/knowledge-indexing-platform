"""Health check route."""
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter

from ..database import get_db
from ..models import HealthResponse

router = APIRouter(tags=["Operations"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service health. Used by load balancers and monitoring.",
)
def health_check() -> HealthResponse:
    db_status = "ok"
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
