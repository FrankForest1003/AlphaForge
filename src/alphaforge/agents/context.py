from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from alphaforge.schemas.strategy_spec import StrictModel

AgentRole = Literal[
    "strategy_designer",
    "code_risk",
    "post_backtest_analysis",
]
RouteType = Literal["traditional", "ml", "hybrid"]


class ContextSection(StrictModel):
    section_id: str
    title: str
    source_path: str
    source_version: str
    source_sha256: str
    content: str


class AgentContextBundle(StrictModel):
    bundle_id: str
    bundle_version: Literal["agent_context_v2"]
    prompt_id: str
    agent_role: AgentRole
    candidate_type: RouteType | None
    template_version: str | None
    sections: tuple[ContextSection, ...] = Field(min_length=1, max_length=1)
    bundle_sha256: str
    character_count: int = Field(ge=1)
    source_paths: tuple[str, ...] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def prompt_is_exactly_one_physical_source(self) -> "AgentContextBundle":
        section = self.sections[0]
        if section.section_id != self.prompt_id:
            raise ValueError("prompt_id must match the only context section")
        if self.source_paths != (section.source_path,):
            raise ValueError("source_paths must identify only the prompt file")
        if self.character_count != len(section.content):
            raise ValueError("character_count must describe the exact prompt text")
        if self.bundle_sha256 != section.source_sha256:
            raise ValueError("bundle digest must equal the exact prompt file digest")
        return self

    def render(self) -> str:
        """Return the English prompt bytes as text, without metadata or hidden instructions."""
        return self.sections[0].content


class ContextAssembler:
    """Select exactly one allowlisted, versioned English prompt for a model call."""

    BUNDLE_VERSION = "agent_context_v2"
    _ASSET_ROOT = Path(__file__).parents[3] / "agent"
    _PROMPT_ROOT = _ASSET_ROOT / "prompts" / "en"
    _PROMPTS: dict[tuple[AgentRole, RouteType | None], str] = {
        ("strategy_designer", "traditional"): "strategy_designer_traditional_v2",
        ("strategy_designer", "ml"): "strategy_designer_ml_v2",
        ("strategy_designer", "hybrid"): "strategy_designer_hybrid_v2",
        ("code_risk", "traditional"): "code_risk_traditional_v2",
        ("code_risk", "ml"): "code_risk_ml_v2",
        ("code_risk", "hybrid"): "code_risk_hybrid_v2",
        ("post_backtest_analysis", None): "post_backtest_analysis_v2",
    }

    def build(
        self,
        *,
        agent_role: AgentRole,
        candidate_type: RouteType | None = None,
        template_version: str | None = None,
    ) -> AgentContextBundle:
        key = (agent_role, candidate_type)
        prompt_id = self._PROMPTS.get(key)
        if prompt_id is None:
            if agent_role == "post_backtest_analysis":
                raise ValueError("post_backtest_analysis context does not accept candidate_type")
            raise ValueError(f"{agent_role} context requires a supported candidate_type")

        path = (self._PROMPT_ROOT / f"{prompt_id}.md").resolve()
        root = self._PROMPT_ROOT.resolve()
        if root not in path.parents:
            raise ValueError(f"prompt path escapes allowlisted root: {path}")
        content = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        relative = path.relative_to(self._ASSET_ROOT.resolve()).as_posix()
        section = ContextSection(
            section_id=prompt_id,
            title=prompt_id,
            source_path=relative,
            source_version="2.0",
            source_sha256=digest,
            content=content,
        )
        return AgentContextBundle(
            bundle_id=f"{prompt_id}:{self.BUNDLE_VERSION}",
            bundle_version=self.BUNDLE_VERSION,
            prompt_id=prompt_id,
            agent_role=agent_role,
            candidate_type=candidate_type,
            template_version=template_version,
            sections=(section,),
            bundle_sha256=digest,
            character_count=len(content),
            source_paths=(relative,),
        )
