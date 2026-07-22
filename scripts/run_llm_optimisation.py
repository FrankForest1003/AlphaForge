#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
from typing import Any

from pydantic import TypeAdapter

from alphaforge.agents.orchestrator import OptimisationOrchestrator
from alphaforge.agents.providers.llm import (
    LLMCodeRiskAgent,
    LLMPostBacktestAnalysisAgent,
    LLMStrategyDesigner,
)
from alphaforge.agents.providers.mock import MockBacktestProvider
from alphaforge.agents.providers.structured import StructuredModelClient
from alphaforge.config import load_model_settings
from alphaforge.demo import build_demo_environment, build_demo_request
from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.agent_outputs import OptimizationResult
from alphaforge.schemas.optimisation import OptimizationConstraints
from alphaforge.services import OptimizationResumer
from backend.app.services import (
    LeanWorkerClient,
    LocalLeanBacktestProvider,
    ValidationEvidenceRunner,
    local_lean_environment_manifest,
)


class ReadableTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)

    def record_audit(self, event) -> None:
        print(
            f"[{event.sequence:02d}] {event.stage:<28} "
            f"{event.subject_id:<36} {event.outcome}",
            flush=True,
        )
        self.record(
            {
                "kind": "pipeline_stage",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                **event.model_dump(mode="json"),
            }
        )

    def write_markdown(self, path: Path, *, result=None, run_error: str | None = None) -> None:
        lines = [
            "# AlphaForge 真实 LLM 闭环日志",
            "",
            "## 安全边界",
            "",
            "- Authorization 请求头已脱敏。",
            "- 日志不包含 `.env` 内容或 API key。",
            "- 下文只展示实际发送的白名单 Context、阶段输入和响应 Schema。",
            "- 不保存模型内部 `reasoning_content`，只保存 Agent 最终结构化原话。",
            "",
            "## 按时间顺序的调用链",
            "",
            "| UTC 时间 | 调用 ID | 事件 | Agent / 阶段 | Schema 纠错次数 | 结果 |",
            "|---|---:|---|---|---:|---|",
            "",
            "> Schema 纠错次数是同一 Agent 输出因 JSON/Pydantic 不合格而发生的一次受限重试。",
        ]
        for event in self.events:
            operation = event.get("operation", event.get("stage", ""))
            outcome = event.get("outcome", "")
            lines.append(
                f"| {event['timestamp_utc']} | {event.get('call_id', '')} | {event['kind']} | {operation} | "
                f"{event.get('attempt', '')} | {outcome} |"
            )

        request_number = 0
        for index, event in enumerate(self.events):
            if event["kind"] != "llm_request":
                continue
            request_number += 1
            operation = event["operation"]
            attempt = event["attempt"]
            call_id = event.get("call_id")
            request_events = [
                item
                for item in self.events[index + 1 :]
                if item.get("call_id") == call_id
            ]
            response = next(
                (
                    item
                    for item in request_events
                    if item["kind"] in {"llm_response", "llm_error"}
                ),
                None,
            )
            validation = next(
                (
                    item
                    for item in request_events
                    if item["kind"] == "llm_validation"
                ),
                None,
            )
            lines.extend(
                [
                    "",
                    f"## 模型调用 {request_number}：{operation}",
                    "",
                    f"- Schema 输出尝试：`{attempt}`",
                    f"- 调用 ID：`{call_id}`",
                    f"- 接口：`{event['endpoint']}`",
                    f"- 模型：`{event['body']['model']}`",
                    f"- 推理强度：`{event['body'].get('reasoning_effort', '未启用')}`",
                    f"- 最大输出：`{event['body'].get('max_tokens')}` tokens",
                    "- Authorization: `Bearer <redacted>`",
                    f"- 本地 Schema 校验：`{(validation or {}).get('outcome', '未执行')}`",
                    "",
                    "### Context Bundle 摘要",
                    "",
                    "```json",
                    json.dumps(event.get("context_bundle"), ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "### 实际 System Message（含完整 Context）",
                    "",
                    event["system_prompt"],
                    "",
                    "### 实际发送给模型的动态输入",
                    "",
                    "```json",
                    json.dumps(event["input"], ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "### 要求回复满足的 JSON Schema",
                    "",
                    "```json",
                    json.dumps(event["json_schema"], ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "### Agent 最终原话",
                    "",
                ]
            )
            if response is None:
                lines.append("没有记录到响应事件。")
            elif response["kind"] == "llm_error":
                lines.append(f"`{response['error']}`")
            else:
                try:
                    decoded = json.loads(response["content"])
                    lines.extend(["```json", json.dumps(decoded, ensure_ascii=False, indent=2), "```"])
                except json.JSONDecodeError:
                    lines.extend(["```text", response["content"], "```"])
            if validation is not None and validation.get("error"):
                lines.extend(
                    [
                        "",
                        "### 本地 Schema 校验错误",
                        "",
                        "```text",
                        validation["error"],
                        "```",
                    ]
                )

            if response is not None and response.get("usage"):
                lines.extend(
                    [
                        "",
                        "### Token 与 Context Cache 使用",
                        "",
                        "```json",
                        json.dumps(response["usage"], ensure_ascii=False, indent=2),
                        "```",
                    ]
                )

        lines.extend(["", "## 最终闭环结果", ""])
        if run_error is not None:
            lines.append(f"运行器停止原因：`{run_error}`")
        elif result is not None:
            lines.extend(
                [
                    f"- 优化状态：`{result.status}`",
                    f"- 最终选择：`{result.selection.selected_strategy_id or '无'}`",
                    f"- 分析错误：`{result.analysis_error or '无'}`",
                    "",
                    "### 各路线结果",
                    "",
                ]
            )
            for candidate in result.candidates:
                lines.append(f"#### {candidate.candidate_type}: `{candidate.state}`")
                lines.append("")
                if candidate.failure_reasons:
                    for reason in candidate.failure_reasons:
                        lines.append(f"- {reason}")
                else:
                    lines.append("- 没有记录失败原因。")
                lines.append("")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the structured LLM Agent pipeline with Local LEAN or the offline "
            "deterministic backtest fixture."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to API_KEY, MODEL and BASE_URL settings.",
    )
    parser.add_argument(
        "--backtest-provider",
        choices=("local-lean", "mock"),
        default="local-lean",
        help="Execution backend; Local LEAN is the production integration path.",
    )
    parser.add_argument(
        "--worker-url",
        default="http://127.0.0.1:18081",
        help="Local LEAN Worker URL.",
    )
    parser.add_argument(
        "--worker-env-file",
        type=Path,
        default=Path("lean_worker/.env"),
        help="File containing ALPHAFORGE_API_TOKEN; the value is never logged.",
    )
    parser.add_argument(
        "--evidence-input",
        type=Path,
        default=None,
        help="Reuse five validated Local LEAN evidence results instead of rerunning them.",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=Path("artifacts/debug_runs/latest/validation_evidence.json"),
        help="Where to write the five normalized pre-design validation results.",
    )
    parser.add_argument(
        "--model-timeout-seconds",
        type=int,
        default=240,
        help="Per-request model transport timeout; Schema retry rules are unchanged.",
    )
    parser.add_argument(
        "--resume-result",
        type=Path,
        default=None,
        help=(
            "Resume a narrowly recognized infrastructure or Prompt-contract failure "
            "without regenerating its design or deterministic source."
        ),
    )
    parser.add_argument(
        "--continue-result",
        type=Path,
        default=None,
        help="Continue a completed no-selection result from its next round.",
    )
    parser.add_argument(
        "--continue-routes",
        nargs="+",
        choices=("traditional", "ml", "hybrid"),
        default=("traditional",),
        help="Routes to allocate the next-round continuation budget to.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/debug_runs/latest/optimization_result.json"),
        help="Where to write the complete validated OptimizationResult.",
    )
    parser.add_argument(
        "--trace-output",
        type=Path,
        default=Path("artifacts/debug_runs/latest/readable_run_log.md"),
        help="Where to write the readable request, response and call-chain log.",
    )
    return parser.parse_args()


def _worker_token(path: Path) -> str:
    environment_token = os.environ.get("ALPHAFORGE_API_TOKEN", "")
    if environment_token:
        return environment_token
    if not path.is_file():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "ALPHAFORGE_API_TOKEN":
            return value.strip().strip('"').strip("'")
    return ""


def main() -> None:
    args = parse_args()
    if args.resume_result is not None and args.continue_result is not None:
        raise ValueError("--resume-result and --continue-result are mutually exclusive")
    initial_result = None
    trace = ReadableTrace()
    client = StructuredModelClient(
        load_model_settings(args.env_file),
        timeout_seconds=args.model_timeout_seconds,
        trace_sink=trace.record,
    )
    if args.backtest_provider == "local-lean":
        backtest_provider = LocalLeanBacktestProvider(
            LeanWorkerClient(
                base_url=args.worker_url,
                token=_worker_token(args.worker_env_file),
            )
        )
        lean_environment = local_lean_environment_manifest()
        if args.resume_result is not None:
            partial = OptimizationResult.model_validate_json(
                args.resume_result.read_text(encoding="utf-8")
            )
            resumer = OptimizationResumer(
                backtest_provider=backtest_provider,
                analysis_agent=LLMPostBacktestAnalysisAgent(client),
                lean_environment=lean_environment,
                audit_sink=trace.record_audit,
            )
            result = None
            run_error = None
            try:
                result = resumer.resume_supported_failures(
                    partial,
                    constraints=OptimizationConstraints(),
                    code_risk_agent=LLMCodeRiskAgent(client),
                )
            except Exception as exc:
                run_error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                trace.write_markdown(
                    args.trace_output, result=result, run_error=run_error
                )
            assert result is not None
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "optimization_id": result.optimization_id,
                        "status": result.status,
                        "selected_strategy_id": result.selection.selected_strategy_id,
                        "resumed_from": str(args.resume_result),
                        "output": str(args.output),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        demo_request = build_demo_request()
        evidence_runner = ValidationEvidenceRunner(
            backtest_provider=backtest_provider,
            lean_environment=lean_environment,
            progress=lambda message: print(message, flush=True),
        )
        if args.continue_result is not None:
            initial_result = OptimizationResult.model_validate_json(
                args.continue_result.read_text(encoding="utf-8")
            )
            evidence = tuple(
                item.backtest_result
                for item in initial_result.evidence_summary.reference_strategies
            )
            # Rebuild fixed policy fields from the current demo mandate. Historical
            # results remain reusable because max_drawdown_limit is a post-backtest
            # admission threshold and never changes generated trading behavior.
            reference_specs = tuple(
                spec
                for _role, spec in evidence_runner.reference_specs(
                    demo_request.parent_spec
                )
            )
            print(f"optimization continuation: {args.continue_result}", flush=True)
        elif args.evidence_input is not None:
            reference_specs = tuple(
                spec
                for _role, spec in evidence_runner.reference_specs(
                    demo_request.parent_spec
                )
            )
            evidence = TypeAdapter(tuple[BacktestResult, ...]).validate_python(
                json.loads(args.evidence_input.read_text(encoding="utf-8"))
            )
            if len(evidence) != 5 or any(
                result.provider != "local_lean_worker_v1.1.3" for result in evidence
            ):
                raise ValueError(
                    "reused evidence must contain five Local LEAN Worker results"
                )
            print(f"validation evidence: reused {args.evidence_input}", flush=True)
        else:
            reference_specs = tuple(
                spec
                for _role, spec in evidence_runner.reference_specs(
                    demo_request.parent_spec
                )
            )
            evidence = evidence_runner.run(demo_request.parent_spec)
        request = demo_request.model_copy(
            update={"evidence": evidence, "reference_specs": reference_specs}
        )
        args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_output.write_text(
            json.dumps(
                [result.model_dump(mode="json") for result in evidence],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        backtest_provider = MockBacktestProvider()
        lean_environment = build_demo_environment()
        request = build_demo_request()

    orchestrator = OptimisationOrchestrator(
        designer=LLMStrategyDesigner(client),
        code_risk_agent=LLMCodeRiskAgent(client),
        backtest_provider=backtest_provider,
        analysis_agent=LLMPostBacktestAnalysisAgent(client),
        lean_environment=lean_environment,
        audit_sink=trace.record_audit,
    )
    result = None
    run_error = None
    try:
        result = orchestrator.run(
            request,
            initial_result=initial_result,
            routes=(tuple(args.continue_routes) if initial_result is not None else None),
        )
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        trace.write_markdown(args.trace_output, result=result, run_error=run_error)

    assert result is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "optimization_id": result.optimization_id,
                "status": result.status,
                "selected_strategy_id": result.selection.selected_strategy_id,
                "candidate_states": {
                    candidate.candidate_type: candidate.state
                    for candidate in result.candidates
                },
                "output": str(args.output),
                "backtest_mode": args.backtest_provider,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
