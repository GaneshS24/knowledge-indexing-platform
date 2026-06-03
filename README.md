# Knowledge Indexing Platform

A multi-tenant document ingestion and full-text search service built as a proof-of-concept implementation for the Director, Platform Engineering assessment.

My background is in large-scale distributed infrastructure (Oracle Exadata Cloud, 20+ years), Python systems programming, OCI/cloud platform engineering, and FedRAMP-aligned security design. This submission reflects patterns I've used in production, adapted to this problem.

---

## Project Structure

```
knowledge-platform/
├── design/
│   └── system_design.md       ← Part 1: Architecture, multi-tenancy, security, scalability
├── service/
│   ├── app/
│   │   ├── __init__.py         ← FastAPI app + request metrics middleware
│   │   ├── database.py         ← SQLite + FTS5 (BM25), tenant-isolated schema
│   │   ├── auth.py             ← API key auth + cross-tenant access prevention
│   │   ├── models.py           ← Pydantic request/response models
│   │   ├── metrics.py          ← In-memory per-tenant metrics store
│   │   └── routes/
│   │       ├── documents.py    ← POST ingest + GET search
│   │       ├── health.py       ← GET /health (load balancer probe)
│   │       └── metrics.py      ← GET /metrics
│   ├── tests/
│   │   └── test_api.py         ← 22 unit tests, 97% coverage
│   ├── benchmark.py            ← Performance benchmark
│   └── requirements.txt
├── swagger/
│   └── openapi.yaml            ← OpenAPI 3.0 spec
├── terraform/
│   ├── main.tf                 ← Provider config
│   ├── variables.tf
│   ├── networking.tf           ← VPC, subnets, security groups
│   ├── ecs.tf                  ← ECS Fargate + ALB + autoscaling + blue/green
│   ├── rds.tf                  ← Aurora PostgreSQL (multi-AZ)
│   ├── iam.tf                  ← Least-privilege IAM roles
│   ├── alarms.tf               ← CloudWatch alarms + dashboard
│   └── outputs.tf
├── Dockerfile
└── README.md
```

---

## Design Decisions & Experience Mapping

| Design Choice | Where I've Used This |
|---|---|
| Tenant isolation via DB row-level security + IAM prefix policies | Cross-tenancy backup/restore across 1,000+ Exadata clusters using IAM policies |
| Object Storage for raw document blobs with per-tenant prefix | Cross-region image replication using OCI Object Storage for Exadata provisioning |
| KMS-backed encryption per tenant | OCI KMS + Secrets-in-Vault integration for Exadata Cloud credential management |
| Async work queue for ingestion pipeline | Gold image provisioning pipeline with lifecycle management across regions |
| Structured audit log (append-only, INSERT-only role) | FedRAMP/HIPAA/PCI-DSS-aligned audit design on Exadata Cloud |
| Python + FastAPI | Python is my primary language; used extensively for diagnostics, automation, and platform tooling |
| Grafana-based observability | Exawatcher observability platform with GenAI query interface |

---

## Part 2: Running the Service

### Prerequisites
- Python 3.11+

### Setup & Run

```bash
cd service
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Two demo tenants are pre-seeded on startup:

| Tenant ID      | API Key            |
|----------------|--------------------|
| `tenant-alpha` | `key-alpha-secret` |
| `tenant-beta`  | `key-beta-secret`  |

**Swagger UI:** http://localhost:8000/docs

Note: Swagger UI is only accessible when the server is running locally. Start the server with the steps above, then open the link in your browser.

---

## API Usage

### Health Check (no auth)
```bash
curl http://localhost:8000/api/v1/health
```

### Ingest a Document
```bash
curl -X POST http://localhost:8000/api/v1/tenants/tenant-alpha/documents \
  -H "X-API-Key: key-alpha-secret" \
  -H "Content-Type: application/json" \
  -d '{"title": "Exadata Storage Architecture", "content": "Smart Scan offloads query processing to storage cells...", "tags": ["exadata", "storage"]}'
```

### Search
```bash
curl "http://localhost:8000/api/v1/tenants/tenant-alpha/documents/search?q=storage&limit=5" \
  -H "X-API-Key: key-alpha-secret"
```

### Cross-tenant isolation — this returns 403
```bash
curl -X POST http://localhost:8000/api/v1/tenants/tenant-beta/documents \
  -H "X-API-Key: key-alpha-secret" \
  -H "Content-Type: application/json" \
  -d '{"title": "Should fail", "content": "Cross-tenant attempt"}'
```

### Metrics
```bash
curl http://localhost:8000/api/v1/metrics
```

---

## Running Tests

```bash
cd service
python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

**22 tests passing, 97% coverage.**

Key test cases:
- Missing/invalid API key → 401
- Cross-tenant access (alpha key on beta tenant path) → 403
- Search results never cross tenant boundary (isolation test)
- Pagination non-overlap
- Content snippet truncated to 200 chars
- Validation: empty title, missing content, >20 tags

---

## Performance

```bash
cd service
python benchmark.py   # requires server running on :8000
```

Typical results (1000 docs ingested, 200 search queries):
```
=== Ingestion ===  ~2s total, ~2ms/doc
=== Search    ===  avg ~4ms, p95 ~8ms   ✓ well under 100ms target
```

---

## Part 3: Deploying with Terraform

### Prerequisites
- Terraform >= 1.6.0
- AWS CLI configured
- Docker image pushed to ECR

### Deploy
```bash
cd terraform
terraform init
terraform plan \
  -var="app_image=<ecr-uri>:latest" \
  -var="db_password=<password>" \
  -var="alarm_email=ops@company.com" \
  -var="environment=prod"
terraform apply ...
```

### Blue/Green Deployments
CodeDeploy shifts traffic 10%/min with automatic rollback on 5xx alarms or failed health checks. The same rolling-update pattern I've used for Exadata infrastructure migration across production regions.

---

## Time Spent

| Part | Time |
|---|---|
| System Design | ~3 hrs |
| Implementation | ~5 hrs |
| Infrastructure | ~3 hrs |
| Tests & Docs | ~2 hrs |
| **Total** | **~13 hrs** |

---

## Assumptions

1. **SQLite for PoC**: Assessment specifies embedded DB. Production path is PostgreSQL (Aurora) with RLS — schema is in the design doc.
2. **API key auth**: Simplified from JWT for PoC. Production design (RS256 JWT, 15-min TTL, RBAC) is fully described in `system_design.md`.
3. **Sync ingestion in PoC**: Documents are indexed synchronously on POST for simplicity. Production uses an async work queue (OCI Queue / SQS) as described in design.
4. **Single region for Terraform**: Multi-region design (cross-region replication via Object Storage) is described in the design doc.

## What I'd Add with More Time

- pgvector extension for semantic search alongside BM25 (natural upgrade from PostgreSQL FTS, no new infra)
- GenAI query interface over the observability/metrics layer — similar to the Exawatcher diagnostics tool I built at Oracle
- Tenant provisioning control plane (onboarding, offboarding, usage billing)
- Per-tenant rate limiting at API Gateway
