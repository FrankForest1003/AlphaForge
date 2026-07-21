#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from alphaforge.agents.context import ContextAssembler


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "agent"
ZH_PROMPTS = ASSETS / "prompts" / "zh-CN"
OUTPUT = ROOT / "docs" / "context" / "CURRENT_AGENT_CONTEXT.md"


AGENTS = (
    ("Traditional Strategy Designer", "strategy_designer", "traditional"),
    ("ML Strategy Designer", "strategy_designer", "ml"),
    ("Hybrid Strategy Designer", "strategy_designer", "hybrid"),
    ("Traditional Code Risk Agent", "code_risk", "traditional"),
    ("ML Code Risk Agent", "code_risk", "ml"),
    ("Hybrid Code Risk Agent", "code_risk", "hybrid"),
    ("Post-Backtest Analysis Agent", "post_backtest_analysis", None),
)


def main() -> None:
    assembler = ContextAssembler()
    lines = [
        "# Current Agent Context — Prompt v2 English/Chinese",
        "",
        "本文逐章展示每个模型调用实际使用的完整英文 System message，以及不发送给模型的完整中文译文。",
        "每章均为独立全文；运行时不拼接共享合同、代码内指令或隐藏结尾。哈希元数据只用于审计。",
        "",
    ]
    for number, (label, role, route) in enumerate(AGENTS, 1):
        bundle = assembler.build(
            agent_role=role,
            candidate_type=route,
            template_version=f"{route}_v1" if route and role == "code_risk" else None,
        )
        english = bundle.render()
        chinese = (ZH_PROMPTS / f"{bundle.prompt_id}.md").read_text(encoding="utf-8")
        lines.extend(
            [
                f"## {number}. {label}",
                "",
                f"- Prompt ID: `{bundle.prompt_id}`",
                f"- Bundle version: `{bundle.bundle_version}`",
                f"- SHA-256: `{bundle.bundle_sha256}`",
                f"- Characters: `{bundle.character_count}`",
                "",
                "### Actual English System message",
                "",
                "~~~~text",
                english.rstrip(),
                "~~~~",
                "",
                "### 完整中文译文（不发送给模型）",
                "",
                "~~~~text",
                chinese.rstrip(),
                "~~~~",
                "",
            ]
        )
    OUTPUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
