"""
Database layer — SQLite with tenant-isolated document storage and FTS5.
"""

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "./knowledge_platform.db")

# Thread-local storage for connections (SQLite is not thread-safe by default)
_local = threading.local()


def _get_raw_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = _get_raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """Create all tables and FTS virtual table."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id          TEXT PRIMARY KEY,
                api_key     TEXT NOT NULL UNIQUE,
                name        TEXT NOT NULL,
                created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS documents (
                id          TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            );

            CREATE INDEX IF NOT EXISTS idx_documents_tenant
                ON documents(tenant_id);

            -- FTS5 virtual table for full-text search
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
            USING fts5(
                id UNINDEXED,
                tenant_id UNINDEXED,
                title,
                content,
                tags,
                content='documents',
                content_rowid='rowid',
                tokenize='porter unicode61'
            );

            -- Keep FTS in sync via triggers
            CREATE TRIGGER IF NOT EXISTS documents_ai
            AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, id, tenant_id, title, content, tags)
                VALUES (new.rowid, new.id, new.tenant_id, new.title, new.content, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_ad
            AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, id, tenant_id, title, content, tags)
                VALUES ('delete', old.rowid, old.id, old.tenant_id, old.title, old.content, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS documents_au
            AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, id, tenant_id, title, content, tags)
                VALUES ('delete', old.rowid, old.id, old.tenant_id, old.title, old.content, old.tags);
                INSERT INTO documents_fts(rowid, id, tenant_id, title, content, tags)
                VALUES (new.rowid, new.id, new.tenant_id, new.title, new.content, new.tags);
            END;

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   TEXT NOT NULL,
                actor       TEXT NOT NULL,
                action      TEXT NOT NULL,
                resource_id TEXT,
                metadata    TEXT,
                created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            );

            -- Seed demo tenants for testing
            INSERT OR IGNORE INTO tenants (id, api_key, name)
            VALUES
                ('tenant-alpha', 'key-alpha-secret', 'Acme Corp'),
                ('tenant-beta',  'key-beta-secret',  'Globex Inc');
            """
        )
        logger.info("Database initialised at %s", DB_PATH)
