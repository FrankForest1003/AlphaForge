import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
const battle = {
  id: "battle-test",
  name: "Test Battle",
  state: "active",
  human_wins: 0,
  ai_wins: 0,
  round_count: 0,
  next_round: 1,
  can_start_round: true,
  rounds: [],
};

function response(payload, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) });
}

function installFetch(run = null) {
  global.fetch = vi.fn((url) => {
    if (url.endsWith("/catalog/universe")) return response(catalog);
    if (url.endsWith("/health")) return response({ status: "ok" });
    if (url.endsWith("/auth/me")) return response({ id: "user-test", username: "tester" });
    if (url.endsWith("/battles")) return response([battle]);
    if (url.endsWith("/battles/battle-test")) return response(battle);
    if (url.endsWith("/forge-history")) return response([]);
    if (url.includes("/forge-runs/") && run) return response(run);
    return response({ detail: "Not Found" }, false);
  });
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  window.localStorage.setItem("alphaforge_token", "test-token");
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

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

async function openBuilder() {
  await screen.findByRole("heading", { name: "Your strategy match history" });
  fireEvent.click(await screen.findByRole("button", { name: /^Test Battle/ }));
  await screen.findByText("How a round works");
  fireEvent.click(screen.getByRole("button", { name: "Prepare Round 1" }));
  await screen.findByRole("heading", { name: "Test Battle" });
}

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
      start_date: "2020-01-02",
      end_date: "2024-12-31",
      initial_cash: 100000,
      benchmark: "SPY",
      transaction_cost_bps: 10,
      slippage_bps: 5,
    },
    baselines: [1, 2, 3, 4].map((index) => ({
      name: `Baseline ${index}`,
      family: "Traditional",
      state: "completed",
      summary: {},
    })),
    human: { state: "completed", source_code: "class UserStrategy: pass  # PRIVATE HUMAN SOURCE", summary: {} },
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
    await openBuilder();
    fireEvent.click(screen.getByRole("button", { name: /Complete Python Code/i }));
    expect(screen.getByLabelText("Complete Strategy Source")).toHaveValue(HUMAN_CODE_STARTER);
    expect(document.querySelector(".python-editor .python-keyword")).toHaveTextContent("from");
  });

  it("offers a bounded advanced multi-factor Human template", async () => {
    render(<App />);
    await openBuilder();
    fireEvent.click(screen.getByRole("button", { name: /Advanced Multi-factor/i }));

    expect(screen.getByText("Portfolio Weighting")).toBeInTheDocument();
    expect(screen.getByText("Gross Exposure")).toBeInTheDocument();
    expect(screen.getByText("Market Regime Filter")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Momentum + Low Volatility" })).toBeInTheDocument();
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

  it("shows the frozen backtest contract on Strategy Results", async () => {
    const run = parameterRun();
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);

    render(<App />);

    await screen.findByRole("heading", { name: "Strategy Results" });
    expect(screen.getByRole("heading", { name: "This backtest used" })).toBeInTheDocument();
    expect(screen.getByText("2020-01-02")).toBeInTheDocument();
    expect(screen.getByText("2024-12-31")).toBeInTheDocument();
    expect(screen.getByText("10 bps fee · 5 bps slippage")).toBeInTheDocument();
    for (const symbol of catalog.default_symbols) {
      expect(screen.getByText(symbol)).toBeInTheDocument();
    }
  });

  it("refreshes the battle immediately so a running round is not shown as unplayed", async () => {
    const runningRun = {
      ...parameterRun(),
      run_id: "forge-running",
      state: "running",
      battle_id: "battle-test",
      round_number: 1,
      battle_analysis: null,
    };
    const runningBattle = {
      ...battle,
      round_count: 1,
      next_round: 2,
      can_start_round: false,
      rounds: [
        {
          round_number: 1,
          forge_run_id: "forge-running",
          state: "running",
          winner: null,
        },
      ],
    };
    window.history.replaceState({}, "", "/?run_id=forge-running");
    global.fetch = vi.fn((url) => {
      if (url.endsWith("/catalog/universe")) return response(catalog);
      if (url.endsWith("/health")) return response({ status: "ok" });
      if (url.endsWith("/auth/me")) return response({ id: "user-test", username: "tester" });
      if (url.endsWith("/battles")) return response([battle]);
      if (url.endsWith("/battles/battle-test")) return response(runningBattle);
      if (url.endsWith("/forge-runs/forge-running")) return response(runningRun);
      return response({ detail: "Not Found" }, false);
    });

    render(<App />);

    const roundButton = await screen.findByRole("button", {
      name: /R1 Running/i,
    });
    expect(roundButton).toBeEnabled();
    expect(screen.queryByRole("button", { name: /R1 Not played/i })).not.toBeInTheDocument();
  });

  it("shows every Critic iteration and identifies the retained trial", async () => {
    const run = parameterRun();
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });
    fireEvent.click(screen.getByRole("button", { name: /AI Forge/i }));

    expect(screen.getAllByText("Iteration 1").length).toBeGreaterThan(0);
    expect(screen.getByText("Best retained")).toBeInTheDocument();
    expect(screen.getByText("Performance Critic")).toBeInTheDocument();
    expect(screen.getByText(/Portfolio \/ Gross Exposure/)).toBeInTheDocument();
  });

  it("highlights and copies complete strategy source", async () => {
    const run = parameterRun();
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });
    fireEvent.click(screen.getByRole("button", { name: /Strategy Code/i }));

    expect(document.querySelector(".source-viewer .python-keyword")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Copy code/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("class UserStrategy: pass  # PRIVATE HUMAN SOURCE"));
    expect(screen.getByRole("button", { name: /Copied/i })).toBeInTheDocument();
  });
});
