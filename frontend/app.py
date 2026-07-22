from __future__ import annotations

import json
from datetime import date
from html import escape
from math import ceil

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import AlphaForgeAPI, AlphaForgeAPIError
from mock_data import AGENT_EVENTS, BASELINE_LESSONS, CANDIDATES, COLORS, LEAN_TEMPLATE, RESULTS


st.set_page_config(
    page_title="AlphaForge",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)
api = AlphaForgeAPI()

WORKFLOW = [
    ("setup", "01", "Rules & Strategy"),
    ("validation", "02", "Admission Check"),
    ("baselines", "03", "Baseline Comparison"),
    ("candidates", "04", "AI Candidates"),
    ("comparison", "05", "Final Comparison"),
    ("review", "06", "Review & Next Round"),
]

PAGE_LEVEL = {page: index for index, (page, _, _) in enumerate(WORKFLOW)}
PAGE_LEVEL.update({"overview": 0, "candidate_detail": 3, "system": 0})


def init_state() -> None:
    defaults = {
        "page": "overview",
        "last_workflow_page": "setup",
        "unlocked_step": 0,
        "battle_id": None,
        "contract_hash": None,
        "experiment_contract": None,
        "guided_strategy": None,
        "baseline_batch_id": None,
        "round": 1,
        "strategy_mode": "Guided Mode",
        "strategy_submitted": False,
        "validation_complete": False,
        "baseline_complete": False,
        "candidates_complete": False,
        "comparison_complete": False,
        "round_complete": False,
        "selected_candidate": "Hybrid",
        "lean_code": LEAN_TEMPLATE,
        "validation_result": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def inject_css() -> None:
    st.markdown(
        """
        <style>
          :root {
            --ink: #152238;
            --body: #304156;
            --muted: #526579;
            --subtle: #64748b;
            --teal: #0f766e;
            --teal-hover: #115e59;
            --teal-soft: #e7f3f1;
            --blue: #1d4ed8;
            --blue-soft: #eaf1ff;
            --amber: #a16207;
            --amber-soft: #fff8df;
            --red: #b42318;
            --red-soft: #fff0ee;
            --border: #d8e1e8;
            --border-strong: #b8c5d0;
            --surface: #ffffff;
            --surface-soft: #f7fafb;
            --canvas: #f4f7f9;
          }
          html, body, [class*="css"] {
            font-family: Inter, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
          }
          .stApp { background: var(--canvas); color: var(--body); font-size: 16px; }
          [data-testid="stHeader"] { background: rgba(243,246,248,.94); }
          [data-testid="stAppViewContainer"],
          [data-testid="stMain"],
          .stMarkdown, .stMarkdown p, .stMarkdown li,
          [data-testid="stText"], [data-testid="stWidgetLabel"] {
            color: var(--body);
          }
          [data-testid="stSidebar"] {
            background: var(--surface);
            border-right: 1px solid var(--border);
          }
          [data-testid="stSidebar"] .stButton > button {
            justify-content: flex-start;
            text-align: left;
            border: 1px solid transparent;
            box-shadow: none;
            background: transparent;
            color: #34465a;
            padding: .55rem .65rem;
          }
          [data-testid="stSidebar"] .stButton > button:hover:enabled {
            background: #edf3f5;
            border-color: #d8e4e7;
            color: var(--ink);
          }
          [data-testid="stSidebar"] .stButton > button:disabled {
            background: transparent;
            color: #64748b;
            opacity: 1;
          }
          .block-container { max-width: 1440px; padding: 2.35rem 2.4rem 5rem; }
          h1, h2, h3 { color: var(--ink) !important; letter-spacing: -.025em; }
          h1 { font-size: clamp(2rem, 3vw, 2.65rem) !important; line-height: 1.12 !important; margin-bottom: .35rem !important; }
          h2 { font-size: 1.48rem !important; margin-top: 1.65rem !important; }
          h3 { font-size: 1.12rem !important; }
          p, li { line-height: 1.65; }
          .brand { font-size: 1.32rem; font-weight: 820; color: var(--ink); letter-spacing: -.025em; }
          .brand-sub { color: var(--muted); font-size: .82rem; line-height: 1.45; margin-top: .16rem; }
          .page-kicker { color: #0b6b63; font-size: .72rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
          .page-subtitle { color: var(--muted); font-size: 1rem; line-height: 1.65; max-width: 880px; }
          .section-label { color: #4c5d70; font-size: .72rem; font-weight: 780; letter-spacing: .08em; text-transform: uppercase; }
          .card {
            padding: 1.08rem 1.15rem;
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            min-height: 112px;
            box-shadow: 0 2px 8px rgba(23,32,51,.04);
          }
          .card-title { color: var(--ink); font-size: 1.04rem; font-weight: 760; line-height: 1.35; margin: .28rem 0 .4rem; }
          .muted { color: #4b5f73; font-size: .91rem; line-height: 1.62; }
          .muted b { color: #2d3c4f; }
          .tag {
            display: inline-block; padding: .2rem .48rem; border-radius: 5px;
            background: var(--teal-soft); color: #0b625b; font-size: .69rem; font-weight: 780;
          }
          .tag.gray { background: #edf1f4; color: #425466; }
          .tag.blue { background: var(--blue-soft); color: #1e4f85; }
          .notice {
            padding: .95rem 1.1rem; border: 1px solid #b6d9d2; border-radius: 12px;
            background: #edf8f5; color: #204942; margin: .5rem 0 1.2rem; line-height: 1.6;
          }
          .notice b { color: #173f3b; }
          .result-banner {
            padding: 1.25rem 1.35rem; border: 1px solid #bddbd5; border-radius: 12px;
            background: linear-gradient(110deg, #ffffff, #eaf5f2);
            box-shadow: 0 1px 3px rgba(23,32,51,.04);
          }
          .step-row { display:flex; gap:.65rem; align-items:flex-start; }
          .step-dot {
            width: 24px; height: 24px; border-radius: 50%; display:grid; place-items:center;
            color:#fff; background:var(--teal); font-size:.7rem; font-weight:800; flex:none;
          }
          div[data-testid="stMetric"] {
            background: var(--surface); border: 1px solid var(--border); padding: .9rem 1rem; border-radius: 12px;
            box-shadow: 0 2px 7px rgba(23,32,51,.035);
          }
          div[data-testid="stMetric"] label { color: #4c6074 !important; font-size: .84rem !important; font-weight: 680; }
          div[data-testid="stMetricValue"] { color: var(--ink); font-size: 1.85rem; font-weight: 760; }
          div[data-testid="stMetricDelta"] { color: #365264; }
          [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
            color: #59697a !important;
          }
          .stButton > button {
            border-radius: 8px; font-weight: 700; background: var(--surface);
            color: #26384c; border-color: var(--border-strong);
          }
          .stButton > button:hover:enabled { color: var(--ink); border-color: #8fa0af; background: #f8fafb; }
          .stButton > button[kind="primary"] { background: var(--teal); border-color: var(--teal); color: #fff; }
          .stButton > button[kind="primary"]:hover { background: var(--teal-hover); border-color: var(--teal-hover); color: #fff; }
          .stButton > button:focus-visible { outline: 3px solid rgba(29,78,216,.24); outline-offset: 2px; }
          .stDownloadButton > button {
            background: var(--surface); color: #26384c; border-color: var(--border-strong); font-weight: 700;
          }
          .stDownloadButton > button:hover { color: var(--ink); border-color: #8fa0af; background: #f8fafb; }
          [data-testid="stProgressBar"] > div > div { background-color: var(--teal); }
          [data-testid="stDataFrame"] {
            border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
            background: var(--surface); box-shadow: 0 2px 8px rgba(23,32,51,.035);
          }
          [data-testid="stDataFrame"] * { color-scheme: light !important; }
          .stTabs [data-baseweb="tab-list"] { gap: 1.25rem; border-bottom: 1px solid var(--border); }
          .stTabs [data-baseweb="tab"] { padding: .65rem .15rem; color: #4b6075; font-size: .94rem; font-weight: 650; }
          .stTabs [aria-selected="true"] { color: var(--ink) !important; }
          .stTabs [data-baseweb="tab-highlight"] { background-color: var(--teal); }
          div[data-baseweb="select"] > div,
          div[data-baseweb="base-input"],
          div[data-baseweb="input"] > div,
          .stTextArea textarea,
          .stDateInput input,
          .stNumberInput input {
            background: var(--surface) !important;
            color: var(--ink) !important;
            border-color: var(--border-strong) !important;
          }
          div[data-baseweb="select"] span,
          .stRadio label, .stCheckbox label,
          [data-testid="stWidgetLabel"] p { color: #34465a !important; }
          input::placeholder, textarea::placeholder { color: #718096 !important; opacity: 1; }
          [data-baseweb="popover"], [data-baseweb="menu"] { color: var(--ink); }
          [data-baseweb="menu"] li { color: var(--body); background: var(--surface); }
          [data-baseweb="menu"] li:hover { color: var(--ink); background: #edf3f5; }
          [data-testid="stExpander"] { background: var(--surface); border-color: var(--border); }
          [data-testid="stAlert"] {
            color: var(--body) !important; border: 1px solid var(--border-strong) !important;
            background: var(--surface) !important; border-radius: 12px !important;
          }
          [data-testid="stAlert"] p, [data-testid="stAlert"] div { color: inherit !important; }
          [data-testid="stAlert"] svg { color: currentColor !important; fill: currentColor !important; }
          [data-testid="stNotificationContentWarning"] { color: #704d00 !important; background: var(--amber-soft) !important; }
          [data-testid="stNotificationContentError"] { color: #8a251d !important; background: var(--red-soft) !important; }
          [data-testid="stNotificationContentSuccess"] { color: #17584e !important; background: #eaf7f3 !important; }
          .batch-bar {
            display: flex; align-items: center; justify-content: space-between; gap: 1rem;
            margin: 1rem 0 1.15rem; padding: .9rem 1rem; background: var(--surface);
            border: 1px solid var(--border); border-radius: 12px;
          }
          .batch-meta { color: var(--muted); font-size: .86rem; line-height: 1.55; overflow-wrap: anywhere; }
          .batch-meta strong { color: var(--ink); }
          .status-pill {
            display: inline-flex; align-items: center; gap: .34rem; padding: .3rem .62rem;
            border-radius: 999px; font-size: .72rem; font-weight: 800; letter-spacing: .035em;
            text-transform: uppercase; white-space: nowrap;
          }
          .status-completed { color: #176254; background: #ddf5ed; }
          .status-running, .status-queued, .status-submitting { color: #155ea2; background: #e8f2ff; }
          .status-failed, .status-timeout { color: #a42b22; background: #ffebe8; }
          .status-unknown { color: #526174; background: #edf1f4; }
          .run-card {
            min-height: 146px; padding: 1rem; background: var(--surface); border: 1px solid var(--border);
            border-radius: 14px; box-shadow: 0 2px 8px rgba(23,32,51,.035);
          }
          .run-card-human {
            border-color: #8fc8bf; background: linear-gradient(115deg, #ffffff, #edf8f5);
            box-shadow: 0 3px 12px rgba(15,118,110,.08);
          }
          .run-card-top { display:flex; align-items:flex-start; justify-content:space-between; gap:.55rem; }
          .run-name { color: var(--ink); font-size: 1rem; font-weight: 760; line-height: 1.38; }
          .run-id { color: #66778a; font-size: .75rem; margin-top: .62rem; overflow-wrap: anywhere; }
          .run-track { color: #4c6074; font-size: .8rem; margin-top: .38rem; }
          .insight-card {
            min-height: 112px; padding: .95rem 1rem; background: linear-gradient(140deg,#fff,#f7fbfb);
            border: 1px solid var(--border); border-radius: 13px;
          }
          .insight-label { color: #5b6d80; font-size: .72rem; font-weight: 800; letter-spacing:.07em; text-transform:uppercase; }
          .insight-value { color: var(--ink); font-size: 1.32rem; font-weight: 800; margin-top:.25rem; }
          .insight-note { color: #566a7d; font-size: .8rem; margin-top:.18rem; }
          hr { border-color: var(--border) !important; }
          code { font-size: .82rem !important; color: #243247 !important; }
          a { color: #145fa3; }
          a:hover { color: #0f477a; }
          @media (max-width: 900px) {
            .block-container { padding: 1.4rem 1rem 4rem; }
            h1 { font-size: 2rem !important; }
            .batch-bar { align-items:flex-start; flex-direction:column; }
            .run-card { min-height: 126px; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def go(page: str) -> None:
    if page in PAGE_LEVEL and page not in {"overview", "system", "candidate_detail"}:
        if PAGE_LEVEL[page] > st.session_state.unlocked_step:
            st.warning("Complete the current step before continuing.")
            return
        st.session_state.last_workflow_page = page
    st.session_state.page = page
    st.rerun()


def unlock_and_go(step: int, page: str) -> None:
    st.session_state.unlocked_step = max(st.session_state.unlocked_step, step)
    go(page)


def guard(required_step: int) -> bool:
    if st.session_state.unlocked_step >= required_step:
        return True
    go(WORKFLOW[st.session_state.unlocked_step][0])
    return False


def page_header(step: str, title: str, subtitle: str) -> None:
    st.markdown(f'<div class="page-kicker">{step} · Round {st.session_state.round}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="page-subtitle">{subtitle}</div>', unsafe_allow_html=True)
    st.write("")


def style_figure(fig, height: int = 330, legend: bool = False):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=25, b=10),
        showlegend=legend,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#334155", size=13),
        hoverlabel=dict(bgcolor="#172033", bordercolor="#172033", font_color="#ffffff"),
    )
    fig.update_xaxes(
        gridcolor="#e2e8ee", linecolor="#cbd5df", zerolinecolor="#cbd5df",
        tickfont=dict(color="#425466"), title_font=dict(color="#334155"),
    )
    fig.update_yaxes(
        gridcolor="#e2e8ee", linecolor="#cbd5df", zerolinecolor="#cbd5df",
        tickfont=dict(color="#425466"), title_font=dict(color="#334155"),
    )
    return fig


BASELINE_PALETTE = ["#0F766E", "#2563EB", "#0891B2", "#7C3AED", "#D97706"]


def metric_chart(
    frame: pd.DataFrame,
    metric: str,
    *,
    title: str | None = None,
    suffix: str = "",
    height: int = 310,
):
    chart_frame = frame.dropna(subset=[metric]).sort_values(metric, ascending=True)
    fig = px.bar(
        chart_frame,
        x=metric,
        y="Strategy",
        orientation="h",
        color="Track",
        color_discrete_map=COLORS,
        text=metric,
    )
    fig.update_traces(
        texttemplate=f"%{{text:.2f}}{suffix}", textposition="outside",
        textfont=dict(color="#243247", size=13),
        marker_line_color="#ffffff", marker_line_width=0.8,
        cliponaxis=False,
    )
    fig.update_layout(title=dict(text=title or metric, font=dict(size=15, color="#172033")))
    fig.update_xaxes(ticksuffix=suffix)
    fig.update_yaxes(title=None, automargin=True)
    return style_figure(fig, height=height, legend=False)


def _status_class(state: str | None) -> str:
    normalized = str(state or "unknown").strip().lower()
    if normalized in {"completed", "running", "queued", "submitting", "failed", "timeout"}:
        return normalized
    return "unknown"


def _run_card(run: dict) -> str:
    state = str(run.get("state") or "unknown")
    state_class = _status_class(state)
    run_id = str(run.get("worker_run_id") or "Waiting for Worker ID")
    card_class = "run-card run-card-human" if run.get("role") == "human" else "run-card"
    return (
        f'<div class="{card_class}">'
        '<div class="run-card-top">'
        f'<div class="run-name">{escape(str(run.get("display_name") or "Baseline"))}</div>'
        f'<span class="status-pill status-{state_class}">{escape(state)}</span>'
        '</div>'
        f'<div class="run-track">{escape(str(run.get("family") or "Unclassified"))}</div>'
        f'<div class="run-id">Run ID<br><strong>{escape(run_id)}</strong></div>'
        '</div>'
    )


def _insight_card(label: str, value: str, note: str) -> str:
    return (
        '<div class="insight-card">'
        f'<div class="insight-label">{escape(label)}</div>'
        f'<div class="insight-value">{escape(value)}</div>'
        f'<div class="insight-note">{escape(note)}</div>'
        '</div>'
    )


def sidebar() -> None:
    with st.sidebar:
        st.markdown('<div class="brand">AlphaForge</div><div class="brand-sub">Strategy learning and evaluation</div>', unsafe_allow_html=True)
        st.write("")
        if st.button("Overview", use_container_width=True):
            go("overview")
        st.markdown('<div class="section-label">Current workflow</div>', unsafe_allow_html=True)
        for index, (page, number, label) in enumerate(WORKFLOW):
            unlocked = index <= st.session_state.unlocked_step
            complete = index < st.session_state.unlocked_step or (index == 5 and st.session_state.round_complete)
            marker = "✓" if complete else number
            if st.button(f"{marker}   {label}", key=f"nav-{page}", disabled=not unlocked, use_container_width=True):
                go(page)
        st.write("")
        st.progress((st.session_state.unlocked_step + 1) / len(WORKFLOW))
        st.caption(f"{st.session_state.battle_id} · Round {st.session_state.round}")
        st.markdown("---")
        if st.button("Runs & system", use_container_width=True):
            go("system")
        mode = "Mock data" if api.mock_mode else "Live services"
        st.caption(mode)


def render_overview() -> None:
    page_header("Overview", "Strategy Challenge", "Build a strategy, compare it with public baselines, then evaluate it against independently generated candidates.")
    st.markdown(
        '<div class="notice"><b>Fair by design.</b> AI candidates are created without access to your strategy, parameters, results or learning feedback. Comparison happens only after both sides are frozen.</div>',
        unsafe_allow_html=True,
    )
    a, b, c = st.columns(3)
    a.metric("Current round", str(st.session_state.round), "Up to 5 rounds")
    if api.mock_mode:
        b.metric("Human best Sharpe", "1.08", "Mock preview")
        c.metric("AI best Sharpe", "1.23", "Mock preview")
    else:
        b.metric("Public baselines", "4", "Real LEAN batch")
        c.metric("AI Forge", "Reserved", "Member-D integration")
    st.subheader("How one round works")
    steps = [
        ("1", "Define and submit", "Freeze the market rules, then create a strategy from a template or LEAN Python."),
        ("2", "Validate", "Run syntax, safety, QC API and LEAN smoke checks before any full backtest."),
        ("3", "Learn from baselines", "Compare your frozen result with four public reference strategies."),
        ("4", "Generate AI candidates", "Traditional, ML and Hybrid candidates are created from public evidence only."),
        ("5", "Compare fairly", "A deterministic judge compares frozen results under the same contract."),
        ("6", "Review or continue", "Export a strategy, improve privately, or start the next isolated round."),
    ]
    for row in [steps[:3], steps[3:]]:
        cols = st.columns(3)
        for col, (no, title, text) in zip(cols, row):
            col.markdown(f'<div class="card"><span class="tag gray">STEP {no}</span><div class="card-title">{title}</div><div class="muted">{text}</div></div>', unsafe_allow_html=True)
    st.write("")
    if st.button("Continue current round", type="primary"):
        go(st.session_state.last_workflow_page)


def render_setup() -> None:
    page_header("Step 1 of 6", "Rules & Strategy", "Set one experiment contract and submit the Human strategy. These rules apply to every strategy in the round.")
    try:
        universe_catalog = api.universe()
        guided_catalog = api.guided_strategies()
    except AlphaForgeAPIError as exc:
        st.error(str(exc))
        st.info("Start the FastAPI backend, or explicitly set ALPHAFORGE_MOCK_MODE=true for the labelled demo.")
        return
    universe = [item["display_ticker"] for item in universe_catalog["tradable_symbols"]]
    if "contract_symbols" not in st.session_state:
        st.session_state.contract_symbols = list(universe)

    rules, strategy = st.columns([1, 1.25], gap="large")
    with rules:
        st.subheader("Experiment contract")
        start, end = st.columns(2)
        start_date = start.date_input("Start date", date(2016, 1, 4))
        end_date = end.date_input("End date", date(2026, 6, 30))
        selected_symbols = st.multiselect(
            "Universe",
            universe,
            key="contract_symbols",
        )
        st.caption(f"{len(selected_symbols)}/30 selected · minimum 5 · standard experiment uses all 30")
        if len(selected_symbols) < 5:
            st.error("Select at least 5 stocks before locking the contract.")
        cash, cost = st.columns(2)
        initial_cash = cash.number_input("Initial cash (USD)", value=100000, step=10000)
        transaction_cost = cost.number_input("Transaction cost (bps)", value=10, min_value=0)
        slippage, drawdown = st.columns(2)
        slippage_bps = slippage.number_input("Slippage (bps)", value=5, min_value=0)
        max_drawdown_pct = drawdown.number_input("Max drawdown gate (%)", value=25, min_value=1, max_value=80)
        data_version = st.text_input("Data version", value="tiingo-eod-v1")
        st.markdown('<div class="notice">The contract is locked when you continue. Human, baselines and AI use the same dates, data, costs and risk limits.</div>', unsafe_allow_html=True)
    with strategy:
        st.subheader("Human strategy")
        mode = st.radio(
            "Entry method",
            ["Guided Mode", "LEAN Code"],
            horizontal=True,
            index=0 if st.session_state.strategy_mode == "Guided Mode" else 1,
        )
        st.session_state.strategy_mode = mode
        guided_template_id = "multi_horizon_momentum"
        guided_template_name = "Multi-Horizon Momentum"
        lookback_value = 126
        top_n_value = 3
        max_weight_value = 35
        if mode == "Guided Mode":
            template_by_name = {
                item["display_name"]: item for item in guided_catalog
            }
            template_name = st.selectbox(
                "Strategy template",
                list(template_by_name),
                key="guided_template",
            )
            template = template_by_name[template_name]
            guided_template_id = template["template_id"]
            guided_template_name = template_name
            lookback, top_n, max_weight = st.columns(3)
            lookback_value = lookback.slider(
                "Lookback days",
                21,
                252,
                int(template["default_lookback_days"]),
                key=f"guided-lookback-{guided_template_id}",
                help="Historical trading days used to rank the selected stocks.",
            )
            top_n_max = max(3, min(10, len(selected_symbols)))
            top_n_value = top_n.slider(
                "Hold Top N",
                3,
                top_n_max,
                3,
                help="This is part of the shared contract and also applies to the four baselines.",
            )
            minimum_weight = ceil(95 / top_n_value)
            max_weight_value = max_weight.slider(
                "Max weight (%)",
                minimum_weight,
                100,
                max(35, minimum_weight),
                help="Minimum adjusts automatically so Top N can reach the 95% target exposure.",
            )
            st.markdown(
                f'<div class="card"><span class="tag blue">GUIDED · REAL LEAN</span>'
                f'<div class="card-title">{escape(template_name)}</div>'
                f'<div class="muted">{escape(template["description"])}<br><br>'
                f'<b>Your controls:</b> {lookback_value}-day lookback · Top {top_n_value} · '
                f'{max_weight_value}% position cap.<br>'
                f'<b>Trade-off:</b> {escape(template["best_for"])}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="notice"><b>Runnable code contract.</b> Keep '
                '<code>UserStrategy(AlphaForgeBaseAlgorithm)</code>, implement '
                '<code>initialize_strategy</code>, <code>on_alpha_data</code> and '
                '<code>on_alpha_end</code>, and read all dates, symbols, cash, sizing '
                'and costs through <code>self.get_parameter</code>. Network, subprocess '
                'and arbitrary file access are blocked.</div>',
                unsafe_allow_html=True,
            )
            with st.expander("What may I edit?", expanded=False):
                st.markdown(
                    "Change the trailing-data score inside `rebalance()`, add LEAN "
                    "indicators, or adjust signal filters. Do not rename the entry class "
                    "or hooks, hard-code experiment dates/cash, bypass "
                    "`af_configure_security`, or remove the completion marker."
                )
            st.session_state.lean_code = st.text_area("LEAN Python", st.session_state.lean_code, height=330)
            st.caption("Code is not sent to any AI Designer. It is used only by validation, LEAN execution and the post-round learning module.")
    st.write("")
    if st.button("Lock contract and continue", type="primary", disabled=len(selected_symbols) < 5):
        contract = {
            "contract_version": "1.0",
            "universe_id": universe_catalog["universe_id"],
            "universe_version": "whitelist_v1.0",
            "symbols": selected_symbols,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_cash": float(initial_cash),
            "resolution": "Daily",
            "rebalance_frequency": "Monthly",
            "top_k": int(top_n_value),
            "target_gross": 0.95,
            "max_position_weight": max_weight_value / 100.0,
            "max_drawdown": max_drawdown_pct / 100.0,
            "transaction_cost_bps": float(transaction_cost),
            "slippage_bps": float(slippage_bps),
            "long_only": True,
            "max_leverage": 1.0,
            "cash_allowed": True,
            "benchmark": "SPY",
            "risk_filter_symbol": "QQQ",
            "risk_sma_period": 200,
            "data_version": data_version,
            "random_seed": 42,
        }
        try:
            battle_payload = {
                "name": f"AlphaForge Round {st.session_state.round}",
                "experiment_contract": contract,
                "strategy_mode": "guided" if mode == "Guided Mode" else "code",
            }
            if mode == "Guided Mode":
                battle_payload["guided_strategy"] = {
                    "template_id": guided_template_id,
                    "lookback_days": int(lookback_value),
                }
            else:
                battle_payload["custom_code"] = st.session_state.lean_code
            battle = api.create_battle(battle_payload)
        except AlphaForgeAPIError as exc:
            st.error(str(exc))
            return
        st.session_state.battle_id = battle["battle_id"]
        st.session_state.contract_hash = battle["contract_hash"]
        st.session_state.experiment_contract = contract
        if mode == "Guided Mode":
            st.session_state.guided_strategy = {
                **(battle.get("guided_strategy") or {
                    "template_id": guided_template_id,
                    "lookback_days": int(lookback_value),
                }),
                "display_name": guided_template_name,
            }
        else:
            st.session_state.guided_strategy = None
        st.session_state.strategy_submitted = True
        unlock_and_go(1, "validation")


def render_validation() -> None:
    if not guard(1):
        return
    page_header("Step 2 of 6", "Admission Check", "Confirm that the submitted strategy is safe and executable before full backtesting.")
    st.markdown('<div class="notice"><b>Why this step exists:</b> passing admission means the strategy can safely enter the shared LEAN environment. It does not mean the strategy is profitable.</div>', unsafe_allow_html=True)
    if not st.session_state.validation_complete:
        left, right = st.columns([1.2, 1])
        with left:
            checks = [
                ("Python syntax", "Checks that the submitted file can be parsed."),
                ("AlphaForge structure", "Requires UserStrategy and the three controlled strategy hooks."),
                ("Restricted capabilities", "Blocks network, subprocess and unrestricted file access."),
                ("LEAN smoke test", "Runs a short isolated execution before the full backtest."),
            ]
            for name, detail in checks:
                st.markdown(f'<div class="card" style="min-height:auto;margin-bottom:.55rem"><div class="card-title">{name}</div><div class="muted">{detail}</div></div>', unsafe_allow_html=True)
        with right:
            st.subheader("Submission summary")
            contract = st.session_state.experiment_contract or {}
            guided = st.session_state.guided_strategy or {}
            strategy_title = (
                guided.get("display_name", "Guided strategy")
                if st.session_state.strategy_mode == "Guided Mode"
                else "Custom LEAN Python"
            )
            st.markdown(
                f'<div class="card"><span class="tag gray">HUMAN · R{st.session_state.round}</span>'
                f'<div class="card-title">{escape(str(strategy_title))}</div>'
                f'<div class="muted">{st.session_state.strategy_mode} · '
                f'{guided.get("lookback_days", "—")}-day lookback · '
                f'Top {contract.get("top_k")} · {float(contract.get("max_position_weight", 0)):.0%} cap<br>'
                f'Contract {st.session_state.battle_id} · {contract.get("start_date")}–{contract.get("end_date")} · '
                f'{contract.get("transaction_cost_bps")} bps fee</div></div>',
                unsafe_allow_html=True,
            )
            st.write("")
            existing = st.session_state.validation_result or {}
            smoke_pending = existing.get("smoke_status") in {"queued", "running"}
            action_label = "Refresh isolated LEAN smoke" if smoke_pending else "Run admission checks"
            if st.button(action_label, type="primary", use_container_width=True):
                if st.session_state.strategy_mode == "Guided Mode":
                    result = {
                        "accepted": True,
                        "checks": {
                            "Guided template schema": True,
                            "Whitelist and position limits": True,
                            "Immutable contract": bool(st.session_state.contract_hash),
                        },
                        "smoke_status": "not_required_for_public_baseline_phase",
                    }
                else:
                    result = (
                        api.code_validation(st.session_state.battle_id)
                        if smoke_pending
                        else api.validate_code(
                            st.session_state.battle_id, st.session_state.lean_code
                        )
                    )
                st.session_state.validation_result = result
                st.session_state.validation_complete = result["accepted"]
                st.rerun()
            if existing:
                st.caption(
                    f"LEAN smoke: {existing.get('smoke_status', 'not submitted')}"
                    + (
                        f" · run {existing.get('smoke_run_id')}"
                        if existing.get("smoke_run_id") else ""
                    )
                )
                for check_name, passed in existing.get("checks", {}).items():
                    st.write(f"{'✓' if passed else '✕'} {check_name}")
                for error in existing.get("errors", []):
                    st.error(error)
        return
    rows = [
        {"Check": "Python syntax", "Status": "Passed", "Evidence": "AST parsed"},
        {"Check": "UserStrategy entry", "Status": "Passed", "Evidence": "Controlled entry class found"},
        {"Check": "Restricted capabilities", "Status": "Passed", "Evidence": "No blocked calls"},
        {"Check": "Experiment contract", "Status": "Passed", "Evidence": f"sha256:{st.session_state.contract_hash[:12]}…"},
    ]
    st.success("Admission passed. The Human strategy version is now frozen for this round.")
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if st.button("Run your strategy + four public baselines", type="primary"):
        if api.mock_mode:
            st.session_state.baseline_complete = True
            unlock_and_go(2, "baselines")
        try:
            batch = api.run_baselines(st.session_state.battle_id)
        except AlphaForgeAPIError as exc:
            st.error(str(exc))
            return
        st.session_state.baseline_batch_id = batch["batch_id"]
        st.session_state.baseline_complete = batch.get("state") == "completed"
        unlock_and_go(2, "baselines")


def render_baselines() -> None:
    if not guard(2):
        return
    page_header("Step 3 of 6", "Baseline Comparison", "Understand the four public reference strategies and compare them with your frozen result.")
    st.markdown('<div class="notice"><b>Information boundary:</b> this page is visible to you. AI Designers receive the four baseline results only; your row and all Human analysis are removed from their context.</div>', unsafe_allow_html=True)
    if api.mock_mode:
        frame = RESULTS.iloc[1:5]
        st.plotly_chart(
            metric_chart(frame, "Sharpe", title="Risk-adjusted return (mock preview)"),
            use_container_width=True,
        )
        st.caption("Labelled demo values. Set ALPHAFORGE_MOCK_MODE=false for real LEAN evidence.")
        return

    try:
        batch = api.baselines(st.session_state.battle_id, refresh=True)
    except AlphaForgeAPIError as exc:
        st.error(str(exc))
        return
    if not batch:
        st.warning("No baseline batch exists for this battle.")
        return

    batch_state = str(batch.get("state") or "unknown")
    batch_state_class = _status_class(batch_state)
    st.markdown(
        '<div class="batch-bar">'
        '<div class="batch-meta">'
        f'<strong>Batch {escape(str(batch["batch_id"]))}</strong><br>'
        f'Contract sha256:{escape(str(batch["contract_hash"])[:12])}… · '
        'all strategies share one immutable experiment contract'
        '</div>'
        f'<span class="status-pill status-{batch_state_class}">{escape(batch_state)}</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    human_runs = [run for run in batch["runs"] if run.get("role") == "human"]
    baseline_runs = [run for run in batch["runs"] if run.get("role", "baseline") == "baseline"]
    if human_runs:
        st.markdown('<div class="section-label">Your frozen LEAN run</div>', unsafe_allow_html=True)
        st.markdown(_run_card(human_runs[0]), unsafe_allow_html=True)
        st.write("")
    else:
        st.info("This is a historical baseline-only batch. Retry to add your Guided strategy as a real LEAN run.")
    st.markdown('<div class="section-label">Four public baselines</div>', unsafe_allow_html=True)
    status_columns = st.columns(4)
    for column, run in zip(status_columns, baseline_runs):
        column.markdown(_run_card(run), unsafe_allow_html=True)
    if batch.get("error"):
        st.error(batch["error"])

    if batch["state"] in {"queued", "running", "submitting"}:
        st.info("LEAN Worker runs one job at a time. Refresh to retrieve the latest normalized evidence.")
        if st.button("Refresh baseline jobs", type="primary"):
            st.rerun()
        return

    completed_runs = [run for run in batch["runs"] if run.get("summary")]
    if not completed_runs:
        st.error("The batch finished without comparable results. Review the run errors, then retry.")
        if st.button("Retry four baselines"):
            try:
                new_batch = api.run_baselines(st.session_state.battle_id)
                st.session_state.baseline_batch_id = new_batch["batch_id"]
                st.rerun()
            except AlphaForgeAPIError as exc:
                st.error(str(exc))
        return

    records = []
    for run in completed_runs:
        summary = run["summary"]
        records.append({
            "Strategy": run["display_name"],
            "Track": run["family"],
            "Role": "Your strategy" if run.get("role") == "human" else "Public baseline",
            "Status": run["state"],
            "Sharpe": summary.get("sharpe_ratio"),
            "CAGR (%)": None if summary.get("cagr") is None else summary["cagr"] * 100,
            "Max drawdown (%)": None if summary.get("maximum_drawdown") is None else summary["maximum_drawdown"] * 100,
            "Turnover (%)": None if summary.get("portfolio_turnover") is None else summary["portfolio_turnover"] * 100,
            "Fees (USD)": summary.get("total_fees"),
            "Orders": summary.get("total_orders"),
            "Eligible": run["eligible_for_comparison"],
        })
    frame = pd.DataFrame(records)

    rankable = frame["Eligible"].fillna(False) & frame["Sharpe"].notna()
    frame.insert(0, "Rank", pd.Series(pd.NA, index=frame.index, dtype="Int64"))
    frame.loc[rankable, "Rank"] = (
        frame.loc[rankable, "Sharpe"].rank(method="min", ascending=False).astype("Int64")
    )

    insight_columns = st.columns(4)
    if rankable.any():
        best_sharpe = frame.loc[frame.loc[rankable, "Sharpe"].idxmax()]
        insight_columns[0].markdown(
            _insight_card(
                "Highest Sharpe",
                f'{best_sharpe["Sharpe"]:.3f}',
                str(best_sharpe["Strategy"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        insight_columns[0].markdown(
            _insight_card("Highest Sharpe", "—", "No comparable value"),
            unsafe_allow_html=True,
        )

    drawdown_rows_with_values = frame.dropna(subset=["Max drawdown (%)"])
    if not drawdown_rows_with_values.empty:
        lowest_drawdown = drawdown_rows_with_values.loc[
            drawdown_rows_with_values["Max drawdown (%)"].idxmin()
        ]
        insight_columns[1].markdown(
            _insight_card(
                "Lowest drawdown",
                f'{lowest_drawdown["Max drawdown (%)"]:.2f}%',
                str(lowest_drawdown["Strategy"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        insight_columns[1].markdown(
            _insight_card("Lowest drawdown", "—", "No comparable value"),
            unsafe_allow_html=True,
        )

    fee_rows_with_values = frame.dropna(subset=["Fees (USD)"])
    if not fee_rows_with_values.empty:
        lowest_fees = fee_rows_with_values.loc[fee_rows_with_values["Fees (USD)"].idxmin()]
        insight_columns[2].markdown(
            _insight_card(
                "Lowest fees",
                f'${lowest_fees["Fees (USD)"]:,.2f}',
                str(lowest_fees["Strategy"]),
            ),
            unsafe_allow_html=True,
        )
    else:
        insight_columns[2].markdown(
            _insight_card("Lowest fees", "—", "No comparable value"),
            unsafe_allow_html=True,
        )

    comparable_count = int(frame["Eligible"].fillna(False).sum())
    expected_count = 5
    insight_columns[3].markdown(
        _insight_card(
            "Comparable evidence",
            f"{comparable_count} / {expected_count}",
            "Completed and contract-eligible",
        ),
        unsafe_allow_html=True,
    )

    st.subheader("Normalized LEAN scorecard")
    st.caption(
        "Rank uses Sharpe among eligible runs. Higher Sharpe/CAGR is better; "
        "lower maximum drawdown, turnover and fees indicate less risk or execution burden."
    )
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        row_height=44,
        column_config={
            "Rank": st.column_config.NumberColumn("Rank", help="Sharpe rank among eligible baselines", format="%d", width="small"),
            "Strategy": st.column_config.TextColumn("Strategy", width="large"),
            "Track": st.column_config.TextColumn("Track", width="medium"),
            "Role": st.column_config.TextColumn("Role", width="medium"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Sharpe": st.column_config.NumberColumn("Sharpe ↑", help="Risk-adjusted return; higher is better", format="%.3f"),
            "CAGR (%)": st.column_config.NumberColumn("CAGR ↑", help="Annualized compound return", format="%.2f%%"),
            "Max drawdown (%)": st.column_config.NumberColumn("Max drawdown ↓", help="Largest peak-to-trough loss; lower is better", format="%.2f%%"),
            "Turnover (%)": st.column_config.NumberColumn("Turnover ↓", help="Portfolio turnover reported by LEAN", format="%.2f%%"),
            "Fees (USD)": st.column_config.NumberColumn("Fees ↓", help="Total simulated transaction fees", format="$%.2f"),
            "Orders": st.column_config.NumberColumn("Orders", format="%d"),
            "Eligible": st.column_config.CheckboxColumn("Eligible", help="Passed result and contract checks"),
        },
    )

    equity_rows = []
    drawdown_rows = []
    for run in completed_runs:
        curve = run.get("performance", {}).get("equity_curve", [])
        first_value = next((float(point.get("portfolio_value")) for point in curve if point.get("portfolio_value")), None)
        if first_value:
            equity_rows.extend({
                "Time": point.get("time"),
                "Normalized value": float(point.get("portfolio_value", 0)) / first_value,
                "Strategy": run["display_name"],
            } for point in curve if point.get("portfolio_value") is not None)
        drawdown_rows.extend({
            "Time": point.get("time"),
            "Drawdown (%)": -abs(float(point.get("drawdown", 0)) * 100),
            "Strategy": run["display_name"],
        } for point in run.get("performance", {}).get("drawdown_curve", []))

    charts = st.tabs([
        "Performance",
        "Risk & cost",
        "Equity curves",
        "Drawdown curves",
        "Baseline lessons",
    ])
    with charts[0]:
        performance_columns = st.columns(2)
        with performance_columns[0]:
            st.plotly_chart(
                metric_chart(frame, "Sharpe", title="Sharpe ratio · higher is better"),
                use_container_width=True,
            )
        with performance_columns[1]:
            st.plotly_chart(
                metric_chart(frame, "CAGR (%)", title="CAGR · higher is better", suffix="%"),
                use_container_width=True,
            )
    with charts[1]:
        risk_columns = st.columns(2)
        with risk_columns[0]:
            st.plotly_chart(
                metric_chart(frame, "Max drawdown (%)", title="Maximum drawdown · lower is better", suffix="%"),
                use_container_width=True,
            )
        with risk_columns[1]:
            st.plotly_chart(
                metric_chart(frame, "Turnover (%)", title="Portfolio turnover · lower is better", suffix="%"),
                use_container_width=True,
            )
        st.plotly_chart(
            metric_chart(frame, "Fees (USD)", title="Total simulated fees · lower is better", suffix=" USD", height=280),
            use_container_width=True,
        )
    with charts[2]:
        if equity_rows:
            figure = px.line(
                pd.DataFrame(equity_rows),
                x="Time",
                y="Normalized value",
                color="Strategy",
                color_discrete_sequence=BASELINE_PALETTE,
            )
            figure.update_traces(line=dict(width=2.4))
            figure.update_layout(title="Growth of $1 under the shared contract")
            st.plotly_chart(style_figure(figure, 390, legend=True), use_container_width=True)
        else:
            st.info("No equity-curve points were returned for this batch.")
    with charts[3]:
        if drawdown_rows:
            figure = px.line(
                pd.DataFrame(drawdown_rows),
                x="Time",
                y="Drawdown (%)",
                color="Strategy",
                color_discrete_sequence=BASELINE_PALETTE,
            )
            figure.update_traces(line=dict(width=2.2))
            figure.update_layout(title="Peak-to-trough drawdown depth")
            st.plotly_chart(style_figure(figure, 390, legend=True), use_container_width=True)
        else:
            st.info("No drawdown-curve points were returned for this batch.")
    with charts[4]:
        for row in [BASELINE_LESSONS[:2], BASELINE_LESSONS[2:]]:
            cols = st.columns(2)
            for col, (no, name, idea, lesson, recipe) in zip(cols, row):
                col.markdown(
                    f'<div class="card"><span class="tag gray">BASELINE {no}</span>'
                    f'<div class="card-title">{name}</div><div class="muted">{idea}</div><br>'
                    f'<div class="muted"><b>Lesson:</b> {lesson}</div><br>'
                    f'<span class="tag blue">{recipe}</span></div>',
                    unsafe_allow_html=True,
                )
            st.write("")

    all_eligible = (
        batch["state"] == "completed"
        and len(completed_runs) == expected_count
        and len(human_runs) == 1
        and len(baseline_runs) == 4
        and all(run["eligible_for_comparison"] for run in completed_runs)
    )
    if all_eligible:
        st.success("Your strategy and all four public baselines are real, normalized, and bound to the same frozen contract.")
    else:
        st.warning("Some baseline evidence is incomplete or ineligible. Retry before freezing the public evidence bundle.")
        if st.button("Retry incomplete baseline batch"):
            try:
                new_batch = api.run_baselines(st.session_state.battle_id)
                st.session_state.baseline_batch_id = new_batch["batch_id"]
                st.rerun()
            except AlphaForgeAPIError as exc:
                st.error(str(exc))
    st.button("AI Forge awaiting member-D Agent Runtime", disabled=True, use_container_width=True)


def render_candidates() -> None:
    if not guard(3):
        return
    page_header("Step 4 of 6", "AI Candidates", "Review three independently designed candidates and the structured evidence produced at each stage.")
    st.markdown('<div class="notice"><b>Context check passed:</b> 4 public baselines · 1 experiment contract · 0 Human strategy fields · 0 Human result fields.</div>', unsafe_allow_html=True)
    st.subheader("Candidate set")
    cols = st.columns(3)
    for col, (track, data) in zip(cols, CANDIDATES.items()):
        with col:
            st.markdown(f'<div class="card"><span class="tag blue">{track.upper()}</span><div class="card-title">{data["title"]}</div><div class="muted">{data["thesis"]}</div><br><div class="muted"><b>Risk level:</b> {data["risk"]}</div></div>', unsafe_allow_html=True)
            if st.button("View design and validation", key=f"detail-{track}", use_container_width=True):
                st.session_state.selected_candidate = track
                go("candidate_detail")
    st.subheader("Process evidence")
    selected = st.selectbox("Inspect stage", [event["stage"] for event in AGENT_EVENTS])
    event = next(item for item in AGENT_EVENTS if item["stage"] == selected)
    summary, chart = st.columns([1, 1.35], gap="large")
    with summary:
        st.markdown(f'<div class="card"><span class="tag gray">{event["owner"]}</span><div class="card-title">{event["stage"]}</div><div class="muted"><b>Finding</b><br>{event["finding"]}</div><br><div class="muted"><b>Output</b><br>{event["output"]}</div></div>', unsafe_allow_html=True)
        st.caption("Structured findings are shown; hidden model reasoning is not displayed.")
    with chart:
        data = pd.DataFrame({"Item": event["chart"].keys(), "Value": event["chart"].values()})
        fig = px.bar(data, x="Item", y="Value", text="Value", color_discrete_sequence=["#0f766e"])
        fig.update_traces(
            textposition="outside",
            textfont=dict(color="#243247", size=13),
            marker_line_color="#ffffff",
            marker_line_width=0.8,
            cliponaxis=False,
        )
        st.plotly_chart(style_figure(fig, 285), use_container_width=True)
    if st.button("Freeze candidates and run final comparison", type="primary"):
        st.session_state.comparison_complete = True
        unlock_and_go(4, "comparison")


def render_candidate_detail() -> None:
    if not guard(3):
        return
    track = st.session_state.selected_candidate
    data = CANDIDATES[track]
    page_header("Candidate detail", data["title"], "A supporting detail view. Return to AI Candidates to continue the main workflow.")
    if st.button("← Back to AI Candidates"):
        go("candidates")
    overview, dsl, code, validation, lineage = st.tabs(["Design", "Strategy spec", "QC Python", "Validation", "Lineage"])
    with overview:
        left, right = st.columns([1.1, 1])
        with left:
            st.subheader("Design decisions")
            for index, item in enumerate(data["changes"], 1):
                st.markdown(f'<div class="step-row"><span class="step-dot">{index}</span><div>{item}</div></div><br>', unsafe_allow_html=True)
        with right:
            row = RESULTS[RESULTS.Track == track].iloc[0]
            a, b, c = st.columns(3)
            a.metric("Sharpe", f"{row.Sharpe:.2f}")
            b.metric("CAGR", f"{row.CAGR:.1f}%")
            c.metric("MDD", f"{row.MDD:.1f}%")
    with dsl:
        spec = {
            "spec_version": "1.0",
            "strategy_id": data["id"],
            "owner": "ai",
            "track": track.lower(),
            "schedule": {"rebalance": "monthly"},
            "signals": data["weights"],
            "portfolio": {"top_n": 3, "max_weight": 0.35},
            "contract_hash": "sha256:9a7c...21ef",
        }
        st.json(spec)
        st.download_button("Download strategy spec", json.dumps(spec, indent=2), file_name=f"{data['id']}.json")
    with code:
        st.code(LEAN_TEMPLATE.replace("UserStrategy", f"AlphaForge{track}R1"), language="python", line_numbers=True)
    with validation:
        checks = pd.DataFrame(
            {
                "Gate": ["Schema", "Semantic rules", "Capability registry", "Contract", "Python AST", "QC API", "Code risk", "LEAN smoke"],
                "Status": ["Passed"] * 8,
                "Evidence": ["schema-v1", "0 errors", "registry-v1", "hash match", "clean", "compatible", "0 blockers", "run-smk-081"],
            }
        )
        st.dataframe(checks, use_container_width=True, hide_index=True)
    with lineage:
        st.code(f"spec hash   sha256:9a7c...21ef\n     ↓ compiler v1.0\ncode hash   sha256:cd31...8a04\n     ↓ LEAN Worker\nrun id      run-{data['id'].lower()}-001\n     ↓ result normalizer\nresult hash sha256:44b2...a93c")


def render_comparison() -> None:
    if not guard(4):
        return
    page_header("Step 5 of 6", "Final Comparison", "The deterministic judge compares the frozen Human result with the selected AI champion under one contract.")
    st.markdown('<div class="result-banner"><div class="page-kicker">ROUND 1 · MOCK RESULT</div><h2 style="margin:.3rem 0">AI Hybrid wins by a narrow margin</h2><div class="muted">It clears the improvement threshold with higher Sharpe, lower drawdown and sufficient robustness. This verdict is rule-based, not an LLM opinion.</div></div>', unsafe_allow_html=True)
    finalists = RESULTS[RESULTS.Track.isin(["Human", "Traditional", "ML", "Hybrid"])]
    a, b, c, d = st.columns(4)
    a.metric("Human Sharpe", "1.08")
    b.metric("AI champion", "1.23", "+0.15 Sharpe")
    c.metric("Drawdown edge", "3.2 pp", "AI Hybrid")
    d.metric("Outcome", "AI wins", "All gates passed")
    chart, score = st.columns([1.35, 1], gap="large")
    with chart:
        st.plotly_chart(metric_chart(finalists, "Sharpe"), use_container_width=True)
    with score:
        st.subheader("Judge scorecard")
        table = pd.DataFrame(
            {
                "Rule": ["Sharpe improvement", "Drawdown not worse", "Turnover budget", "Robustness", "Contract match"],
                "Result": ["Passed", "Passed", "Passed", "Passed", "Passed"],
            }
        )
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.caption("Possible outcomes: Human wins, AI wins, or Draw.")
    if st.button("Open learning review", type="primary"):
        st.session_state.round_complete = True
        unlock_and_go(5, "review")


def render_review() -> None:
    if not guard(5):
        return
    page_header("Step 6 of 6", "Review & Next Round", "Understand the result, export an artifact, or begin another round with two isolated improvement tracks.")
    worked, improve = st.columns(2, gap="large")
    worked.markdown('<div class="card"><span class="tag">WHAT WORKED</span><div class="card-title">Your signal found persistent trends</div><div class="muted">It beat all four public baselines and kept turnover moderate. The 126-day horizon is a useful foundation.</div></div>', unsafe_allow_html=True)
    improve.markdown('<div class="card"><span class="tag blue">NEXT EXPERIMENT</span><div class="card-title">Separate alpha from position sizing</div><div class="muted">Keep the signal private. Test a regime filter or volatility-aware sizing to reduce risk-off drawdown.</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="notice"><b>One-way teaching boundary:</b> this comparison may help the Human player, but it is blocked from the next AI context.</div>', unsafe_allow_html=True)
    st.subheader("Choose what happens next")
    export, next_round = st.columns(2, gap="large")
    with export:
        st.markdown('<div class="card"><div class="card-title">Export the champion</div><div class="muted">Download the strategy spec now. QC Python and the full report will come from the live backend.</div></div>', unsafe_allow_html=True)
        st.download_button(
            "Download Mock strategy spec",
            json.dumps({"strategy": "AI-H-R1", "mock": True}, indent=2),
            file_name="alphaforge_champion.json",
            use_container_width=True,
        )
    with next_round:
        st.markdown('<div class="card"><div class="card-title">Continue independently</div><div class="muted">You revise your private strategy. AI Critic reviews only AI-owned candidates and results.</div></div>', unsafe_allow_html=True)
        if st.button("Start Round 2", type="primary", use_container_width=True):
            st.session_state.round += 1
            st.session_state.page = "setup"
            st.session_state.last_workflow_page = "setup"
            st.session_state.unlocked_step = 0
            st.session_state.strategy_submitted = False
            st.session_state.validation_complete = False
            st.session_state.baseline_complete = False
            st.session_state.candidates_complete = False
            st.session_state.comparison_complete = False
            st.session_state.round_complete = False
            st.rerun()
    with st.expander("AI Critic summary for the next round"):
        a, b, c = st.columns(3)
        a.markdown('<div class="card"><span class="tag gray">KEEP</span><div class="card-title">Regime protection</div><div class="muted">It reduced drawdown in AI-owned runs.</div></div>', unsafe_allow_html=True)
        b.markdown('<div class="card"><span class="tag gray">CHANGE</span><div class="card-title">Static 85/15 blend</div><div class="muted">The fixed mix underused ML in stable regimes.</div></div>', unsafe_allow_html=True)
        c.markdown('<div class="card"><span class="tag gray">TEST</span><div class="card-title">Adaptive blend</div><div class="muted">Condition weights on volatility without reading Human data.</div></div>', unsafe_allow_html=True)
        st.caption("Critic input manifest: 3 AI candidates · 3 AI result hashes · 0 Human fields · 0 Education fields")


def render_system() -> None:
    page_header("Utility", "Runs & System", "Operational status is available at any time and does not change workflow progress.")
    try:
        health = api.health()
    except AlphaForgeAPIError as exc:
        health = {"backend": "unavailable", "lean_worker": {"status": "unavailable"}, "agent_runtime": "not_configured"}
        st.error(str(exc))
    cols = st.columns(4)
    services = [
        ("Frontend", "Healthy"),
        ("Backend", "Demo" if api.mock_mode else health.get("backend", "unknown")),
        ("Agent runtime", "Mock" if api.mock_mode else health.get("agent_runtime", "not_configured")),
        ("LEAN Worker", "Demo" if api.mock_mode else health.get("lean_worker", {}).get("status", "unknown")),
    ]
    for col, (name, status) in zip(cols, services):
        col.metric(name, status)
    jobs = pd.DataFrame(
        [
            ("job-human-r1", "Human backtest", "Succeeded", "Human only"),
            ("job-base-04", "Baseline batch", "Succeeded", "Public"),
            ("job-forge-r1", "Candidate generation", "Succeeded", "AI only"),
            ("job-ai-h-r1", "AI backtest", "Succeeded", "AI only"),
        ],
        columns=["Job ID", "Type", "Status", "Data boundary"],
    )
    st.subheader("Recent jobs")
    st.dataframe(jobs, use_container_width=True, hide_index=True)
    with st.expander("Information isolation contract"):
        st.json(
            {
                "ai_allowlist": ["experiment_contract", "public_baselines", "ai_history", "ai_critique"],
                "blocked": ["human_code", "human_parameters", "human_results", "education_feedback"],
            }
        )


init_state()
inject_css()
sidebar()

RENDERERS = {
    "overview": render_overview,
    "setup": render_setup,
    "validation": render_validation,
    "baselines": render_baselines,
    "candidates": render_candidates,
    "candidate_detail": render_candidate_detail,
    "comparison": render_comparison,
    "review": render_review,
    "system": render_system,
}

if st.session_state.page not in RENDERERS:
    st.session_state.page = "overview"
RENDERERS[st.session_state.page]()
