import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App, { HUMAN_CODE_STARTER } from "./App";

const catalog = {
  tradable_symbols: [
    { display_ticker: "MSFT", sector: "Information Technology" },
    { display_ticker: "AAPL", sector: "Information Technology" },
  ],
  benchmarks: ["SPY"],
  default_symbols: ["MSFT"],
};

function response(payload, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(payload),
  });
}

function installFetch(run = null, history = []) {
  global.fetch = vi.fn((url) => {
    if (url.endsWith("/catalog/universe")) return response(catalog);
    if (url.endsWith("/health")) return response({ status: "ok" });
    if (url.endsWith("/forge-history")) return response(history);
    if (url.includes("/forge-runs/") && run) return response(run);
    return response({ detail: "Not Found" }, false, 404);
  });
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  global.ResizeObserver = class ResizeObserver {
    constructor(callback) {
      this.callback = callback;
    }
    observe(target) {
      this.callback([{ target, contentRect: { width: 800, height: 320 } }]);
    }
    unobserve() {}
    disconnect() {}
  };
  installFetch();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AlphaForge Studio", () => {
  it("opens on the backtest builder without internal architecture copy", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Create a Backtest" })).toBeInTheDocument();
    expect(screen.getByText("Human Strategy")).toBeInTheDocument();
    expect(screen.queryByText(/parallel Designers/i)).not.toBeInTheDocument();
  });

  it("provides a complete Human strategy base template", async () => {
    render(<App />);
    await screen.findByText("Stock Candidate Pool");
    fireEvent.click(screen.getByRole("button", { name: /Complete Python Code/i }));
    const editor = screen.getByLabelText("Complete Strategy Source");
    expect(editor).toHaveValue(HUMAN_CODE_STARTER);
    expect(editor.value).toContain("class UserStrategy");
    expect(editor.value).toContain("def initialize(self)");
    expect(editor.value).toContain("self.set_holdings(");
    expect(editor.value).not.toContain("af_rebalance_to_weights");
  });

  it("shows guided strategy controls with readable labels", async () => {
    render(<App />);
    expect(await screen.findByText("Strategy Preview")).toBeInTheDocument();
    expect(screen.getByText("Lookback Period")).toBeInTheDocument();
    expect(screen.getByText("Rebalance Schedule")).toBeInTheDocument();
    expect(screen.getByText("Number Of Holdings")).toBeInTheDocument();
  });

  it("uses consistent result labels and categories", async () => {
    const run = {
      run_id: "forge-test",
      state: "completed",
      settings: { symbols: ["MSFT"], initial_cash: 100000, benchmark: "SPY" },
      baselines: [
        { name: "Momentum Baseline", family: "Traditional", state: "completed", summary: { cagr: 0.1, sharpe_ratio: 1.1, maximum_drawdown: 0.12, end_equity: 110000 } },
      ],
      human: { state: "completed", source_code: "class UserStrategy: pass", summary: { cagr: 0.08 } },
      candidates: [
        { track: "ML", state: "accepted", source_code: "class UserStrategy: pass", summary: { cagr: 0.12 }, repair_attempts: 1, acceptance_history: [] },
      ],
    };
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Strategy Comparison" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Maximum Drawdown" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Ending Equity" })).toBeInTheDocument();
    expect(screen.getAllByText("Generated Strategy")).not.toHaveLength(0);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/v1/forge-runs/forge-test", expect.anything()));
  });

  it("shows the AI information boundary and deterministic preflight evidence", async () => {
    const run = {
      run_id: "forge-test",
      state: "running",
      settings: { symbols: ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"] },
      baselines: [1, 2, 3, 4].map((index) => ({
        name: `Baseline ${index}`,
        state: "completed",
        summary: {},
      })),
      human: { state: "completed", source_code: "PRIVATE HUMAN SOURCE" },
      candidates: [
        {
          track: "ML",
          state: "running",
          source_code: "class UserStrategy: pass",
          design: {
            strategy_name: "Stable ML Ranker",
            thesis: "Rank stocks using time-ordered model forecasts.",
            signals: ["model prediction"],
            selection_rule: "Select the top two finite predictions.",
            strategy_spec: {
              signal_family: null,
              model_family: "gradient_boosting",
              rebalance_frequency: "monthly",
              lookback_days: 126,
              label_horizon_days: 21,
              top_k: 2,
              weighting: "equal",
            },
          },
          preflight: { status: "passed", diagnostics: [] },
          validation_history: [{ attempt: 0, status: "passed" }],
          repair_history: [],
          repair_attempts: 0,
          worker_run_id: "worker-1",
          usage: { total_tokens: 4200 },
        },
      ],
    };
    window.history.replaceState({}, "", "/?run_id=forge-test");
    installFetch(run);
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });
    fireEvent.click(screen.getByRole("button", { name: /AI Forge/i }));

    expect(
      screen.getByRole("heading", { name: "User Strategy Hidden From AI" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Stable ML Ranker")).toBeInTheDocument();
    expect(screen.getByText(/model family: gradient_boosting/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Deterministic source checks passed/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE HUMAN SOURCE")).not.toBeInTheDocument();
  });

  it("keeps educational content in a dedicated Learning workspace", async () => {
    const run = {
      run_id: "forge-learning",
      state: "completed",
      settings: { symbols: ["MSFT"], initial_cash: 100000, benchmark: "SPY" },
      baselines: [
        { name: "Momentum Rank", family: "Traditional", state: "completed", summary: {} },
      ],
      human: { state: "completed", summary: {} },
      candidates: [],
      battle_analysis: {
        education_summary: {
          best_strategy_analysis: {
            headline: "Why Human Strategy leads this round",
            why_better: ["Higher risk-adjusted score."],
            tradeoffs_and_boundaries: ["Historical evidence only."],
          },
          human_feedback: {
            strengths: ["Controlled drawdown."],
            improvements: ["Test a slower rebalance schedule."],
          },
          knowledge_card: {
            title: "Return is not risk-adjusted return",
            lesson: "Sharpe and drawdown describe the path.",
            question: "Was the extra return worth the risk?",
          },
          risk_disclaimer: "Backtests do not guarantee future returns.",
        },
        baseline_classroom: {},
      },
    };
    window.history.replaceState({}, "", "/?run_id=forge-learning");
    installFetch(run);
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });
    fireEvent.click(screen.getByRole("button", { name: "Learning" }));

    expect(await screen.findByRole("heading", { name: "Learning Review" })).toBeInTheDocument();
    expect(screen.getByText("Why Human Strategy leads this round")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Metrics answer different questions" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Four reference ideas, four different trade-offs" })).toBeInTheDocument();
  });

  it("keeps robustness testing in an optional dedicated workspace", async () => {
    const run = {
      run_id: "forge-robustness",
      state: "completed",
      settings: {
        symbols: ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        initial_cash: 100000,
        benchmark: "SPY",
      },
      baselines: [],
      human: { state: "completed", summary: { cagr: 0.1 } },
      candidates: [
        {
          track: "ML",
          state: "accepted",
          summary: { cagr: 0.12, sharpe_ratio: 1.0, maximum_drawdown: 0.2 },
        },
      ],
      robustness: null,
    };
    window.history.replaceState({}, "", "/?run_id=forge-robustness");
    installFetch(run);
    render(<App />);
    await screen.findByRole("heading", { name: "Strategy Results" });
    fireEvent.click(screen.getByRole("button", { name: "Robustness" }));

    expect(await screen.findByRole("heading", { name: "Robustness Lab" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Change assumptions, not strategy code" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Robustness Test/i })).toBeInTheDocument();
  });

  it("renders a five-round Human versus AI arena with revision meaning", async () => {
    const rounds = [
      {
        run_id: "forge-round-1",
        state: "completed",
        created_at: "2026-07-23T10:00:00Z",
        winner: { side: "ai", label: "AI · Hybrid", reason: "Higher Sharpe." },
        human: {
          state: "completed",
          summary: { sharpe_ratio: 0.9, cagr: 0.1, maximum_drawdown: 0.2, end_equity: 110000 },
        },
        candidates: [
          {
            track: "Hybrid",
            state: "accepted",
            summary: { sharpe_ratio: 1.1, cagr: 0.12, maximum_drawdown: 0.18, end_equity: 120000 },
            acceptance_history: [
              {
                attempt: 2,
                worker_run_id: "worker-round-1",
                summary: { sharpe_ratio: 1.1, cagr: 0.12, maximum_drawdown: 0.18, end_equity: 120000 },
                revision_effectiveness: {
                  kind: "evidence_only",
                  effective: true,
                  semantic_source_changed: true,
                  trading_behavior_changed: false,
                  result_changed: false,
                  resolved_checks: ["A2"],
                  note: "Audit evidence improved without changing trading results.",
                },
                report: {
                  decision: "accept",
                  checks: [],
                },
              },
            ],
          },
        ],
      },
    ];
    installFetch(null, rounds);
    render(<App />);
    await screen.findByRole("heading", { name: "Create a Backtest" });
    fireEvent.click(screen.getByRole("button", { name: /PK Arena/i }));

    expect(await screen.findByRole("heading", { name: /Human vs AI/i })).toBeInTheDocument();
    expect(screen.getByText("Round 1")).toBeInTheDocument();
    expect(screen.getAllByText("AI · Hybrid").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText(/Inspect all AI challengers/i));
    expect(screen.getByText("Evidence-only revision")).toBeInTheDocument();
    expect(screen.getByText(/Audit evidence improved/i)).toBeInTheDocument();
    expect(screen.getByText("Independent Acceptance Agent")).toBeInTheDocument();
    expect(screen.getByText(/Agent decision: accept/i)).toBeInTheDocument();
  });
});
