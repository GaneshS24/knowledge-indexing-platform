"""
Performance benchmark — measures ingestion and search latency.

Usage:
    python benchmark.py

Expects the server running on http://localhost:8000
"""

import json
import random
import string
import time
import httpx

BASE_URL = "http://localhost:8000/api/v1"
TENANT_ID = "tenant-alpha"
API_KEY = "key-alpha-secret"
HEADERS = {"X-API-Key": API_KEY}

LOREM = (
    "knowledge indexing platform document content search retrieval "
    "enterprise tenant isolation security compliance audit logging "
    "scalability performance caching distributed system microservices "
    "python fastapi sqlite fulltext bm25 relevance ranking pagination"
).split()


def random_doc():
    title = " ".join(random.choices(LOREM, k=4)).title()
    content = " ".join(random.choices(LOREM, k=80))
    tags = random.sample(LOREM[:20], k=random.randint(0, 5))
    return {"title": title, "content": content, "tags": tags}


def benchmark_ingestion(n=1000):
    print(f"\n=== Ingestion Benchmark ({n} docs) ===")
    start = time.perf_counter()
    with httpx.Client(base_url=BASE_URL, headers=HEADERS) as client:
        for i in range(n):
            r = client.post(f"/tenants/{TENANT_ID}/documents", json=random_doc())
            assert r.status_code == 201, r.text
    elapsed = time.perf_counter() - start
    print(f"Total:    {elapsed:.2f}s")
    print(f"Rate:     {n / elapsed:.1f} docs/sec")
    print(f"Avg:      {elapsed / n * 1000:.1f} ms/doc")


def benchmark_search(n=200):
    queries = random.choices(LOREM, k=n)
    print(f"\n=== Search Benchmark ({n} queries) ===")
    times = []
    with httpx.Client(base_url=BASE_URL, headers=HEADERS) as client:
        for q in queries:
            t0 = time.perf_counter()
            r = client.get(f"/tenants/{TENANT_ID}/documents/search", params={"q": q})
            assert r.status_code == 200
            times.append((time.perf_counter() - t0) * 1000)

    times.sort()
    print(f"Min:      {min(times):.1f} ms")
    print(f"Avg:      {sum(times)/len(times):.1f} ms")
    print(f"p95:      {times[int(len(times)*0.95)]:.1f} ms")
    print(f"p99:      {times[int(len(times)*0.99)]:.1f} ms")
    print(f"Max:      {max(times):.1f} ms")
    p95 = times[int(len(times) * 0.95)]
    if p95 < 100:
        print("✓ p95 under 100ms target")
    else:
        print("✗ p95 EXCEEDS 100ms target")


if __name__ == "__main__":
    benchmark_ingestion(1000)
    benchmark_search(200)
