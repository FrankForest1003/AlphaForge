from __future__ import annotations

import csv
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .manifest import ManifestStore


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "median": None, "q1": None, "q3": None, "iqr": None}
    quartiles = statistics.quantiles(ordered, n=4, method="inclusive") if len(ordered) > 1 else [ordered[0]] * 3
    return {
        "count": len(ordered), "median": statistics.median(ordered),
        "q1": quartiles[0], "q3": quartiles[2], "iqr": quartiles[2] - quartiles[0],
    }


def _hierarchical_bootstrap_95ci(
    paired: dict[tuple[int, str], dict[str, float]],
    *,
    samples: int = 2_000,
) -> dict[str, float | None]:
    by_replicate: dict[int, list[float]] = defaultdict(list)
    for (replicate, _), values in paired.items():
        if {"full", "no_critic"} <= values.keys():
            by_replicate[replicate].append(values["full"] - values["no_critic"])
    replicate_ids = sorted(by_replicate)
    if not replicate_ids:
        return {"lower": None, "upper": None}
    generator = random.Random(17_291)
    draws = []
    for _ in range(samples):
        sampled_values = []
        for replicate in generator.choices(replicate_ids, k=len(replicate_ids)):
            track_values = by_replicate[replicate]
            sampled_values.extend(
                generator.choices(track_values, k=len(track_values))
            )
        draws.append(statistics.mean(sampled_values))
    draws.sort()
    return {
        "lower": draws[int(0.025 * (len(draws) - 1))],
        "upper": draws[int(0.975 * (len(draws) - 1))],
    }


def build_report(store: ManifestStore) -> dict[str, Any]:
    manifest = store.read()
    artifacts = []
    for unit_id, unit in manifest["units"].items():
        if unit.get("artifact"):
            path = store.experiment_dir / unit["artifact"]
            if path.exists():
                artifacts.append((unit_id, unit, read_json(path)))
    if manifest["study_kind"] == "reliability":
        report, rows = _reliability_report(manifest, artifacts)
    else:
        report, rows = _forge_report(manifest, artifacts)
    report["experiment_id"] = manifest["experiment_id"]
    report["study_id"] = manifest["study_id"]
    report["usage"] = manifest["usage"]
    report_json = store.experiment_dir / "report.json"
    report_csv = store.experiment_dir / "report.csv"
    report_md = store.experiment_dir / "report.md"
    write_json(report_json, report)
    _write_csv(report_csv, rows)
    report_md.write_text(_markdown(report), encoding="utf-8")
    store.set_artifact("report_json", "report.json")
    store.set_artifact("report_csv", "report.csv")
    store.set_artifact("report_markdown", "report.md")
    return report


def _reliability_report(manifest: dict[str, Any], artifacts: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for _, unit, artifact in artifacts:
        row = {
            "arm": unit.get("arm"), "track": unit.get("track"), "replicate": unit.get("replicate"),
            "passed": artifact.get("status") == "passed", "first_schema_pass": artifact.get("first_schema_pass", False),
            "api_attempts": artifact.get("api_attempts", 0), "semantic_retry_count": artifact.get("semantic_retry_count", 0),
            "total_tokens": (artifact.get("usage") or {}).get("total_tokens", 0),
            "elapsed_seconds": artifact.get("elapsed_seconds"), "strategy_spec_sha256": artifact.get("strategy_spec_sha256"),
        }
        rows.append(row); grouped[(str(row["arm"]), str(row["track"]))].append(row)
    groups = []
    for (arm, track), items in sorted(grouped.items()):
        count = len(items)
        groups.append({
            "arm": arm, "track": track, "observations": count,
            "success_rate": sum(bool(x["passed"]) for x in items) / count,
            "first_schema_pass_rate": sum(bool(x["first_schema_pass"]) for x in items) / count,
            "semantic_retry_rate": sum(int(x["semantic_retry_count"] or 0) > 0 for x in items) / count,
            "unique_spec_count": len({x["strategy_spec_sha256"] for x in items if x["strategy_spec_sha256"]}),
            "tokens": _stats([float(x["total_tokens"] or 0) for x in items]),
            "latency_seconds": _stats([float(x["elapsed_seconds"] or 0) for x in items]),
        })
    return {"kind": "reliability", "groups": groups}, rows


def _forge_report(manifest: dict[str, Any], artifacts: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    paired: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    for _, unit, artifact in artifacts:
        arm = str(unit.get("arm"))
        if arm == "shared":
            iterations = artifact.get("iterations") or []
            summary = (iterations[0].get("summary") or {}) if iterations else {}
            rows.append({
                "arm": "one_shot", "track": unit.get("track"),
                "replicate": unit.get("replicate"),
                "completed": bool(iterations and iterations[0].get("status") == "completed"),
                "best_iteration": 1,
                "sharpe_ratio": summary.get("sharpe_ratio"), "cagr": summary.get("cagr"),
                "maximum_drawdown": summary.get("maximum_drawdown"),
                "total_tokens": (artifact.get("usage") or {}).get("total_tokens", 0),
                "lean_jobs": (artifact.get("usage") or {}).get("lean_jobs", 0),
                "elapsed_seconds": artifact.get("elapsed_seconds"),
            })
            continue
        summary = artifact.get("best_summary") or {}
        analysis = artifact.get("best_analysis") or {}
        statistics_block = analysis.get("statistics") or {}
        behavior = artifact.get("best_behavior_evidence") or {}
        iterations = artifact.get("iterations") or []
        iteration_one_summary = (iterations[0].get("summary") or {}) if iterations else {}
        best_sharpe = _number(summary.get("sharpe_ratio"))
        iteration_one_sharpe = _number(iteration_one_summary.get("sharpe_ratio"))
        effective_usage = artifact.get("effective_usage") or artifact.get("usage") or {}
        row = {
            "arm": arm, "track": unit.get("track"), "replicate": unit.get("replicate"),
            "completed": artifact.get("status") == "completed", "best_iteration": artifact.get("best_iteration"),
            "sharpe_ratio": summary.get("sharpe_ratio"), "cagr": summary.get("cagr"),
            "maximum_drawdown": summary.get("maximum_drawdown"),
            "sortino_ratio": summary.get("sortino_ratio"),
            "best_minus_iteration_one_sharpe": (
                best_sharpe - iteration_one_sharpe
                if best_sharpe is not None and iteration_one_sharpe is not None
                else None
            ),
            "annualized_volatility": statistics_block.get("annualized_volatility", summary.get("annualized_volatility")),
            "portfolio_turnover": statistics_block.get("annualized_turnover", summary.get("portfolio_turnover")),
            "total_fees": statistics_block.get("total_fees", summary.get("total_fees")),
            "filled_order_count": behavior.get("filled_order_count"),
            "max_gross_exposure": behavior.get("max_gross_exposure"),
            "total_tokens": effective_usage.get("total_tokens", 0),
            "lean_jobs": effective_usage.get("lean_jobs", 0),
            "elapsed_seconds": artifact.get("effective_elapsed_seconds", artifact.get("elapsed_seconds")),
        }
        rows.append(row); grouped[(arm, str(row["track"]))].append(row)
        sharpe = _number(row["sharpe_ratio"])
        if sharpe is not None and arm in {"full", "no_critic"}:
            paired[(int(row["replicate"]), str(row["track"]))][arm] = sharpe
    for row in rows:
        if row["arm"] == "one_shot":
            grouped[("one_shot", str(row["track"]))].append(row)
    groups = []
    for (arm, track), items in sorted(grouped.items()):
        groups.append({
            "arm": arm, "track": track, "observations": len(items),
            "completion_rate": sum(bool(x["completed"]) for x in items) / len(items),
            "sharpe_ratio": _stats([v for x in items if (v := _number(x["sharpe_ratio"])) is not None]),
            "cagr": _stats([v for x in items if (v := _number(x["cagr"])) is not None]),
            "maximum_drawdown": _stats([v for x in items if (v := _number(x["maximum_drawdown"])) is not None]),
            "best_minus_iteration_one_sharpe": _stats([v for x in items if (v := _number(x.get("best_minus_iteration_one_sharpe"))) is not None]),
            "total_tokens": _stats([float(x["total_tokens"] or 0) for x in items]),
            "elapsed_seconds": _stats([float(x["elapsed_seconds"] or 0) for x in items]),
        })
    differences = [values["full"] - values["no_critic"] for values in paired.values() if {"full", "no_critic"} <= values.keys()]
    return {
        "kind": "forge", "groups": groups,
        "paired_full_minus_no_critic_sharpe": {
            **_stats(differences),
            "full_win_rate": (sum(x > 0 for x in differences) / len(differences) if differences else None),
            "hierarchical_bootstrap_95ci": _hierarchical_bootstrap_95ci(paired),
        },
    }, rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def _markdown(report: dict[str, Any]) -> str:
    lines = [f"# {report['study_id']}", "", f"Experiment: `{report['experiment_id']}`", ""]
    for group in report.get("groups", []):
        lines.extend([f"## {group['arm']} · {group['track']}", "", "```json", json.dumps(group, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)
