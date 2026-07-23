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

function installFetch(run = null) {
  global.fetch = vi.fn((url) => {
    if (url.endsWith("/catalog/universe")) return response(catalog);
    if (url.endsWith("/health")) return response({ status: "ok" });
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
});
