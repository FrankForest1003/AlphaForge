from __future__ import annotations

from typing import Any

import requests


class WorkerClientError(RuntimeError):
    pass


class LeanWorkerClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"X-Worker-Token": token} if token else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f": {exc.response.text[:500]}"
            raise WorkerClientError(f"LEAN Worker request failed{detail}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def data_status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/data/status")

    def submit(self, strategy_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/jobs",
            json={"strategy_id": strategy_id, "parameters": parameters},
        )

    def job(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}")

    def result(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}/result")
