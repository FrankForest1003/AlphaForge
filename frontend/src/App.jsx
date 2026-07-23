import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Code2,
  FlaskConical,
  Gauge,
  Layers3,
  Play,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  UserRound,
  XCircle,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_ROOT = "/api/v1";
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
  const rows = (run.baselines || []).map((item) => ({
    ...item,
    id: `baseline-${item.name}`,
    strategy: item.name,
    category: "Reference Strategy",
    revisions: null,
  }));
  if (run.human) {
    rows.push({
      ...run.human,
      id: "human",
      strategy: "Human Strategy",
      category: "Human Strategy",
      revisions: null,
    });
  }
  for (const item of run.candidates || []) {
    rows.push({
      ...item,
      id: `generated-${item.track}`,
      strategy: `${formatTrack(item.track)} Strategy`,
      category: "Generated Strategy",
      revisions: item.repair_attempts || 0,
    });
  }
  return rows;
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
        <button className={view === "results" ? "active" : ""} onClick={() => onView("results")}>
          <BarChart3 size={18} />
          Results
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
      current.includes(ticker) ? current.filter((item) => item !== ticker) : [...current, ticker],
    );
  };

  const valid =
    symbols.length > 0 &&
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
            <p>Select the investment universe and shared backtest assumptions.</p>
          </div>
          <div className="selection-count">{symbols.length} Selected</div>
        </div>

        <div className="market-layout">
          <div className="universe-panel">
            <div className="section-toolbar">
              <div>
                <h3>Stock Candidate Pool</h3>
                <p>Strategies may choose any subset of the selected stocks.</p>
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

      <div className="launch-bar">
        <div>
          <strong>Ready To Start</strong>
          <span>{symbols.length ? `${symbols.length} stocks selected` : "Select at least one stock"} · {humanMode === "guided" ? "Guided Setup" : "Complete Python Code"}</span>
          {startDate >= endDate ? <span className="validation-message">The Start Date must be earlier than the End Date.</span> : null}
          {error ? <span className="validation-message">{error}</span> : null}
        </div>
        <button className="primary-button" disabled={!valid || submitting} onClick={submit}>
          {submitting ? <RefreshCw className="spin" size={18} /> : <Play size={18} fill="currentColor" />}
          {submitting ? "Starting Backtest" : "Start Backtest"}
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

function ResultsTable({ rows }) {
  return (
    <section className="table-card">
      <div className="card-heading"><div><span className="section-kicker">Comparable Results</span><h2>Strategy Comparison</h2></div></div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Strategy</th><th>Category</th><th>Status</th><th>Revisions</th><th>CAGR</th><th>Sharpe Ratio</th><th>Maximum Drawdown</th><th>Ending Equity</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td><strong>{row.strategy}</strong></td>
                <td><span className={`category-tag category-${row.category.split(" ")[0].toLowerCase()}`}>{row.category}</span></td>
                <td><StatusChip state={row.state} /></td>
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
  ];
  return (
    <div className="behavior-grid">
      {items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{formatNumber(value)}</strong></div>)}
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
              <div><strong>{formatTrack(candidate.track)} Strategy</strong><span>{candidate.repair_attempts || 0} Revisions</span></div>
              <StatusChip state={candidate.state} />
            </div>
            {candidate.error && candidate.state === "failed" ? <div className="inline-error">{candidate.error}</div> : null}
            <ReviewHistory history={candidate.acceptance_history} />
          </div>
        ))}
      </div>
    </section>
  );
}

function ResultsWorkspace({ run, loading, error, onRefresh, onBuild }) {
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
        actions={<button className="secondary-button" onClick={onRefresh} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} /> Refresh</button>}
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
      <MetricChart rows={rows} />
      <ResultsTable rows={rows} />
      <GeneratedReviews candidates={run.candidates} />
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

  useEffect(() => {
    if (initialRunId) loadRun(initialRunId);
  }, [initialRunId, loadRun]);

  useEffect(() => {
    if (!runId || (run && TERMINAL_RUN_STATES.has(run.state))) return undefined;
    const timer = window.setInterval(() => loadRun(runId, { quiet: true }), 3000);
    return () => window.clearInterval(timer);
  }, [runId, run, loadRun]);

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

  return (
    <div className="app-shell">
      <Sidebar view={view} onView={setView} runId={runId} onOpenRun={openRun} serviceStatus={serviceStatus} />
      <main className="main-content">
        {view === "build" ? <BuildWorkspace catalog={catalog} loadingCatalog={catalogLoading} onCreated={handleCreated} /> : null}
        {view === "results" ? <ResultsWorkspace run={run} loading={runLoading} error={runError} onRefresh={() => loadRun(runId)} onBuild={() => setView("build")} /> : null}
        {view === "code" ? <CodeWorkspace run={run} onBuild={() => setView("build")} /> : null}
      </main>
    </div>
  );
}
