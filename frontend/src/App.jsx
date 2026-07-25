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
  Copy,
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
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
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

    def initialize(self):
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
        self.set_warm_up(2, Resolution.DAILY)

    def rebalance(self):
        if self.is_warming_up:
            return
        weight = 0.90 / len(self.symbols)
        targets = [PortfolioTarget(symbol, weight) for symbol in self.symbols]
        self.set_holdings(
            targets,
            liquidate_existing_holdings=True,
            tag="Monthly equal weight",
        )

    def on_data(self, data):
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
  const token = window.localStorage.getItem("alphaforge_token");
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
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
    categoryLabel: item.baseline_execution === "reused"
      ? "Reference · R1 reused"
      : "Reference Strategy",
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
      revisions: item.iteration_count || 0,
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

function Sidebar({ view, onView, runId, onOpenRun, serviceStatus, user, onLogout }) {
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
        <button className={view === "lobby" ? "active" : ""} onClick={() => onView("lobby")}>
          <Trophy size={18} />
          Battle Lobby
        </button>
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
      <div className="signed-in-user">
        <UserRound size={18} />
        <span><small>Signed in as</small>{user?.username}</span>
        <button type="button" onClick={onLogout} aria-label="Sign out">Sign out</button>
      </div>
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

function BuildWorkspace({
  catalog,
  loadingCatalog,
  onCreated,
  battle,
  initialHumanStrategy,
  recommendations = [],
}) {
  const seedGuided = initialHumanStrategy?.guided || {};
  const frozenContract = battle?.contract || null;
  const contractFrozen = Boolean(frozenContract && battle?.round_count > 0);
  const initialized = useRef(false);
  const [symbols, setSymbols] = useState(frozenContract?.symbols || []);
  const [startDate, setStartDate] = useState(frozenContract?.start_date || "2020-01-02");
  const [endDate, setEndDate] = useState(frozenContract?.end_date || "2024-12-31");
  const [initialCash, setInitialCash] = useState(frozenContract?.initial_cash || 100000);
  const [benchmark, setBenchmark] = useState(frozenContract?.benchmark || "SPY");
  const [transactionCost, setTransactionCost] = useState(frozenContract?.transaction_cost_bps ?? 10);
  const [slippage, setSlippage] = useState(frozenContract?.slippage_bps ?? 5);
  const [humanMode, setHumanMode] = useState(initialHumanStrategy?.mode || "guided");
  const [guidedLevel, setGuidedLevel] = useState(seedGuided.level || "basic");
  const [signal, setSignal] = useState(seedGuided.signal || "momentum");
  const [lookback, setLookback] = useState(seedGuided.lookback_days || 60);
  const [secondaryLookback, setSecondaryLookback] = useState(seedGuided.secondary_lookback_days || 63);
  const [primarySignalWeight, setPrimarySignalWeight] = useState(seedGuided.primary_signal_weight ?? 0.65);
  const [rebalance, setRebalance] = useState(seedGuided.rebalance || "monthly");
  const [holdings, setHoldings] = useState(seedGuided.holdings || 3);
  const [weighting, setWeighting] = useState(seedGuided.weighting || "equal");
  const [grossExposure, setGrossExposure] = useState(seedGuided.gross_exposure ?? 0.90);
  const [maxPositionWeight, setMaxPositionWeight] = useState(seedGuided.max_position_weight ?? 0.45);
  const [rebalanceThreshold, setRebalanceThreshold] = useState(seedGuided.rebalance_threshold ?? 0.02);
  const [requirePositiveScore, setRequirePositiveScore] = useState(seedGuided.require_positive_score || false);
  const [marketTrendFilter, setMarketTrendFilter] = useState(seedGuided.market_trend_filter || false);
  const [marketSmaWindow, setMarketSmaWindow] = useState(seedGuided.market_sma_window || 200);
  const [sourceCode, setSourceCode] = useState(initialHumanStrategy?.source_code || HUMAN_CODE_STARTER);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (catalog && !initialized.current) {
      initialized.current = true;
      setSymbols(frozenContract?.symbols || catalog.default_symbols || []);
      setBenchmark(frozenContract?.benchmark || (catalog.benchmarks || ["SPY"])[0] || "SPY");
    }
  }, [catalog, frozenContract]);

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
    Number(holdings) * Number(maxPositionWeight) >= Number(grossExposure) &&
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
              level: guidedLevel,
              signal,
              lookback_days: Number(lookback),
              secondary_lookback_days: Number(secondaryLookback),
              primary_signal_weight: Number(primarySignalWeight),
              rebalance,
              holdings: Number(holdings),
              weighting,
              gross_exposure: Number(grossExposure),
              max_position_weight: Number(maxPositionWeight),
              rebalance_threshold: Number(rebalanceThreshold),
              require_positive_score: requirePositiveScore,
              market_trend_filter: marketTrendFilter,
              market_sma_window: Number(marketSmaWindow),
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
          battle_id: battle?.id || null,
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
        eyebrow={battle ? `Best of Five · Round ${battle.next_round} of 5` : "New Experiment"}
        title={battle ? battle.name : "Create a Backtest"}
        description={battle
          ? `Current score: You ${battle.human_wins} — ${battle.ai_wins} AI. Adjust your strategy, then run the next fair round.`
          : "Choose one market setup, add your own strategy, and compare every result on equal terms."}
      />
      {battle?.rounds?.length ? (
        <div className="round-adjustment-guide">
          <Lightbulb size={22} />
          <div>
            <strong>Make one understandable change this round</strong>
            <p>For lower drawdown, reduce gross exposure or position cap. For a steadier Sharpe ratio, try inverse-volatility weighting. For fewer trades, keep monthly rebalancing and raise the rebalance threshold. Change one or two controls so you can explain what caused the result.</p>
          </div>
        </div>
      ) : null}

      <section className="step-card">
        <div className="step-heading">
          <span className="step-number">01</span>
            <div>
              <h2>Market Setup</h2>
              <p>Freeze one experiment contract shared by Human, AI, and all baselines.</p>
          </div>
          <div className="selection-count">{symbols.length} Selected</div>
        </div>
        {contractFrozen ? (
          <div className="contract-lock-note"><ShieldCheck size={19} /><span><strong>Battle contract locked after Round 1.</strong> Stocks, dates, cash, benchmark, fees, and slippage stay unchanged so every round remains comparable.</span></div>
        ) : null}

        <div className="market-layout">
          <div className="universe-panel">
            <div className="section-toolbar">
              <div>
                <h3>Stock Candidate Pool</h3>
                <p>Select 5–30 stocks. Strategies may choose a subset during each rebalance.</p>
              </div>
              <div className="text-actions">
                <button type="button" disabled={contractFrozen} onClick={() => setSymbols(tradable.map((item) => item.display_ticker))}>
                  Select All
                </button>
                <button type="button" disabled={contractFrozen} onClick={() => setSymbols([])}>Clear</button>
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
                            disabled={contractFrozen}
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
              <Field label="Start Date"><input type="date" disabled={contractFrozen} value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Field>
              <Field label="End Date"><input type="date" disabled={contractFrozen} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Field>
            </div>
            <Field label="Initial Cash"><div className="input-prefix"><span>$</span><input type="number" disabled={contractFrozen} min="1000" step="10000" value={initialCash} onChange={(event) => setInitialCash(event.target.value)} /></div></Field>
            <Field label="Benchmark"><select disabled={contractFrozen} value={benchmark} onChange={(event) => setBenchmark(event.target.value)}>{(catalog?.benchmarks || ["SPY"]).map((item) => <option key={item}>{item}</option>)}</select></Field>
            <div className="two-fields">
              <Field label="Transaction Cost" hint="Basis Points"><input type="number" disabled={contractFrozen} min="0" step="1" value={transactionCost} onChange={(event) => setTransactionCost(event.target.value)} /></Field>
              <Field label="Slippage" hint="Basis Points"><input type="number" disabled={contractFrozen} min="0" step="1" value={slippage} onChange={(event) => setSlippage(event.target.value)} /></Field>
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

        {recommendations.length ? (
          <div className="human-form-recommendations">
            <div className="human-form-recommendation-heading">
              <div><Lightbulb size={19} /><strong>Recommended settings from the previous round</strong></div>
              <span>{recommendations.length} suggestion{recommendations.length === 1 ? "" : "s"}</span>
            </div>
            <p>The guided values below have been pre-filled. Review the reason for each change before starting this round.</p>
            <div className="human-form-recommendation-grid">
              {recommendations.map((item) => {
                const guided = String(item.parameter_path || "").startsWith("guided.");
                return (
                  <article key={item.parameter_path}>
                    <div>
                      <strong>{item.label}</strong>
                      <small>{item.target_metric || "Strategy quality"}</small>
                    </div>
                    <div className="recommended-value">
                      <code>{String(item.current_value)}</code>
                      <ArrowRight size={14} />
                      <b>{String(item.recommended_value)}</b>
                    </div>
                    <p>{item.reason}</p>
                    <span className={guided ? "recommendation-applied" : "recommendation-manual"}>
                      {guided ? "Pre-filled" : "Manual code change"}
                    </span>
                  </article>
                );
              })}
            </div>
          </div>
        ) : null}

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
            <div className="guided-builder">
              <div className="guided-level-tabs">
                <button type="button" className={guidedLevel === "basic" ? "active" : ""} onClick={() => setGuidedLevel("basic")}>
                  Basic Template
                </button>
                <button type="button" className={guidedLevel === "advanced" ? "active" : ""} onClick={() => setGuidedLevel("advanced")}>
                  Advanced Multi-factor
                </button>
              </div>
              <div className="guided-fields">
              <Field label="Signal">
                <select value={signal} onChange={(event) => setSignal(event.target.value)}>
                  <option value="momentum">Momentum</option>
                  <option value="mean_reversion">Mean Reversion</option>
                  <option value="low_volatility">Low Volatility</option>
                  <option value="momentum_low_volatility">Momentum + Low Volatility</option>
                  <option value="trend_quality">Relative Trend Quality</option>
                </select>
              </Field>
              <Field label="Lookback Period">
                {guidedLevel === "basic" ? (
                  <select value={lookback} onChange={(event) => setLookback(event.target.value)}>
                    <option value="20">20 Days</option><option value="60">60 Days</option><option value="120">120 Days</option>
                  </select>
                ) : <input type="number" min="10" max="252" value={lookback} onChange={(event) => setLookback(event.target.value)} />}
              </Field>
              <Field label="Rebalance Schedule">
                <select value={rebalance} onChange={(event) => setRebalance(event.target.value)}>
                  <option value="monthly">Monthly</option><option value="weekly">Weekly</option>
                </select>
              </Field>
              <Field label="Number Of Holdings">
                {guidedLevel === "basic" ? (
                  <select value={holdings} onChange={(event) => setHoldings(event.target.value)}>
                    <option value="2">2 Stocks</option><option value="3">3 Stocks</option><option value="5">5 Stocks</option>
                  </select>
                ) : <input type="number" min="2" max="10" value={holdings} onChange={(event) => setHoldings(event.target.value)} />}
              </Field>
              {guidedLevel === "advanced" ? (
                <>
                  <Field label="Risk Lookback" hint="Used by volatility and secondary factors">
                    <input type="number" min="10" max="252" value={secondaryLookback} onChange={(event) => setSecondaryLookback(event.target.value)} />
                  </Field>
                  <Field label="Primary Factor Weight">
                    <input type="number" min="0.2" max="0.9" step="0.05" value={primarySignalWeight} onChange={(event) => setPrimarySignalWeight(event.target.value)} />
                  </Field>
                  <Field label="Portfolio Weighting">
                    <select value={weighting} onChange={(event) => setWeighting(event.target.value)}>
                      <option value="equal">Equal Weight</option>
                      <option value="inverse_volatility">Inverse Volatility</option>
                      <option value="score">Signal Score</option>
                    </select>
                  </Field>
                  <Field label="Gross Exposure">
                    <input type="number" min="0.5" max="0.95" step="0.05" value={grossExposure} onChange={(event) => setGrossExposure(event.target.value)} />
                  </Field>
                  <Field label="Maximum Position">
                    <input type="number" min="0.1" max="0.6" step="0.05" value={maxPositionWeight} onChange={(event) => setMaxPositionWeight(event.target.value)} />
                  </Field>
                  <Field label="No-trade Threshold">
                    <input type="number" min="0" max="0.1" step="0.01" value={rebalanceThreshold} onChange={(event) => setRebalanceThreshold(event.target.value)} />
                  </Field>
                  <Field label="Signal Filter">
                    <select value={String(requirePositiveScore)} onChange={(event) => setRequirePositiveScore(event.target.value === "true")}>
                      <option value="false">Always rank Top-K</option>
                      <option value="true">Require positive score</option>
                    </select>
                  </Field>
                  <Field label="Market Regime Filter">
                    <select value={String(marketTrendFilter)} onChange={(event) => setMarketTrendFilter(event.target.value === "true")}>
                      <option value="false">Disabled</option>
                      <option value="true">Benchmark above SMA</option>
                    </select>
                  </Field>
                  {marketTrendFilter ? (
                    <Field label="Market SMA Window">
                      <input type="number" min="20" max="252" value={marketSmaWindow} onChange={(event) => setMarketSmaWindow(event.target.value)} />
                    </Field>
                  ) : null}
                </>
              ) : null}
              </div>
              {Number(holdings) * Number(maxPositionWeight) < Number(grossExposure) ? (
                <p className="guided-validation">Increase holdings or maximum position weight so the portfolio can reach its target exposure.</p>
              ) : null}
            </div>
            <div className="strategy-summary">
              <div className="summary-icon"><Sparkles size={20} /></div>
              <div>
                <span>Strategy Preview</span>
                <strong>{readableEnum(signal)} Strategy</strong>
                <p>
                  Rank the selected pool using a {lookback}-day signal, hold {holdings} stocks,
                  rebalance {rebalance}, and target {Math.round(Number(grossExposure) * 100)}% gross exposure.
                </p>
                <small>{guidedLevel === "advanced" ? `${readableEnum(weighting)} allocation with configurable risk controls.` : "Safe defaults compiled through the fixed LEAN template."}</small>
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
            <PythonCodeEditor
              ariaLabel="Complete Strategy Source"
              value={sourceCode}
              onChange={(event) => setSourceCode(event.target.value)}
            />
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

function BattleRoundSwitcher({ battle, runId, onSwitch }) {
  if (!battle?.rounds?.length) return null;
  return (
    <nav className="battle-round-switcher" aria-label="Battle rounds">
      <div>
        <span>Battle rounds</span>
        <strong>{battle.name}</strong>
      </div>
      <div className="battle-round-buttons">
        {[1, 2, 3, 4, 5].map((number) => {
          const round = battle.rounds.find((item) => item.round_number === number);
          const active = round?.forge_run_id === runId;
          return (
            <button
              type="button"
              key={number}
              disabled={!round}
              className={`${active ? "active" : ""} ${round?.winner ? `winner-${round.winner}` : ""}`}
              onClick={() => round && onSwitch(round.forge_run_id)}
              aria-current={active ? "page" : undefined}
            >
              <strong>R{number}</strong>
              <small>
                {!round
                  ? "Not played"
                  : round.state === "completed"
                    ? `${round.winner === "human" ? "You" : "AI"} won`
                    : statusLabel(round.state)}
              </small>
            </button>
          );
        })}
      </div>
      <span className="battle-round-score">You {battle.human_wins} · {battle.ai_wins} AI</span>
    </nav>
  );
}

const PARAMETER_LABELS = {
  algorithm: "Model",
  target: "Prediction target",
  horizon_days: "Forecast horizon",
  pooled_training_rows: "Training rows",
  retrain_every_rebalances: "Retrain interval",
  n_estimators: "Estimators",
  learning_rate: "Learning rate",
  max_depth: "Maximum depth",
  min_samples_leaf: "Minimum leaf samples",
  ridge_alpha: "Ridge alpha",
  top_k: "Holdings",
  require_positive_score: "Positive scores only",
  hybrid_model_weight: "ML contribution",
  weighting: "Allocation method",
  gross_exposure: "Target exposure",
  max_position_weight: "Single-stock limit",
  volatility_window: "Risk lookback",
  minimum_variance_blend: "Minimum-variance blend",
  rebalance_threshold: "No-trade threshold",
  frequency: "Rebalance frequency",
  minutes_after_open: "Execution after open",
  market_trend_filter: "Market trend filter",
  market_sma_window: "Market trend lookback",
  stop_loss: "Stop loss",
  maximum_drawdown: "Portfolio drawdown guard",
  cooldown_days: "Risk cooldown",
};

const PERCENT_PARAMETERS = new Set([
  "hybrid_model_weight",
  "gross_exposure",
  "max_position_weight",
  "minimum_variance_blend",
  "rebalance_threshold",
  "stop_loss",
  "maximum_drawdown",
]);

const PYTHON_KEYWORDS = new Set([
  "and", "as", "assert", "async", "await", "break", "class", "continue",
  "def", "del", "elif", "else", "except", "finally", "for", "from",
  "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
  "or", "pass", "raise", "return", "try", "while", "with", "yield",
]);

const PYTHON_TOKEN_PATTERN = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#[^\n]*|@[A-Za-z_]\w*|\b[A-Za-z_]\w*\b|\b\d+(?:\.\d+)?\b)/g;

function pythonTokenClass(token) {
  if (token.startsWith("#")) return "python-comment";
  if (token.startsWith("\"") || token.startsWith("'")) return "python-string";
  if (token.startsWith("@")) return "python-decorator";
  if (PYTHON_KEYWORDS.has(token)) return "python-keyword";
  if (["True", "False", "None"].includes(token)) return "python-constant";
  if (/^\d/.test(token)) return "python-number";
  if (["self", "super"].includes(token)) return "python-builtin";
  return "";
}

function PythonHighlight({ source }) {
  const fragments = [];
  let cursor = 0;
  for (const match of String(source || "").matchAll(PYTHON_TOKEN_PATTERN)) {
    if (match.index > cursor) fragments.push(String(source).slice(cursor, match.index));
    const token = match[0];
    const className = pythonTokenClass(token);
    fragments.push(className
      ? <span className={className} key={`${match.index}-${token}`}>{token}</span>
      : token);
    cursor = match.index + token.length;
  }
  if (cursor < String(source || "").length) fragments.push(String(source).slice(cursor));
  return <code>{fragments}</code>;
}

function PythonCodeEditor({ value, onChange, ariaLabel }) {
  const highlightRef = useRef(null);
  const syncScroll = (event) => {
    if (!highlightRef.current) return;
    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  };
  return (
    <div className="python-editor">
      <pre ref={highlightRef} aria-hidden="true"><PythonHighlight source={value} /></pre>
      <textarea
        aria-label={ariaLabel}
        spellCheck="false"
        value={value}
        onChange={onChange}
        onScroll={syncScroll}
      />
    </div>
  );
}

function PythonCodeBlock({ source }) {
  return <pre className="python-code-block"><PythonHighlight source={source} /></pre>;
}

function readableEnum(value) {
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function parameterValue(key, value) {
  if (value === null || value === undefined) return "Not enabled";
  if (typeof value === "boolean") return value ? "Enabled" : "Disabled";
  if (PERCENT_PARAMETERS.has(key) && typeof value === "number") {
    const percentage = value * 100;
    return `${percentage.toFixed(percentage % 1 ? 1 : 0)}%`;
  }
  if (key === "horizon_days") return `${value} trading days`;
  if (key === "retrain_every_rebalances") {
    return `Every ${value} rebalance${value === 1 ? "" : "s"}`;
  }
  if (key === "volatility_window" || key === "market_sma_window") return `${value} days`;
  if (key === "minutes_after_open") return `${value} minutes`;
  if (key === "cooldown_days") return `${value} days`;
  return typeof value === "string" ? readableEnum(value) : formatNumber(value);
}

function ParameterGrid({ values, omit = [] }) {
  if (!values) return null;
  const entries = Object.entries(values).filter(
    ([key, value]) => !omit.includes(key) && value !== undefined,
  );
  return (
    <dl className="parameter-grid">
      {entries.map(([key, value]) => (
        <div key={key} className={value === null ? "parameter-muted" : ""}>
          <dt>{PARAMETER_LABELS[key] || readableEnum(key)}</dt>
          <dd>{parameterValue(key, value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function FeatureList({ title, features, components }) {
  const rows = components || (features || []).map((feature) => ({ feature }));
  if (!rows.length) return null;
  return (
    <div className="feature-list">
      <span className="parameter-subtitle">{title}</span>
      {rows.map((row, index) => (
        <div className="feature-row" key={`${row.feature?.kind}-${row.feature?.window}-${index}`}>
          <strong>{readableEnum(row.feature?.kind || "Feature")}</strong>
          <span>{row.feature?.window}-day lookback</span>
          {row.direction ? <span>{readableEnum(row.direction)} ranks better</span> : null}
          {row.weight != null ? <b>{Math.round(row.weight * 100)}% blend</b> : null}
        </div>
      ))}
    </div>
  );
}

function StrategyParameters({ spec }) {
  if (!spec) return null;
  const modelLabel = spec.model
    ? readableEnum(spec.model.algorithm)
    : `${spec.signal?.components?.length || 0}-factor transparent rank`;
  return (
    <section className="strategy-parameters" aria-label="Strategy configuration">
      <div className="parameter-overview">
        <div><span>Decision engine</span><strong>{modelLabel}</strong></div>
        <div><span>Portfolio</span><strong>Top {spec.selection?.top_k || "—"} holdings</strong></div>
        <div><span>Allocation</span><strong>{readableEnum(spec.portfolio?.weighting || "Not set")}</strong></div>
        <div><span>Exposure</span><strong>{parameterValue("gross_exposure", spec.portfolio?.gross_exposure)}</strong></div>
        <div><span>Rebalance</span><strong>{readableEnum(spec.schedule?.frequency || "—")}</strong></div>
      </div>

      <details className="strategy-parameter-details">
        <summary>
          <span>
            <strong>Full strategy configuration</strong>
            <small>Every parameter sent to the fixed LEAN template, grouped by purpose</small>
          </span>
          <ChevronDown size={17} />
        </summary>
        <div className="parameter-section-grid">
          {spec.signal ? (
            <section className="parameter-section">
              <h4>Transparent signal</h4>
              <FeatureList title="Ranking factors" components={spec.signal.components || []} />
            </section>
          ) : null}
          {spec.model ? (
            <section className="parameter-section">
              <h4>Machine-learning model</h4>
              <FeatureList title="Model features" features={spec.model.features || []} />
              <ParameterGrid values={spec.model} omit={["features"]} />
            </section>
          ) : null}
          <section className="parameter-section">
            <h4>Selection and allocation</h4>
            <ParameterGrid values={spec.selection} />
            <ParameterGrid values={spec.portfolio} />
          </section>
          <section className="parameter-section">
            <h4>Schedule and risk controls</h4>
            <ParameterGrid values={spec.schedule} />
            <ParameterGrid values={spec.risk} />
          </section>
        </div>
      </details>
    </section>
  );
}

function AIForgeWorkspace({ run, onBuild }) {
  if (!run) {
    return (
      <>
        <PageHeader
          eyebrow="Independent AI Track"
          title="AI Forge"
          description="Inspect parameter design, Critic feedback, and best-of-three selection."
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
    candidates.length === 3 && candidates.every((item) => Boolean(item.strategy_spec));
  const templateResolved =
    candidates.length === 3 &&
    candidates.every((item) => Boolean(item.source_code) || item.state === "failed");
  const trialLoopStarted = candidates.some(
    (item) => Boolean(item.worker_run_id) || (item.iterations || []).length > 0,
  );
  const reviewsFinished =
    candidates.length === 3 &&
    candidates.every((item) => ["accepted", "rejected", "failed"].includes(item.state));
  const judgeFinished = Boolean(run.battle_analysis) && run.state === "completed";
  const reusedBaselines = (run.baselines || []).some(
    (item) => item.baseline_execution === "reused",
  );

  const stages = [
    {
      number: "01",
      title: "Public Evidence",
      copy: reusedBaselines
        ? "Reuse the frozen Round 1 baseline evidence"
        : "Round 1 runs four baselines on isolated LEAN workers",
      state: stageState(baselinesReady, !baselinesReady),
    },
    {
      number: "02",
      title: "Parallel Entrants",
      copy: "Three Designers start while the hidden Human strategy runs independently",
      state: stageState(designsReady, baselinesReady),
    },
    {
      number: "03",
      title: "Validate & Compile",
      copy: "Every trial validates JSON parameters and compiles the fixed LEAN template",
      state: stageState(templateResolved, designsReady),
    },
    {
      number: "04",
      title: "Parallel Trial Loops",
      copy: "Tracks run in parallel; within each: LEAN → Critic → Designer, up to 3 trials",
      state: stageState(reviewsFinished, trialLoopStarted),
    },
    {
      number: "05",
      title: "Judge & Champion",
      copy: "A1–A5 review, select each round best, then challenge its track incumbent",
      state: stageState(judgeFinished, reviewsFinished),
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
            results, and the bounded strategy DSL. Human code, parameters,
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
      <div className={`forge-coach-loop ${judgeFinished ? "ready" : ""}`}>
        <Lightbulb size={18} />
        <div>
          <strong>After the round: AI Coach closes the learning loop</strong>
          <span>
            It reads only public and AI evidence, then tells the next-round
            Designer to refine parameters, rotate a mechanism, or rebuild the track.
          </span>
        </div>
        <ArrowRight size={18} />
        <b>Next round</b>
      </div>

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
            const spec = candidate.strategy_spec || {};
            const usage = candidate.usage || {};
            return (
              <article className="forge-track-card" key={candidate.track}>
                <div className="forge-track-header">
                  <div className="strategy-avatar"><Sparkles size={18} /></div>
                  <div>
                    <span>{formatTrack(candidate.track)} Candidate</span>
                    <h3>{spec.strategy_name || "Design pending"}</h3>
                  </div>
                  <StatusChip state={candidate.state} />
                </div>

                <p className="forge-thesis">
                  {spec.thesis || "The structured candidate design will appear after generation."}
                </p>
                {candidate.selection_origin === "prior_round_incumbent" ? (
                  <div className="retained-attempt-note incumbent">
                    This round did not beat the track champion. The strategy from
                    Round {candidate.retained_from_round} remains active; this
                    round&apos;s strongest challenger is Trial {candidate.current_round_best_iteration}.
                  </div>
                ) : candidate.best_iteration != null ? (
                  <div className="retained-attempt-note">
                    Iteration {candidate.best_iteration} produced the strongest
                    Sharpe-first result and is retained for this track.
                  </div>
                ) : null}

                {design.reference_baselines?.length ? (
                  <div className="baseline-improvement-plan">
                    <div className="reference-strip">
                      <span>Compared with</span>
                      <div>
                        {design.reference_baselines.map((name) => (
                          <strong key={name}>{name}</strong>
                        ))}
                      </div>
                    </div>
                    <div className="candidate-design-grid">
                      <div>
                        <span>Improvement hypothesis</span>
                        <p>{design.improvement_hypothesis}</p>
                      </div>
                      <div>
                        <span>Expected trade-off</span>
                        <p>{design.expected_tradeoff}</p>
                      </div>
                    </div>
                    {design.differentiation ? (
                      <div className="design-differences">
                        <span>What this candidate changes</span>
                        <ul>
                          {(Array.isArray(design.differentiation)
                            ? design.differentiation
                            : [design.differentiation]
                          ).map((item, index) => (
                            <li key={`${item}-${index}`}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="forge-evidence-row">
                  <div>
                    <span>Template</span>
                    <strong>{candidate.source_code ? "Compiled" : "Waiting"}</strong>
                  </div>
                  <div>
                    <span>LEAN Run</span>
                    <strong>{candidate.worker_run_id ? "Submitted" : "Waiting"}</strong>
                  </div>
                  <div>
                    <span>Trials</span>
                    <strong>{candidate.iteration_count || 0} / 3</strong>
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

                {candidate.strategy_spec ? (
                  <StrategyParameters spec={candidate.strategy_spec} />
                ) : null}

                {candidate.source_code ? (
                  <div className="preflight-pass">
                    <CheckCircle2 size={16} />
                    Schema-valid parameters compiled with template-v1.
                  </div>
                ) : null}

                {candidate.iterations?.length ? (
                  <div className="forge-iteration-section">
                    <div className="forge-section-heading">
                      <span>Backtest evolution</span>
                      <strong>
                        {candidate.iterations.length} completed trial
                        {candidate.iterations.length === 1 ? "" : "s"}
                      </strong>
                    </div>
                    <IterationHistory candidate={candidate} showCodeChanges />
                  </div>
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
                <div><dt>Sharpe</dt><dd>{formatNumber(card.components.sharpe_ratio)}</dd></div>
                <div><dt>CAGR</dt><dd>{formatNumber(card.components.cagr)}</dd></div>
                <div><dt>Drawdown</dt><dd>{formatNumber(card.components.drawdown_control)}</dd></div>
                <div><dt>Volatility</dt><dd>{formatNumber(card.components.volatility_control)}</dd></div>
                <div><dt>Cost</dt><dd>{formatNumber(card.components.cost_efficiency)}</dd></div>
                <div><dt>Execution</dt><dd>{formatNumber(card.components.execution_evidence)}</dd></div>
                <div><dt>Explainability</dt><dd>{formatNumber(card.components.explainability)}</dd></div>
              </dl>
            ) : <p>{card.eligibility_reasons?.join(" · ")}</p>}
          </article>
        ))}
      </div>
      <p className="judge-method">Public weights: 35% Sharpe · 30% CAGR · 15% drawdown · 5% volatility · 5% cost · 5% execution evidence · 5% explainability. Scores within two points are a draw. Optional robustness results are reported separately because only the selected strategy is stress-tested.</p>
    </section>
  );
}

function ChampionStrategyFlow({ run, analysis }) {
  const champion = analysis?.overall_best || analysis?.ai_champion;
  if (!champion) return null;
  const candidate = (run?.candidates || []).find((item) => item.track === champion.track);
  const spec = candidate?.strategy_spec;
  const guided = champion.id === "human" ? run?.human?.guided : null;
  if (!spec && !guided) return null;
  const features = spec?.signal?.components?.map((item) => readableEnum(item.feature?.kind)).join(" + ")
    || spec?.model?.features?.slice(0, 3).map((item) => readableEnum(item.kind)).join(" + ")
    || readableEnum(guided?.signal || "Market data");
  const nodes = [
    ["Evidence", features],
    ["Decision", spec?.model ? readableEnum(spec.model.algorithm) : "Transparent rank"],
    ["Selection", `Top ${spec?.selection?.top_k || guided?.holdings || "—"} stocks`],
    ["Allocation", readableEnum(spec?.portfolio?.weighting || guided?.weighting || "equal")],
    ["Risk", (spec?.risk?.market_trend_filter || guided?.market_trend_filter) ? "Market trend filter" : "Exposure and position caps"],
  ];
  return (
    <section className="teaching-flow-card">
      <div className="card-heading"><div><span className="section-kicker">Strategy DNA</span><h2>How the champion turns data into positions</h2></div></div>
      <div className="strategy-flow">
        {nodes.map(([label, value], index) => (
          <div className="strategy-flow-step" key={label}>
            <div><span>{String(index + 1).padStart(2, "0")}</span><small>{label}</small><strong>{value}</strong></div>
            {index < nodes.length - 1 ? <ArrowRight size={18} /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function RiskReturnTeachingChart({ analysis }) {
  const rows = (analysis?.judge?.scorecards || [])
    .filter((item) => item.eligible && item.summary?.maximum_drawdown != null && item.summary?.sharpe_ratio != null)
    .map((item) => ({
      name: item.label,
      drawdown: Number(item.summary.maximum_drawdown) * 100,
      sharpe: Number(item.summary.sharpe_ratio),
      cagr: Math.max(4, Math.abs(Number(item.summary.cagr || 0)) * 100),
      owner: item.owner,
    }));
  if (!rows.length) return null;
  const groups = [["baseline", "#718096"], ["human", "#c58b39"], ["ai", "#238b7b"]];
  return (
    <section className="teaching-chart-card">
      <div className="card-heading">
        <div><span className="section-kicker">Risk–Return Map</span><h2>Higher and further left is generally stronger</h2></div>
        <p>Bubble size represents CAGR.</p>
      </div>
      <div className="risk-map-legend" aria-label="Strategy category legend">
        {groups.map(([owner, color]) => (
          <span key={owner}><i style={{ backgroundColor: color }} />{readableEnum(owner)}</span>
        ))}
      </div>
      <div className="teaching-chart">
        <ResponsiveContainer width="100%" height={360}>
          <ScatterChart margin={{ top: 16, right: 24, bottom: 52, left: 18 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e3e9ec" />
            <XAxis type="number" dataKey="drawdown" name="Maximum Drawdown" unit="%" tick={{ fontSize: 12 }} label={{ value: "Maximum Drawdown (%) →", position: "bottom", offset: 20 }} />
            <YAxis type="number" dataKey="sharpe" name="Sharpe Ratio" tick={{ fontSize: 12 }} label={{ value: "Sharpe Ratio", angle: -90, position: "insideLeft" }} />
            <ZAxis type="number" dataKey="cagr" range={[70, 340]} name="CAGR" unit="%" />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            {groups.map(([owner, color]) => <Scatter key={owner} name={readableEnum(owner)} data={rows.filter((item) => item.owner === owner)} fill={color} />)}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-labels">{rows.map((item) => <span key={item.name}>{item.name}</span>)}</div>
    </section>
  );
}

function IterationLearningPath({ run, analysis }) {
  const track = analysis?.ai_champion?.track;
  const candidate = (run?.candidates || []).find((item) => item.track === track);
  const iterations = candidate?.champion_iterations?.length
    ? candidate.champion_iterations
    : candidate?.iterations || [];
  const selectedIteration = candidate?.champion_best_iteration
    || candidate?.best_iteration;
  if (!iterations.length) return null;
  return (
    <section className="iteration-learning-card">
      <div className="card-heading">
        <div><span className="section-kicker">Champion Lineage · {formatTrack(track)}</span><h2>How the best AI strategy evolved</h2></div>
        <span>{candidate.selection_origin === "prior_round_incumbent"
          ? `Showing the retained Round ${candidate.retained_from_round} champion`
          : `Selected trial: ${selectedIteration || "—"}`}</span>
      </div>
      <div className="iteration-learning-track">
        {iterations.map((item, index) => (
          <article className={Number(item.iteration) === Number(selectedIteration) ? "selected" : ""} key={item.iteration}>
            <div><span>Trial {item.iteration}</span>{Number(item.iteration) === Number(selectedIteration) ? <strong>Champion selected</strong> : null}</div>
            <dl>
              <div><dt>CAGR</dt><dd>{formatMetric(item.summary?.cagr, "percent")}</dd></div>
              <div><dt>Sharpe</dt><dd>{formatMetric(item.summary?.sharpe_ratio, "number")}</dd></div>
              <div><dt>Drawdown</dt><dd>{formatMetric(item.summary?.maximum_drawdown, "percent")}</dd></div>
            </dl>
            <p>{item.critique?.diagnosis || "Completed fixed-template backtest."}</p>
            {index < iterations.length - 1 ? <ArrowRight size={18} /> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function LLMTeachingReview({ education }) {
  const review = education?.llm_review;
  if (!review) {
    return education?.llm_state === "pending" ? (
      <section className="learning-pending"><RefreshCw className="spin" size={20} /><div><strong>Generating the evidence-grounded teaching review</strong><p>The completed results remain available while the explainer works.</p></div></section>
    ) : null;
  }
  const explanation = review.strategy_explanation || {};
  const concept = review.quant_concept || {};
  return (
    <section className="llm-teaching-review">
      <div className="card-heading"><div><span className="section-kicker">Teaching Explainer</span><h2>{explanation.thesis}</h2></div><span className="education-state">Grounded in this run</span></div>
      <div className="teaching-explanation-grid">
        <article><strong>How it works</strong><ol>{(explanation.mechanics || []).map((item) => <li key={item}>{item}</li>)}</ol></article>
        <article><strong>Why it led</strong><ul>{(explanation.why_it_led || []).map((item) => <li key={item}>{item}</li>)}</ul></article>
        <article><strong>Where it may fail</strong><ul>{(explanation.failure_modes || []).map((item) => <li key={item}>{item}</li>)}</ul></article>
      </div>
      <div className="next-round-lab">
        <div><span className="section-kicker">Next-Round Lab</span><h3>Change one variable, then test the hypothesis</h3></div>
        <div className="next-round-grid">
          {(review.next_round_actions || []).map((action) => (
            <article key={`${action.parameter_path}-${action.proposed_value}`}>
              <div><strong>{action.title}</strong><span>{action.expected_metric}</span></div>
              <p>{action.hypothesis}</p>
              <div className="parameter-change"><code>{action.parameter_path}</code><b>{action.current_value}</b><ArrowRight size={15} /><b>{action.proposed_value}</b></div>
              <small><b>Trade-off:</b> {action.tradeoff}</small>
              <small><b>Validate:</b> {action.validation}</small>
            </article>
          ))}
        </div>
      </div>
      <div className="dynamic-quant-concept"><BookOpen size={22} /><div><span>{readableEnum(concept.chart_hint || "Quant concept")}</span><h3>{concept.title}</h3><p>{concept.explanation}</p><strong>{concept.takeaway}</strong></div></div>
      <div className="overfitting-watch"><strong>Overfitting watch</strong>{(review.overfitting_watch || []).map((item) => <p key={item}>{item}</p>)}</div>
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
          {feedback.parameter_recommendations?.length ? (
            <div className="learning-parameter-recommendations">
              <strong>Suggested values</strong>
              {feedback.parameter_recommendations.map((item) => (
                <p key={item.parameter_path}><span>{item.label}</span><code>{String(item.current_value)}</code><ArrowRight size={13} /><b>{String(item.recommended_value)}</b></p>
              ))}
            </div>
          ) : null}
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
      <LLMTeachingReview education={analysis?.education_summary} />
      <ChampionStrategyFlow run={run} analysis={analysis} />
      <RiskReturnTeachingChart analysis={analysis} />
      <IterationLearningPath run={run} analysis={analysis} />
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
          <span className="section-kicker">Protocol v2</span>
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
              {verdict?.worst_scenario_score != null ? <small>Weakest scenario: {formatNumber(verdict.worst_scenario_score)} / 100</small> : null}
            </div>
          </section>
          <section className="robustness-table-card">
            <div className="table-scroll">
              <table className="comparison-table robustness-table">
                <thead><tr><th>Scenario</th><th>Status</th><th>Stress score</th><th>CAGR</th><th>Sharpe</th><th>Drawdown</th><th>Sharpe retained</th><th>CAGR retained</th><th>Checks</th></tr></thead>
                <tbody>
                  {(robustness.scenarios || []).map((scenario) => {
                    const passed = (scenario.checks || []).filter((check) => check.passed).length;
                    return (
                      <tr key={scenario.id}>
                        <td>
                          <strong>{scenario.label}</strong>
                          <small>{scenario.purpose}</small>
                          {scenario.thresholds ? (
                            <small className="scenario-thresholds">
                              Required: CAGR {formatMetric(scenario.thresholds.cagr_retention, "percent")} retained · Sharpe {formatMetric(scenario.thresholds.sharpe_retention, "percent")} retained · drawdown ≤ {formatMetric(scenario.thresholds.maximum_drawdown, "percent")}
                            </small>
                          ) : null}
                        </td>
                        <td><StatusChip state={scenario.state} /></td>
                        <td>{scenario.score == null ? "—" : `${formatNumber(scenario.score)} / 100`}</td>
                        <td>{formatMetric(scenario.summary?.cagr, "percent")}</td>
                        <td>{formatMetric(scenario.summary?.sharpe_ratio, "number")}</td>
                        <td>{formatMetric(scenario.summary?.maximum_drawdown, "percent")}</td>
                        <td>{scenario.sharpe_retention == null ? "—" : formatMetric(scenario.sharpe_retention, "percent")}</td>
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
          <thead><tr><th>Strategy</th><th>Category</th><th>Status</th><th>Score</th><th>Trials</th><th>CAGR</th><th>Sharpe Ratio</th><th>Maximum Drawdown</th><th>Ending Equity</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td><strong>{row.strategy}</strong></td>
                <td><span className={`category-tag category-${row.category.split(" ")[0].toLowerCase()}`}>{row.categoryLabel || row.category}</span></td>
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

function flattenStrategySpec(value, prefix = "", result = {}) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => flattenStrategySpec(item, `${prefix}[${index}]`, result));
    return result;
  }
  if (value && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => {
      flattenStrategySpec(item, prefix ? `${prefix}.${key}` : key, result);
    });
    return result;
  }
  result[prefix] = value;
  return result;
}

function diffDisplayValue(path, value) {
  const key = path.split(".").at(-1)?.replace(/\[\d+\]/g, "") || path;
  return parameterValue(key, value);
}

function StrategyChangeSummary({ previousSpec, currentSpec, iteration }) {
  if (!currentSpec) return null;
  if (!previousSpec) {
    return (
      <div className="compiled-change-summary initial">
        <Code2 size={17} />
        <div><strong>Initial compiled strategy</strong><p>Trial {iteration} establishes the first validated parameter set injected into the fixed Python template.</p></div>
      </div>
    );
  }
  const before = flattenStrategySpec(previousSpec);
  const after = flattenStrategySpec(currentSpec);
  const ignored = new Set(["schema_version", "strategy_name", "thesis"]);
  const changes = [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter((path) => !ignored.has(path) && before[path] !== after[path])
    .map((path) => ({ path, before: before[path], after: after[path] }));
  return (
    <div className="compiled-change-panel">
      <div className="compiled-change-heading">
        <div><Code2 size={17} /><span><strong>Compiled code delta</strong><small>Trial {iteration - 1} → Trial {iteration}</small></span></div>
        <b>{changes.length} parameter change{changes.length === 1 ? "" : "s"}</b>
      </div>
      {changes.length ? (
        <div className="compiled-change-list">
          {changes.slice(0, 10).map((change) => (
            <div key={change.path}>
              <code>{change.path}</code>
              <span>{diffDisplayValue(change.path, change.before)}</span>
              <ArrowRight size={14} />
              <strong>{diffDisplayValue(change.path, change.after)}</strong>
            </div>
          ))}
          {changes.length > 10 ? <small>+ {changes.length - 10} additional injected parameter changes</small> : null}
        </div>
      ) : <p>No executable parameter changed; this trial reused the same compiled strategy configuration.</p>}
      <p className="compiled-change-note">The Python engine template is fixed. These JSON parameter changes are the exact executable differences between compiled trials.</p>
    </div>
  );
}

function IterationHistory({ candidate, showCodeChanges = false }) {
  const iterations = candidate?.iterations || [];
  if (!iterations.length) {
    return <p className="muted-copy">Iteration results will appear after the first template backtest.</p>;
  }
  return (
    <div className="review-history">
      {candidate.selection_origin === "prior_round_incumbent" ? (
        <div className="incumbent-retention-banner">
          <ShieldCheck size={17} />
          <span>
            Round {candidate.retained_from_round} remains this track&apos;s champion.
            The trials below are this round&apos;s challengers and were not selected.
          </span>
        </div>
      ) : null}
      {iterations.map((entry, index) => {
        const critique = entry.critique || {};
        const isBest = candidate.selection_origin !== "prior_round_incumbent"
          && Number(candidate.best_iteration) === Number(entry.iteration);
        return (
          <details key={entry.worker_run_id || entry.iteration} open={isBest || index === iterations.length - 1}>
            <summary>
              <span>Iteration {entry.iteration}</span>
              <span className={`decision ${isBest ? "decision-accept" : "decision-revise"}`}>
                {isBest ? "Best retained" : "Evaluated"}
              </span>
              <ChevronDown size={17} />
            </summary>
            <div className="review-body">
              <div className="review-metrics">
                <span>CAGR <strong>{formatMetric(entry.summary?.cagr, "percent")}</strong></span>
                <span>Sharpe <strong>{formatMetric(entry.summary?.sharpe_ratio, "number")}</strong></span>
                <span>Drawdown <strong>{formatMetric(entry.summary?.maximum_drawdown, "percent")}</strong></span>
                <span>Equity <strong>{formatMetric(entry.summary?.end_equity, "currency")}</strong></span>
              </div>
              {showCodeChanges ? (
                <StrategyChangeSummary
                  previousSpec={iterations[index - 1]?.strategy_spec}
                  currentSpec={entry.strategy_spec}
                  iteration={Number(entry.iteration)}
                />
              ) : null}
              {entry.strategy_spec ? (
                <div className="iteration-configuration">
                  <span className="parameter-subtitle">Parameters tested in this trial</span>
                  <StrategyParameters spec={entry.strategy_spec} />
                </div>
              ) : null}
              <BehaviorGrid evidence={entry.behavior_evidence} />
              {critique.diagnosis ? (
                <div className="review-authority">
                  <ShieldCheck size={17} />
                  <div><strong>Performance Critic</strong><span>{critique.diagnosis}</span></div>
                </div>
              ) : null}
              {critique.strengths?.length || critique.weaknesses?.length ? (
                <div className="critic-observation-grid">
                  <div className="critic-strengths">
                    <strong>What worked</strong>
                    <ul>{(critique.strengths || []).map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul>
                  </div>
                  <div className="critic-weaknesses">
                    <strong>What needs attention</strong>
                    <ul>{(critique.weaknesses || []).map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul>
                  </div>
                </div>
              ) : null}
              {critique.preserve?.length ? (
                <div className="preserve-row">
                  <strong>Preserve next round</strong>
                  <div>{critique.preserve.map((item, itemIndex) => <span key={itemIndex}>{item}</span>)}</div>
                </div>
              ) : null}
              {critique.recommended_changes?.length ? (
                <div className="repair-request">
                  <strong>Suggestions returned to Designer</strong>
                  <div className="change-list">
                    {critique.recommended_changes.map((change, changeIndex) => (
                      <div className="change-card" key={`${change.field}-${changeIndex}`}>
                        <div>
                          <code>{readableEnum(change.field.replaceAll(".", " / "))}</code>
                          <span>{readableEnum(change.direction)}</span>
                        </div>
                        <p>{change.reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {critique.overfitting_warning ? (
                <div className="overfitting-note">
                  <strong>Overfitting watch</strong>
                  <p>{critique.overfitting_warning}</p>
                </div>
              ) : null}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function DetailedGeneratedReviews({ candidates }) {
  if (!candidates?.length) return null;
  return (
    <section className="review-card">
      <div className="card-heading"><div><span className="section-kicker">Quality Review</span><h2>Generated Strategy Reviews</h2></div></div>
      <div className="candidate-review-grid">
        {candidates.map((candidate) => (
          <div className="candidate-review" key={candidate.track}>
            <div className="candidate-title">
              <div className="strategy-avatar"><ShieldCheck size={19} /></div>
              <div>
                <strong>{formatTrack(candidate.track)} Strategy</strong>
                <span>{candidate.iteration_count || 0} Trials · {candidate.selection_origin === "prior_round_incumbent"
                  ? `Round ${candidate.retained_from_round} champion`
                  : `best ${candidate.best_iteration || "pending"}`}</span>
              </div>
              <StatusChip state={candidate.state} />
            </div>
            {candidate.error && ["failed", "rejected"].includes(candidate.state) ? <div className="inline-error">{candidate.error}</div> : null}
            <IterationHistory candidate={candidate} />
          </div>
        ))}
      </div>
    </section>
  );
}

function GeneratedReviews({ candidates }) {
  if (!candidates?.length) return null;
  return (
    <section className="review-card">
      <div className="card-heading">
        <div><span className="section-kicker">Quality Snapshot</span><h2>Generated Strategy Reviews</h2></div>
        <p>Concise outcomes only. Open AI Forge for parameters, Critic feedback, and compiled changes.</p>
      </div>
      <div className="generated-review-summary-grid">
        {candidates.map((candidate) => {
          const currentBest = (candidate.iterations || []).find(
            (item) => Number(item.iteration) === Number(candidate.current_round_best_iteration || candidate.best_iteration),
          ) || (candidate.iterations || []).at(-1);
          const summary = candidate.summary || currentBest?.summary || {};
          const diagnosis = currentBest?.critique?.diagnosis;
          return (
            <article className="generated-review-summary" key={candidate.track}>
              <div className="candidate-title">
                <div className="strategy-avatar"><ShieldCheck size={19} /></div>
                <div>
                  <strong>{formatTrack(candidate.track)} Strategy</strong>
                  <span>
                    {candidate.iteration_count || 0} trials · {candidate.selection_origin === "prior_round_incumbent"
                      ? `Round ${candidate.retained_from_round} champion retained`
                      : `Trial ${candidate.best_iteration || "pending"} retained`}
                  </span>
                </div>
                <StatusChip state={candidate.state} />
              </div>
              <div className="generated-review-metrics">
                <span>CAGR<strong>{formatMetric(summary.cagr, "percent")}</strong></span>
                <span>Sharpe<strong>{formatMetric(summary.sharpe_ratio, "number")}</strong></span>
                <span>Drawdown<strong>{formatMetric(summary.maximum_drawdown, "percent")}</strong></span>
              </div>
              {diagnosis ? <p>{diagnosis}</p> : null}
              {candidate.error && ["failed", "rejected"].includes(candidate.state) ? <div className="inline-error">{candidate.error}</div> : null}
              <small className="forge-detail-hint">Full iteration lineage is available in AI Forge.</small>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function BacktestContract({ run }) {
  const settings = run?.settings || {};
  const symbols = settings.symbols || [];
  const reusedBaselines = (run?.baselines || []).some(
    (item) => item.baseline_execution === "reused",
  );
  return (
    <section className="backtest-contract-card">
      <div className="backtest-contract-heading">
        <div>
          <span className="section-kicker">Frozen Experiment Contract</span>
          <h2>This backtest used</h2>
        </div>
        <div className="contract-context-badges">
          {run?.round_number ? <span>Battle Round {run.round_number}</span> : null}
          {reusedBaselines ? <span>Round 1 baselines reused</span> : null}
        </div>
      </div>
      <div className="backtest-contract-grid">
        <div>
          <span>Backtest Window</span>
          <strong>
            <span className="contract-date">{settings.start_date || "—"}</span>
            <ArrowRight size={14} />
            <span className="contract-date">{settings.end_date || "—"}</span>
          </strong>
        </div>
        <div>
          <span>Initial Cash</span>
          <strong>{formatMetric(settings.initial_cash, "currency")}</strong>
        </div>
        <div>
          <span>Benchmark</span>
          <strong>{settings.benchmark || "—"}</strong>
        </div>
        <div>
          <span>Trading Assumptions</span>
          <strong>
            {settings.transaction_cost_bps ?? "—"} bps fee · {settings.slippage_bps ?? "—"} bps slippage
          </strong>
        </div>
      </div>
      <div className="contract-symbols">
        <div>
          <span>Selected Stock Universe</span>
          <strong>{symbols.length} stocks</strong>
        </div>
        <div className="contract-symbol-list">
          {symbols.length
            ? symbols.map((symbol) => <span key={symbol}>{symbol}</span>)
            : <em>No symbols recorded</em>}
        </div>
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
      <BacktestContract run={run} />
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
        description="Each completed Forge Run is one round. The deterministic Judge prioritizes Sharpe and CAGR, then checks drawdown, volatility, cost, execution evidence, and explainability."
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
                      <IterationHistory candidate={candidate} />
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
      if (item.source_code) result.push({ id: item.track, label: `${formatTrack(item.track)} Strategy`, category: "Template-compiled Strategy", source: item.source_code, state: item.state });
    }
    return result;
  }, [run]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (sources.length && !sources.some((item) => item.id === selected)) setSelected(sources[0].id);
  }, [sources, selected]);
  const current = sources.find((item) => item.id === selected);
  const [copied, setCopied] = useState("");
  const copyCurrent = async () => {
    if (!current?.source) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(current.source);
      } else {
        const fallback = document.createElement("textarea");
        fallback.value = current.source;
        fallback.style.position = "fixed";
        fallback.style.opacity = "0";
        document.body.appendChild(fallback);
        fallback.select();
        document.execCommand("copy");
        fallback.remove();
      }
      setCopied(current.id);
      window.setTimeout(() => setCopied(""), 1800);
    } catch {
      setCopied("");
    }
  };

  return (
    <>
      <PageHeader eyebrow="Source Review" title="Strategy Code" description="Inspect the complete Python source used for each submitted strategy." />
      {!run ? <EmptyRun onBuild={onBuild} /> : (
        <section className="source-workspace">
          <div className="source-tabs">
            {sources.map((item) => <button key={item.id} className={selected === item.id ? "active" : ""} onClick={() => setSelected(item.id)}><Code2 size={16} /><span>{item.label}<small>{item.category}</small></span></button>)}
          </div>
          <div className="source-viewer">
            {current ? (
              <>
                <div className="source-header">
                  <div><span>{current.category}</span><h2>{current.label}</h2></div>
                  <div className="source-header-actions">
                    <StatusChip state={current.state} />
                    <button type="button" className={`copy-code-button ${copied === current.id ? "copied" : ""}`} onClick={copyCurrent}>
                      {copied === current.id ? <Check size={16} /> : <Copy size={16} />}
                      {copied === current.id ? "Copied" : "Copy code"}
                    </button>
                  </div>
                </div>
                <PythonCodeBlock source={current.source} />
              </>
            ) : <div className="chart-empty"><Code2 size={22} /><span>Source code is not available yet.</span></div>}
          </div>
        </section>
      )}
    </>
  );
}

function AuthWorkspace({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      window.localStorage.setItem("alphaforge_token", result.token);
      onAuthenticated(result.user);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card">
        <BrandMark />
        <p className="eyebrow">AlphaForge Arena</p>
        <h1>Build, learn, and win a best-of-five strategy battle.</h1>
        <p>Your account keeps every round, score, strategy revision, and learning review together.</p>
        <div className="auth-tabs">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Sign in</button>
          <button className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>Create account</button>
        </div>
        <form onSubmit={submit}>
          <Field label="Username">
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </Field>
          <Field label="Password" hint="At least 8 characters">
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </Field>
          {error ? <div className="error-banner">{error}</div> : null}
          <button className="primary-button" disabled={busy || username.trim().length < 3 || password.length < 8}>
            {busy ? <RefreshCw className="spin" size={17} /> : <ArrowRight size={17} />}
            {mode === "login" ? "Enter Battle Lobby" : "Create Account"}
          </button>
        </form>
      </section>
    </main>
  );
}

function BattleLobby({
  battles,
  activeBattle,
  loading,
  error,
  onCreate,
  onOpen,
  onStartRound,
  onOpenRound,
  onDelete,
}) {
  const [name, setName] = useState("My Alpha Battle");
  const [creating, setCreating] = useState(false);

  const create = async (event) => {
    event.preventDefault();
    setCreating(true);
    try {
      await onCreate(name);
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Battle Lobby"
        title="Your strategy match history"
        description="Each match is first to three wins, with at most five rounds. Every round uses the same transparent scoring policy."
      />
      <section className="battle-lobby-grid">
        <div className="battle-list-panel">
          <div className="panel-title"><History size={19} /><h2>Saved Battles</h2></div>
          {loading ? <div className="loading-block"><RefreshCw className="spin" size={18} /> Loading battles</div> : null}
          {error ? <div className="error-banner">{error}</div> : null}
          {!loading && !battles.length ? <div className="empty-panel">No battles yet. Create your first match.</div> : null}
          {battles.map((battle) => (
            <div key={battle.id} className={`battle-list-item ${activeBattle?.id === battle.id ? "active" : ""}`}>
              <button className="battle-open-button" onClick={() => onOpen(battle.id)}>
                <span><strong>{battle.name}</strong><small>{battle.round_count}/5 rounds · {statusLabel(battle.state)}</small></span>
                <b>{battle.human_wins} <em>—</em> {battle.ai_wins}</b>
              </button>
              <button className="battle-delete-button" aria-label={`Delete ${battle.name}`} onClick={() => onDelete(battle)}><XCircle size={18} /></button>
            </div>
          ))}
          <form className="new-battle-form" onSubmit={create}>
            <Field label="New battle name">
              <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
            </Field>
            <button className="primary-button" disabled={creating || !name.trim()}>
              {creating ? <RefreshCw className="spin" size={17} /> : <Play size={17} />}
              Start New Battle
            </button>
          </form>
        </div>

        <div className="battle-detail-panel">
          {!activeBattle ? (
            <div className="empty-panel"><Trophy size={28} /> Select a battle to see its rounds.</div>
          ) : (
            <>
              <div className="battle-scoreboard">
                <div><small>You</small><strong>{activeBattle.human_wins}</strong></div>
                <span>BEST OF FIVE<small>First to 3 wins</small></span>
                <div><small>AI Forge</small><strong>{activeBattle.ai_wins}</strong></div>
              </div>
              <div className="round-timeline">
                {[1, 2, 3, 4, 5].map((number) => {
                  const round = activeBattle.rounds?.find((item) => item.round_number === number);
                  return (
                    <button key={number} disabled={!round} className={round ? `round-node winner-${round.winner || "pending"}` : "round-node empty"} onClick={() => round && onOpenRound(round.forge_run_id)}>
                      <span>R{number}</span>
                      <small>{round ? (round.state === "completed" ? `${round.winner === "human" ? "You" : "AI"} won` : statusLabel(round.state)) : "Not played"}</small>
                    </button>
                  );
                })}
              </div>
              {activeBattle.rounds?.length ? (() => {
                const latest = activeBattle.rounds[activeBattle.rounds.length - 1];
                const memory = latest.coach_memory;
                const recommendations = latest.education?.human_feedback?.parameter_recommendations || [];
                return (
                  <>
                    {recommendations.length ? (
                      <div className="human-recommendation-card">
                        <div className="panel-title"><Settings2 size={19} /><h3>Recommended Human settings for Round {latest.round_number + 1}</h3></div>
                        <p>These values respond to your last result. Apply them together or use them as a one-change experiment.</p>
                        <div className="recommendation-list">
                          {recommendations.map((item) => (
                            <article key={item.parameter_path}>
                              <span>{item.label}<small>{item.target_metric}</small></span>
                              <div><code>{String(item.current_value)}</code><ArrowRight size={15} /><strong>{String(item.recommended_value)}</strong></div>
                              <p>{item.reason}</p>
                            </article>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="coach-memory-card">
                      <div className="panel-title"><Lightbulb size={19} /><h3>AI Coach learned after Round {latest.round_number}</h3></div>
                      {memory ? (
                        <>
                          <p>{memory.round_summary}</p>
                          <div className="coach-track-lessons">
                            {(memory.track_lessons || []).map((lesson) => (
                              <details className="coach-track-lesson" key={lesson.track}>
                                <summary>
                                  <div className="coach-lesson-heading">
                                    <strong>{formatTrack(lesson.track)}</strong>
                                    {lesson.next_move ? <span className={`coach-move coach-move-${lesson.next_move}`}>{readableEnum(lesson.next_move)}</span> : null}
                                  </div>
                                  <p className="coach-lesson-preview">{lesson.evidence_summary}</p>
                                  <span className="coach-lesson-expand">
                                    <span>View evidence &amp; next plan</span>
                                    <ChevronDown size={17} />
                                  </span>
                                </summary>
                                <div className="coach-lesson-body">
                                  <p>{lesson.evidence_summary}</p>
                                  {lesson.decision_reason ? <p className="coach-decision-reason">{lesson.decision_reason}</p> : null}
                                  <div className="coach-change-scope">
                                    {lesson.change_scope ? <span>Change: <b>{readableEnum(lesson.change_scope)}</b></span> : null}
                                    {lesson.parameter_change_budget ? <span>Budget: <b>{lesson.parameter_change_budget} parameters</b></span> : null}
                                  </div>
                                  <ul>
                                    {(lesson.next_hypotheses || []).map((hypothesis, index) => <li key={index}>{hypothesis}</li>)}
                                  </ul>
                                </div>
                              </details>
                            ))}
                          </div>
                          <p className="overfit-note">{memory.overfitting_guard}</p>
                        </>
                      ) : <p>{latest.coach_state === "pending" ? "The Coach is converting this round's AI evidence into next-round guidance…" : "Coaching becomes available after a completed round."}</p>}
                    </div>
                  </>
                );
              })() : (
                <div className="round-rules"><strong>How a round works</strong><p>You choose or edit a strategy. Four public baselines and three AI tracks run under the same contract. The eligible Human and best AI scorecards decide the round.</p></div>
              )}
              {activeBattle.state === "completed" ? (
                <div className="battle-finished"><Trophy size={24} /><strong>{activeBattle.winner === "human" ? "You won the match!" : "AI Forge won this match."}</strong></div>
              ) : (
                <button className="primary-button battle-next-button" disabled={!activeBattle.can_start_round} onClick={() => onStartRound(activeBattle.rounds?.[activeBattle.rounds.length - 1]?.education?.human_feedback?.parameter_recommendations || [])}>
                  <Play size={17} />
                  {activeBattle.round_count
                    ? `${activeBattle.rounds?.[activeBattle.rounds.length - 1]?.education?.human_feedback?.parameter_recommendations?.length ? "Apply Suggestions & " : ""}Prepare Round ${activeBattle.next_round}`
                    : "Prepare Round 1"}
                </button>
              )}
            </>
          )}
        </div>
      </section>
    </>
  );
}

function BattleArenaWorkspace({ battle, onLobby, onOpenRound }) {
  if (!battle) {
    return (
      <>
        <PageHeader eyebrow="PK Arena" title="Five-round match details" description="Open a saved battle to review its complete head-to-head record." />
        <div className="empty-state"><div className="empty-icon"><Trophy size={28} /></div><h2>No battle selected</h2><p>Select a battle from the lobby first.</p><button className="primary-button" onClick={onLobby}><ArrowRight size={17} /> Open Battle Lobby</button></div>
      </>
    );
  }
  return (
    <>
      <PageHeader
        eyebrow="PK Arena · Best of Five"
        title={battle.name}
        description={`You ${battle.human_wins} — ${battle.ai_wins} AI · ${battle.round_count} of 5 rounds completed`}
        actions={<button className="secondary-button" onClick={onLobby}><History size={17} /> Battle History</button>}
      />
      <section className="arena-contract-card">
        <div><ShieldCheck size={21} /><span><strong>Frozen battle contract</strong><small>Every round uses exactly the same universe and backtest assumptions.</small></span></div>
        {battle.contract ? (
          <dl>
            <div><dt>Stocks</dt><dd>{battle.contract.symbols?.join(", ")}</dd></div>
            <div><dt>Window</dt><dd>{battle.contract.start_date} → {battle.contract.end_date}</dd></div>
            <div><dt>Cash / Benchmark</dt><dd>{formatMetric(battle.contract.initial_cash, "currency")} · {battle.contract.benchmark}</dd></div>
            <div><dt>Costs</dt><dd>{battle.contract.transaction_cost_bps} bps fee · {battle.contract.slippage_bps} bps slippage</dd></div>
          </dl>
        ) : <p>The contract will freeze when Round 1 starts.</p>}
      </section>
      <section className="five-round-detail">
        {[1, 2, 3, 4, 5].map((number) => {
          const round = battle.rounds?.find((item) => item.round_number === number);
          if (!round) {
            return <article className="arena-round-card future" key={number}><div className="arena-round-heading"><span>Round {number}</span><small>Not played</small></div></article>;
          }
          const human = round.result?.human || {};
          const champion = round.result?.battle_analysis?.ai_champion || {};
          const recommendations = round.education?.human_feedback?.parameter_recommendations || [];
          return (
            <article className={`arena-round-card winner-${round.winner || "pending"}`} key={number}>
              <div className="arena-round-heading">
                <div><span>Round {number}</span><h2>{round.state === "completed" ? `${round.winner === "human" ? "You" : "AI"} won this round` : statusLabel(round.state)}</h2></div>
                <div className="round-score"><strong>{formatNumber(round.human_score)}</strong><small>Human</small><em>vs</em><strong>{formatNumber(round.ai_score)}</strong><small>AI</small></div>
                <button className="secondary-button" onClick={() => onOpenRound(round.forge_run_id)}>Open full results <ArrowRight size={15} /></button>
              </div>
              {round.state === "completed" ? (
                <>
                  <div className="round-comparison-table">
                    <div className="table-head"><span>Contestant</span><span>CAGR</span><span>Sharpe</span><span>Drawdown</span><span>Score</span></div>
                    <div><strong>Your strategy</strong><span>{formatMetric(human.summary?.cagr, "percent")}</span><span>{formatMetric(human.summary?.sharpe_ratio, "number")}</span><span>{formatMetric(human.summary?.maximum_drawdown, "percent")}</span><span>{formatNumber(round.human_score)}</span></div>
                    <div><strong>AI · {formatTrack(round.ai_champion_track)}</strong><span>{formatMetric(champion.summary?.cagr, "percent")}</span><span>{formatMetric(champion.summary?.sharpe_ratio, "number")}</span><span>{formatMetric(champion.summary?.maximum_drawdown, "percent")}</span><span>{formatNumber(round.ai_score)}</span></div>
                  </div>
                  {recommendations.length ? (
                    <div className="arena-round-recommendations">
                      <strong>Recommended before the next round</strong>
                      {recommendations.map((item) => <p key={item.parameter_path}><span>{item.label}</span><code>{String(item.current_value)}</code><ArrowRight size={14} /><b>{String(item.recommended_value)}</b><small>{item.reason}</small></p>)}
                    </div>
                  ) : null}
                  {round.coach_memory?.round_summary ? <p className="arena-coach-summary"><Lightbulb size={17} /> <span><strong>AI Coach:</strong> {round.coach_memory.round_summary}</span></p> : null}
                </>
              ) : null}
            </article>
          );
        })}
      </section>
    </>
  );
}

export default function App() {
  const initialRunId = new URLSearchParams(window.location.search).get("run_id") || "";
  const [view, setView] = useState(initialRunId ? "results" : "lobby");
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [battles, setBattles] = useState([]);
  const [activeBattle, setActiveBattle] = useState(null);
  const [battleLoading, setBattleLoading] = useState(false);
  const [battleError, setBattleError] = useState("");
  const [roundSeed, setRoundSeed] = useState(null);
  const [roundRecommendations, setRoundRecommendations] = useState([]);
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

  const loadBattles = useCallback(async () => {
    setBattleLoading(true);
    setBattleError("");
    try {
      setBattles(await apiRequest("/battles"));
    } catch (error) {
      setBattleError(error.message);
    } finally {
      setBattleLoading(false);
    }
  }, []);

  const loadBattle = useCallback(async (battleId) => {
    if (!battleId) return null;
    try {
      const detail = await apiRequest(`/battles/${encodeURIComponent(battleId)}`);
      setActiveBattle(detail);
      setRoundSeed(null);
      setRoundRecommendations([]);
      setBattles((current) => [detail, ...current.filter((item) => item.id !== detail.id)]);
      return detail;
    } catch (error) {
      setBattleError(error.message);
      return null;
    }
  }, []);

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

  useEffect(() => {
    const token = window.localStorage.getItem("alphaforge_token");
    if (!token) {
      setAuthLoading(false);
      return;
    }
    apiRequest("/auth/me")
      .then(setUser)
      .catch(() => window.localStorage.removeItem("alphaforge_token"))
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    if (user) loadBattles();
  }, [user, loadBattles]);

  const loadRun = useCallback(async (id, { quiet = false } = {}) => {
    if (!id) return;
    if (!quiet) setRunLoading(true);
    setRunError("");
    try {
      const result = await apiRequest(`/forge-runs/${encodeURIComponent(id)}`);
      setRun(result);
      setRunId(id);
      setRunQuery(id);
      if (result.battle_id) loadBattle(result.battle_id);
    } catch (error) {
      setRunError(error.message);
      if (!quiet) setRun(null);
    } finally {
      if (!quiet) setRunLoading(false);
    }
  }, [loadBattle]);

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
    const educationActive = run?.battle_analysis?.education_summary?.llm_state === "pending";
    const latestRound = activeBattle?.rounds?.[activeBattle.rounds.length - 1];
    const coachActive = latestRound?.forge_run_id === runId && latestRound?.coach_state === "pending";
    if (!runId || (run && TERMINAL_RUN_STATES.has(run.state) && !robustnessActive && !educationActive && !coachActive)) return undefined;
    const timer = window.setInterval(() => loadRun(runId, { quiet: true }), 3000);
    return () => window.clearInterval(timer);
  }, [runId, run, activeBattle, loadRun]);

  useEffect(() => {
    if (view === "arena") loadHistory();
  }, [view, loadHistory]);

  const openRun = (id) => {
    setView("results");
    loadRun(id);
  };

  const handleCreated = (created) => {
    setRoundSeed(null);
    setRoundRecommendations([]);
    setRun(created);
    setRunId(created.run_id);
    setRunQuery(created.run_id);
    setView("results");
    if (created.battle_id) loadBattle(created.battle_id);
  };

  const createBattle = async (name) => {
    const battle = await apiRequest("/battles", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setActiveBattle(battle);
    setRoundSeed(null);
    setRoundRecommendations([]);
    setBattles((current) => [battle, ...current]);
    setView("build");
  };

  const startNextRound = (recommendations = []) => {
    const latest = activeBattle?.rounds?.[activeBattle.rounds.length - 1];
    const strategy = latest?.human_strategy
      ? JSON.parse(JSON.stringify(latest.human_strategy))
      : null;
    if (strategy?.mode === "guided") {
      for (const recommendation of recommendations) {
        const [scope, field] = String(recommendation.parameter_path || "").split(".");
        if (scope === "guided" && field && strategy.guided) {
          strategy.guided[field] = recommendation.recommended_value;
        }
      }
    }
    setRoundSeed(strategy);
    setRoundRecommendations(recommendations);
    setRun(null);
    setRunId("");
    setRunQuery("");
    setView("build");
  };

  const deleteBattle = async (battle) => {
    if (!window.confirm(`Delete "${battle.name}" and all of its rounds? This cannot be undone.`)) return;
    try {
      await apiRequest(`/battles/${encodeURIComponent(battle.id)}`, { method: "DELETE" });
      setBattles((current) => current.filter((item) => item.id !== battle.id));
      if (activeBattle?.id === battle.id) {
        setActiveBattle(null);
        setRun(null);
        setRunId("");
        setRunQuery("");
        setRoundRecommendations([]);
      }
    } catch (error) {
      setBattleError(error.message);
    }
  };

  const logout = async () => {
    try {
      await apiRequest("/auth/logout", { method: "POST" });
    } catch {
      // Local logout remains valid when the backend is temporarily unavailable.
    }
    window.localStorage.removeItem("alphaforge_token");
    setUser(null);
    setBattles([]);
    setActiveBattle(null);
    setRun(null);
    setRunId("");
    setRunQuery("");
    setRoundRecommendations([]);
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

  if (authLoading) {
    return <div className="app-loading"><RefreshCw className="spin" size={24} /> Loading AlphaForge</div>;
  }
  if (!user) {
    return <AuthWorkspace onAuthenticated={(authenticated) => { setUser(authenticated); setView("lobby"); }} />;
  }

  const previousHumanStrategy = roundSeed || (activeBattle?.rounds?.length
    ? activeBattle.rounds[activeBattle.rounds.length - 1].human_strategy
    : null);

  return (
    <div className="app-shell">
      <Sidebar view={view} onView={setView} runId={runId} onOpenRun={openRun} serviceStatus={serviceStatus} user={user} onLogout={logout} />
      <main className="main-content">
        {!["lobby", "build", "arena"].includes(view) ? (
          <BattleRoundSwitcher battle={activeBattle} runId={runId} onSwitch={loadRun} />
        ) : null}
        {view === "lobby" ? <BattleLobby battles={battles} activeBattle={activeBattle} loading={battleLoading} error={battleError} onCreate={createBattle} onOpen={loadBattle} onStartRound={startNextRound} onOpenRound={openRun} onDelete={deleteBattle} /> : null}
        {view === "build" ? (
          activeBattle?.state === "active"
          && activeBattle?.can_start_round
          && !(run?.battle_id === activeBattle.id && !TERMINAL_RUN_STATES.has(run.state)) ? (
            <BuildWorkspace key={`${activeBattle.id}-${activeBattle.next_round}`} catalog={catalog} loadingCatalog={catalogLoading} onCreated={handleCreated} battle={activeBattle} initialHumanStrategy={previousHumanStrategy} recommendations={roundRecommendations} />
          ) : (
            <div className="empty-state"><div className="empty-icon"><Trophy size={28} /></div><h2>Open the Battle Lobby</h2><p>Create a battle, wait for the current round review, or choose an active match before preparing another round.</p><button className="primary-button" onClick={() => setView("lobby")}><ArrowRight size={17} /> Open Battle Lobby</button></div>
          )
        ) : null}
        {view === "results" ? <ResultsWorkspace run={run} loading={runLoading} error={runError} onRefresh={() => loadRun(runId)} onBuild={() => setView("build")} onLearning={() => setView("learning")} /> : null}
        {view === "forge" ? <AIForgeWorkspace run={run} onBuild={() => setView("build")} /> : null}
        {view === "robustness" ? <RobustnessWorkspace run={run} loading={runLoading} error={runError} onBuild={() => setView("build")} onStart={startRobustness} /> : null}
        {view === "learning" ? <LearningWorkspace run={run} loading={runLoading} error={runError} onResults={() => setView("results")} onBuild={() => setView("build")} /> : null}
        {view === "arena" ? <BattleArenaWorkspace battle={activeBattle} onLobby={() => setView("lobby")} onOpenRound={openRun} /> : null}
        {view === "code" ? <CodeWorkspace run={run} onBuild={() => setView("build")} /> : null}
      </main>
    </div>
  );
}
