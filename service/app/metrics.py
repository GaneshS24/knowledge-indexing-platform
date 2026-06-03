"""
In-memory metrics store — thread-safe per-tenant request tracking.
"""

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TenantStats:
    request_count: int = 0
    error_count: int = 0
    total_response_time_ms: float = 0.0
    response_times: List[float] = field(default_factory=list)

    @property
    def avg_response_time_ms(self) -> float:
        if not self.request_count:
            return 0.0
        return self.total_response_time_ms / self.request_count

    @property
    def error_rate(self) -> float:
        if not self.request_count:
            return 0.0
        return self.error_count / self.request_count


class MetricsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._tenants: Dict[str, TenantStats] = defaultdict(TenantStats)
        self._start_time = time.monotonic()

    def record_request(self, tenant_id: str, duration_ms: float, is_error: bool) -> None:
        with self._lock:
            stats = self._tenants[tenant_id]
            stats.request_count += 1
            stats.total_response_time_ms += duration_ms
            if is_error:
                stats.error_count += 1

    def get_stats(self) -> Dict[str, TenantStats]:
        with self._lock:
            return dict(self._tenants)

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def total_requests(self) -> int:
        with self._lock:
            return sum(s.request_count for s in self._tenants.values())


# Singleton
metrics_store = MetricsStore()
