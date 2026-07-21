from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from alphaforge.agents.context import ContextAssembler


HEADINGS = tuple(
    f"## {index}. {title}"
    for index, title in enumerate(
        (
            "Identity",
            "Mission and success criteria",
            "Inputs you receive",
            "Decisions you own",
            "Decisions you do not own",
            "Domain and route rules",
            "Required working procedure",
            "Output contract",
            "Failure and refusal behavior",
            "Final self-check",
        ),
        1,
    )
)


def all_bundles():
    assembler = ContextAssembler()
    for role in ("strategy_designer", "code_risk"):
        for route in ("traditional", "ml", "hybrid"):
            yield assembler.build(
                agent_role=role,
                candidate_type=route,
                template_version=f"{route}_v1" if role == "code_risk" else None,
            )
    yield assembler.build(agent_role="post_backtest_analysis")


def test_exactly_seven_physical_prompts_are_registered() -> None:
    bundles = tuple(all_bundles())
    assert len(bundles) == 7
    assert len({bundle.prompt_id for bundle in bundles}) == 7
    assert all(bundle.bundle_version == "agent_context_v2" for bundle in bundles)
    assert all(len(bundle.sections) == 1 for bundle in bundles)


def test_bundle_is_exact_prompt_file_without_hidden_text() -> None:
    bundle = ContextAssembler().build(
        agent_role="code_risk", candidate_type="ml", template_version="ml_v1"
    )
    prompt_path = (
        Path(__file__).parents[2]
        / "agent"
        / bundle.source_paths[0]
    )
    raw = prompt_path.read_bytes()
    assert bundle.render().encode("utf-8") == raw
    assert bundle.bundle_sha256 == hashlib.sha256(raw).hexdigest()
    assert bundle.character_count == len(raw.decode("utf-8"))
    assert bundle.source_paths == ("prompts/en/code_risk_ml_v2.md",)


def test_prompt_inventory_has_required_identity_and_ten_sections() -> None:
    for bundle in all_bundles():
        prompt = bundle.render()
        assert prompt.startswith("You are ")
        assert all(prompt.count(heading) == 1 for heading in HEADINGS)
        assert "An Agent" not in prompt
        assert "The Agent" not in prompt
        assert ".env" not in prompt
        assert "API_KEY" not in prompt


@pytest.mark.parametrize("route", ["traditional", "ml", "hybrid"])
def test_designer_prompts_do_not_describe_downstream_work(route: str) -> None:
    prompt = ContextAssembler().build(
        agent_role="strategy_designer", candidate_type=route
    ).render().lower()
    for forbidden in (
        "code risk",
        "repair agent",
        "smoke test",
        "candidateselector",
        "code template",
        "downstream role",
    ):
        assert forbidden not in prompt


@pytest.mark.parametrize("route", ["traditional", "ml", "hybrid"])
def test_risk_prompt_has_route_checklist_without_result_payload(route: str) -> None:
    prompt = ContextAssembler().build(
        agent_role="code_risk", candidate_type=route, template_version=f"{route}_v1"
    ).render()
    assert "receive no returns, portfolio metrics, or backtest result" in prompt
    assert "BacktestResult" not in prompt
    assert "code_location" in prompt
    assert "required_correction" in prompt
    assert "request a model to edit source" in prompt


@pytest.mark.parametrize("route", ["ml", "hybrid"])
def test_ml_risk_prompt_requires_realized_sample_proof_for_leakage(route: str) -> None:
    prompt = ContextAssembler().build(
        agent_role="code_risk", candidate_type=route, template_version=f"{route}_v1"
    ).render()
    assert "A negative shift is not by itself" in prompt
    assert "concrete retained" in prompt
    assert "dropna" in prompt
    assert "NaN" in prompt


def test_analysis_prompt_is_evidence_only() -> None:
    prompt = ContextAssembler().build(agent_role="post_backtest_analysis").render().lower()
    assert "mock" in prompt
    assert "simulated" in prompt
    assert "seven metrics" in prompt
    assert "reproducible historical backtest" in prompt
    assert "it is not live trading" in prompt
    for forbidden in ("generated code", "code template", "repair agent"):
        assert forbidden not in prompt


def test_removed_code_writing_roles_are_rejected() -> None:
    assembler = ContextAssembler()
    with pytest.raises(ValueError):
        assembler.build(agent_role="qc_code", candidate_type="ml")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        assembler.build(agent_role="repair", candidate_type="ml")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        assembler.build(agent_role="post_backtest_analysis", candidate_type="ml")


def test_chinese_translations_match_runtime_prompt_inventory() -> None:
    root = Path(__file__).parents[2]
    prompt_root = root / "agent" / "prompts"
    english_files = sorted((prompt_root / "en").glob("*.md"))
    chinese_files = sorted((prompt_root / "zh-CN").glob("*.md"))
    assert [path.name for path in english_files] == [path.name for path in chinese_files]
    assert len(chinese_files) == 7
    for path in chinese_files:
        content = path.read_text(encoding="utf-8")
        assert content.startswith("你是")
        assert all(f"## {index}." in content for index in range(1, 11))
        assert "同上" not in content


def test_expanded_review_contains_every_full_bilingual_prompt() -> None:
    root = Path(__file__).parents[2]
    expanded = (root / "docs" / "context" / "CURRENT_AGENT_CONTEXT.md").read_text(
        encoding="utf-8"
    )
    assert expanded.count("### Actual English System message") == 7
    assert expanded.count("### 完整中文译文（不发送给模型）") == 7
    assert "同上" not in expanded
    for bundle in all_bundles():
        chinese_path = (
            root
            / "agent"
            / "prompts"
            / "zh-CN"
            / f"{bundle.prompt_id}.md"
        )
        assert bundle.render().rstrip() in expanded
        assert chinese_path.read_text(encoding="utf-8").rstrip() in expanded
