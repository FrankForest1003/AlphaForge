"""Crash-resumable manifest storage for standalone ablation execution."""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from .config import StudyConfig

try:
    import fcntl
except ImportError:  # pragma: no cover - AlphaForge runs on Linux/macOS.
    fcntl = None


MANIFEST_SCHEMA_VERSION = "1.0"
EXPERIMENT_STATES = {"planned", "running", "completed", "failed"}
UNIT_STATES = {"pending", "running", "completed", "failed", "interrupted"}


class ManifestError(RuntimeError):
    """Raised for invalid transitions or corrupt persisted experiment state."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"manifest value is not JSON serializable: {exc}") from exc


class ManifestStore:
    """Own one experiment directory and update its manifest atomically.

    Unit identifiers are scheduler-defined stable strings such as
    ``full/1/ML/critic/1``. Completed units are immutable by default, allowing a
    resumed scheduler to skip paid API calls and completed LEAN jobs.
    """

    def __init__(self, experiment_dir: str | Path) -> None:
        self.experiment_dir = Path(experiment_dir).expanduser().resolve()
        self.path = self.experiment_dir / "manifest.json"
        self.lock_path = self.experiment_dir / ".manifest.lock"
        self._thread_lock = threading.RLock()

    @classmethod
    def create(
        cls,
        runs_root: str | Path,
        study: StudyConfig,
        *,
        provenance: Mapping[str, Any],
        experiment_id: str | None = None,
    ) -> "ManifestStore":
        root = Path(runs_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        identifier = experiment_id or (
            f"{study.study_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        if not identifier or any(part in {"", ".", ".."} for part in identifier.split("/")):
            raise ManifestError("invalid experiment_id")
        directory = (root / identifier).resolve()
        if directory.parent != root:
            raise ManifestError("experiment_id must identify a direct child of runs_root")
        directory.mkdir(parents=False, exist_ok=False)
        store = cls(directory)
        now = utc_now()
        document = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "experiment_id": identifier,
            "study_id": study.study_id,
            "study_kind": study.kind,
            "status": "planned",
            "created_at": now,
            "updated_at": now,
            "config": study.to_dict(),
            "provenance": _json_copy(dict(provenance)),
            "frozen_inputs": {},
            "units": {},
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "llm_attempts": 0,
                "lean_jobs": 0,
            },
            "errors": [],
            "artifacts": {},
        }
        store._atomic_write(document)
        return store

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+", encoding="utf-8") as lock_file:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _atomic_write(self, document: Mapping[str, Any]) -> None:
        payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _validate(document: Mapping[str, Any]) -> None:
        if document.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ManifestError("unsupported manifest schema_version")
        if document.get("status") not in EXPERIMENT_STATES:
            raise ManifestError("invalid experiment status")
        units = document.get("units")
        if not isinstance(units, dict):
            raise ManifestError("manifest units must be an object")
        for unit_id, unit in units.items():
            if not isinstance(unit_id, str) or not isinstance(unit, dict):
                raise ManifestError("invalid manifest unit entry")
            if unit.get("status") not in UNIT_STATES:
                raise ManifestError(f"invalid status for unit {unit_id}")

    def read(self) -> dict[str, Any]:
        with self._locked():
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ManifestError(f"cannot read manifest: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
            self._validate(document)
            return document

    def update(
        self,
        mutator: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Apply one locked mutation and return a detached snapshot."""

        with self._locked():
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ManifestError(f"cannot update manifest: {exc}") from exc
            self._validate(document)
            mutator(document)
            document["updated_at"] = utc_now()
            self._validate(document)
            self._atomic_write(document)
            return copy.deepcopy(document)

    def set_status(self, status: str, *, error: str | None = None) -> dict[str, Any]:
        if status not in EXPERIMENT_STATES:
            raise ManifestError(f"unknown experiment status: {status}")

        def mutate(document: dict[str, Any]) -> None:
            current = document["status"]
            allowed = {
                "planned": {"running", "failed"},
                "running": {"running", "completed", "failed"},
                "failed": {"running", "failed"},
                "completed": {"completed"},
            }
            if status not in allowed[current]:
                raise ManifestError(f"cannot transition experiment {current} -> {status}")
            document["status"] = status
            if error:
                document["errors"].append({"time": utc_now(), "message": error})

        return self.update(mutate)

    def register_units(self, units: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Add planned units without replacing already persisted work."""

        normalized = [_json_copy(dict(unit)) for unit in units]

        def mutate(document: dict[str, Any]) -> None:
            for unit in normalized:
                unit_id = unit.pop("id", None)
                if not isinstance(unit_id, str) or not unit_id.strip():
                    raise ManifestError("every unit requires a non-empty id")
                if unit_id in document["units"]:
                    continue
                document["units"][unit_id] = {
                    **unit,
                    "status": "pending",
                    "attempt": 0,
                    "started_at": None,
                    "finished_at": None,
                    "artifact": None,
                    "error": None,
                    "possible_duplicate_external_call": False,
                }

        return self.update(mutate)

    def start_unit(self, unit_id: str) -> dict[str, Any]:
        def mutate(document: dict[str, Any]) -> None:
            unit = self._unit(document, unit_id)
            if unit["status"] == "completed":
                raise ManifestError(f"completed unit cannot restart: {unit_id}")
            if unit["status"] == "running":
                raise ManifestError(f"unit is already running: {unit_id}")
            unit.update(
                {
                    "status": "running",
                    "attempt": int(unit.get("attempt", 0)) + 1,
                    "started_at": utc_now(),
                    "finished_at": None,
                    "error": None,
                }
            )

        return self.update(mutate)

    def complete_unit(
        self,
        unit_id: str,
        *,
        artifact: str,
        usage: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        if not artifact:
            raise ManifestError("completed units require an artifact path")
        addition = dict(usage or {})

        def mutate(document: dict[str, Any]) -> None:
            unit = self._unit(document, unit_id)
            if unit["status"] == "completed":
                if unit.get("artifact") == artifact:
                    return
                raise ManifestError(f"completed unit artifact is immutable: {unit_id}")
            if unit["status"] != "running":
                raise ManifestError(f"unit must be running before completion: {unit_id}")
            unit.update(
                {
                    "status": "completed",
                    "finished_at": utc_now(),
                    "artifact": artifact,
                    "error": None,
                }
            )
            for key in document["usage"]:
                document["usage"][key] += int(addition.get(key, 0) or 0)

        return self.update(mutate)

    def fail_unit(
        self,
        unit_id: str,
        error: str,
        *,
        artifact: str | None = None,
    ) -> dict[str, Any]:
        def mutate(document: dict[str, Any]) -> None:
            unit = self._unit(document, unit_id)
            if unit["status"] == "completed":
                raise ManifestError(f"completed unit cannot fail: {unit_id}")
            unit.update(
                {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "artifact": artifact,
                    "error": error,
                }
            )

        return self.update(mutate)

    def recover_interrupted(self) -> dict[str, Any]:
        """Mark orphaned running units retryable after an unclean shutdown.

        External LLM calls do not expose an idempotency key. Retrying such a unit
        may duplicate a paid request, so recovery records that fact explicitly.
        """

        def mutate(document: dict[str, Any]) -> None:
            for unit in document["units"].values():
                if unit["status"] == "running":
                    unit.update(
                        {
                            "status": "interrupted",
                            "finished_at": utc_now(),
                            "error": "scheduler stopped before recording a terminal artifact",
                            "possible_duplicate_external_call": bool(
                                unit.get("external_call", False)
                            ),
                        }
                    )

        return self.update(mutate)

    def set_frozen_input(self, name: str, value: Any) -> dict[str, Any]:
        frozen = _json_copy(value)

        def mutate(document: dict[str, Any]) -> None:
            current = document["frozen_inputs"].get(name)
            if current is not None and current != frozen:
                raise ManifestError(f"frozen input cannot change: {name}")
            document["frozen_inputs"][name] = frozen

        return self.update(mutate)

    def set_artifact(self, name: str, relative_path: str) -> dict[str, Any]:
        if not relative_path:
            raise ManifestError("artifact path must be non-empty")

        def mutate(document: dict[str, Any]) -> None:
            document["artifacts"][name] = relative_path

        return self.update(mutate)

    def pending_units(self) -> list[dict[str, Any]]:
        document = self.read()
        return [
            {"id": unit_id, **copy.deepcopy(unit)}
            for unit_id, unit in document["units"].items()
            if unit["status"] in {"pending", "failed", "interrupted"}
        ]

    @staticmethod
    def _unit(document: dict[str, Any], unit_id: str) -> dict[str, Any]:
        try:
            return document["units"][unit_id]
        except KeyError as exc:
            raise ManifestError(f"unknown unit: {unit_id}") from exc
