#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_CACHE = Path(tempfile.gettempdir()) / "alphaforge-matplotlib"
_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE))

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "architecture" / "AlphaForge_Agent_Orchestration.png"

BLUE = "C0"
AGENT_FILL = "#eaf2fb"
EXECUTION_FILL = "#f2f2f2"


def node(
    ax,
    x: float,
    y: float,
    text: str,
    *,
    width: float,
    height: float = 0.075,
    kind: str = "component",
    fontsize: float = 13,
) -> None:
    if kind == "agent":
        facecolor = AGENT_FILL
        boxstyle = "round,pad=0.012,rounding_size=0.018"
    elif kind == "execution":
        facecolor = EXECUTION_FILL
        boxstyle = "round,pad=0.012,rounding_size=0.035"
    else:
        facecolor = "white"
        boxstyle = "square,pad=0.012"

    ax.add_patch(
        FancyBboxPatch(
            (x - width / 2, y - height / 2),
            width,
            height,
            boxstyle=boxstyle,
            linewidth=1.5,
            edgecolor=BLUE,
            facecolor=facecolor,
        )
    )
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, weight="bold")


def arrow(
    ax,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = "0.35",
    linestyle: str = "-",
    connectionstyle: str = "arc3",
    linewidth: float = 1.3,
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=13,
            linewidth=linewidth,
            color=color,
            linestyle=linestyle,
            connectionstyle=connectionstyle,
            shrinkA=0,
            shrinkB=0,
        )
    )


def main() -> None:
    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.suptitle("AlphaForge Agent Orchestration", fontsize=24, weight="bold", y=0.965)
    ax.set_title("NUS Summer Workshop", fontsize=14, color="0.4", pad=14)

    # Input and shared evidence.
    node(ax, 0.30, 0.85, "Strategy + Baselines", width=0.18, fontsize=14)
    node(ax, 0.60, 0.85, "Evidence Summary", width=0.18, fontsize=14)
    arrow(ax, (0.39, 0.85), (0.51, 0.85))

    # Three strategy designers run in parallel.
    designers = (
        (0.32, "Traditional\nDesigner"),
        (0.50, "ML\nDesigner"),
        (0.68, "Hybrid\nDesigner"),
    )
    for x, label in designers:
        node(ax, x, 0.68, label, width=0.14, kind="agent", fontsize=13)
        arrow(
            ax,
            (0.60, 0.85 - 0.0375),
            (x, 0.68 + 0.0375),
        )

    # A shared pipeline is executed independently for every design.
    pipeline_y = 0.46
    pipeline = (
        (0.09, "Spec\nBuilder", "component"),
        (0.255, "QC Code\nAgent", "agent"),
        (0.42, "Static\nCheck", "component"),
        (0.585, "Code Risk\nAgent", "agent"),
        (0.75, "LEAN Smoke\nTest", "execution"),
        (0.915, "Backtest", "execution"),
    )
    for x, label, kind in pipeline:
        node(ax, x, pipeline_y, label, width=0.125, kind=kind, fontsize=12.5)
    for left, right in zip(pipeline, pipeline[1:]):
        arrow(ax, (left[0] + 0.0625, pipeline_y), (right[0] - 0.0625, pipeline_y))

    # The three designer outputs feed the same per-candidate pipeline contract.
    bus_y = 0.58
    for x, _ in designers:
        ax.plot([x, x], [0.68 - 0.0375, bus_y], color="0.5", linewidth=1.1)
    ax.plot([0.09, 0.68], [bus_y, bus_y], color="0.5", linewidth=1.1)
    arrow(ax, (0.09, bus_y), (0.09, pipeline_y + 0.0375))

    # Repair is a small local loop around implementation checks.
    node(ax, 0.585, 0.295, "Repair Agent", width=0.15, kind="agent", fontsize=13)
    for source_x, target_x in ((0.42, 0.54), (0.585, 0.585), (0.75, 0.63)):
        arrow(
            ax,
            (source_x, pipeline_y - 0.0375),
            (target_x, 0.295 + 0.0375),
            color="0.55",
            linestyle="--",
            linewidth=1.0,
        )
    arrow(
        ax,
        (0.585 - 0.075, 0.295),
        (0.42, pipeline_y - 0.0375),
        color=BLUE,
        connectionstyle="arc3,rad=-0.25",
    )

    # All candidate results are considered together, then selected and returned.
    final_y = 0.12
    final = (
        (0.23, "Post-Backtest\nAnalysis Agent", "agent", 0.18),
        (0.50, "Candidate\nSelector", "component", 0.16),
        (0.77, "Result", "component", 0.16),
    )
    for x, label, kind, width in final:
        node(ax, x, final_y, label, width=width, kind=kind, fontsize=13.5)
    arrow(ax, (0.23 + 0.09, final_y), (0.50 - 0.08, final_y))
    arrow(ax, (0.50 + 0.08, final_y), (0.77 - 0.08, final_y))

    # Row transition from the final pipeline stage to post-backtest analysis.
    ax.plot([0.915, 0.915], [pipeline_y - 0.0375, 0.205], color="0.35", linewidth=1.3)
    ax.plot([0.915, 0.23], [0.205, 0.205], color="0.35", linewidth=1.3)
    arrow(ax, (0.23, 0.205), (0.23, final_y + 0.0375))

    fig.savefig(OUTPUT, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
