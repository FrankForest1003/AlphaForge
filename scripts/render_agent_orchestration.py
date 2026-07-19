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
NODE_HEIGHT = 0.085


def node(
    ax,
    x: float,
    y: float,
    text: str,
    *,
    width: float,
    height: float = NODE_HEIGHT,
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


def legend_item(ax, x: float, y: float, label: str, kind: str) -> None:
    if kind == "agent":
        facecolor = AGENT_FILL
        boxstyle = "round,pad=0.004,rounding_size=0.006"
    elif kind == "execution":
        facecolor = EXECUTION_FILL
        boxstyle = "round,pad=0.004,rounding_size=0.012"
    else:
        facecolor = "white"
        boxstyle = "square,pad=0.004"
    ax.add_patch(
        FancyBboxPatch(
            (x, y - 0.014),
            0.028,
            0.028,
            boxstyle=boxstyle,
            linewidth=1.3,
            edgecolor=BLUE,
            facecolor=facecolor,
        )
    )
    ax.text(x + 0.038, y, label, ha="left", va="center", fontsize=11.5, color="0.25")


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
    fig.subplots_adjust(left=0.025, right=0.975, bottom=0.035, top=0.90)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.suptitle("AlphaForge Agent Orchestration", fontsize=27, weight="bold", y=0.965)
    legend_item(ax, 0.30, 0.945, "Agent", "agent")
    legend_item(ax, 0.45, 0.945, "Deterministic / Data", "component")
    legend_item(ax, 0.69, 0.945, "LEAN Execution", "execution")

    # Input and shared evidence.
    node(ax, 0.30, 0.84, "Strategy + Baselines", width=0.20, fontsize=16)
    node(ax, 0.60, 0.84, "Evidence Summary", width=0.20, fontsize=16)
    arrow(ax, (0.40, 0.84), (0.50, 0.84))

    # Three strategy designers run in parallel.
    designers = (
        (0.32, "Traditional\nDesigner"),
        (0.50, "ML\nDesigner"),
        (0.68, "Hybrid\nDesigner"),
    )
    for x, label in designers:
        node(ax, x, 0.67, label, width=0.15, kind="agent", fontsize=14.5)
        arrow(
            ax,
            (0.60, 0.84 - NODE_HEIGHT / 2),
            (x, 0.67 + NODE_HEIGHT / 2),
        )

    # A shared pipeline is executed independently for every design.
    pipeline_y = 0.44
    pipeline = (
        (0.09, "Spec\nBuilder", "component"),
        (0.255, "QC Code\nAgent", "agent"),
        (0.42, "Static\nCheck", "component"),
        (0.585, "Code Risk\nAgent", "agent"),
        (0.75, "LEAN Smoke\nTest", "execution"),
        (0.915, "Backtest", "execution"),
    )
    for x, label, kind in pipeline:
        node(ax, x, pipeline_y, label, width=0.135, kind=kind, fontsize=14)
    for left, right in zip(pipeline, pipeline[1:]):
        arrow(ax, (left[0] + 0.0675, pipeline_y), (right[0] - 0.0675, pipeline_y))

    # The three designer outputs feed the same per-candidate pipeline contract.
    bus_y = 0.555
    for x, _ in designers:
        ax.plot([x, x], [0.67 - NODE_HEIGHT / 2, bus_y], color="0.5", linewidth=1.1)
    ax.plot([0.09, 0.68], [bus_y, bus_y], color="0.5", linewidth=1.1)
    arrow(ax, (0.09, bus_y), (0.09, pipeline_y + NODE_HEIGHT / 2))

    # Repair is a small local loop around implementation checks.
    node(ax, 0.585, 0.265, "Repair Agent", width=0.165, kind="agent", fontsize=14.5)
    for source_x, target_x in ((0.42, 0.54), (0.585, 0.585), (0.75, 0.63)):
        arrow(
            ax,
            (source_x, pipeline_y - NODE_HEIGHT / 2),
            (target_x, 0.265 + NODE_HEIGHT / 2),
            color="0.55",
            linestyle="--",
            linewidth=1.0,
        )
    arrow(
        ax,
        (0.585 - 0.0825, 0.265),
        (0.42, pipeline_y - NODE_HEIGHT / 2),
        color=BLUE,
        connectionstyle="arc3,rad=-0.25",
    )

    # All candidate results are considered together, then selected and returned.
    final_y = 0.085
    final = (
        (0.23, "Post-Backtest\nAnalysis Agent", "agent", 0.20),
        (0.50, "Candidate\nSelector", "component", 0.18),
        (0.77, "Result", "component", 0.18),
    )
    for x, label, kind, width in final:
        node(ax, x, final_y, label, width=width, kind=kind, fontsize=15)
    arrow(ax, (0.23 + 0.10, final_y), (0.50 - 0.09, final_y))
    arrow(ax, (0.50 + 0.09, final_y), (0.77 - 0.09, final_y))

    # Row transition from the final pipeline stage to post-backtest analysis.
    ax.plot([0.915, 0.915], [pipeline_y - NODE_HEIGHT / 2, 0.17], color="0.35", linewidth=1.3)
    ax.plot([0.915, 0.23], [0.17, 0.17], color="0.35", linewidth=1.3)
    arrow(ax, (0.23, 0.17), (0.23, final_y + NODE_HEIGHT / 2))

    fig.savefig(OUTPUT, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
