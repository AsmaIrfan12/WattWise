"""Runtime observability helpers for lightweight metrics and SLO signals."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from threading import Lock
from typing import Any


class MetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = datetime.utcnow().isoformat()
        self._counters = Counter()
        self._scheduler_jobs: dict[str, dict[str, Any]] = {}

    def record_request(self, status_code: int) -> None:
        with self._lock:
            self._counters["requests_total"] += 1
            if 200 <= status_code < 300:
                self._counters["requests_2xx_total"] += 1
            elif 400 <= status_code < 500:
                self._counters["requests_4xx_total"] += 1
            elif status_code >= 500:
                self._counters["requests_5xx_total"] += 1

    def record_auth_failure(self) -> None:
        with self._lock:
            self._counters["auth_failures_total"] += 1

    def record_reading_ingested(self) -> None:
        with self._lock:
            self._counters["readings_ingested_total"] += 1

    def record_scheduler_run(
        self,
        job_name: str,
        status: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        with self._lock:
            self._scheduler_jobs[job_name] = {
                "status": status,
                "last_started_at": started_at.isoformat(),
                "last_finished_at": ended_at.isoformat(),
                "last_duration_ms": duration_ms,
                "runs_total": self._scheduler_jobs.get(job_name, {}).get("runs_total", 0) + 1,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started_at": self._started_at,
                "counters": dict(self._counters),
                "scheduler": dict(self._scheduler_jobs),
            }


metrics_store = MetricsStore()
