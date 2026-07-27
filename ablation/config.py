"""Validated, dependency-free configuration for standalone ablation studies."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping


StudyKind = Literal["reliability", "forge"]
TRACKS = ("Traditional", "ML", "Hybrid")


class ConfigError(ValueError):
    """Raised when a study file is incomplete or internally inconsistent."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field_name} must be a JSON object")
    return dict(value)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{field_name} must be a positive integer")
    return value


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class ArmConfig:
    """One controlled intervention within a study."""

    id: str
    label: str
    options: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArmConfig":
        item = _mapping(raw, "arm")
        unknown = set(item).difference({"id", "label", "options"})
        if unknown:
            raise ConfigError(f"unknown arm fields: {sorted(unknown)}")
        arm_id = _non_empty_string(item.get("id"), "arm.id")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in arm_id):
            raise ConfigError(
                "arm.id may contain only lowercase letters, digits, '_' and '-'"
            )
        return cls(
            id=arm_id,
            label=_non_empty_string(item.get("label"), f"arm {arm_id}.label"),
            options=MappingProxyType(_mapping(item.get("options", {}), "arm.options")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "options": dict(self.options)}


@dataclass(frozen=True)
class StudyConfig:
    """Immutable experiment definition loaded from a versioned JSON file."""

    schema_version: str
    study_id: str
    kind: StudyKind
    description: str
    replicates: int
    tracks: tuple[str, ...]
    max_parallel_tracks: int
    arms: tuple[ArmConfig, ...]
    run_settings: Mapping[str, Any]
    execution: Mapping[str, Any]
    reporting: Mapping[str, Any]
    source_path: Path | None = None

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        source_path: Path | None = None,
    ) -> "StudyConfig":
        item = _mapping(raw, "study")
        allowed = {
            "schema_version",
            "study_id",
            "kind",
            "description",
            "replicates",
            "tracks",
            "max_parallel_tracks",
            "arms",
            "run_settings",
            "execution",
            "reporting",
        }
        unknown = set(item).difference(allowed)
        if unknown:
            raise ConfigError(f"unknown study fields: {sorted(unknown)}")

        kind = item.get("kind")
        if kind not in {"reliability", "forge"}:
            raise ConfigError("kind must be 'reliability' or 'forge'")

        raw_tracks = item.get("tracks", list(TRACKS))
        if not isinstance(raw_tracks, list) or not raw_tracks:
            raise ConfigError("tracks must be a non-empty JSON array")
        tracks = tuple(_non_empty_string(value, "tracks[]") for value in raw_tracks)
        if len(tracks) != len(set(tracks)):
            raise ConfigError("tracks must be unique")
        unsupported_tracks = set(tracks).difference(TRACKS)
        if unsupported_tracks:
            raise ConfigError(f"unsupported tracks: {sorted(unsupported_tracks)}")

        raw_arms = item.get("arms")
        if not isinstance(raw_arms, list) or not raw_arms:
            raise ConfigError("arms must be a non-empty JSON array")
        arms = tuple(ArmConfig.from_dict(value) for value in raw_arms)
        arm_ids = [arm.id for arm in arms]
        if len(arm_ids) != len(set(arm_ids)):
            raise ConfigError("arm ids must be unique")

        max_parallel = _positive_int(
            item.get("max_parallel_tracks", len(tracks)),
            "max_parallel_tracks",
        )
        if max_parallel > len(tracks):
            raise ConfigError("max_parallel_tracks cannot exceed the track count")

        run_settings = _mapping(item.get("run_settings", {}), "run_settings")
        if kind == "forge":
            required_settings = {
                "symbols",
                "start_date",
                "end_date",
                "initial_cash",
                "benchmark",
                "transaction_cost_bps",
                "slippage_bps",
            }
            missing = required_settings.difference(run_settings)
            if missing:
                raise ConfigError(
                    f"forge run_settings are missing fields: {sorted(missing)}"
                )

        return cls(
            schema_version=_non_empty_string(
                item.get("schema_version"), "schema_version"
            ),
            study_id=_non_empty_string(item.get("study_id"), "study_id"),
            kind=kind,
            description=_non_empty_string(item.get("description"), "description"),
            replicates=_positive_int(item.get("replicates"), "replicates"),
            tracks=tracks,
            max_parallel_tracks=max_parallel,
            arms=arms,
            run_settings=MappingProxyType(run_settings),
            execution=MappingProxyType(
                _mapping(item.get("execution", {}), "execution")
            ),
            reporting=MappingProxyType(
                _mapping(item.get("reporting", {}), "reporting")
            ),
            source_path=source_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "kind": self.kind,
            "description": self.description,
            "replicates": self.replicates,
            "tracks": list(self.tracks),
            "max_parallel_tracks": self.max_parallel_tracks,
            "arms": [arm.to_dict() for arm in self.arms],
            "run_settings": dict(self.run_settings),
            "execution": dict(self.execution),
            "reporting": dict(self.reporting),
        }


def load_study(path: str | Path) -> StudyConfig:
    """Load and validate one study definition without reading environment secrets."""

    resolved = Path(path).expanduser().resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read study file {resolved}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in study file {resolved}: {exc}") from exc
    return StudyConfig.from_dict(raw, source_path=resolved)
