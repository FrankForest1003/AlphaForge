from __future__ import annotations

import ablation.worker as worker_module


class ScriptedPool:
    def __init__(self, *, states=None, status="completed"):
        self.states = iter(states or ["completed"])
        self.status = status
        self.calls: list[tuple] = []

    def submit_custom(self, source_code, parameters, *, timeout_seconds):
        self.calls.append(("submit", source_code, parameters, timeout_seconds))
        return {"run_id": "worker-1::run-7"}

    def job(self, run_id):
        self.calls.append(("job", run_id))
        return {"state": next(self.states)}

    def result(self, run_id):
        self.calls.append(("result", run_id))
        return {
            "status": self.status,
            "summary": {"sharpe_ratio": 1.1},
            "errors": [],
        }

    def log(self, run_id):
        self.calls.append(("log", run_id))
        return "LEAN completed"

    def details(self, run_id):
        self.calls.append(("details", run_id))
        return {"portfolio": [{"time": "2024-01-01", "total_value": 110_000}]}


def test_worker_pool_normalizes_urls_and_uses_explicit_token(monkeypatch):
    captured = {}

    def fake_from_urls(urls, *, token, timeout):
        captured.update(urls=urls, token=token, timeout=timeout)
        return "pool"

    monkeypatch.setenv(
        "ABLATION_WORKER_URLS",
        " http://worker-1:8081/,http://worker-2:8081/ ",
    )
    monkeypatch.setenv("ALPHAFORGE_WORKER_TOKEN", "worker-secret")
    monkeypatch.setattr(
        worker_module.LeanWorkerPoolClient,
        "from_urls",
        fake_from_urls,
    )

    assert worker_module.worker_pool() == "pool"
    assert captured == {
        "urls": ["http://worker-1:8081", "http://worker-2:8081"],
        "token": "worker-secret",
        "timeout": 30.0,
    }


def test_run_source_polls_and_builds_completed_artifact(monkeypatch):
    pool = ScriptedPool(states=["queued", "running", "completed"])
    monkeypatch.setattr(worker_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        worker_module,
        "build_behavior_evidence",
        lambda details: {"filled_order_count": 3, "source": details},
    )
    monkeypatch.setattr(
        worker_module,
        "build_performance_analysis",
        lambda details, summary, *, initial_cash: {
            "initial_cash": initial_cash,
            "summary": summary,
        },
    )
    executor = worker_module.WorkerExecutor(
        pool,
        poll_seconds=0,
        timeout_seconds=30,
    )

    artifact = executor.run_source("class UserStrategy: pass", {"initial_cash": "100000"})

    assert artifact.worker_run_id == "worker-1::run-7"
    assert artifact.state == "completed"
    assert artifact.result["status"] == "completed"
    assert artifact.console_log == "LEAN completed"
    assert artifact.behavior_evidence["filled_order_count"] == 3
    assert artifact.analysis["initial_cash"] == 100_000.0
    assert [call[0] for call in pool.calls] == [
        "submit",
        "job",
        "job",
        "job",
        "result",
        "log",
        "details",
    ]
    assert artifact.to_dict()["worker_run_id"] == artifact.worker_run_id


def test_run_source_preserves_result_when_log_and_details_are_unavailable():
    class IncompleteEvidencePool(ScriptedPool):
        def log(self, run_id):
            raise RuntimeError("log unavailable")

        def details(self, run_id):
            raise RuntimeError("details unavailable")

    artifact = worker_module.WorkerExecutor(
        IncompleteEvidencePool(),
        poll_seconds=0,
        timeout_seconds=30,
    ).run_source("source", {"initial_cash": "100000"})

    assert artifact.result["status"] == "completed"
    assert artifact.console_log == ""
    assert artifact.details == {"collection_error": "details unavailable"}
    assert artifact.behavior_evidence == {}
    assert artifact.analysis == {}


def test_run_source_does_not_collect_details_for_failed_result():
    pool = ScriptedPool(status="failed")

    artifact = worker_module.WorkerExecutor(
        pool,
        poll_seconds=0,
        timeout_seconds=30,
    ).run_source("source", {"initial_cash": "100000"})

    assert artifact.result["status"] == "failed"
    assert artifact.details == {}
    assert "details" not in [call[0] for call in pool.calls]


def test_run_source_retries_only_transient_unknown_run(monkeypatch):
    class EventuallyVisiblePool(ScriptedPool):
        def __init__(self):
            super().__init__()
            self.polls = 0

        def job(self, run_id):
            self.polls += 1
            if self.polls < 3:
                raise worker_module.WorkerClientError(
                    "unknown",
                    status_code=404,
                    response_text="Unknown run_id",
                )
            return {"state": "completed", "result_path": "/runtime/result.json"}

    monkeypatch.setattr(worker_module.time, "sleep", lambda _: None)
    pool = EventuallyVisiblePool()
    artifact = worker_module.WorkerExecutor(pool, poll_seconds=0).run_source(
        "source", {"initial_cash": "100000"}
    )
    assert artifact.result["status"] == "completed"
    assert pool.polls == 3


def test_run_source_does_not_fetch_result_before_result_path_exists():
    class MissingResultPool(ScriptedPool):
        def job(self, run_id):
            return {"state": "failed", "result_path": None, "error": "engine failed"}

    pool = MissingResultPool()
    try:
        worker_module.WorkerExecutor(pool, poll_seconds=0).run_source(
            "source", {"initial_cash": "100000"}
        )
    except RuntimeError as exc:
        assert str(exc) == "engine failed"
    else:
        raise AssertionError("expected a terminal Worker error")
    assert "result" not in [call[0] for call in pool.calls]


def test_run_source_raises_after_polling_deadline(monkeypatch):
    pool = ScriptedPool(states=["running"])
    clocks = iter([0.0, 62.0, 62.1])
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: next(clocks))

    executor = worker_module.WorkerExecutor(
        pool,
        poll_seconds=0,
        timeout_seconds=1,
    )

    try:
        executor.run_source("source", {"initial_cash": "100000"})
    except TimeoutError as exc:
        assert "worker-1::run-7" in str(exc)
    else:
        raise AssertionError("expected polling timeout")


def test_run_spec_validates_and_compiles_before_submitting(monkeypatch):
    calls = []
    executor = worker_module.WorkerExecutor(ScriptedPool())
    monkeypatch.setattr(
        worker_module,
        "validate_strategy_spec",
        lambda spec: calls.append(("validate", spec)) or "validated",
    )
    monkeypatch.setattr(
        worker_module,
        "compile_strategy_source",
        lambda spec: calls.append(("compile", spec)) or "compiled source",
    )
    monkeypatch.setattr(
        executor,
        "run_source",
        lambda source, parameters: calls.append(("run", source, parameters))
        or "artifact",
    )

    assert executor.run_spec({"track": "Traditional"}, {"initial_cash": "1"}) == (
        "artifact"
    )
    assert calls == [
        ("validate", {"track": "Traditional"}),
        ("compile", "validated"),
        ("run", "compiled source", {"initial_cash": "1"}),
    ]
