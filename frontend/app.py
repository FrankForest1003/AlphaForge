from __future__ import annotations

import json
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import AlphaForgeAPI
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
        "battle_id": "BTL-2026-071",
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
            --ink: #172033;
            --body: #334155;
            --muted: #526174;
            --subtle: #64748b;
            --teal: #0f766e;
            --teal-hover: #115e59;
            --teal-soft: #e7f3f1;
            --blue: #1d4ed8;
            --blue-soft: #eaf1ff;
            --border: #d5dde5;
            --border-strong: #c2ccd6;
            --surface: #ffffff;
            --surface-soft: #f7f9fb;
            --canvas: #f3f6f8;
          }
          .stApp { background: var(--canvas); color: var(--body); }
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
          .block-container { max-width: 1320px; padding-top: 2rem; padding-bottom: 5rem; }
          h1, h2, h3 { color: var(--ink) !important; letter-spacing: -.025em; }
          h1 { font-size: 2rem !important; margin-bottom: .25rem !important; }
          h2 { font-size: 1.35rem !important; }
          h3 { font-size: 1.05rem !important; }
          .brand { font-size: 1.18rem; font-weight: 800; color: var(--ink); letter-spacing: -.02em; }
          .brand-sub { color: var(--muted); font-size: .77rem; margin-top: .12rem; }
          .page-kicker { color: #0b6b63; font-size: .72rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
          .page-subtitle { color: var(--muted); font-size: .96rem; line-height: 1.55; max-width: 780px; }
          .section-label { color: #4c5d70; font-size: .72rem; font-weight: 780; letter-spacing: .08em; text-transform: uppercase; }
          .card {
            padding: 1rem 1.05rem;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: var(--surface);
            min-height: 112px;
            box-shadow: 0 1px 2px rgba(23,32,51,.035);
          }
          .card-title { color: var(--ink); font-size: 1rem; font-weight: 760; margin: .22rem 0 .35rem; }
          .muted { color: #4b5b6d; font-size: .89rem; line-height: 1.55; }
          .muted b { color: #2d3c4f; }
          .tag {
            display: inline-block; padding: .2rem .48rem; border-radius: 5px;
            background: var(--teal-soft); color: #0b625b; font-size: .69rem; font-weight: 780;
          }
          .tag.gray { background: #edf1f4; color: #425466; }
          .tag.blue { background: var(--blue-soft); color: #1e4f85; }
          .notice {
            padding: .8rem .95rem; border: 1px solid #bddbd5; border-radius: 10px;
            background: #edf7f4; color: #244a46; margin: .4rem 0 1rem;
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
            background: var(--surface); border: 1px solid var(--border); padding: .75rem .9rem; border-radius: 10px;
          }
          div[data-testid="stMetric"] label { color: #526174 !important; font-weight: 650; }
          div[data-testid="stMetricValue"] { color: var(--ink); }
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
          [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
          .stTabs [data-baseweb="tab-list"] { gap: 1.25rem; border-bottom: 1px solid var(--border); }
          .stTabs [data-baseweb="tab"] { padding-left: 0; padding-right: 0; color: #526174; }
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
          [data-testid="stAlert"] { color: var(--body); }
          [data-testid="stAlert"] p { color: inherit !important; }
          hr { border-color: var(--border) !important; }
          code { font-size: .82rem !important; color: #243247 !important; }
          a { color: #145fa3; }
          a:hover { color: #0f477a; }
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


def metric_chart(frame: pd.DataFrame, metric: str, height: int = 340):
    fig = px.bar(
        frame,
        x="Strategy",
        y=metric,
        color="Track",
        color_discrete_map=COLORS,
        text=metric,
    )
    fig.update_traces(
        texttemplate="%{text:.2f}", textposition="outside",
        textfont=dict(color="#243247", size=13),
        marker_line_color="#ffffff", marker_line_width=0.8,
        cliponaxis=False,
    )
    fig.update_xaxes(tickangle=-18)
    return style_figure(fig, height=height)


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
    b.metric("Human best Sharpe", "1.08", "Mock preview")
    c.metric("AI best Sharpe", "1.23", "Mock preview")
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
    rules, strategy = st.columns([1, 1.25], gap="large")
    with rules:
        st.subheader("Experiment contract")
        start, end = st.columns(2)
        start.date_input("Start date", date(2015, 1, 1))
        end.date_input("End date", date(2025, 12, 31))
        st.multiselect(
            "Universe",
            ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "JPM", "COST"],
            default=["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
        )
        cash, cost = st.columns(2)
        cash.number_input("Initial cash (USD)", value=100000, step=10000)
        cost.number_input("Transaction cost (bps)", value=10, min_value=0)
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
        if mode == "Guided Mode":
            template = st.selectbox("Framework", ["Multi-Horizon Momentum", "SMA Risk Filter", "Mean Reversion"])
            lookback, top_n, max_weight = st.columns(3)
            lookback_value = lookback.slider("Lookback days", 21, 252, 126)
            top_n_value = top_n.slider("Hold Top N", 1, 10, 3)
            max_weight_value = max_weight.slider("Max weight (%)", 10, 100, 35)
            st.markdown(
                f'<div class="card"><span class="tag blue">LIVE SUMMARY</span><div class="card-title">{template}</div><div class="muted">Rank the universe using {lookback_value} days of history, hold the top {top_n_value}, and cap each position at {max_weight_value}%.</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.session_state.lean_code = st.text_area("LEAN Python", st.session_state.lean_code, height=330)
            st.caption("Code is not sent to any AI Designer. It is used only by validation, LEAN execution and the post-round learning module.")
    st.write("")
    if st.button("Save contract and submit strategy", type="primary"):
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
                ("QCAlgorithm structure", "Requires a valid algorithm class and Initialize method."),
                ("Restricted capabilities", "Blocks network, subprocess and unrestricted file access."),
                ("LEAN smoke test", "Runs a short isolated execution before the full backtest."),
            ]
            for name, detail in checks:
                st.markdown(f'<div class="card" style="min-height:auto;margin-bottom:.55rem"><div class="card-title">{name}</div><div class="muted">{detail}</div></div>', unsafe_allow_html=True)
        with right:
            st.subheader("Submission summary")
            st.markdown(f'<div class="card"><span class="tag gray">HUMAN · R{st.session_state.round}</span><div class="card-title">{st.session_state.strategy_mode}</div><div class="muted">Contract BTL-2026-071 · 2015–2025 · monthly rebalance · 10 bps cost</div></div>', unsafe_allow_html=True)
            st.write("")
            if st.button("Run admission checks", type="primary", use_container_width=True):
                result = api.validate_code(st.session_state.battle_id, st.session_state.lean_code)
                st.session_state.validation_result = result
                st.session_state.validation_complete = result["accepted"]
                st.rerun()
        return
    rows = [
        {"Check": "Python syntax", "Status": "Passed", "Evidence": "AST parsed"},
        {"Check": "QCAlgorithm entry", "Status": "Passed", "Evidence": "Entry class found"},
        {"Check": "Restricted capabilities", "Status": "Passed", "Evidence": "No blocked calls"},
        {"Check": "LEAN smoke test", "Status": "Passed", "Evidence": "Mock run completed"},
    ]
    st.success("Admission passed. The Human strategy version is now frozen for this round.")
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if st.button("Run Human and baseline backtests", type="primary"):
        st.session_state.baseline_complete = True
        unlock_and_go(2, "baselines")


def render_baselines() -> None:
    if not guard(2):
        return
    page_header("Step 3 of 6", "Baseline Comparison", "Understand the four public reference strategies and compare them with your frozen result.")
    st.markdown('<div class="notice"><b>Information boundary:</b> this page is visible to you. AI Designers receive the four baseline results only; your row and all Human analysis are removed from their context.</div>', unsafe_allow_html=True)
    frame = RESULTS.iloc[:5]
    human = frame.iloc[0]
    a, b, c, d = st.columns(4)
    a.metric("Human Sharpe", f"{human.Sharpe:.2f}", "+0.12 vs best baseline")
    b.metric("CAGR", f"{human.CAGR:.1f}%")
    c.metric("Max drawdown", f"{human.MDD:.1f}%")
    d.metric("Turnover", f"{human.Turnover:.1f}%")
    chart, explanation = st.columns([1.5, 1], gap="large")
    with chart:
        st.plotly_chart(metric_chart(frame, "Sharpe"), use_container_width=True)
    with explanation:
        st.subheader("What this tells you")
        st.markdown('<div class="card"><div class="card-title">Your signal adds value</div><div class="muted">It leads all four public baselines on risk-adjusted return in this Mock result. The remaining concern is drawdown rather than raw return.</div></div>', unsafe_allow_html=True)
        st.write("")
        st.markdown('<div class="card"><div class="card-title">Sharpe is not the whole score</div><div class="muted">The final judge also checks drawdown, turnover, robustness and the shared experiment contract.</div></div>', unsafe_allow_html=True)
    st.subheader("Four public baselines")
    cols = st.columns(4)
    for col, (no, name, idea, lesson, recipe) in zip(cols, BASELINE_LESSONS):
        col.markdown(f'<div class="card"><span class="tag gray">BASELINE {no}</span><div class="card-title">{name}</div><div class="muted">{idea}</div><br><div class="muted"><b>Lesson:</b> {lesson}</div><br><span class="tag blue">{recipe}</span></div>', unsafe_allow_html=True)
    st.write("")
    if st.button("Freeze public evidence and generate AI candidates", type="primary"):
        st.session_state.candidates_complete = True
        unlock_and_go(3, "candidates")


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
    cols = st.columns(4)
    services = [
        ("Frontend", "Healthy"),
        ("Backend", "Reserved" if api.mock_mode else "Healthy"),
        ("Agent runtime", "Mock" if api.mock_mode else "Healthy"),
        ("LEAN Worker", "Reserved" if api.mock_mode else "Healthy"),
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
