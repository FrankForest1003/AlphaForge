import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App, { HUMAN_CODE_STARTER } from "./App";

const catalog = {
  tradable_symbols: [
    { display_ticker: "MSFT", sector: "Information Technology" },
    { display_ticker: "AAPL", sector: "Information Technology" },
    { display_ticker: "NVDA", sector: "Information Technology" },
    { display_ticker: "GOOGL", sector: "Communication Services" },
    { display_ticker: "AMZN", sector: "Consumer Discretionary" },
  ],
  benchmarks: ["SPY"],
  default_symbols: ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
};

function response(payload, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) });
}

function installFetch(run = null) {
  global.fetch = vi.fn((url) => {
    if (url.endsWith("/catalog/universe")) return response(catalog);
    if (url.endsWith("/health")) return response({ status: "ok" });
    if (url.endsWith("/forge-history")) return response([]);
    if (url.includes("/forge-runs/") && run) return response(run);
    return response({ detail: "Not Found" }, false);
  });
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  global.ResizeObserver = class ResizeObserver {
    constructor(callback) { this.callback = callback; }
    observe(target) {
      this.callback([{ target, contentRect: { width: 800, height: 320 } }]);
    }
    unobserve() {}
    disconnect() {}
  };
  installFetch();
});

afterEach(() => vi.restoreAllMocks());

function parameterRun() {
  const spec = {
    schema_version: "template-v1",
    strategy_name: "Transparent Risk Rank",
    track: "Traditional",
    thesis: "Momentum and volatility ranks may improve risk adjusted returns.",
    signal: { components: [] },
    selection: { top_k: 5 },
    portfolio: { weighting: "inverse_volatility" },
  };
  const iteration = {
    iteration: 1,
    worker_run_id: "worker-1",
    strategy_spec: spec,
    summary: {
      cagr: 0.12,
      sharpe_ratio: 1.1,
      maximum_drawdown: 0.18,
      end_equity: 120000,
    },
    behavior_evidence: {},
    critique: {
      diagnosis: "Risk-adjusted return is competitive with the public reference.",
      recommended_changes: [
        {
          field: "portfolio.gross_exposure",
          direction: "decrease",
          reason: "Test whether lower exposure reduces drawdown.",
        },
      ],
      overfitting_warning: "One historical improvement is not future evidence.",
    },
  };
  return {
    run_id: "forge-test",
    state: "completed",
    settings: {
      symbols: catalog.default_symbols,
      initial_cash: 100000,
      benchmark: "SPY",
    },
    baselines: [1, 2, 3, 4].map((index) => ({
      name: `Baseline ${index}`,
      family: "Traditional",
      state: "completed",
      summary: {},
    })),
    human: { state: "completed", source_code: "PRIVATE HUMAN SOURCE", summary: {} },
    candidates: [
      {
        track: "Traditional",
        state: "accepted",
        source_code: "class UserStrategy: pass",
        design: {
          reference_baselines: ["Momentum Rank"],
          improvement_hypothesis: "Volatility weighting may reduce drawdown.",
          differentiation: ["inverse volatility weights"],
          expected_tradeoff: "May lag concentrated rallies.",
        },
        strategy_spec: spec,
        iteration_count: 1,
        best_iteration: 1,
        iterations: [iteration],
        critique_history: [{ iteration: 1, report: iteration.critique }],
        summary: iteration.summary,
        worker_run_id: "worker-1",
        usage: { total_tokens: 500 },
      },
    ],
  };
}

describe("AlphaForge Studio", () => {
  it("opens the builder and provides a complete Human code starter", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Create a Backtest" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Complete Python Code/i }));
    expect(screen.getByLabelText("Complete Strategy Source")).toHaveValue(HUMAN_CODE_STARTER);
  });

  it("shows the parameter-template AI workflow without Human leakage", async () => {
    const run = parameterRun();
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });
    fireEvent.click(screen.getByRole("button", { name: /AI Forge/i }));

    expect(screen.getByRole("heading", { name: "User Strategy Hidden From AI" })).toBeInTheDocument();
    expect(screen.getByText("Transparent Risk Rank")).toBeInTheDocument();
    expect(screen.getByText(/Schema-valid parameters compiled/i)).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE HUMAN SOURCE")).not.toBeInTheDocument();
  });

  it("shows every Critic iteration and identifies the retained trial", async () => {
    const run = parameterRun();
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });

    expect(screen.getAllByText("Iteration 1").length).toBeGreaterThan(0);
    expect(screen.getByText("Best retained")).toBeInTheDocument();
    expect(screen.getByText("Performance Critic")).toBeInTheDocument();
    expect(screen.getByText(/portfolio.gross_exposure/)).toBeInTheDocument();
  });
});
