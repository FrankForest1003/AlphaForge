from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from api_client import AlphaForgeAPI, AlphaForgeAPIError


st.set_page_config(
    page_title="AlphaForge Studio",
    page_icon="⚒️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(145deg, #f7f9fc 0%, #eef3f8 100%); }
    [data-testid="stSidebar"] { background: #101827; }
    [data-testid="stSidebar"] * { color: #e8eef8; }
    .af-hero {
        padding: 1.5rem 1.7rem; border-radius: 1.25rem; color: white;
        background: linear-gradient(120deg, #101827 0%, #1f3a5f 65%, #1c7f75 100%);
        box-shadow: 0 18px 50px rgba(16, 24, 39, .15); margin-bottom: 1.1rem;
    }
    .af-hero h1 { margin: 0; font-size: 2.15rem; letter-spacing: -.04em; }
    .af-hero p { margin: .45rem 0 0; color: #cbd9ed; font-size: 1rem; }
    .af-kicker { color: #6ee7d2; font-weight: 700; letter-spacing: .08em; font-size: .74rem; }
    .af-card {
        border: 1px solid #dbe4ef; border-radius: 1rem; padding: 1rem 1.1rem;
        background: rgba(255,255,255,.86); min-height: 7rem;
    }
    .af-card strong { color: #17243a; }
    .af-card span { color: #617089; font-size: .9rem; }
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,.88); border: 1px solid #dbe4ef;
        padding: .8rem 1rem; border-radius: .9rem;
    }
    div[data-testid="stButton"] button { border-radius: .72rem; font-weight: 650; }
    div[data-testid="stTabs"] button { font-weight: 650; }
    div[data-testid="stCodeBlock"] { border-radius: .9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


TERMINAL_RUN_STATES = {"completed", "failed"}
FINISHED_ITEM_STATES = {
    "accepted",
    "rejected",
    "failed",
    "completed",
    "completed_with_data_gaps",
    "timeout",
}

HUMAN_CODE_STARTER = '''from datetime import datetime

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
'''


api = AlphaForgeAPI()


def metric(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    number = float(value)
    return f"{number * 100:.2f}%" if percent else f"{number:.3f}"


def result_rows(run: dict[str, Any]) -> pd.DataFrame:
    items: list[dict[str, Any]] = []
    items.extend(
        {**item, "strategy": item.get("name"), "kind": "Reference"}
        for item in run.get("baselines", [])
    )
    human = run.get("human") or {}
    if human:
        items.append({**human, "strategy": "Your strategy", "kind": "Your strategy"})
    items.extend(
        {**item, "strategy": item.get("track"), "kind": "Generated"}
        for item in run.get("candidates", [])
    )
    rows = []
    for item in items:
        summary = item.get("summary") or {}
        rows.append(
            {
                "Strategy": item.get("strategy"),
                "Type": item.get("kind"),
                "State": item.get("state"),
                "Revisions": item.get("repair_attempts", "—"),
                "CAGR": metric(summary.get("cagr"), percent=True),
                "Sharpe": metric(summary.get("sharpe_ratio")),
                "Max drawdown": metric(summary.get("maximum_drawdown"), percent=True),
                "End equity": (
                    f"${float(summary['end_equity']):,.2f}"
                    if summary.get("end_equity") is not None
                    else "—"
                ),
            }
        )
    return pd.DataFrame(rows)


def acceptance_table(report: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Check": check.get("id"),
                "Status": check.get("status"),
                "Evidence": "\n".join(check.get("evidence") or []),
                "Reason": check.get("reason"),
            }
            for check in report.get("checks", [])
        ]
    )


def load_starter_code() -> None:
    st.session_state["human_code"] = HUMAN_CODE_STARTER


def go_to(view: str) -> None:
    st.session_state["next_workspace_view"] = view


def run_progress(run: dict[str, Any]) -> tuple[int, int]:
    states = [item.get("state") for item in run.get("baselines", [])]
    states.append((run.get("human") or {}).get("state"))
    states.extend(item.get("state") for item in run.get("candidates", []))
    return sum(state in FINISHED_ITEM_STATES for state in states), len(states)


def render_behavior(evidence: dict[str, Any]) -> None:
    if not evidence:
        st.caption("Behavior evidence will appear after the backtest completes.")
        return
    cols = st.columns(4)
    cols[0].metric("Filled orders", int(evidence.get("filled_order_count", 0)))
    cols[1].metric("Invested snapshots", int(evidence.get("invested_snapshot_count", 0)))
    cols[2].metric(
        "Max gross exposure",
        f"{float(evidence.get('max_gross_exposure', 0)):.3f}",
    )
    cols[3].metric("Rebalances", int(evidence.get("rebalance_count", 0)))
    symbols = evidence.get("traded_symbols") or []
    st.caption("Traded symbols: " + (", ".join(symbols) if symbols else "—"))


def render_human(human: dict[str, Any]) -> None:
    top = st.columns([1, 1, 2])
    top[0].metric("State", human.get("state", "waiting"))
    top[1].metric("Input mode", human.get("mode", "—"))
    guided = human.get("guided")
    if guided:
        top[2].caption(
            f"{guided['signal']} · {guided['lookback_days']} days · "
            f"{guided['rebalance']} · top {guided['holdings']}"
        )
    if human.get("error"):
        st.error(human["error"])
    render_behavior(human.get("behavior_evidence") or {})
    if human.get("source_code"):
        st.code(human["source_code"], language="python", line_numbers=True)


def render_candidate(candidate: dict[str, Any]) -> None:
    usage = candidate.get("usage") or {}
    cols = st.columns(3)
    cols[0].metric("State", candidate.get("state", "waiting"))
    cols[1].metric("Revisions", candidate.get("repair_attempts", 0))
    cols[2].metric("Total tokens", f"{int(usage.get('total_tokens', 0) or 0):,}")
    if candidate.get("error"):
        st.error(candidate["error"])
    acceptance_history = candidate.get("acceptance_history") or []
    if acceptance_history:
        st.markdown("#### Review history")
        for item in acceptance_history:
            report = item.get("report") or {}
            decision = report.get("decision", "unknown")
            with st.expander(
                f"Attempt {item.get('attempt')} · {decision}",
                expanded=item is acceptance_history[-1],
            ):
                st.caption(f"Backtest run: {item.get('worker_run_id', '—')}")
                st.dataframe(
                    acceptance_table(report),
                    hide_index=True,
                    use_container_width=True,
                )
                if report.get("repair_request"):
                    st.warning(report["repair_request"])
                render_behavior(item.get("behavior_evidence") or {})
    if candidate.get("source_code"):
        st.markdown("#### Complete source")
        st.code(candidate["source_code"], language="python", line_numbers=True)
    else:
        st.caption("Source code has not been generated yet.")


def render_run_dashboard(run: dict[str, Any]) -> None:
    done, total = run_progress(run)
    total_tokens = sum(
        int((item.get("usage") or {}).get("total_tokens", 0) or 0)
        for item in run.get("candidates", [])
    )
    header = st.columns([2.5, 1, 1, 1])
    header[0].subheader(f"Run · {run.get('run_id', '—')}")
    header[0].caption(run.get("stage", ""))
    header[1].metric("Run state", run.get("state", "unknown"))
    header[2].metric("Finished", f"{done}/{total}")
    header[3].metric("API tokens", f"{total_tokens:,}")
    st.progress(done / total if total else 0.0)
    if run.get("error"):
        st.error(run["error"])

    overview_tab, human_tab, designers_tab = st.tabs(
        ["Overview", "Your strategy", "Generated strategies"]
    )
    with overview_tab:
        st.dataframe(
            result_rows(run),
            hide_index=True,
            use_container_width=True,
        )
    with human_tab:
        render_human(run.get("human") or {})
    with designers_tab:
        candidates = run.get("candidates", [])
        if candidates:
            tabs = st.tabs([item["track"] for item in candidates])
            for tab, candidate in zip(tabs, candidates):
                with tab:
                    render_candidate(candidate)


def current_run_id() -> str | None:
    value = st.session_state.get("forge_run_id") or st.query_params.get("run_id")
    return str(value) if value else None


next_view = st.session_state.pop("next_workspace_view", None)
if next_view is not None:
    st.session_state["workspace_view"] = next_view
st.session_state.setdefault("workspace_view", "Create run")

query_run_id = st.query_params.get("run_id")
if query_run_id:
    st.session_state["forge_run_id"] = str(query_run_id)

with st.sidebar:
    st.markdown("### ⚒️ AlphaForge")
    st.caption("Strategy development workspace")
    view = st.radio(
        "Workspace",
        ["Create run", "Live run", "Strategy lab"],
        key="workspace_view",
        label_visibility="collapsed",
    )
    st.divider()
    lookup = st.text_input("Open run ID", value=current_run_id() or "")
    if st.button("Open run", use_container_width=True, disabled=not lookup.strip()):
        st.session_state["forge_run_id"] = lookup.strip()
        st.query_params["run_id"] = lookup.strip()
        go_to("Live run")
        st.rerun()
    st.caption("Build · test · compare")

st.markdown(
    """
    <div class="af-hero">
      <div class="af-kicker">LOCAL LEAN STRATEGY STUDIO</div>
      <h1>AlphaForge</h1>
      <p>Design strategies, run comparable backtests, and inspect every result in one workspace.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    catalog = api.universe()
except AlphaForgeAPIError as exc:
    st.error(str(exc))
    st.stop()

tradable = catalog.get("tradable_symbols", [])
default_symbols = set(catalog.get("default_symbols", []))
benchmarks = catalog.get("benchmarks", ["SPY"])
for item in tradable:
    ticker = item["display_ticker"]
    st.session_state.setdefault(f"stock_{ticker}", ticker in default_symbols)


if view == "Create run":
    st.subheader("Create one comparable run")
    st.caption("Shared market and execution settings apply throughout this run.")
    settings_tab, human_setup_tab = st.tabs(["1 · Shared settings", "2 · Your strategy"])

    with settings_tab:
        left, right = st.columns([3, 2], gap="large")
        with left:
            title_col, select_all, clear_all = st.columns([3, 1, 1])
            title_col.markdown("#### Stock candidate pool")
            if select_all.button("Select all", use_container_width=True):
                for item in tradable:
                    st.session_state[f"stock_{item['display_ticker']}"] = True
                st.rerun()
            if clear_all.button("Clear", use_container_width=True):
                for item in tradable:
                    st.session_state[f"stock_{item['display_ticker']}"] = False
                st.rerun()
            checkbox_columns = st.columns(5)
            for index, item in enumerate(tradable):
                ticker = item["display_ticker"]
                with checkbox_columns[index % 5]:
                    st.checkbox(
                        ticker,
                        key=f"stock_{ticker}",
                        help=item.get("sector", ""),
                    )
        with right:
            st.markdown("#### Backtest window")
            start_date = st.date_input("Start date", value=date(2020, 1, 2))
            end_date = st.date_input("End date", value=date(2024, 12, 31))
            initial_cash = st.number_input(
                "Initial cash", min_value=1_000.0, value=100_000.0, step=10_000.0
            )
            benchmark = st.selectbox("Benchmark", benchmarks)
            cost_col, slip_col = st.columns(2)
            transaction_cost_bps = cost_col.number_input(
                "Transaction cost (bps)", min_value=0.0, value=10.0, step=1.0
            )
            slippage_bps = slip_col.number_input(
                "Slippage (bps)", min_value=0.0, value=5.0, step=1.0
            )

    with human_setup_tab:
        st.markdown("#### Choose how to provide your strategy")
        human_mode_label = st.segmented_control(
            "Strategy input",
            ["Guided builder", "Complete Python code"],
            default="Guided builder",
            label_visibility="collapsed",
        )
        if human_mode_label == "Guided builder":
            st.info(
                "Your selections are converted into complete, visible LEAN Python source."
            )
            guided_cols = st.columns(4)
            signal_label = guided_cols[0].selectbox(
                "Signal", ["Momentum", "Mean reversion"]
            )
            lookback_days = guided_cols[1].selectbox("Lookback", [20, 60, 120], index=1)
            rebalance_label = guided_cols[2].selectbox(
                "Rebalance", ["Monthly", "Weekly"]
            )
            holdings = guided_cols[3].selectbox("Holdings", [1, 2, 3], index=1)
            st.markdown(
                "<div class='af-card'><strong>Generated strategy</strong><br>"
                f"<span>{signal_label} ranks the selected pool over {lookback_days} days; "
                f"the top {holdings} rebalance {rebalance_label.lower()} at 95% gross exposure.</span></div>",
                unsafe_allow_html=True,
            )
        else:
            action_col, note_col = st.columns([1, 4])
            action_col.button(
                "Load starter",
                on_click=load_starter_code,
                use_container_width=True,
            )
            note_col.caption(
                "Submit one complete file containing class UserStrategy. The source is backtested as supplied."
            )
            st.session_state.setdefault("human_code", "")
            st.text_area(
                "Complete QuantConnect Python source",
                key="human_code",
                height=520,
                placeholder="Paste the complete UserStrategy source here…",
            )

    selected_symbols = [
        item["display_ticker"]
        for item in tradable
        if st.session_state.get(f"stock_{item['display_ticker']}", False)
    ]
    code_ready = (
        human_mode_label == "Guided builder"
        or bool(st.session_state.get("human_code", "").strip())
    )
    can_start = bool(selected_symbols) and start_date < end_date and code_ready
    footer = st.columns([2, 1, 1])
    footer[0].caption(
        f"{len(selected_symbols)} stocks selected · Input: {human_mode_label or 'Guided builder'}"
    )
    if not selected_symbols:
        footer[0].warning("Select at least one stock.")
    elif start_date >= end_date:
        footer[0].warning("The start date must be earlier than the end date.")
    elif not code_ready:
        footer[0].warning("Paste complete strategy source or load the starter.")

    if footer[2].button(
        "Start full run",
        type="primary",
        disabled=not can_start,
        use_container_width=True,
    ):
        settings_payload = {
            "symbols": selected_symbols,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_cash": initial_cash,
            "benchmark": benchmark,
            "transaction_cost_bps": transaction_cost_bps,
            "slippage_bps": slippage_bps,
        }
        if human_mode_label == "Complete Python code":
            human_payload = {
                "mode": "code",
                "source_code": st.session_state["human_code"],
            }
        else:
            human_payload = {
                "mode": "guided",
                "guided": {
                    "signal": (
                        "momentum" if signal_label == "Momentum" else "mean_reversion"
                    ),
                    "lookback_days": lookback_days,
                    "rebalance": (
                        "monthly" if rebalance_label == "Monthly" else "weekly"
                    ),
                    "holdings": holdings,
                },
            }
        try:
            created = api.create_forge_run(
                {"settings": settings_payload, "human_strategy": human_payload}
            )
            st.session_state["forge_run_id"] = created["run_id"]
            st.session_state["forge_run"] = created
            st.query_params["run_id"] = created["run_id"]
            go_to("Live run")
            st.rerun()
        except AlphaForgeAPIError as exc:
            st.error(str(exc))


elif view == "Live run":
    run_id = current_run_id()
    if not run_id:
        st.info("Create a run or enter a run ID in the sidebar.")
    else:
        @st.fragment(run_every="3s")
        def live_run_fragment(active_run_id: str) -> None:
            try:
                run = api.forge_run(active_run_id)
                st.session_state["forge_run"] = run
                render_run_dashboard(run)
                if run.get("state") in TERMINAL_RUN_STATES:
                    st.success("Run finished. Strategy source files are ready for review.")
            except AlphaForgeAPIError as exc:
                st.error(str(exc))

        live_run_fragment(run_id)
        st.button(
            "Open Strategy lab",
            type="primary",
            on_click=go_to,
            args=("Strategy lab",),
        )


else:
    run_id = current_run_id()
    if not run_id:
        st.info("Create or open a run before entering Strategy lab.")
    else:
        try:
            run = api.forge_run(run_id)
            st.session_state["forge_run"] = run
            options = ["Your strategy"] + [
                item["track"] for item in run.get("candidates", [])
            ]
            selected = st.selectbox("Strategy source", options)
            if selected == "Your strategy":
                item = run.get("human") or {}
                source = item.get("source_code") or ""
                st.subheader("Your strategy")
                render_behavior(item.get("behavior_evidence") or {})
            else:
                item = next(
                    candidate
                    for candidate in run.get("candidates", [])
                    if candidate["track"] == selected
                )
                source = item.get("source_code") or ""
                st.subheader(selected)
                render_candidate(item)
            if source:
                st.download_button(
                    "Download complete Python source",
                    data=source,
                    file_name=f"alphaforge_{selected.lower().replace(' ', '_')}.py",
                    mime="text/x-python",
                )
                if selected == "Your strategy":
                    st.code(source, language="python", line_numbers=True)
            else:
                st.caption("Source is not available yet.")
        except AlphaForgeAPIError as exc:
            st.error(str(exc))
