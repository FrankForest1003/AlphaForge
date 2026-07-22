from __future__ import annotations

import os
from typing import Any

import requests


class AlphaForgeAPI:
    """Single integration boundary between Streamlit and FastAPI."""

    def __init__(self) -> None:
        self.base_url = os.getenv("ALPHAFORGE_API_BASE_URL", "http://backend:8000/v1").rstrip("/")
        self.mock_mode = os.getenv("ALPHAFORGE_MOCK_MODE", "true").lower() == "true"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = requests.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        if self.mock_mode:
            return {"mode": "mock", "frontend": "healthy", "backend": "reserved", "lean_worker": "reserved"}
        return self._request("GET", "/health")

    def create_battle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mock_mode:
            return {"battle_id": "BTL-2026-071", "round_id": "R1", "status": "draft", **payload}
        return self._request("POST", "/battles", json=payload)

    def validate_code(self, battle_id: str, code: str) -> dict[str, Any]:
        if self.mock_mode:
            checks = {
                "Python syntax": "class" in code and "def Initialize" in code,
                "QCAlgorithm entry": "QCAlgorithm" in code,
                "Initialize method": "Initialize" in code,
                "Restricted imports": "subprocess" not in code and "socket" not in code,
            }
            return {"accepted": all(checks.values()), "checks": checks, "smoke_status": "ready"}
        return self._request("POST", "/strategies/code/validate", json={"battle_id": battle_id, "code": code})

    def endpoint_registry(self) -> list[tuple[str, str]]:
        return [
            ("POST", "/battles"),
            ("POST", "/strategies/guided/preview"),
            ("POST", "/strategies/code/validate"),
            ("POST", "/battles/{id}/baselines/run"),
            ("POST", "/battles/{id}/rounds/{round}/ai-forge"),
            ("GET", "/battles/{id}/rounds/{round}/agent-events"),
            ("POST", "/battles/{id}/rounds/{round}/evaluate"),
            ("GET", "/battles/{id}/rounds/{round}/education-summary"),
            ("POST", "/battles/{id}/rounds/{round}/next"),
        ]

