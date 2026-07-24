import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Code2,
  FlaskConical,
  Gauge,
  History,
  Layers3,
  Lightbulb,
  Play,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Scale,
  Sparkles,
  TrendingUp,
  Trophy,
  UserRound,
  XCircle,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_ROOT = "/api/v1";
const MIN_STOCKS = 5;
const MAX_STOCKS = 30;
const TERMINAL_RUN_STATES = new Set(["completed", "failed"]);
const FINISHED_ITEM_STATES = new Set([
  "accepted",
  "rejected",
  "failed",
  "completed",
  "completed_with_data_gaps",
  "timeout",
]);

export const HUMAN_CODE_STARTER = `from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2020-01-02"))
        end = datetime.fromisoformat(self._parameter("end_date", "2024-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))

        fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        slippage_bps = float(self._parameter("slippage_bps", "5"))
        tickers = [
            item.strip().upper()
            for item in self._parameter("symbols", "MSFT,AAPL,NVDA").split(",")
            if item.strip()
        ]
        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security, fee_bps=fee_bps, slippage_bps=slippage_bps
            )
            self.symbols.append(self.af_track_symbol(security.symbol))

        benchmark_ticker = self._parameter("benchmark", "SPY").strip().upper()
        benchmark = self.add_equity(benchmark_ticker, Resolution.DAILY)
        self.af_configure_security(benchmark)
        self.af_use_security_benchmark(benchmark.symbol)

        self.schedule.on(
            self.date_rules.month_start(self.symbols[0]),
            self.time_rules.after_market_open(self.symbols[0], 30),
            self.rebalance,
        )

    def rebalance(self):
        weight = 0.95 / len(self.symbols)
        self.af_rebalance_to_weights(
            {symbol: weight for symbol in self.symbols},
            "Monthly equal weight",
        )

    def on_alpha_data(self, data):
        pass
`;

const STATUS_LABELS = {
  waiting: "Waiting",
  queued: "Queued",
  submitting: "Submitting",
  generating: "Generating",
  generated: "Generated",
  running: "Running",
  validating: "Under Review",
  repairing: "Revising",
  accepted: "Accepted",
  rejected: "Rejected",
  completed: "Completed",
  completed_with_data_gaps: "Completed With Data Gaps",
  timeout: "Timed Out",
  failed: "Failed",
};

const METRICS = {
  cagr: { label: "CAGR", format: "percent", color: "#2f7f73" },
  sharpe_ratio: { label: "Sharpe Ratio", format: "number", color: "#4263a5" },
  maximum_drawdown: {
    label: "Maximum Drawdown",
    format: "percent",
    color: "#c4664e",
  },
  end_equity: { label: "Ending Equity", format: "currency", color: "#a06b28" },
};

const CATEGORY_COLORS = {
  "Reference Strategy": "#70829b",
  "Human Strategy": "#a06b28",
  "Generated Strategy": "#2f7f73",
};

const CURVE_COLORS = [
  "#335c9b",
  "#70829b",
  "#8c6bb1",
  "#4f8f83",
  "#c18135",
  "#22796f",
  "#b45d48",
  "#5573b7",
];

const BASELINE_CLASSROOM = {
  "Momentum Rank": {
    principle: "Hold the stocks with the strongest medium-term relative performance.",
    lesson: "Trends can persist, but crowded leadership may reverse quickly.",
  },
  "Mean Reversion": {
    principle: "Buy recent laggards when short-term price moves appear stretched.",
    lesson: "Contrarian diversification helps only when weakness is temporary.",
  },
  "Gradient Boosting": {
    principle: "Combine lagged features with a nonlinear model to rank expected returns.",
    lesson: "Time-safe training and real prediction evidence matter more than model complexity.",
  },
  "Hybrid ML + Minimum Variance": {
    principle: "Blend forecasts with covariance-aware portfolio construction.",
    lesson: "Signal selection and risk allocation are separate design decisions.",
  },
};

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.message || `Request failed (${response.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function statusLabel(value) {
  if (!value) return "Waiting";
  return STATUS_LABELS[value] || String(value).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatTrack(track) {
  if (track === "ML") return "Machine Learning";
  return track || "Generated";
}

function chartLabel(name) {
  return String(name)
    .replace("Hybrid ML + Minimum Variance", "Hybrid Baseline")
    .replace("Machine Learning", "ML")
    .replace(" Strategy", "");
}

function formatMetric(value, kind) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  if (kind === "percent") return `${(number * 100).toFixed(2)}%`;
  if (kind === "currency") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(number);
  }
  return number.toFixed(3);
}

function formatNumber(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(value);
}

function strategyRows(run) {
  if (!run) return [];
  const scorecards = new Map(
    (run.battle_analysis?.judge?.scorecards || []).map((item) => [item.id, item]),
  );
  const rows = (run.baselines || []).map((item, index) => ({
    ...item,
    id: `baseline-${item.name}`,
    scoreId: `baseline-${index}`,
    strategy: item.name,
    category: "Reference Strategy",
    revisions: null,
    scorecard: scorecards.get(`baseline-${index}`),
  }));
  if (run.human) {
    rows.push({
      ...run.human,
      id: "human",
      scoreId: "human",
      strategy: "Human Strategy",
      category: "Human Strategy",
      revisions: null,
      scorecard: scorecards.get("human"),
    });
  }
  for (const item of run.candidates || []) {
    const scoreId = `ai-${String(item.track || "").toLowerCase()}`;
    rows.push({
      ...item,
      id: `generated-${item.track}`,
      scoreId,
      strategy: `${formatTrack(item.track)} Strategy`,
      category: "Generated Strategy",
      revisions: item.repair_attempts || 0,
      scorecard: scorecards.get(scoreId),
    });
  }
  return rows;
}

function curveDataset(rows, valueKey, benchmark, initialCash) {
  const byDate = new Map();
  const series = [];
  rows.forEach((row, index) => {
    const curve = row.analysis?.equity_curve || [];
    if (!curve.length) return;
    const key = row.id;
    series.push({
      key,
      label: chartLabel(row.strategy),
      color: CURVE_COLORS[index % CURVE_COLORS.length],
    });
    curve.forEach((point) => {
      const date = point.date;
      if (!date) return;
      if (!byDate.has(date)) byDate.set(date, { date });
      byDate.get(date)[key] = Number(point[valueKey]);
    });
  });

  const benchmarkCurve = rows.find((row) => row.analysis?.benchmark_curve?.length)
    ?.analysis?.benchmark_curve || [];
  if (benchmarkCurve.length && valueKey === "equity") {
    const key = "shared-benchmark";
    series.push({ key, label: `Benchmark · ${benchmark || "SPY"}`, color: "#9aa6b5", dashed: true });
    benchmarkCurve.forEach((point) => {
      if (!point.date) return;
      if (!byDate.has(point.date)) byDate.set(point.date, { date: point.date });
      byDate.get(point.date)[key] = Number(
        point.equity ?? Number(initialCash || 0) * Number(point.normalized_value || 1),
      );
    });
  }
  return {
    data: [...byDate.values()].sort((left, right) => left.date.localeCompare(right.date)),
    series,
  };
}

function bestAcceptedAi(round) {
  const accepted = (round?.candidates || []).filter(
    (item) => item.state === "accepted" && item.summary,
  );
  return accepted.sort((left, right) => {
    const leftSummary = left.summary || {};
    const rightSummary = right.summary || {};
    return (
      Number(rightSummary.sharpe_ratio ?? -Infinity)
      - Number(leftSummary.sharpe_ratio ?? -Infinity)
      || Number(rightSummary.cagr ?? -Infinity)
      - Number(leftSummary.cagr ?? -Infinity)
      || Number(leftSummary.maximum_drawdown ?? Infinity)
      - Number(rightSummary.maximum_drawdown ?? Infinity)
    );
  })[0] || null;
}

function setRunQuery(runId) {
  const url = new URL(window.location.href);
  if (runId) url.searchParams.set("run_id", runId);
  else url.searchParams.delete("run_id");
  window.history.replaceState({}, "", url);
}

function StatusChip({ state }) {
  const finished = FINISHED_ITEM_STATES.has(state);
  return (
    <span className={`status-chip status-${state || "waiting"}`}>
      <span className={finished ? "status-dot finished" : "status-dot"} />
      {statusLabel(state)}
    </span>
  );
}

function BrandMark() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <TrendingUp size={22} strokeWidth={2.4} />
    </div>
  );
}

function Sidebar({ view, onView, runId, onOpenRun, serviceStatus }) {
  const [lookup, setLookup] = useState(runId || "");
  useEffect(() => setLookup(runId || ""), [runId]);

  const submitLookup = (event) => {
    event.preventDefault();
    if (lookup.trim()) onOpenRun(lookup.trim());
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <BrandMark />
        <div>
          <strong>AlphaForge</strong>
          <span>Strategy Studio</span>
        </div>
      </div>

      <nav className="nav-list" aria-label="Workspace">
        <button className={view === "build" ? "active" : ""} onClick={() => onView("build")}>
          <Sparkles size={18} />
          Build
        </button>
        <button className={view === "forge" ? "active" : ""} onClick={() => onView("forge")}>
          <FlaskConical size={18} />
          AI Forge
        </button>
        <button className={view === "results" ? "active" : ""} onClick={() => onView("results")}>
          <BarChart3 size={18} />
          Results
        </button>
        <button className={view === "robustness" ? "active" : ""} onClick={() => onView("robustness")}>
          <Gauge size={18} />
          Robustness
        </button>
        <button className={view === "learning" ? "active" : ""} onClick={() => onView("learning")}>
          <BookOpen size={18} />
          Learning
        </button>
        <button className={view === "arena" ? "active" : ""} onClick={() => onView("arena")}>
          <Trophy size={18} />
          PK Arena
        </button>
        <button className={view === "code" ? "active" : ""} onClick={() => onView("code")}>
          <Code2 size={18} />
          Strategy Code
        </button>
      </nav>

      <div className="sidebar-spacer" />
      <div className="run-lookup">
        <label htmlFor="run-lookup">Open A Run</label>
        <form onSubmit={submitLookup}>
          <Search size={16} />
          <input
            id="run-lookup"
            value={lookup}
            onChange={(event) => setLookup(event.target.value)}
            placeholder="Run ID"
          />
          <button aria-label="Open Run" disabled={!lookup.trim()}>
            <ArrowRight size={16} />
          </button>
        </form>
      </div>
      <div className="service-state">
        <span className={`service-light ${serviceStatus}`} />
        <span>{serviceStatus === "online" ? "Services Available" : serviceStatus === "loading" ? "Checking Services" : "Services Unavailable"}</span>
      </div>
    </aside>
  );
}

function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="header-actions">{actions}</div> : null}
    </header>
  );
}

function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

function BuildWorkspace({ catalog, loadingCatalog, onCreated }) {
  const initialized = useRef(false);
  const [symbols, setSymbols] = useState([]);
  const [startDate, setStartDate] = useState("2020-01-02");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [initialCash, setInitialCash] = useState(100000);
  const [benchmark, setBenchmark] = useState("SPY");
  const [transactionCost, setTransactionCost] = useState(10);
  const [slippage, setSlippage] = useState(5);
  const [humanMode, setHumanMode] = useState("guided");
  const [signal, setSignal] = useState("momentum");
  const [lookback, setLookback] = useState(60);
  const [rebalance, setRebalance] = useState("monthly");
  const [holdings, setHoldings] = useState(2);
  const [sourceCode, setSourceCode] = useState(HUMAN_CODE_STARTER);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (catalog && !initialized.current) {
      initialized.current = true;
      setSymbols(catalog.default_symbols || []);
      setBenchmark((catalog.benchmarks || ["SPY"])[0] || "SPY");
    }
  }, [catalog]);

  const tradable = catalog?.tradable_symbols || [];
  const grouped = useMemo(() => {
    const groups = {};
    for (const item of tradable) {
      const sector = item.sector || "Other";
      if (!groups[sector]) groups[sector] = [];
      groups[sector].push(item);
    }
    return groups;
  }, [tradable]);

  const toggleSymbol = (ticker) => {
    setSymbols((current) =>
      current.includes(ticker)
        ? current.filter((item) => item !== ticker)
        : current.length < MAX_STOCKS
          ? [...current, ticker]
          : current,
    );
  };

  const valid =
    symbols.length >= MIN_STOCKS &&
    symbols.length <= MAX_STOCKS &&
    startDate < endDate &&
    (humanMode === "guided" || sourceCode.trim().length > 0);

  const submit = async () => {
    if (!valid || submitting) return;
    setSubmitting(true);
    setError("");
    const humanStrategy =
      humanMode === "guided"
        ? {
            mode: "guided",
            guided: {
              signal,
              lookback_days: Number(lookback),
              rebalance,
              holdings: Number(holdings),
            },
          }
        : { mode: "code", source_code: sourceCode };
    try {
      const created = await apiRequest("/forge-runs", {
        method: "POST",
        body: JSON.stringify({
          settings: {
            symbols,
            start_date: startDate,
            end_date: endDate,
            initial_cash: Number(initialCash),
            benchmark,
            transaction_cost_bps: Number(transactionCost),
            slippage_bps: Number(slippage),
          },
          human_strategy: humanStrategy,
        }),
      });
      onCreated(created);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="New Experiment"
        title="Create a Backtest"
        description="Choose one market setup, add your own strategy, and compare every result on equal terms."
      />

      <section className="step-card">
        <div className="step-heading">
          <span className="step-number">01</span>
            <div>
              <h2>Market Setup</h2>
              <p>Freeze one experiment contract shared by Human, AI, and all baselines.</p>
          </div>
          <div className="selection-count">{symbols.length} Selected</div>
        </div>

        <div className="market-layout">
          <div className="universe-panel">
            <div className="section-toolbar">
              <div>
                <h3>Stock Candidate Pool</h3>
                <p>Select 5–30 stocks. Strategies may choose a subset during each rebalance.</p>
              </div>
              <div className="text-actions">
                <button type="button" onClick={() => setSymbols(tradable.map((item) => item.display_ticker))}>
                  Select All
                </button>
                <button type="button" onClick={() => setSymbols([])}>Clear</button>
              </div>
            </div>
            {loadingCatalog ? (
              <div className="loading-block"><RefreshCw className="spin" size={20} /> Loading Stocks</div>
            ) : (
              <div className="sector-groups">
                {Object.entries(grouped).map(([sector, items]) => (
                  <div className="sector-group" key={sector}>
                    <h4>{sector}</h4>
                    <div className="ticker-grid">
                      {items.map((item) => {
                        const checked = symbols.includes(item.display_ticker);
                        return (
                          <button
                            type="button"
                            key={item.display_ticker}
                            className={`ticker-option ${checked ? "selected" : ""}`}
                            onClick={() => toggleSymbol(item.display_ticker)}
                            aria-pressed={checked}
                          >
                            <span>{item.display_ticker}</span>
                            <span className="checkbox-mark">{checked ? <Check size={13} /> : null}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="settings-panel">
            <div className="panel-title"><Settings2 size={18} /><h3>Backtest Settings</h3></div>
            <div className="two-fields">
              <Field label="Start Date"><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Field>
              <Field label="End Date"><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Field>
            </div>
            <Field label="Initial Cash"><div className="input-prefix"><span>$</span><input type="number" min="1000" step="10000" value={initialCash} onChange={(event) => setInitialCash(event.target.value)} /></div></Field>
            <Field label="Benchmark"><select value={benchmark} onChange={(event) => setBenchmark(event.target.value)}>{(catalog?.benchmarks || ["SPY"]).map((item) => <option key={item}>{item}</option>)}</select></Field>
            <div className="two-fields">
              <Field label="Transaction Cost" hint="Basis Points"><input type="number" min="0" step="1" value={transactionCost} onChange={(event) => setTransactionCost(event.target.value)} /></Field>
              <Field label="Slippage" hint="Basis Points"><input type="number" min="0" step="1" value={slippage} onChange={(event) => setSlippage(event.target.value)} /></Field>
            </div>
          </div>
        </div>
      </section>

      <section className="step-card">
        <div className="step-heading">
          <span className="step-number">02</span>
          <div>
            <h2>Human Strategy</h2>
            <p>Use a guided setup or submit one complete QuantConnect Python strategy.</p>
          </div>
        </div>

        <div className="mode-tabs" role="tablist" aria-label="Human Strategy Input">
          <button className={humanMode === "guided" ? "active" : ""} onClick={() => setHumanMode("guided")}>
            <FlaskConical size={17} /> Guided Setup
          </button>
          <button className={humanMode === "code" ? "active" : ""} onClick={() => setHumanMode("code")}>
            <Code2 size={17} /> Complete Python Code
          </button>
        </div>

        {humanMode === "guided" ? (
          <div className="guided-layout">
            <div className="guided-fields">
              <Field label="Signal">
                <select value={signal} onChange={(event) => setSignal(event.target.value)}>
                  <option value="momentum">Momentum</option>
                  <option value="mean_reversion">Mean Reversion</option>
                </select>
              </Field>
              <Field label="Lookback Period">
                <select value={lookback} onChange={(event) => setLookback(event.target.value)}>
                  <option value="20">20 Days</option><option value="60">60 Days</option><option value="120">120 Days</option>
                </select>
              </Field>
              <Field label="Rebalance Schedule">
                <select value={rebalance} onChange={(event) => setRebalance(event.target.value)}>
                  <option value="monthly">Monthly</option><option value="weekly">Weekly</option>
                </select>
              </Field>
              <Field label="Number Of Holdings">
                <select value={holdings} onChange={(event) => setHoldings(event.target.value)}>
                  <option value="1">1 Stock</option><option value="2">2 Stocks</option><option value="3">3 Stocks</option>
                </select>
              </Field>
            </div>
            <div className="strategy-summary">
              <div className="summary-icon"><Sparkles size={20} /></div>
              <div>
                <span>Strategy Preview</span>
                <strong>{signal === "momentum" ? "Momentum" : "Mean Reversion"} Ranking</strong>
                <p>
                  Rank the selected pool using a {lookback}-day signal, hold {holdings} {Number(holdings) === 1 ? "stock" : "stocks"}, and rebalance {rebalance} at 95% gross exposure.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="code-input-panel">
            <div className="code-toolbar">
              <div>
                <h3>Complete Strategy Source</h3>
                <p>The file must define <code>UserStrategy</code>. Shared settings remain available as parameters.</p>
              </div>
              <button className="secondary-button" type="button" onClick={() => setSourceCode(HUMAN_CODE_STARTER)}>
                <RefreshCw size={15} /> Restore Base Template
              </button>
            </div>
            <textarea aria-label="Complete Strategy Source" spellCheck="false" value={sourceCode} onChange={(event) => setSourceCode(event.target.value)} />
          </div>
        )}
      </section>

      <section className="contract-notice">
        <div className="summary-icon"><ShieldCheck size={20} /></div>
        <div>
          <span>Experiment Contract</span>
          <strong>Shared settings become immutable when the Arena starts.</strong>
          <p>
            Human and AI strategies receive the same stocks, dates, cash, benchmark,
            costs, and slippage. The Human strategy remains hidden from AI generation.
          </p>
        </div>
      </section>

      <div className="launch-bar">
        <div>
          <strong>Ready To Start</strong>
          <span>{symbols.length ? `${symbols.length} stocks selected` : "Select 5–30 stocks"} · {humanMode === "guided" ? "Guided Setup" : "Complete Python Code"}</span>
          {symbols.length < MIN_STOCKS ? <span className="validation-message">Select at least {MIN_STOCKS} stocks to create a comparable experiment.</span> : null}
          {startDate >= endDate ? <span className="validation-message">The Start Date must be earlier than the End Date.</span> : null}
          {error ? <span className="validation-message">{error}</span> : null}
        </div>
        <button className="primary-button" disabled={!valid || submitting} onClick={submit}>
          {submitting ? <RefreshCw className="spin" size={18} /> : <Play size={18} fill="currentColor" />}
          {submitting ? "Freezing Contract" : "Freeze Contract & Start Arena"}
        </button>
      </div>
    </>
  );
}

function EmptyRun({ onBuild }) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><BarChart3 size={28} /></div>
      <h2>No Run Selected</h2>
      <p>Create a new backtest or open an existing Run ID from the navigation panel.</p>
      <button className="primary-button" onClick={onBuild}><Sparkles size={17} /> Create A Backtest</button>
    </div>
  );
}

function stageState(done, active) {
  if (done) return "completed";
  return active ? "running" : "waiting";
}

function AIForgeWorkspace({ run, onBuild }) {
  if (!run) {
    return (
      <>
        <PageHeader
          eyebrow="Independent AI Track"
          title="AI Forge"
          description="Inspect independent candidate design, validation, backtesting, and acceptance."
        />
        <EmptyRun onBuild={onBuild} />
      </>
    );
  }

  const candidates = run.candidates || [];
  const baselinesReady =
    (run.baselines || []).length === 4 &&
    run.baselines.every((item) => item.state === "completed");
  const designsReady =
    candidates.length === 3 && candidates.every((item) => Boolean(item.source_code));
  const preflightReady =
    candidates.length === 3 &&
    candidates.every((item) => item.preflight?.status === "passed");
  const workerStarted = candidates.some((item) => Boolean(item.worker_run_id));
  const reviewsFinished =
    candidates.length === 3 &&
    candidates.every((item) => ["accepted", "rejected", "failed"].includes(item.state));

  const stages = [
    {
      number: "01",
      title: "Public Evidence",
      copy: "Four baselines under the frozen contract",
      state: stageState(baselinesReady, !baselinesReady),
    },
    {
      number: "02",
      title: "Independent Design",
      copy: "Traditional, ML, and Hybrid plans",
      state: stageState(designsReady, baselinesReady),
    },
    {
      number: "03",
      title: "Static Validation",
      copy: "Syntax, capability, settings, and track checks",
      state: stageState(preflightReady, designsReady),
    },
    {
      number: "04",
      title: "LEAN Backtest",
      copy: "Real orders and behavior evidence",
      state: stageState(workerStarted && reviewsFinished, workerStarted),
    },
    {
      number: "05",
      title: "Acceptance",
      copy: "A1–A5 evidence review",
      state: stageState(reviewsFinished, workerStarted),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Independent AI Track"
        title="AI Forge"
        description={`Run ${run.run_id} · structured evidence only, no hidden chain-of-thought`}
      />

      <section className="information-boundary">
        <div className="boundary-icon"><ShieldCheck size={22} /></div>
        <div>
          <span>Information Boundary Active</span>
          <h2>User Strategy Hidden From AI</h2>
          <p>
            Designers receive only the frozen run settings, four public baseline
            results, and the AlphaForge capability contract. Human code, parameters,
            results, trades, and education feedback are excluded.
          </p>
        </div>
      </section>

      <section className="forge-stage-grid" aria-label="AI Forge stages">
        {stages.map((stage) => (
          <div className={`forge-stage stage-${stage.state}`} key={stage.number}>
            <div className="forge-stage-top">
              <span>{stage.number}</span>
              <StatusChip state={stage.state} />
            </div>
            <strong>{stage.title}</strong>
            <p>{stage.copy}</p>
          </div>
        ))}
      </section>

      <section className="forge-tracks">
        <div className="card-heading">
          <div>
            <span className="section-kicker">Candidate Lineages</span>
            <h2>Three Independent Tracks</h2>
          </div>
        </div>
        <div className="forge-track-grid">
          {candidates.map((candidate) => {
            const design = candidate.design || {};
            const preflight = candidate.preflight;
            const diagnostics = preflight?.diagnostics || [];
            const usage = candidate.usage || {};
            return (
              <article className="forge-track-card" key={candidate.track}>
                <div className="forge-track-header">
                  <div className="strategy-avatar"><Sparkles size={18} /></div>
                  <div>
                    <span>{formatTrack(candidate.track)} Candidate</span>
                    <h3>{design.strategy_name || "Design pending"}</h3>
                  </div>
                  <StatusChip state={candidate.state} />
                </div>

                <p className="forge-thesis">
                  {design.thesis || "The structured candidate design will appear after generation."}
                </p>
                {candidate.best_observed_attempt != null ? (
                  <div className="retained-attempt-note">
                    Showing source and metrics from runnable Review {Number(candidate.best_observed_attempt) + 1}; later repair attempts did not pass Acceptance.
                  </div>
                ) : null}

                {design.reference_baselines?.length ? (
                  <div className="baseline-improvement-plan">
                    <div><span>Public references</span><strong>{design.reference_baselines.join(" · ")}</strong></div>
                    <p><b>Hypothesis</b>{design.improvement_hypothesis}</p>
                    <p><b>What changes</b>{Array.isArray(design.differentiation) ? design.differentiation.join(" · ") : design.differentiation}</p>
                    <p><b>Expected trade-off</b>{design.expected_tradeoff}</p>
                  </div>
                ) : null}

                <div className="forge-evidence-row">
                  <div>
                    <span>Preflight</span>
                    <strong>{preflight ? statusLabel(preflight.status) : "Waiting"}</strong>
                  </div>
                  <div>
                    <span>LEAN Run</span>
                    <strong>{candidate.worker_run_id ? "Submitted" : "Waiting"}</strong>
                  </div>
                  <div>
                    <span>Repairs</span>
                    <strong>{candidate.repair_attempts || 0}</strong>
                  </div>
                  <div>
                    <span>Generation Retry</span>
                    <strong>{candidate.generation_retries || 0}</strong>
                  </div>
                  <div>
                    <span>Tokens</span>
                    <strong>{formatNumber(usage.total_tokens || 0)}</strong>
                  </div>
                </div>

                {design.signals?.length ? (
                  <div className="design-block">
                    <span>Decision Signals</span>
                    <div className="design-tags">
                      {design.signals.map((item) => <i key={item}>{item}</i>)}
                    </div>
                  </div>
                ) : null}

                {design.strategy_spec ? (
                  <div className="design-block">
                    <span>Bounded Strategy Spec</span>
                    <div className="design-tags">
                      {Object.entries(design.strategy_spec)
                        .filter(([, value]) => value !== null && value !== undefined)
                        .map(([key, value]) => (
                          <i key={key}>{key.replaceAll("_", " ")}: {String(value)}</i>
                        ))}
                    </div>
                  </div>
                ) : null}

                {design.selection_rule ? (
                  <div className="design-block">
                    <span>Selection Rule</span>
                    <p>{design.selection_rule}</p>
                  </div>
                ) : null}

                {diagnostics.length ? (
                  <div className="preflight-errors">
                    <strong>Static validation findings</strong>
                    <ul>
                      {diagnostics.map((item, index) => (
                        <li key={`${item.code}-${index}`}>
                          <code>{item.code}</code> {item.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : preflight?.status === "passed" ? (
                  <div className="preflight-pass">
                    <CheckCircle2 size={16} />
                    Deterministic source checks passed before LEAN submission.
                  </div>
                ) : null}

                {candidate.repair_history?.length ? (
                  <details className="repair-lineage">
                    <summary>
                      Repair lineage · {candidate.repair_history.length}
                      <ChevronDown size={16} />
                    </summary>
                    <div>
                      {candidate.repair_history.map((item) => (
                        <p key={`${item.attempt}-${item.trigger}`}>
                          <strong>R{item.attempt} · {item.classification}</strong>
                          <span>{item.first_interrupted_stage || item.trigger}</span>
                        </p>
                      ))}
                    </div>
                  </details>
                ) : null}

                {candidate.error ? <div className="inline-error">{candidate.error}</div> : null}
              </article>
            );
          })}
        </div>
      </section>
    </>
  );
}

function MetricChart({ rows }) {
  const [metricKey, setMetricKey] = useState("cagr");
  const metric = METRICS[metricKey];
  const data = rows
    .filter((row) => row.summary && row.summary[metricKey] !== undefined)
    .map((row) => ({
      name: chartLabel(row.strategy),
      value: Number(row.summary[metricKey]),
      category: row.category,
    }));

  return (
    <section className="chart-card">
      <div className="card-heading chart-heading">
        <div><span className="section-kicker">Performance View</span><h2>{metric.label}</h2></div>
        <div className="metric-switcher">
          {Object.entries(METRICS).map(([key, item]) => (
            <button key={key} className={metricKey === key ? "active" : ""} onClick={() => setMetricKey(key)}>{item.label}</button>
          ))}
        </div>
      </div>
      <div className="chart-area">
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 12, right: 16, left: 4, bottom: 12 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5eaf0" />
              <XAxis dataKey="name" tick={{ fill: "#66758b", fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
              <YAxis tick={{ fill: "#66758b", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(value) => formatMetric(value, metric.format)} width={72} />
              <Tooltip formatter={(value) => [formatMetric(value, metric.format), metric.label]} cursor={{ fill: "rgba(47, 127, 115, 0.06)" }} />
              <Bar dataKey="value" radius={[7, 7, 2, 2]} maxBarSize={58}>
                {data.map((entry) => <Cell key={entry.name} fill={CATEGORY_COLORS[entry.category] || metric.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="chart-empty"><Activity size={22} /><span>Results will appear when backtests complete.</span></div>
        )}
      </div>
      <div className="chart-legend">
        {Object.entries(CATEGORY_COLORS).map(([name, color]) => <span key={name}><i style={{ background: color }} />{name}</span>)}
      </div>
    </section>
  );
}

function PortfolioJourney({ rows, settings }) {
  const [view, setView] = useState("equity");
  const valueKey = view === "equity" ? "equity" : "drawdown";
  const { data, series } = curveDataset(
    rows,
    valueKey,
    settings?.benchmark,
    settings?.initial_cash,
  );
  return (
    <section className="chart-card journey-card">
      <div className="card-heading chart-heading">
        <div>
          <span className="section-kicker">Portfolio Journey</span>
          <h2>{view === "equity" ? "Total Portfolio Value" : "Underwater Drawdown"}</h2>
          <p className="card-subcopy">
            {view === "equity"
              ? "How one dollar of starting capital evolved through the shared test window."
              : "Distance below each strategy’s previous equity peak; closer to zero is better."}
          </p>
        </div>
        <div className="metric-switcher">
          <button className={view === "equity" ? "active" : ""} onClick={() => setView("equity")}>Total Assets</button>
          <button className={view === "drawdown" ? "active" : ""} onClick={() => setView("drawdown")}>Drawdown</button>
        </div>
      </div>
      <div className="journey-chart">
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 16, right: 22, left: 12, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5eaf0" />
              <XAxis dataKey="date" minTickGap={34} tick={{ fill: "#66758b", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis
                tick={{ fill: "#66758b", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={84}
                tickFormatter={(value) => formatMetric(value, view === "equity" ? "currency" : "percent")}
              />
              <Tooltip
                labelFormatter={(label) => `Date · ${label}`}
                formatter={(value, name) => [
                  formatMetric(value, view === "equity" ? "currency" : "percent"),
                  series.find((item) => item.key === name)?.label || name,
                ]}
              />
              <Legend formatter={(value) => series.find((item) => item.key === value)?.label || value} />
              {series.map((item) => (
                <Line
                  key={item.key}
                  type="monotone"
                  dataKey={item.key}
                  name={item.key}
                  stroke={item.color}
                  strokeWidth={item.dashed ? 1.7 : 2.2}
                  strokeDasharray={item.dashed ? "6 5" : undefined}
                  dot={false}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="chart-empty"><Activity size={22} /><span>Worker equity curves will appear after completed backtests.</span></div>
        )}
      </div>
    </section>
  );
}

function RiskCostTable({ rows }) {
  return (
    <section className="table-card">
      <div className="card-heading">
        <div>
          <span className="section-kicker">Risk &amp; Trading Cost</span>
          <h2>What the headline return leaves out</h2>
          <p className="card-subcopy">Derived from daily portfolio snapshots and actual filled order events.</p>
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Strategy</th><th>Total Return</th><th>Sortino</th><th>Annual Volatility</th>
              <th>Annual Turnover</th><th>Total Fees</th><th>Filled Orders</th><th>Max Gross</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const statistics = row.analysis?.statistics || {};
              const evidence = row.behavior_evidence || {};
              return (
                <tr key={`risk-${row.id}`}>
                  <td><strong>{row.strategy}</strong></td>
                  <td>{formatMetric(statistics.total_return, "percent")}</td>
                  <td>{formatMetric(statistics.sortino_ratio, "number")}</td>
                  <td>{formatMetric(statistics.annualized_volatility, "percent")}</td>
                  <td>{formatMetric(statistics.annualized_turnover, "percent")}</td>
                  <td>{formatMetric(statistics.total_fees, "currency")}</td>
                  <td>{formatNumber(evidence.filled_order_count ?? statistics.filled_event_count)}</td>
                  <td>{formatMetric(evidence.max_gross_exposure, "percent")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function JudgeBreakdown({ analysis }) {
  if (!analysis?.judge) return null;
  const verdict = analysis.verdict || {};
  const scorecards = (analysis.judge.scorecards || [])
    .filter((item) => item.owner === "human" || item.owner === "ai")
    .sort((left, right) => Number(right.score ?? -1) - Number(left.score ?? -1));
  return (
    <section className="judge-card">
      <div className="judge-verdict">
        <div className={`verdict-emblem verdict-${verdict.side || "none"}`}><Scale size={24} /></div>
        <div>
          <span className="section-kicker">Deterministic Battle Judge</span>
          <h2>{verdict.label || "Waiting for eligible results"}</h2>
          <p>{verdict.reason}</p>
        </div>
        {analysis.ai_champion ? (
          <div className="champion-callout">
            <span>AI Champion</span>
            <strong>{analysis.ai_champion.label}</strong>
            <small>{formatNumber(analysis.ai_champion.score)} / 100</small>
          </div>
        ) : null}
      </div>
      <div className="scorecard-grid">
        {scorecards.map((card) => (
          <article key={card.id} className={!card.eligible ? "scorecard-ineligible" : ""}>
            <div><strong>{card.label}</strong><span>{card.eligible ? `${formatNumber(card.score)} points` : "Ineligible"}</span></div>
            {card.eligible ? (
              <dl>
                <div><dt>Risk-adjusted</dt><dd>{formatNumber(card.components.risk_adjusted_return)}</dd></div>
                <div><dt>Drawdown</dt><dd>{formatNumber(card.components.drawdown_and_volatility)}</dd></div>
                <div><dt>Robustness</dt><dd>{formatNumber(card.components.robustness)}</dd></div>
                <div><dt>Cost</dt><dd>{formatNumber(card.components.cost_and_turnover)}</dd></div>
                <div><dt>Explainability</dt><dd>{formatNumber(card.components.explainability)}</dd></div>
              </dl>
            ) : <p>{card.eligibility_reasons?.join(" · ")}</p>}
          </article>
        ))}
      </div>
      <p className="judge-method">Public weights: 40% risk-adjusted return · 25% drawdown/volatility · 20% robustness · 10% cost/turnover · 5% explainability. Scores within two points are a draw.</p>
    </section>
  );
}

function LearningReview({ analysis }) {
  const education = analysis?.education_summary;
  if (!education) return null;
  const best = education.best_strategy_analysis || {};
  const feedback = education.human_feedback || {};
  const card = education.knowledge_card || {};
  return (
    <section className="learning-review">
      <div className="card-heading">
        <div><span className="section-kicker">Learning Review</span><h2>What to keep, question, and improve</h2></div>
      </div>
      <div className="learning-grid">
        <article className="learning-best">
          <Trophy size={21} />
          <div><span>Best strategy analysis</span><h3>{best.headline}</h3></div>
          <ul>{(best.why_better || []).map((item) => <li key={item}>{item}</li>)}</ul>
          <div className="tradeoff-note"><strong>Trade-offs and boundaries</strong>{(best.tradeoffs_and_boundaries || []).map((item) => <p key={item}>{item}</p>)}</div>
        </article>
        <article>
          <Lightbulb size={21} />
          <div><span>Your next round</span><h3>Specific improvement ideas</h3></div>
          {feedback.strengths?.length ? <div className="strength-list"><strong>Worth preserving</strong>{feedback.strengths.map((item) => <p key={item}>✓ {item}</p>)}</div> : null}
          <ol>{(feedback.improvements || []).map((item) => <li key={item}>{item}</li>)}</ol>
        </article>
        <article className="knowledge-card">
          <BookOpen size={21} />
          <div><span>Quant concept</span><h3>{card.title}</h3></div>
          <p>{card.lesson}</p>
          <blockquote>{card.question}</blockquote>
        </article>
      </div>
      <p className="education-disclaimer">{education.risk_disclaimer}</p>
    </section>
  );
}

function BaselineClassroom({ baselines, lessons }) {
  if (!baselines?.length) return null;
  return (
    <section className="classroom-card">
      <div className="card-heading">
        <div><span className="section-kicker">Baseline Classroom</span><h2>Four reference ideas, four different trade-offs</h2></div>
      </div>
      <div className="classroom-grid">
        {baselines.map((baseline) => {
          const lesson = lessons?.[baseline.name] || BASELINE_CLASSROOM[baseline.name] || {};
          return (
            <article key={baseline.name}>
              <span>{baseline.family}</span>
              <h3>{baseline.name}</h3>
              <p>{lesson.principle}</p>
              <small>{lesson.learn || lesson.lesson}</small>
              {lesson.watch ? <em>Watch: {lesson.watch}</em> : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function MetricGuide() {
  const metrics = [
    ["CAGR", "Annualized growth rate. It rewards compounding but says nothing about the path taken."],
    ["Sharpe", "Return earned per unit of volatility. Higher is better when measured consistently."],
    ["Sortino", "Similar to Sharpe, but penalizes downside volatility rather than all volatility."],
    ["Maximum Drawdown", "Largest peak-to-trough loss. It approximates the patience and capital an investor needed."],
    ["Turnover", "How much of the portfolio is traded. More turnover increases fee, slippage, and capacity risk."],
    ["Gross Exposure", "Total absolute invested weight. It reveals whether returns used more market exposure."],
  ];
  return (
    <section className="metric-guide">
      <div className="card-heading">
        <div><span className="section-kicker">How To Read The Evidence</span><h2>Metrics answer different questions</h2></div>
      </div>
      <div className="metric-guide-grid">
        {metrics.map(([name, copy]) => <article key={name}><strong>{name}</strong><p>{copy}</p></article>)}
      </div>
    </section>
  );
}

function LearningWorkspace({ run, loading, error, onResults, onBuild }) {
  if (!run && loading) return <div className="page-loading"><RefreshCw className="spin" size={24} /> Loading Learning Review</div>;
  if (!run) {
    return (
      <>
        <PageHeader eyebrow="Education Center" title="Learning Review" description="Complete a Forge Run to unlock strategy lessons and personalized next-round guidance." />
        <EmptyRun onBuild={onBuild} />
        {error ? <div className="inline-error centered">{error}</div> : null}
      </>
    );
  }
  const analysis = run.battle_analysis;
  return (
    <>
      <PageHeader
        eyebrow="Education Center"
        title="Learning Review"
        description="Understand why strategies behaved differently before changing code or starting another round."
        actions={<button className="secondary-button" onClick={onResults}><BarChart3 size={16} /> Back to Results</button>}
      />
      {!analysis ? (
        <section className="learning-pending">
          <Activity size={22} />
          <div><strong>Teaching summary is waiting for completed evidence</strong><p>The baseline lessons are available now. Personalized advice appears after Human and AI runs finish.</p></div>
        </section>
      ) : null}
      <LearningReview analysis={analysis} />
      <MetricGuide />
      <BaselineClassroom
        baselines={run.baselines}
        lessons={analysis?.baseline_classroom}
      />
    </>
  );
}

function RobustnessWorkspace({ run, loading, error, onBuild, onStart }) {
  const [target, setTarget] = useState("best_ai");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState("");
  const robustness = run?.robustness;
  const active = ["queued", "running"].includes(robustness?.state);
  const verdict = robustness?.verdict;
  const start = async () => {
    setSubmitting(true);
    setActionError("");
    try {
      await onStart(target);
    } catch (requestError) {
      setActionError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!run && loading) return <div className="page-loading"><RefreshCw className="spin" size={24} /> Loading Robustness Lab</div>;
  if (!run) {
    return (
      <>
        <PageHeader eyebrow="Stress Testing" title="Robustness Lab" description="Complete a Forge Run before testing a selected strategy under controlled perturbations." />
        <EmptyRun onBuild={onBuild} />
        {error ? <div className="inline-error centered">{error}</div> : null}
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Stress Testing"
        title="Robustness Lab"
        description="Run a deterministic stress battery separately from the main contest, without giving another LLM control of the verdict."
        actions={active ? <StatusChip state={robustness.state} /> : null}
      />
      <section className="robustness-intro">
        <div>
          <span className="section-kicker">Protocol v1</span>
          <h2>Change assumptions, not strategy code</h2>
          <p>The exact frozen source is rerun with a recent-regime slice, a delayed start, double friction, and—when more than five stocks are available—a deterministic universe dropout.</p>
        </div>
        <div className="robustness-actions">
          <label>
            <span>Strategy under test</span>
            <select value={target} onChange={(event) => setTarget(event.target.value)} disabled={active || submitting}>
              <option value="best_ai">Best accepted AI</option>
              <option value="human">Human strategy</option>
            </select>
          </label>
          <button className="primary-button" onClick={start} disabled={active || submitting || run.state !== "completed"}>
            {active || submitting ? <RefreshCw className="spin" size={17} /> : <Play size={17} />}
            {robustness ? "Run Again" : "Run Robustness Test"}
          </button>
        </div>
      </section>
      {actionError ? <div className="inline-error">{actionError}</div> : null}
      {robustness ? (
        <>
          <section className={`robustness-verdict robustness-${verdict?.grade || robustness.state}`}>
            <div className="verdict-emblem"><ShieldCheck size={24} /></div>
            <div>
              <span>{robustness.target_label}</span>
              <h2>{verdict ? `${formatNumber(verdict.score)} / 100 · ${statusLabel(verdict.grade)}` : statusLabel(robustness.state)}</h2>
              <p>{verdict?.conclusion || "LEAN is running the frozen strategy through each stress scenario."}</p>
            </div>
          </section>
          <section className="robustness-table-card">
            <div className="table-scroll">
              <table className="comparison-table robustness-table">
                <thead><tr><th>Scenario</th><th>Status</th><th>CAGR</th><th>Sharpe</th><th>Drawdown</th><th>Return retained</th><th>Checks</th></tr></thead>
                <tbody>
                  {(robustness.scenarios || []).map((scenario) => {
                    const passed = (scenario.checks || []).filter((check) => check.passed).length;
                    return (
                      <tr key={scenario.id}>
                        <td><strong>{scenario.label}</strong><small>{scenario.purpose}</small></td>
                        <td><StatusChip state={scenario.state} /></td>
                        <td>{formatMetric(scenario.summary?.cagr, "percent")}</td>
                        <td>{formatMetric(scenario.summary?.sharpe_ratio, "number")}</td>
                        <td>{formatMetric(scenario.summary?.maximum_drawdown, "percent")}</td>
                        <td>{scenario.cagr_retention == null ? "—" : formatMetric(scenario.cagr_retention, "percent")}</td>
                        <td>{scenario.checks?.length ? `${passed}/${scenario.checks.length}` : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          {verdict?.limitations?.length ? (
            <section className="robustness-limitations">
              <Lightbulb size={20} />
              <div><strong>Interpretation limits</strong>{verdict.limitations.map((item) => <p key={item}>{item}</p>)}</div>
            </section>
          ) : null}
          {robustness.error ? <div className="inline-error">{robustness.error}</div> : null}
        </>
      ) : (
        <section className="robustness-empty">
          <Gauge size={24} />
          <div><strong>No robustness battery has been run yet</strong><p>This is intentionally optional so the normal Forge flow stays fast.</p></div>
        </section>
      )}
    </>
  );
}

function ResultsTable({ rows }) {
  return (
    <section className="table-card">
      <div className="card-heading"><div><span className="section-kicker">Comparable Results</span><h2>Strategy Comparison</h2></div></div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Strategy</th><th>Category</th><th>Status</th><th>Score</th><th>Revisions</th><th>CAGR</th><th>Sharpe Ratio</th><th>Maximum Drawdown</th><th>Ending Equity</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td><strong>{row.strategy}</strong></td>
                <td><span className={`category-tag category-${row.category.split(" ")[0].toLowerCase()}`}>{row.category}</span></td>
                <td><StatusChip state={row.state} /></td>
                <td>{row.scorecard?.eligible ? <strong>{formatNumber(row.scorecard.score)}</strong> : "—"}</td>
                <td>{row.revisions === null ? "—" : row.revisions}</td>
                <td>{formatMetric(row.summary?.cagr, "percent")}</td>
                <td>{formatMetric(row.summary?.sharpe_ratio, "number")}</td>
                <td>{formatMetric(row.summary?.maximum_drawdown, "percent")}</td>
                <td>{formatMetric(row.summary?.end_equity, "currency")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BehaviorGrid({ evidence }) {
  if (!evidence || !Object.keys(evidence).length) return null;
  const items = [
    ["Filled Orders", evidence.filled_order_count],
    ["Invested Snapshots", evidence.invested_snapshot_count],
    ["Maximum Gross Exposure", evidence.max_gross_exposure],
    ["Rebalances", evidence.rebalance_count],
    ["Completed Rebalances", evidence.staged_rebalance_completed_count],
    ["Replaced Targets", evidence.staged_rebalance_replacement_count],
  ];
  return (
    <div className="behavior-grid">
      {items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{formatNumber(value)}</strong></div>)}
    </div>
  );
}

function RevisionEffect({ effect }) {
  if (!effect) return null;
  const labels = {
    initial_evaluation: "Initial execution",
    evidence_only: "Evidence-only revision",
    strategy_behavior_change: "Strategy behavior changed",
    ineffective: "Ineffective revision",
  };
  return (
    <div className={`revision-effect effect-${effect.kind || "initial_evaluation"}`}>
      <div>
        <History size={17} />
        <strong>{labels[effect.kind] || "Revision analysis"}</strong>
      </div>
      <p>{effect.note}</p>
      <div className="revision-facts">
        {effect.semantic_source_changed !== null ? (
          <span>Executable code: {effect.semantic_source_changed ? "changed" : "unchanged"}</span>
        ) : null}
        {effect.trading_behavior_changed !== null ? (
          <span>Trading behavior: {effect.trading_behavior_changed ? "changed" : "unchanged"}</span>
        ) : null}
        {effect.result_changed !== null ? (
          <span>Metrics: {effect.result_changed ? "changed" : "unchanged"}</span>
        ) : null}
        {effect.resolved_checks?.length ? <span>Resolved: {effect.resolved_checks.join(", ")}</span> : null}
      </div>
    </div>
  );
}

function ReviewHistory({ history }) {
  if (!history?.length) return <p className="muted-copy">Review details will appear after the strategy completes a backtest.</p>;
  return (
    <div className="review-history">
      {history.map((entry, index) => {
        const report = entry.report || {};
        return (
          <details key={`${entry.worker_run_id}-${index}`} open={index === history.length - 1}>
            <summary>
              <span>Review {entry.attempt || index + 1}</span>
              <span className={`decision decision-${report.decision}`}>{report.decision === "accept" ? "Accepted" : "Revision Requested"}</span>
              <ChevronDown size={17} />
            </summary>
            <div className="review-body">
              {report.policy_version ? (
                <div className="review-authority">
                  <ShieldCheck size={17} />
                  <div>
                    <strong>Backend-verified decision</strong>
                    <span>
                      {report.policy_version}
                      {report.agent_advisory_decision
                        ? ` · Agent advised ${report.agent_advisory_decision}`
                        : " · Agent supplied evidence notes only"}
                    </span>
                  </div>
                </div>
              ) : null}
              <RevisionEffect effect={entry.revision_effectiveness} />
              {entry.summary ? (
                <div className="review-metrics">
                  <span>CAGR <strong>{formatMetric(entry.summary.cagr, "percent")}</strong></span>
                  <span>Sharpe <strong>{formatMetric(entry.summary.sharpe_ratio, "number")}</strong></span>
                  <span>Drawdown <strong>{formatMetric(entry.summary.maximum_drawdown, "percent")}</strong></span>
                  <span>Equity <strong>{formatMetric(entry.summary.end_equity, "currency")}</strong></span>
                </div>
              ) : null}
              <BehaviorGrid evidence={entry.behavior_evidence} />
              <div className="check-list">
                {(report.checks || []).map((check) => (
                  <div className={`check-row check-${check.status}`} key={check.id}>
                    {check.status === "pass" ? <CheckCircle2 size={19} /> : <XCircle size={19} />}
                    <div><strong>{check.id} · {check.status === "pass" ? "Passed" : "Failed"}</strong><p>{check.reason}</p>{check.evidence?.length ? <ul>{check.evidence.map((item, evidenceIndex) => <li key={evidenceIndex}>{item}</li>)}</ul> : null}</div>
                  </div>
                ))}
              </div>
              {report.repair_request ? <div className="repair-request"><strong>Revision Request</strong><p>{report.repair_request}</p></div> : null}
              {entry.source_code ? (
                <details className="revision-source">
                  <summary><Code2 size={15} /> View code used in this review</summary>
                  <pre><code>{entry.source_code}</code></pre>
                </details>
              ) : null}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function GeneratedReviews({ candidates }) {
  if (!candidates?.length) return null;
  return (
    <section className="review-card">
      <div className="card-heading"><div><span className="section-kicker">Quality Review</span><h2>Generated Strategy Reviews</h2></div></div>
      <div className="candidate-review-grid">
        {candidates.map((candidate) => (
          <div className="candidate-review" key={candidate.track}>
            <div className="candidate-title">
              <div className="strategy-avatar"><ShieldCheck size={19} /></div>
              <div><strong>{formatTrack(candidate.track)} Strategy</strong><span>{candidate.repair_attempts || 0} Revisions · {candidate.generation_retries || 0} Generation Retries</span></div>
              <StatusChip state={candidate.state} />
            </div>
            {candidate.error && ["failed", "rejected"].includes(candidate.state) ? <div className="inline-error">{candidate.error}</div> : null}
            {candidate.best_observed_attempt != null ? <div className="retained-attempt-note">Metrics and source were retained from runnable Review {Number(candidate.best_observed_attempt) + 1}; status remains Rejected.</div> : null}
            <ReviewHistory history={candidate.acceptance_history} />
          </div>
        ))}
      </div>
    </section>
  );
}

function ResultsWorkspace({ run, loading, error, onRefresh, onBuild, onLearning }) {
  if (!run && loading) return <div className="page-loading"><RefreshCw className="spin" size={24} /> Loading Run</div>;
  if (!run) return <><PageHeader eyebrow="Backtest Results" title="Results" description="Compare completed strategies and inspect their review history." /><EmptyRun onBuild={onBuild} />{error ? <div className="inline-error centered">{error}</div> : null}</>;

  const rows = strategyRows(run);
  const finished = rows.filter((item) => FINISHED_ITEM_STATES.has(item.state)).length;
  const progress = rows.length ? Math.round((finished / rows.length) * 100) : 0;
  const settings = run.settings || {};

  return (
    <>
      <PageHeader
        eyebrow="Backtest Results"
        title="Strategy Results"
        description={`Run ${run.run_id}`}
        actions={(
          <div className="header-action-row">
            <button className="secondary-button" onClick={onLearning}><BookOpen size={16} /> Learning Review</button>
            <button className="secondary-button" onClick={onRefresh} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} /> Refresh</button>
          </div>
        )}
      />
      <section className="run-overview">
        <div className="run-status-block">
          <span>Run Status</span>
          <div><StatusChip state={run.state} /><strong>{progress}%</strong></div>
          <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
        </div>
        <div className="overview-stat"><Layers3 size={20} /><div><span>Selected Stocks</span><strong>{settings.symbols?.length || 0}</strong></div></div>
        <div className="overview-stat"><CircleDollarSign size={20} /><div><span>Initial Cash</span><strong>{formatMetric(settings.initial_cash, "currency")}</strong></div></div>
        <div className="overview-stat"><Gauge size={20} /><div><span>Benchmark</span><strong>{settings.benchmark || "—"}</strong></div></div>
      </section>
      {run.error ? <div className="inline-error">{run.error}</div> : null}
      <JudgeBreakdown analysis={run.battle_analysis} />
      <MetricChart rows={rows} />
      <PortfolioJourney rows={rows} settings={settings} />
      <ResultsTable rows={rows} />
      <RiskCostTable rows={rows} />
      <GeneratedReviews candidates={run.candidates} />
    </>
  );
}

function ArenaSide({ side, label, state, summary, winner }) {
  return (
    <div className={`arena-side arena-${side} ${winner ? "round-winner" : ""}`}>
      <div className="arena-side-title">
        {side === "human" ? <UserRound size={20} /> : <Sparkles size={20} />}
        <div><span>{side === "human" ? "Human Player" : "AI Challenger"}</span><strong>{label}</strong></div>
        {winner ? <Trophy size={19} /> : null}
      </div>
      <StatusChip state={state} />
      <div className="arena-side-metrics">
        <span>Sharpe<strong>{formatMetric(summary?.sharpe_ratio, "number")}</strong></span>
        <span>CAGR<strong>{formatMetric(summary?.cagr, "percent")}</strong></span>
        <span>Drawdown<strong>{formatMetric(summary?.maximum_drawdown, "percent")}</strong></span>
        <span>Equity<strong>{formatMetric(summary?.end_equity, "currency")}</strong></span>
      </div>
    </div>
  );
}

function ArenaWorkspace({ history, loading, error, onRefresh }) {
  const rounds = [...(history || [])].reverse();
  const humanWins = rounds.filter((item) => item.winner?.side === "human").length;
  const aiWins = rounds.filter((item) => item.winner?.side === "ai").length;
  const draws = rounds.length - humanWins - aiWins;

  return (
    <>
      <PageHeader
        eyebrow="Best of Five"
        title="Human vs AI · PK Arena"
        description="Each completed Forge Run is one round. The deterministic Judge balances risk-adjusted return, drawdown, robustness, trading cost, and explainability."
        actions={<button className="secondary-button" onClick={onRefresh} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} /> Refresh rounds</button>}
      />
      <section className="arena-scoreboard">
        <div className="score-team score-human"><UserRound size={24} /><span>Human</span><strong>{humanWins}</strong></div>
        <div className="score-center">
          <span>BEST OF FIVE</span>
          <div className="round-pips">
            {Array.from({ length: 5 }, (_, index) => {
              const result = rounds[index]?.winner?.side;
              return <i key={index} className={result ? `pip-${result}` : ""}>{index + 1}</i>;
            })}
          </div>
          <small>{draws ? `${draws} unresolved round${draws > 1 ? "s" : ""}` : `${rounds.length}/5 rounds played`}</small>
        </div>
        <div className="score-team score-ai"><Sparkles size={24} /><span>AI</span><strong>{aiWins}</strong></div>
      </section>
      {error ? <div className="inline-error">{error}</div> : null}
      {loading && !rounds.length ? <div className="page-loading"><RefreshCw className="spin" size={24} /> Loading PK history</div> : null}
      {!loading && !rounds.length ? (
        <section className="empty-state"><div><Trophy size={26} /></div><h2>No rounds played yet</h2><p>Complete a new Forge Run to record Round 1. The arena keeps the latest five rounds.</p></section>
      ) : null}
      <div className="arena-round-list">
        {rounds.map((round, index) => {
          const championTrack = round.battle_analysis?.ai_champion?.track;
          const ai = (round.candidates || []).find(
            (candidate) => candidate.track === championTrack,
          ) || bestAcceptedAi(round);
          const winnerSide = round.winner?.side;
          return (
            <article className="arena-round" key={round.run_id}>
              <div className="arena-round-header">
                <div><span>Round {index + 1}</span><strong>{round.run_id}</strong><small>{new Date(round.created_at).toLocaleString()}</small></div>
                <div className={`round-result result-${winnerSide || "none"}`}><Trophy size={16} />{round.winner?.label || "No winner"}</div>
              </div>
              <div className="arena-versus">
                <ArenaSide side="human" label="Human Strategy" state={round.human?.state} summary={round.human?.summary} winner={winnerSide === "human"} />
                <div className="versus-mark">VS</div>
                <ArenaSide side="ai" label={ai ? `${formatTrack(ai.track)} Strategy` : "No accepted candidate"} state={ai?.state || "failed"} summary={ai?.summary} winner={winnerSide === "ai"} />
              </div>
              <p className="round-rule">{round.winner?.reason}</p>
              <details className="round-details">
                <summary>Inspect all AI challengers and revision rounds <ChevronDown size={17} /></summary>
                <div className="round-candidates">
                  {(round.candidates || []).map((candidate) => (
                    <div key={candidate.track}>
                      <div className="round-candidate-title"><strong>{formatTrack(candidate.track)}</strong><StatusChip state={candidate.state} /></div>
                      {candidate.error ? <p className="round-candidate-error">{candidate.error}</p> : null}
                      <ReviewHistory history={candidate.acceptance_history} />
                    </div>
                  ))}
                </div>
              </details>
            </article>
          );
        })}
      </div>
    </>
  );
}

function CodeWorkspace({ run, onBuild }) {
  const sources = useMemo(() => {
    if (!run) return [];
    const result = [];
    if (run.human?.source_code) result.push({ id: "human", label: "Human Strategy", category: "Human Strategy", source: run.human.source_code, state: run.human.state });
    for (const item of run.candidates || []) {
      if (item.source_code) result.push({ id: item.track, label: `${formatTrack(item.track)} Strategy`, category: "Generated Strategy", source: item.source_code, state: item.state });
    }
    return result;
  }, [run]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (sources.length && !sources.some((item) => item.id === selected)) setSelected(sources[0].id);
  }, [sources, selected]);
  const current = sources.find((item) => item.id === selected);

  return (
    <>
      <PageHeader eyebrow="Source Review" title="Strategy Code" description="Inspect the complete Python source used for each submitted strategy." />
      {!run ? <EmptyRun onBuild={onBuild} /> : (
        <section className="source-workspace">
          <div className="source-tabs">
            {sources.map((item) => <button key={item.id} className={selected === item.id ? "active" : ""} onClick={() => setSelected(item.id)}><Code2 size={16} /><span>{item.label}<small>{item.category}</small></span></button>)}
          </div>
          <div className="source-viewer">
            {current ? <><div className="source-header"><div><span>{current.category}</span><h2>{current.label}</h2></div><StatusChip state={current.state} /></div><pre><code>{current.source}</code></pre></> : <div className="chart-empty"><Code2 size={22} /><span>Source code is not available yet.</span></div>}
          </div>
        </section>
      )}
    </>
  );
}

export default function App() {
  const initialRunId = new URLSearchParams(window.location.search).get("run_id") || "";
  const [view, setView] = useState(initialRunId ? "results" : "build");
  const [catalog, setCatalog] = useState(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [serviceStatus, setServiceStatus] = useState("loading");
  const [runId, setRunId] = useState(initialRunId);
  const [run, setRun] = useState(null);
  const [runLoading, setRunLoading] = useState(Boolean(initialRunId));
  const [runError, setRunError] = useState("");
  const [historyRounds, setHistoryRounds] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([apiRequest("/catalog/universe"), apiRequest("/health")])
      .then(([universe, health]) => {
        if (!active) return;
        setCatalog(universe);
        setServiceStatus(health.status === "ok" ? "online" : "offline");
      })
      .catch(() => {
        if (active) setServiceStatus("offline");
      })
      .finally(() => {
        if (active) setCatalogLoading(false);
      });
    return () => { active = false; };
  }, []);

  const loadRun = useCallback(async (id, { quiet = false } = {}) => {
    if (!id) return;
    if (!quiet) setRunLoading(true);
    setRunError("");
    try {
      const result = await apiRequest(`/forge-runs/${encodeURIComponent(id)}`);
      setRun(result);
      setRunId(id);
      setRunQuery(id);
    } catch (error) {
      setRunError(error.message);
      if (!quiet) setRun(null);
    } finally {
      if (!quiet) setRunLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistoryRounds(await apiRequest("/forge-history"));
    } catch (error) {
      setHistoryError(error.message);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialRunId) loadRun(initialRunId);
  }, [initialRunId, loadRun]);

  useEffect(() => {
    const robustnessActive = ["queued", "running"].includes(run?.robustness?.state);
    if (!runId || (run && TERMINAL_RUN_STATES.has(run.state) && !robustnessActive)) return undefined;
    const timer = window.setInterval(() => loadRun(runId, { quiet: true }), 3000);
    return () => window.clearInterval(timer);
  }, [runId, run, loadRun]);

  useEffect(() => {
    if (view === "arena") loadHistory();
  }, [view, loadHistory]);

  const openRun = (id) => {
    setView("results");
    loadRun(id);
  };

  const handleCreated = (created) => {
    setRun(created);
    setRunId(created.run_id);
    setRunQuery(created.run_id);
    setView("results");
  };

  const startRobustness = useCallback(async (target) => {
    if (!runId) throw new Error("Create or open a Forge Run first.");
    const result = await apiRequest(
      `/forge-runs/${encodeURIComponent(runId)}/robustness`,
      { method: "POST", body: JSON.stringify({ target }) },
    );
    setRun((current) => current ? { ...current, robustness: result } : current);
    return result;
  }, [runId]);

  return (
    <div className="app-shell">
      <Sidebar view={view} onView={setView} runId={runId} onOpenRun={openRun} serviceStatus={serviceStatus} />
      <main className="main-content">
        {view === "build" ? <BuildWorkspace catalog={catalog} loadingCatalog={catalogLoading} onCreated={handleCreated} /> : null}
        {view === "results" ? <ResultsWorkspace run={run} loading={runLoading} error={runError} onRefresh={() => loadRun(runId)} onBuild={() => setView("build")} onLearning={() => setView("learning")} /> : null}
        {view === "forge" ? <AIForgeWorkspace run={run} onBuild={() => setView("build")} /> : null}
        {view === "robustness" ? <RobustnessWorkspace run={run} loading={runLoading} error={runError} onBuild={() => setView("build")} onStart={startRobustness} /> : null}
        {view === "learning" ? <LearningWorkspace run={run} loading={runLoading} error={runError} onResults={() => setView("results")} onBuild={() => setView("build")} /> : null}
        {view === "arena" ? <ArenaWorkspace history={historyRounds} loading={historyLoading} error={historyError} onRefresh={loadHistory} /> : null}
        {view === "code" ? <CodeWorkspace run={run} onBuild={() => setView("build")} /> : null}
      </main>
    </div>
  );
}
