"""Background job manager with cancellation, progress and ETA."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    """In-memory mirror of a job row; the DB is the source of truth."""
    job_id: int
    kind: str
    state: str = "queued"
    total: int = 0
    done: int = 0
    current: str = ""
    percent: float = 0.0
    eta_seconds: float = 0.0
    status_text: str = "Queued"
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    cancelled: bool = False

    def elapsed(self) -> float:
        return max(0.001, (self.finished_at or time.time()) - self.started_at)


class JobManager:
    """Thread-pool-like manager that runs one job at a time per kind."""

    def __init__(self, repo: Any):
        self.repo = repo
        self._threads: Dict[int, threading.Thread] = {}
        self._cancel_flags: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, params: Dict[str, Any],
              runner: Callable[["JobState", Callable[[], bool]], None]) -> int:
        job_id = self.repo.create_job(kind, params)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        thread = threading.Thread(
            target=self._run, args=(job_id, kind, params, runner, cancel_event),
            name=f"job-{kind}-{job_id}", daemon=True,
        )
        self._threads[job_id] = thread
        thread.start()
        return job_id

    def _run(self, job_id: int, kind: str, params: Dict[str, Any],
             runner: Callable[[JobState, Callable[[], bool]], None],
             cancel_event: threading.Event) -> None:
        state = JobState(job_id=job_id, kind=kind, started_at=time.time())
        self._write_state(state, started=True)
        try:
            def is_cancelled() -> bool:
                return cancel_event.is_set() or state.cancelled

            runner(state, is_cancelled)
            if is_cancelled():
                state.state = "cancelled"
                state.status_text = "Cancelled by user"
            elif state.error:
                state.state = "error"
            else:
                state.state = "done"
                state.percent = 100.0
                state.status_text = "Done"
        except Exception as exc:
            logger.exception("Job %s crashed", job_id)
            state.state = "error"
            state.error = str(exc)
            state.status_text = f"Error: {exc}"
        finally:
            state.finished_at = time.time()
            self._write_state(state, finished=True)

    def _write_state(self, s: JobState, started: bool = False,
                     finished: bool = False) -> None:
        fields = {
            "state": s.state,
            "total": s.total,
            "done": s.done,
            "current": s.current,
            "percent": round(s.percent, 2),
            "eta_seconds": int(s.eta_seconds),
            "status_text": s.status_text,
        }
        if started:
            fields["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if finished:
            fields["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if s.error:
                fields["error"] = s.error
        self.repo.update_job(s.job_id, fields)
        # Append a friendly event for the UI
        self.repo.append_job_event(
            s.job_id,
            level="ERROR" if s.state == "error" else ("WARN" if s.state == "cancelled" else "INFO"),
            message=s.status_text or s.state,
        )

    def progress(self, s: JobState, current: str, done: int, total: int) -> None:
        """Update progress + estimate ETA."""
        s.done = max(0, int(done))
        s.total = max(int(total), s.done)
        s.current = current
        s.percent = (100.0 * s.done / s.total) if s.total else 0.0
        elapsed = max(0.001, time.time() - s.started_at)
        rate = s.done / elapsed if elapsed > 0 else 0
        remaining = (s.total - s.done) / rate if rate > 0 else 0
        s.eta_seconds = max(0.0, remaining)
        if s.done >= s.total:
            s.status_text = f"Finalising {current}…"
        else:
            s.status_text = (
                f"Processing {s.done + 1} of {s.total}: {current} "
                f"({s.percent:.0f}%, ETA {int(s.eta_seconds)}s)"
            )
        self._write_state(s)

    def cancel(self, job_id: int) -> bool:
        evt = self._cancel_flags.get(job_id)
        if not evt:
            return False
        evt.set()
        return True
