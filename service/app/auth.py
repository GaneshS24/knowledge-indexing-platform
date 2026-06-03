"""
Authentication middleware — API key validation with tenant context injection.
"""

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, Path, status

from .database import get_db

logger = logging.getLogger(__name__)


def get_tenant_from_api_key(
    x_api_key: Optional[str] = Header(None, description="API key for authentication"),
) -> dict:
    """
    Validate the API key and return tenant info.
    Raises 401 if missing/invalid.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name FROM tenants WHERE api_key = ?",
            (x_api_key,),
        ).fetchone()

    if row is None:
        logger.warning("Invalid API key attempt: %s...", x_api_key[:8])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return {"tenant_id": row["id"], "tenant_name": row["name"]}


def verify_tenant_access(
    tenant_id: str = Path(..., description="Tenant identifier"),
    tenant_ctx: dict = Depends(get_tenant_from_api_key),
) -> dict:
    """
    Ensure the authenticated tenant matches the path tenant_id.
    Prevents cross-tenant data access.
    """
    if tenant_ctx["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: tenant mismatch",
        )
    return tenant_ctx
