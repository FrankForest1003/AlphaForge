from __future__ import annotations

from datetime import date, timedelta
import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from alphaforge.schemas.agent_outputs import GeneratedCode
from alphaforge.schemas.backtest import BacktestMetrics, BacktestResult, SmokeTestResult
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.strategy_spec import MLLogic, StrategySpec


class LeanWorkerError(RuntimeError):
    pass


class LeanWorkerClient:
    """Authenticated HTTP client for the isolated localhost LEAN Worker."""

    TERMINAL_STATES = {"completed", "completed_with_data_gaps", "failed", "timeout"}

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:18081",
        token: str | None = None,
        request_timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or os.environ.get("ALPHAFORGE_WORKER_TOKEN") or os.environ.get(
            "ALPHAFORGE_API_TOKEN", ""
        )
        self.request_timeout_seconds = request_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if authenticated and self.token:
            headers["X-Worker-Token"] = self.token
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                content = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise LeanWorkerError(f"Worker HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise LeanWorkerError(f"Worker connection failed: {exc}") from exc
        return json.loads(content) if content else None

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", authenticated=False)

    def data_status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/data/status")

    def deploy(self, spec: StrategySpec, code: GeneratedCode) -> dict[str, Any]:
        metadata = code.compiler_metadata
        required_symbols = sorted({*spec.universe.symbols, "SPY"})
        return self._request(
            "POST",
            "/v1/strategies/generated",
            {
                "strategy_id": spec.strategy_id,
                "algorithm_class": metadata["algorithm_class"],
                "expected_marker": metadata["completion_marker"],
                "source": code.source,
                "source_sha256": code.source_sha256,
                "spec_sha256": code.spec_sha256,
                "candidate_type": spec.logic.kind,
                "default_parameters": {
                    "start_date": spec.execution.start_date.isoformat(),
                    "end_date": spec.execution.end_date.isoformat(),
                    "initial_cash": str(spec.execution.initial_cash),
                },
                "required_symbols": required_symbols,
                "supports_ml": isinstance(spec.logic, MLLogic)
                or getattr(spec.logic, "kind", None) == "hybrid",
            },
        )

    def submit(
        self,
        strategy_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: int = 3600,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/jobs",
            {
                "strategy_id": strategy_id,
                "parameters": parameters or {},
                "timeout_seconds": timeout_seconds,
            },
        )

    def wait(self, run_id: str, *, deadline_seconds: int = 4200) -> dict[str, Any]:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            record = self._request("GET", f"/v1/jobs/{run_id}")
            if record.get("state") in self.TERMINAL_STATES:
                return record
            time.sleep(self.poll_interval_seconds)
        raise LeanWorkerError(f"Worker job polling deadline exceeded: {run_id}")

    def result(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{run_id}/result")


class LocalLeanBacktestProvider:
    """BacktestProvider that deploys digest-bound code to Local LEAN Worker."""

    def __init__(self, client: LeanWorkerClient, *, timeout_seconds: int = 3600) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    def smoke_test(self, spec: StrategySpec, code: GeneratedCode) -> SmokeTestResult:
        try:
            health = self.client.health()
            if health.get("status") != "ok":
                raise LeanWorkerError(f"Worker health is {health.get('status', 'unknown')}")
            self.client.deploy(spec, code)
            status = self.client.data_status()
            common_end = status.get("common_end_date")
            if not status.get("ready") or not common_end:
                raise LeanWorkerError("Worker market-data catalog is not ready")
            end = date.fromisoformat(common_end)
            start = max(spec.execution.start_date, end - timedelta(days=120))
            submission = self.client.submit(
                spec.strategy_id,
                parameters={"start_date": start.isoformat(), "end_date": end.isoformat()},
                timeout_seconds=min(self.timeout_seconds, 900),
            )
            record = self.client.wait(submission["run_id"], deadline_seconds=1200)
            if record.get("state") != "completed":
                return SmokeTestResult(
                    strategy_id=spec.strategy_id,
                    status="failed",
                    diagnostics=(f"WORKER_STATE:{record.get('state')}",),
                    provider="local_lean_worker_v1.1.3",
                )
            result = self.client.result(submission["run_id"])
            eligible = bool(result.get("evaluation", {}).get("eligible_for_comparison"))
            return SmokeTestResult(
                strategy_id=spec.strategy_id,
                status="passed" if eligible else "failed",
                diagnostics=tuple(result.get("evaluation", {}).get("rejection_reasons", [])),
                provider="local_lean_worker_v1.1.3",
            )
        except Exception as exc:
            return SmokeTestResult(
                strategy_id=spec.strategy_id,
                status="failed",
                diagnostics=(f"{type(exc).__name__}: {exc}",),
                provider="local_lean_worker_v1.1.3",
            )

    def run(self, spec: StrategySpec, code: GeneratedCode) -> BacktestResult:
        try:
            self.client.deploy(spec, code)
            submission = self.client.submit(
                spec.strategy_id,
                parameters={
                    "start_date": spec.execution.start_date.isoformat(),
                    "end_date": spec.execution.end_date.isoformat(),
                    "initial_cash": str(spec.execution.initial_cash),
                },
                timeout_seconds=self.timeout_seconds,
            )
            record = self.client.wait(
                submission["run_id"], deadline_seconds=self.timeout_seconds + 600
            )
            if record.get("state") != "completed":
                return self._failed(spec, submission["run_id"], record.get("state", "failed"))
            result = self.client.result(submission["run_id"])
            if not result.get("evaluation", {}).get("eligible_for_comparison"):
                reasons = result.get("evaluation", {}).get("rejection_reasons", [])
                return self._failed(spec, submission["run_id"], ",".join(reasons))
            summary = result["summary"]
            statistics = result["statistics"]
            metrics = BacktestMetrics(
                cagr=float(summary["cagr"]),
                sharpe_ratio=float(summary["sharpe_ratio"]),
                sortino_ratio=float(summary["sortino_ratio"]),
                max_drawdown=float(summary["maximum_drawdown"]),
                annual_volatility=float(statistics["annual_standard_deviation"]),
                turnover=float(summary["portfolio_turnover"]),
                total_fees=float(summary["total_fees"]),
            )
            return BacktestResult(
                run_id=submission["run_id"],
                strategy_id=spec.strategy_id,
                strategy_role="candidate",
                status="completed",
                dataset_split="validation",
                provider="local_lean_worker_v1.1.3",
                metrics=metrics,
                warnings=(),
            )
        except Exception as exc:
            return self._failed(spec, "worker-request-failed", f"{type(exc).__name__}: {exc}")

    def _failed(self, spec: StrategySpec, run_id: str, reason: str) -> BacktestResult:
        return BacktestResult(
            run_id=run_id,
            strategy_id=spec.strategy_id,
            strategy_role="candidate",
            status="failed",
            dataset_split="validation",
            provider="local_lean_worker_v1.1.3",
            metrics=None,
            warnings=(reason,),
        )


def local_lean_environment_manifest() -> LeanEnvironmentManifest:
    """Pinned manifest for the repository's Local LEAN Runtime contract."""

    return LeanEnvironmentManifest(
        provider="local_lean",
        lean_version="2.5@0269115d3cfbf691c7a0b7cfcc9ed412cafb91f6",
        python_version="3.11",
        data_version="alphaforge_us_equity_30_v1.0",
        normalization_mode="raw",
        brokerage_model="cash-long-only",
        fee_model="LEAN configured fee model",
        slippage_model="LEAN configured slippage model",
        time_zone="America/New_York",
        allowed_imports=(
            "AlgorithmImports",
            "alphaforge_base",
            "datetime",
            "numpy",
            "pandas",
            "sklearn",
        ),
        python_dependencies=("numpy", "pandas", "scikit-learn"),
        qc_api_profile="local_lean_v1.1.3",
        template_compatibility=(
            "traditional_local_lean_v1",
            "ml_local_lean_v1",
            "hybrid_local_lean_v1",
        ),
    )
