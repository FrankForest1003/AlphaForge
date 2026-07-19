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

BOX_WIDTH = 0.155
BOX_HEIGHT = 0.095
BLUE = "C0"


def add_box(ax, x: float, y: float, title: str, detail: str = "") -> None:
    left = x - BOX_WIDTH / 2
    bottom = y - BOX_HEIGHT / 2
    box = FancyBboxPatch(
        (left, bottom),
        BOX_WIDTH,
        BOX_HEIGHT,
        boxstyle="round,pad=0.012,rounding_size=0.012",
        linewidth=1.4,
        edgecolor=BLUE,
        facecolor="white",
    )
    ax.add_patch(box)
    ax.text(x, y + 0.014, title, ha="center", va="center", fontsize=10.5, weight="bold")
    if detail:
        ax.text(x, y - 0.022, detail, ha="center", va="center", fontsize=8.3, color="0.35")


def arrow(ax, start: tuple[float, float], end: tuple[float, float], **kwargs) -> None:
    options = {
        "arrowstyle": "-|>",
        "mutation_scale": 12,
        "linewidth": 1.25,
        "color": "0.35",
        "shrinkA": 0,
        "shrinkB": 0,
    }
    options.update(kwargs)
    ax.add_patch(FancyArrowPatch(start, end, **options))


def main() -> None:
    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.suptitle("AlphaForge Agent Orchestration", fontsize=22, weight="bold", y=0.965)
    ax.set_title("NUS Summer Workshop", fontsize=13, color="0.35", pad=16)

    # Row 1: design, left to right.
    row1 = [
        (0.10, "Normalized Evidence", "Parent + four baselines"),
        (0.29, "Evidence Summarizer", "Metrics + run IDs"),
        (0.48, "Strategy Designers", "Traditional · ML · Hybrid"),
        (0.67, "CandidateDesign", "Strict schema"),
        (0.86, "SpecBuilder + Validation", "Immutable fields + diff"),
    ]
    for x, title, detail in row1:
        add_box(ax, x, 0.78, title, detail)
    for left, right in zip(row1, row1[1:]):
        arrow(ax, (left[0] + BOX_WIDTH / 2, 0.78), (right[0] - BOX_WIDTH / 2, 0.78))

    # Row 2: implementation and execution, right to left.
    row2 = [
        (0.86, "QC Code Agent", "main.py + digests"),
        (0.67, "Static Code Validation", "AST + API allowlist"),
        (0.48, "Code Risk Agent", "No backtest data"),
        (0.29, "LEAN Smoke Test", "Compile + minimal run"),
        (0.10, "Full Backtest", "Normalized result"),
    ]
    for x, title, detail in row2:
        add_box(ax, x, 0.50, title, detail)
    arrow(ax, (0.86, 0.78 - BOX_HEIGHT / 2), (0.86, 0.50 + BOX_HEIGHT / 2))
    for right, left in zip(row2, row2[1:]):
        arrow(ax, (right[0] - BOX_WIDTH / 2, 0.50), (left[0] + BOX_WIDTH / 2, 0.50))

    # Explicit pre-backtest boundary: Code Risk must approve before smoke testing.
    ax.plot([0.385, 0.385], [0.425, 0.575], linestyle="--", linewidth=1.1, color="0.5")
    ax.text(
        0.385,
        0.595,
        "PRE-BACKTEST SAFETY GATE",
        ha="center",
        va="bottom",
        fontsize=8.5,
        color="0.35",
    )

    # Repair is local to code validation, code risk and smoke failures.
    add_box(ax, 0.48, 0.32, "Repair Agent", "Implementation fixes only")
    failure_style = {"linestyle": "--", "color": "0.5", "linewidth": 1.0}
    arrow(ax, (0.67, 0.50 - BOX_HEIGHT / 2), (0.54, 0.32 + BOX_HEIGHT / 2), **failure_style)
    arrow(ax, (0.48, 0.50 - BOX_HEIGHT / 2), (0.48, 0.32 + BOX_HEIGHT / 2), **failure_style)
    arrow(ax, (0.29, 0.50 - BOX_HEIGHT / 2), (0.42, 0.32 + BOX_HEIGHT / 2), **failure_style)
    arrow(
        ax,
        (0.48 + BOX_WIDTH / 2, 0.32),
        (0.67, 0.50 - BOX_HEIGHT / 2),
        connectionstyle="arc3,rad=-0.28",
        color=BLUE,
    )
    ax.text(0.61, 0.355, "re-validate", fontsize=8.3, color=BLUE, ha="center")

    # Row 3: one analysis call followed by deterministic selection.
    row3 = [
        (0.18, "Unified Post-Backtest\nAnalysis", "One call · all route outcomes"),
        (0.50, "Deterministic Selector", "Hard eligibility rules"),
        (0.82, "OptimizationResult", "Selection + audit trail"),
    ]
    for x, title, detail in row3:
        add_box(ax, x, 0.13, title, detail)
    arrow(ax, (0.10, 0.50 - BOX_HEIGHT / 2), (0.18, 0.13 + BOX_HEIGHT / 2), connectionstyle="arc3,rad=0.12")
    for left, right in zip(row3, row3[1:]):
        arrow(ax, (left[0] + BOX_WIDTH / 2, 0.13), (right[0] - BOX_WIDTH / 2, 0.13))

    ax.text(0.10, 0.875, "DESIGN", fontsize=10, weight="bold", color="0.45")
    ax.text(0.10, 0.595, "CODE & EXECUTION", fontsize=10, weight="bold", color="0.45")
    ax.text(0.10, 0.225, "ANALYSIS & SELECTION", fontsize=10, weight="bold", color="0.45")

    fig.savefig(OUTPUT, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
