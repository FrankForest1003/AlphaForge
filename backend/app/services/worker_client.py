from __future__ import annotations

import threading
from typing import Any

import requests


class WorkerClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

    @property
    def is_unknown_run(self) -> bool:
        return self.status_code == 404 and "unknown run_id" in self.response_text.lower()


class LeanWorkerClient:
    """HTTP adapter for one isolated LEAN execution service."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"X-Worker-Token": token} if token else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Normalize transport failures into the backend's worker error type."""

        parse_json = kwargs.pop("parse_json", True)
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json() if parse_json else response.text
        except requests.RequestException as exc:
            detail = ""
            status_code = None
            response_text = ""
            if getattr(exc, "response", None) is not None:
                status_code = exc.response.status_code
                response_text = exc.response.text[:500]
                detail = f": {response_text}"
            raise WorkerClientError(
                f"LEAN Worker request failed{detail}",
                status_code=status_code,
                response_text=response_text,
            ) from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def submit(self, strategy_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/jobs",
            json={"strategy_id": strategy_id, "parameters": parameters},
        )

    def submit_custom(
        self,
        algorithm_code: str,
        parameters: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "algorithm_code": algorithm_code,
            "parameters": parameters,
        }
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds
        return self._request("POST", "/v1/custom-jobs", json=payload)

    def job(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}")

    def result(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}/result")

    def log(self, run_id: str) -> str:
        return self._request("GET", f"/v1/jobs/{run_id}/log", parse_json=False)

    def details(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}/details")


class LeanWorkerPoolClient:
    """Route each submitted LEAN job to one isolated single-job Worker.

    The returned virtual run id embeds the selected slot so every later poll,
    result, log, and details request is sticky without an external load balancer
    or an in-memory routing table.
    """

    RUN_ID_SEPARATOR = "::"
    TERMINAL_STATES = {
        "completed",
        "completed_with_data_gaps",
        "failed",
        "timeout",
    }

    def __init__(self, workers: list[LeanWorkerClient]) -> None:
        if not workers:
            raise ValueError("at least one LEAN Worker is required")
        self.workers = list(workers)
        self._active = [0 for _ in workers]
        self._next_equal_slot = 0
        self._leases: dict[str, int] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_urls(
        cls,
        urls: list[str] | tuple[str, ...],
        token: str = "",
        timeout: float = 20.0,
    ) -> "LeanWorkerPoolClient":
        return cls(
            [
                LeanWorkerClient(url, token=token, timeout=timeout)
                for url in urls
            ]
        )

    def _select_slot(self) -> int:
        with self._lock:
            # Least-active routing avoids queueing new jobs behind a busy slot;
            # round-robin tie breaking prevents a permanent preference for slot 0.
            minimum = min(self._active)
            candidates = [
                index
                for index, count in enumerate(self._active)
                if count == minimum
            ]
            slot = next(
                (
                    index
                    for index in candidates
                    if index >= self._next_equal_slot
                ),
                candidates[0],
            )
            self._active[slot] += 1
            self._next_equal_slot = (slot + 1) % len(self.workers)
            return slot

    def _virtual_run_id(self, slot: int, run_id: str) -> str:
        return f"worker-{slot + 1}{self.RUN_ID_SEPARATOR}{run_id}"

    def _route(self, virtual_run_id: str) -> tuple[int, str]:
        if self.RUN_ID_SEPARATOR not in virtual_run_id:
            # Backwards-compatible routing for run ids created before pooling.
            return 0, virtual_run_id
        label, run_id = virtual_run_id.split(self.RUN_ID_SEPARATOR, 1)
        if not label.startswith("worker-") or not run_id:
            raise WorkerClientError("Invalid pooled LEAN Worker run_id")
        try:
            slot = int(label.removeprefix("worker-")) - 1
        except ValueError as exc:
            raise WorkerClientError("Invalid pooled LEAN Worker run_id") from exc
        if slot < 0 or slot >= len(self.workers):
            raise WorkerClientError("Unknown LEAN Worker slot")
        return slot, run_id

    def _release(self, virtual_run_id: str, slot: int) -> None:
        with self._lock:
            # Pop makes release idempotent because both terminal polling and
            # result retrieval may observe completion for the same job.
            leased_slot = self._leases.pop(virtual_run_id, None)
            if leased_slot is None:
                return
            self._active[leased_slot] = max(0, self._active[leased_slot] - 1)

    def _submit(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        slot = self._select_slot()
        try:
            submitted = getattr(self.workers[slot], method)(*args, **kwargs)
        except Exception:
            with self._lock:
                self._active[slot] = max(0, self._active[slot] - 1)
            raise
        payload = dict(submitted)
        virtual_run_id = self._virtual_run_id(slot, str(submitted["run_id"]))
        with self._lock:
            self._leases[virtual_run_id] = slot
        payload["run_id"] = virtual_run_id
        payload["worker_slot"] = slot + 1
        return payload

    def health(self) -> dict[str, Any]:
        slots = []
        for index, worker in enumerate(self.workers):
            try:
                payload = worker.health()
            except WorkerClientError as exc:
                payload = {"status": "unavailable", "error": str(exc)}
            with self._lock:
                active = self._active[index]
            slots.append(
                {
                    "slot": index + 1,
                    "url": getattr(worker, "base_url", f"worker-{index + 1}"),
                    "active_jobs": active,
                    **payload,
                }
            )
        ready = sum(item.get("status") == "ok" for item in slots)
        return {
            "status": "ok" if ready == len(slots) else "degraded",
            "ready_workers": ready,
            "worker_count": len(slots),
            "capacity": len(slots),
            "slots": slots,
        }

    def submit(self, strategy_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._submit("submit", strategy_id, parameters)

    def submit_custom(
        self,
        algorithm_code: str,
        parameters: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        return self._submit(
            "submit_custom",
            algorithm_code,
            parameters,
            timeout_seconds=timeout_seconds,
        )

    def job(self, virtual_run_id: str) -> dict[str, Any]:
        slot, run_id = self._route(virtual_run_id)
        record = self.workers[slot].job(run_id)
        if record.get("state") in self.TERMINAL_STATES:
            self._release(virtual_run_id, slot)
        return record

    def result(self, virtual_run_id: str) -> dict[str, Any]:
        slot, run_id = self._route(virtual_run_id)
        try:
            return self.workers[slot].result(run_id)
        finally:
            self._release(virtual_run_id, slot)

    def log(self, virtual_run_id: str) -> str:
        slot, run_id = self._route(virtual_run_id)
        return self.workers[slot].log(run_id)

    def details(self, virtual_run_id: str) -> dict[str, Any]:
        slot, run_id = self._route(virtual_run_id)
        return self.workers[slot].details(run_id)
