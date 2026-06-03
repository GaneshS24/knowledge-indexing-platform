# Multi-Tenant Knowledge Indexing Platform — System Design

## 1. Architecture Overview

This platform provides enterprise customers a shared, isolated knowledge indexing service for ingesting documents and performing full-text search, with strict data isolation, audit logging, and compliance alignment (FedRAMP, PCI-DSS, HIPAA).

My design draws on direct experience building multi-region provisioning systems, IAM-based cross-tenancy access, and observability platforms on Oracle Cloud Infrastructure (OCI).

### High-Level Architecture Diagram

```
                    ┌──────────────────────────────────────────────┐
                    │               Client Layer                   │
                    │   Enterprise Apps / SDKs / Direct API Users  │
                    └──────────────────┬───────────────────────────┘
                                       │ HTTPS / TLS 1.3
                    ┌──────────────────▼───────────────────────────┐
                    │            API Gateway + WAF                 │
                    │   Rate limiting · TLS termination · Routing  │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │         Auth Middleware (API Key / JWT)      │
                    │   Validates key → injects tenant_id context  │
                    └──────┬───────────────────────┬───────────────┘
                           │                       │
          ┌────────────────▼──────┐   ┌────────────▼──────────────┐
          │   Ingestion Service   │   │      Search Service       │
          │   (Python / FastAPI)  │   │   (Python / FastAPI)      │
          └────────────┬──────────┘   └────────────┬──────────────┘
                       │                            │
          ┌────────────▼──────────┐   ┌────────────▼──────────────┐
          │   Async Work Queue    │   │   PostgreSQL FTS / SQLite │
          │ (OCI Queue / SQS)     │   │   (per-tenant RLS)        │
          └────────────┬──────────┘   └───────────────────────────┘
                       │
          ┌────────────▼──────────┐   ┌───────────────────────────┐
          │   Document Processor  │   │   Object Storage (OCI /S3)│
          │   (Python workers)    │───│   s3://bucket/{tenantId}/ │
          └────────────┬──────────┘   └───────────────────────────┘
                       │
          ┌────────────▼──────────┐   ┌───────────────────────────┐
          │   PostgreSQL (Aurora) │   │   KMS (OCI Vault / AWS)   │
          │   metadata + RLS      │   │   Per-tenant encryption   │
          └───────────────────────┘   └───────────────────────────┘

          ┌──────────────────────────────────────────────────────┐
          │          Observability Layer                         │
          │   Structured logs · Metrics (Grafana) · Audit trail  │
          └──────────────────────────────────────────────────────┘
```

**Ingestion flow:**
1. Client POSTs document → API Gateway → Auth injects `tenant_id`
2. Ingestion Service writes metadata to PostgreSQL, pushes raw blob to Object Storage under tenant-scoped prefix
3. Work queue message triggers Document Processor (Python worker) to parse, index into FTS, write audit log
4. Structured audit event written to append-only audit table and streamed to log aggregation

**Search flow:**
1. Client GETs search → API Gateway → Auth → Search Service
2. Search Service queries PostgreSQL FTS with mandatory `tenant_id` filter (RLS enforced at DB layer too)
3. Results ranked by BM25, returned with relevance scores; hot queries served from in-process cache

---

## 2. Multi-Tenancy Strategy

### Isolation Model: Shared Infrastructure, Logical Isolation

I chose this model based on hands-on experience designing cross-tenancy access for VM backup/restore across 1,000+ Exadata clusters using IAM policies — the same pattern applies here. Dedicated infrastructure per tenant is too costly at scale; logical isolation with layered enforcement gives equivalent security for most workloads.

| Layer | Isolation Mechanism |
|---|---|
| API | API key carries `tenant_id`; all downstream calls propagate it as mandatory context |
| PostgreSQL | `tenant_id` column on every table + Row-Level Security policy; app role cannot bypass |
| Object Storage | Key prefix `/{tenantId}/documents/`; IAM bucket policy denies cross-prefix access |
| KMS | Per-tenant encryption key option for regulated workloads (mirrors OCI KMS / TDE pattern) |
| Audit log | Append-only table; app role has INSERT only, no UPDATE/DELETE |

**Why not dedicated DB per tenant?**
At fleet scale (100+ tenants), dedicated RDS instances multiply cost and operational burden. PostgreSQL RLS enforced at the database engine level — not just the application — gives strong isolation. For FedRAMP High or HIPAA customers, we'd offer a dedicated-DB tier (I've implemented this pattern for Exadata dedicated infrastructure).

### Database Schema (Production — PostgreSQL)

```sql
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    tags        TEXT[],
    ts_vector   TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('english', title || ' ' || content)
                ) STORED,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_docs_tenant    ON documents(tenant_id);
CREATE INDEX idx_docs_fts       ON documents USING GIN(ts_vector);

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON documents
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- Append-only audit log (app role: INSERT only)
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   UUID NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,  -- e.g. 'document.created'
    resource_id TEXT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

---

## 3. Scalability Considerations

### Ingestion: 100K Documents/Day

100K/day = ~1.2 docs/sec average, with realistic bursts to 10–50×. My design uses an async pipeline — the Ingestion API returns `202 Accepted` immediately and hands off to a work queue. This is the same pattern I used for gold-image provisioning across regions, where synchronous provisioning was impractical at scale.

- **Work queue** (OCI Queue or SQS): decouples ingestion rate from processing capacity
- **Python worker pool**: 5–10 concurrent workers; each parses, indexes, and writes audit log
- At peak burst (50K docs/hour), ~14 docs/sec — handled by 10 workers with ~700ms per doc budget
- **Object Storage** for raw blobs: unlimited scale, cheap, supports lifecycle policies. I used this exact pattern for cross-region image replication on Exadata.

### Search: 10K Concurrent Queries

- **PostgreSQL FTS (GIN index)**: handles thousands of QPS on properly indexed tables; BM25 ranking via `ts_rank`
- **Connection pooling** (PgBouncer): pools app connections to DB; prevents connection exhaustion under burst load — critical lesson from Exadata fleet operations
- **Application-level cache**: short TTL (60s) for repeated identical queries per tenant, keyed `{tenant_id}:{query_hash}`
- **Horizontal scaling**: stateless API service scales behind a load balancer; read replicas for SELECT-heavy workloads
- **Read replicas**: route search queries to replica; writes (ingest) go to primary

### Caching Strategy

| Layer | Mechanism | TTL | Cached Content |
|---|---|---|---|
| Search results | In-process dict / Redis | 60s | `{tenantId}:{queryHash}` → result list |
| Tenant API key lookup | In-process LRU | 300s | API key → tenant context |
| Document metadata | Redis (optional) | 300s | Frequently fetched docs |

---

## 4. Security & Compliance

My background includes delivering UEFI Secure Boot, FIPS-aligned platforms, LUKS disk encryption, and FedRAMP-aligned systems on Exadata. The same principles apply here.

### Authentication & Authorization

- **API Keys**: HMAC-SHA256 signed, stored hashed (bcrypt) in DB; never logged in plaintext
- **JWT** (production): RS256 signed, 15-min TTL, contain `tenant_id` + `scopes`; refresh token stored server-side
- **RBAC**: roles per tenant (admin, writer, reader); enforced at service layer before DB query

### Encryption

| Layer | Mechanism |
|---|---|
| In transit | TLS 1.3 enforced; HSTS headers; no TLS 1.0/1.1 |
| At rest — DB | AES-256 via KMS CMK (OCI Vault or AWS KMS); per-tenant key for high-compliance |
| At rest — Object Storage | SSE-KMS; per-tenant prefix uses separate CMK where required |
| Secrets | KMS-backed secrets store (OCI Secrets-in-Vault or AWS Secrets Manager); rotation every 90 days |
| Disk (infrastructure) | LUKS-based full-disk encryption on all compute nodes |

I designed the key management system integrated with OCI KMS and Secrets-in-Vault for Exadata Cloud; the same pattern applies directly here.

### Audit Logging

Every state-changing operation emits a structured audit event:

```json
{
  "tenant_id": "acme-corp",
  "actor": "api_key:sha256:abc...",
  "action": "document.created",
  "resource_id": "doc-uuid-...",
  "ip_address": "1.2.3.4",
  "timestamp": "2025-12-15T10:00:00Z",
  "request_id": "req-xyz"
}
```

Audit logs are:
- Written to append-only `audit_log` table (app role: INSERT only, no DELETE/UPDATE)
- Streamed to log aggregation (Grafana / CloudWatch) with 7-year retention for FedRAMP
- Exportable to cold storage (Object Storage / S3 Glacier) for compliance archiving

---

## 5. High Availability & Fault Tolerance

Based on experience running Exadata Cloud Service across multiple production regions:

- **Multi-AZ PostgreSQL Aurora**: automatic failover <30s; 2 read replicas in prod
- **Stateless API services**: deployed across 2+ AZs; ALB health-checks every 10s; failed tasks replaced automatically
- **Work queue DLQ**: failed processing messages go to dead-letter queue after 3 retries; alert on DLQ depth
- **Object Storage**: 11-nines durability; cross-region replication for DR (mirrors Exadata image replication design)
- **Circuit breaker** (tenacity / Resilience4j): wraps all downstream calls to DB and storage

**RTO: ~2 min | RPO: ~1 min**

---

## 6. Technology Stack Justification

| Component | Choice | Rationale | Trade-offs |
|---|---|---|---|
| API Framework | FastAPI (Python) | Python is my primary language; async support; auto-generates OpenAPI docs | GIL limits CPU-bound tasks; use workers to mitigate |
| Database | PostgreSQL (Aurora) | Built-in FTS, GIN indexes, RLS, JSONB, mature at scale | More ops overhead than SQLite; worth it at production scale |
| Search | PostgreSQL FTS + BM25 | No additional infrastructure; `ts_rank` gives good relevance; I've used this pattern in diagnostics platform | Not as tunable as OpenSearch for large corpora; upgrade path is pgvector or OpenSearch |
| Queue | OCI Queue / SQS | Fully managed; DLQ support; deep Lambda/worker integration | Eventual consistency; not FIFO by default |
| Object Storage | OCI Object Storage / S3 | Unlimited scale; lifecycle policies; I used this for cross-region image replication on Exadata | Latency for small objects; eventual consistency on overwrites |
| Key Management | OCI Vault / AWS KMS | I integrated KMS + Secrets-in-Vault for Exadata Cloud; same pattern | Vendor lock-in; mitigated by abstraction layer |
| Observability | Structured logs + Grafana | Used Grafana-based observability for Exadata diagnostics platform; familiar | CloudWatch costs at high volume; Grafana adds ops overhead |
| Infra-as-Code | Terraform | Multi-cloud; state management; reusable modules | State file management requires locking (S3 + DynamoDB) |

**What I'd add with more time:**
- pgvector extension for semantic/embedding-based search alongside BM25 (natural upgrade from PostgreSQL FTS)
- Tenant-level rate limiting at API Gateway (usage plans per tenant)
- GenAI query interface over the observability layer — similar to the Exawatcher diagnostics tool I built at Oracle
- Control plane service for tenant provisioning, onboarding, and billing
