"""
AB Fulfillment & Supply Defect Intelligence - Streamlit dashboard.

Tabs: Fulfillment | Escalation Queue | Supply | SQL Explorer | Data Quality.
All data on this dashboard is SIMULATED unless you load your own CSVs through
the pipeline (see README).
"""

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from modules.warehouse import Warehouse  # noqa: E402
from pipeline_direct import run as run_direct  # noqa: E402

# categorical slots 1-2 of the validated reference palette; neutrals for reference lines
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#8a8984"
RED, AMBER, GREEN = "#b91c1c", "#a16207", "#15803d"

st.set_page_config(page_title="AB Defect Intelligence", layout="wide")


def _layout(fig: go.Figure, title: str, height: int = 340, yfmt: str | None = None) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)), height=height,
        margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.2),
        hovermode="x unified" if yfmt else "closest",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,.18)", tickformat=yfmt, zeroline=False)
    return fig


def _hline(fig: go.Figure, y: float, label: str, color: str = GREY) -> None:
    fig.add_hline(y=y, line=dict(color=color, width=1, dash="dash"),
                  annotation_text=label, annotation_position="top left",
                  annotation_font=dict(size=11, color=color))


# ── sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Pipeline")
    pipeline = st.radio("pipeline", ["Direct (no LLM)", "Claude-augmented"],
                        label_visibility="collapsed")
    api_key = None
    if pipeline == "Claude-augmented":
        api_key = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-...")
        st.caption("Key is held in this session only.")
    n_days = st.slider("Days of data", 28, 90, 90)
    seed = st.number_input("Random seed", value=42, step=1)
    run_btn = st.button("Run analysis", type="primary", use_container_width=True)
    st.caption("All data is simulated. Seeded anomalies exist to validate detection.")

st.title("AB Fulfillment & Supply Defect Intelligence")
st.caption("Defect detection, root cause, inventory policy, supplier OTIF and an owned escalation queue. "
           "SQL on DuckDB, pandas, Excel/VBA output.")

# ── run ────────────────────────────────────────────────────────────────────
if run_btn:
    if pipeline == "Claude-augmented" and not api_key:
        st.error("Anthropic API key required for the Claude pipeline.")
        st.stop()
    with st.spinner("Running analysis..."):
        out_path = str(Path(tempfile.gettempdir()) / "ab_defect_report.xlsx")
        res = run_direct(seed=int(seed), n_days=n_days, output_path=out_path, verbose=False)
        memo, guard = "", None
        if pipeline == "Claude-augmented":
            try:
                import anthropic
                from modules.excel_reporter import build_workbook
                from pipeline_claude import SYSTEM_PROMPT, _build_payload, _guard
                payload = _build_payload(res)
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model=config.CLAUDE_MODEL, max_tokens=1500, system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content":
                               f"Write the escalation memo.\n\nMETRICS:\n{json.dumps(payload, indent=2, default=str)}"
                               "\n\nUse only the numbers above."}])
                memo = msg.content[0].text
                guard = _guard(memo, payload)
                f = res["_frames"]
                build_workbook(f["df"], f["anomalies"], f["root"], memo_text=memo,
                               output_path=out_path, queue=f["queue"], supply=f["supply"])
            except Exception as e:  # surface, don't crash the dashboard
                st.error(f"Claude step failed: {e}")
        st.session_state["res"] = {"run": res, "memo": memo, "guard": guard, "path": out_path}

if "res" not in st.session_state:
    st.info("Set the options in the sidebar and click **Run analysis**.")
    st.stop()

R = st.session_state["res"]
res, F = R["run"], R["run"]["_frames"]
df, A, root, queue, supply = F["df"], F["anomalies"], F["root"], F["queue"], F["supply"]
wh: Warehouse = F["warehouse"]
o, wow = A["overall"], A["wow"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Overall defect rate", f"{o['overall_defect_rate']:.2%}",
          f"{wow['delta']:+.2%} WoW", delta_color="inverse")
c2.metric("Open P1 escalations", int((queue["priority"] == "P1").sum()))
if supply:
    c3.metric("Network OTIF", f"{supply['supplier_summary']['network_otif']:.1%}",
              f"target {config.OTIF_TARGET:.0%}", delta_color="off")
    c4.metric("Inventory fill rate", f"{supply['inventory_summary']['network_fill_rate']:.1%}")

tab_f, tab_q, tab_s, tab_sql, tab_dq = st.tabs(
    ["Fulfillment", "Escalation Queue", "Supply", "SQL Explorer", "Data Quality"])

# ── Fulfillment ────────────────────────────────────────────────────────────
with tab_f:
    nodes = A["nodes"].sort_values("defect_rate")
    fig = go.Figure(go.Bar(x=nodes["defect_rate"], y=nodes["node"], orientation="h",
                           marker_color=BLUE, hovertemplate="%{y}: %{x:.2%}<extra></extra>"))
    _hline_x = lambda x, t: fig.add_vline(x=x, line=dict(color=GREY, width=1, dash="dash"),
                                          annotation_text=t, annotation_font=dict(size=11, color=GREY))
    _hline_x(config.WARNING_THRESHOLD, f"watch {config.WARNING_THRESHOLD:.1%}")
    _hline_x(config.DEFECT_THRESHOLD, f"escalate {config.DEFECT_THRESHOLD:.0%}")
    fig.update_xaxes(range=[0, max(config.DEFECT_THRESHOLD * 1.1, nodes["defect_rate"].max() * 1.1)])
    st.plotly_chart(_layout(fig, "Defect rate by fulfillment center (full period)", 380, "0.0%"),
                    use_container_width=True)

    colA, colB = st.columns(2)
    with colA:
        wk = wh.run("04_weekly_trend")
        net = wk.groupby("week_start").agg(d=("defects", "sum"), s=("shipments", "sum")).reset_index()
        net["rate"] = net["d"] / net["s"]
        fig = go.Figure(go.Scatter(x=net["week_start"], y=net["rate"], mode="lines+markers",
                                   line=dict(color=BLUE, width=2), marker=dict(size=7),
                                   hovertemplate="%{x|%b %d}: %{y:.2%}<extra></extra>"))
        st.plotly_chart(_layout(fig, "Network defect rate by week (complete weeks)", 320, "0.0%"),
                        use_container_width=True)
    with colB:
        p = root["pareto"].sort_values("count")
        fig = go.Figure(go.Bar(x=p["pct_of_total"], y=p["label"], orientation="h", marker_color=BLUE,
                               customdata=p["cumulative_pct"],
                               hovertemplate="%{y}: %{x:.1%} of defects<br>cumulative %{customdata:.1%}<extra></extra>"))
        st.plotly_chart(_layout(fig, "Pareto - share of defects by type", 320, "0%"),
                        use_container_width=True)

    node_pick = st.selectbox("Node daily view (rate vs same-weekday baseline)", sorted(df["node"].unique()),
                             index=sorted(df["node"].unique()).index("CHI-4"))
    d = F["rolling"][F["rolling"]["node"] == node_pick]
    ev = d[d["is_anomaly"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["date"], y=d["base_mean"], name="same-weekday baseline", mode="lines",
                             line=dict(color=GREY, width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=d["date"], y=d["defect_rate"], name=f"{node_pick} daily rate", mode="lines",
                             line=dict(color=BLUE, width=2)))
    fig.add_trace(go.Scatter(x=ev["date"], y=ev["defect_rate"], name="anomaly", mode="markers",
                             marker=dict(color=ORANGE, size=9, line=dict(color="white", width=2))))
    st.plotly_chart(_layout(fig, f"{node_pick}: daily defect rate and anomalies", 340, "0.0%"),
                    use_container_width=True)

    st.markdown("**Largest excess-defect segments** (actual defects minus shipments x network rate)")
    cont = F["contribution"]
    st.dataframe(cont[cont["rank_in_dimension"] <= 5][
        ["node", "dimension", "segment", "shipments", "defect_rate", "rate_ratio", "excess_defects", "top_defect"]
    ].style.format({"shipments": "{:,.0f}", "defect_rate": "{:.2%}", "rate_ratio": "{:.2f}x",
                    "excess_defects": "{:,.0f}"}), use_container_width=True, hide_index=True)

# ── Escalation queue ───────────────────────────────────────────────────────
with tab_q:
    dom = st.multiselect("Domain", sorted(queue["domain"].unique()), default=sorted(queue["domain"].unique()))
    q = queue[queue["domain"].isin(dom)]
    st.dataframe(q.style.format({"value": "{:.2%}", "benchmark": "{:.2%}", "est_cost_usd": "${:,.0f}"}),
                 use_container_width=True, hide_index=True)
    st.caption("Score = 100 x (0.5 x impact + 0.5 x deviation). Impact is dollars vs a per-domain materiality cap; "
               "deviation is distance from benchmark. Owners and SLA days come from config.py.")

# ── Supply ─────────────────────────────────────────────────────────────────
with tab_s:
    if not supply:
        st.info("No inventory / PO data in this run.")
    else:
        sc = supply["supplier_scorecard"].sort_values("otif")
        fig = go.Figure(go.Bar(x=sc["otif"], y=sc["supplier_id"], orientation="h", marker_color=BLUE,
                               hovertemplate="%{y}: OTIF %{x:.1%}<extra></extra>"))
        fig.add_vline(x=config.OTIF_TARGET, line=dict(color=GREY, width=1, dash="dash"),
                      annotation_text=f"target {config.OTIF_TARGET:.0%}", annotation_font=dict(size=11, color=GREY))
        fig.update_xaxes(range=[0, 1.05])
        st.plotly_chart(_layout(fig, "Supplier OTIF (on-time AND in-full per PO)", 340, "0%"),
                        use_container_width=True)

        pol = supply["policy"]
        cat = pol.groupby("category").apply(
            lambda g: g["fulfilled_units"].sum() / g["demand_units"].sum(), include_groups=False
        ).sort_values().reset_index(name="fill")
        fig = go.Figure(go.Bar(x=cat["fill"], y=cat["category"], orientation="h", marker_color=BLUE,
                               hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
        fig.update_xaxes(range=[0.7, 1.0])
        st.plotly_chart(_layout(fig, "Inventory fill rate by category (axis starts at 70%)", 340, "0%"),
                        use_container_width=True)

        hist = (supply["daily_demand"].assign(date=lambda x: pd.to_datetime(x["date"]))
                .groupby("date")["demand_units"].sum().tail(28))
        fc = (supply["forecast"].assign(date=lambda x: pd.to_datetime(x["date"]))
              .groupby("date")["forecast_units"].sum())
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist.index, y=hist.values, name="actual", mode="lines",
                                 line=dict(color=BLUE, width=2)))
        fig.add_trace(go.Scatter(x=fc.index, y=fc.values, name="forecast", mode="lines",
                                 line=dict(color=ORANGE, width=2)))
        st.plotly_chart(_layout(fig, f"Network demand: 28 days actual, {config.FORECAST_HORIZON_DAYS} days forecast "
                                      f"(median backtest WAPE {supply['inventory_summary']['median_wape']:.1%})",
                                340, ",.0f"), use_container_width=True)

        st.markdown("**Reorder policy** (safety stock = z x sqrt(LT x sd_d^2 + d^2 x sd_LT^2))")
        show = pol[["node", "category", "supplier_id", "on_hand", "on_order", "days_of_supply", "safety_stock",
                    "reorder_point", "current_policy_rop", "recommended_order_qty", "status"]]
        st.dataframe(show.style.format({"days_of_supply": "{:.1f}", "on_hand": "{:,.0f}", "on_order": "{:,.0f}",
                                        "safety_stock": "{:,.0f}", "reorder_point": "{:,.0f}",
                                        "current_policy_rop": "{:,.0f}", "recommended_order_qty": "{:,.0f}"}),
                     use_container_width=True, hide_index=True)

# ── SQL explorer ───────────────────────────────────────────────────────────
with tab_sql:
    st.caption(f"Tables: {', '.join(wh.tables())}. Read-only; one SELECT / WITH statement.")
    names = wh.list_queries()
    pick = st.selectbox("Named query", names)
    st.code(wh.query_text(pick), language="sql")
    st.dataframe(wh.run(pick).head(200), use_container_width=True, hide_index=True)
    st.markdown("**Ad-hoc query**")
    text = st.text_area("SQL", "SELECT node, SUM(total_defects) AS defects\nFROM fulfillment\nGROUP BY node\nORDER BY defects DESC",
                        height=120)
    if st.button("Run SQL"):
        try:
            st.dataframe(wh.sql(text), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(str(e))

# ── Data quality ───────────────────────────────────────────────────────────
with tab_dq:
    chk = pd.DataFrame(res["reconciliation"])
    st.metric("Reconciliation checks passed", f"{int(chk['passed'].sum())}/{len(chk)}")
    chk["result"] = chk["passed"].map({True: "PASS", False: "FAIL"})
    st.dataframe(chk[["result", "check", "detail"]], use_container_width=True, hide_index=True)
    st.caption("Metrics are computed twice by independent code (pandas and SQL) and compared before use.")

# ── downloads & memo ───────────────────────────────────────────────────────
st.divider()
with open(R["path"], "rb") as fh:
    st.download_button("Download Excel report (.xlsx)", fh.read(), file_name="AB_Defect_Report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.caption("Workbook sheets include live formulas (Formula Pivot). To add the real VBA macros see vba/README.md.")

if R["memo"]:
    st.subheader(f"Escalation memo ({config.CLAUDE_MODEL})")
    st.text(R["memo"])
    g = R["guard"]
    if g:
        st.metric("Hallucination guard reliability", f"{g['reliability_score']}%", g["overall_status"], delta_color="off")
        st.caption(f"{g['verified']} verified, {g['approx']} approximate, {g['unverified']} unverified numbers.")
