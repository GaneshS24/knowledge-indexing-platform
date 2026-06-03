"""
Knowledge Indexing Platform — Main Application Entry Point
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from .database import init_db
from .metrics import metrics_store
from .routes.documents import router as documents_router
from .routes.health import router as health_router
from .routes.metrics import router as metrics_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — initialising database")
    init_db()
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Knowledge Indexing Platform",
    description=(
        "Multi-tenant document ingestion and search service. "
        "Authenticate with an API key in the `X-API-Key` header."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    """Record per-tenant request count, latency, and error rate."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    # Extract tenant_id from path if present (/api/v1/tenants/{tenantId}/...)
    path_parts = request.url.path.split("/")
    tenant_id = None
    try:
        idx = path_parts.index("tenants")
        tenant_id = path_parts[idx + 1]
    except (ValueError, IndexError):
        pass

    if tenant_id:
        metrics_store.record_request(
            tenant_id=tenant_id,
            duration_ms=duration_ms,
            is_error=response.status_code >= 400,
        )

    return response


app.include_router(documents_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
