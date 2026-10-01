"""
AB Fulfillment Defect Intelligence — Excel Reporter
Builds a fully formatted Excel workbook using openpyxl.

Python generates the report (auto-formatted tables, status colours, freeze
panes, filters, native charts, live formulas) so it runs on a schedule. The
same workbook can then be refreshed/formatted/exported by the real VBA macros
in vba/DefectReportMacros.bas - see vba/README.md.

Sheets:
  1. Weekly Summary    Overview KPIs, node status, WoW trend
  2. Node Analysis     Defect rates by FC with color coding
  3. Root Cause        Pareto + weighted impact table
  4. Carrier Report    Carrier performance ranking
  5. Drill Down        Full daily data, auto-filtered
  6. Escalation Memo   Pre-filled memo for FC partners (Claude pipeline)
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone

import openpyxl
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
import pandas as pd


# ── Color palette ──────────────────────────────────────────────────────────
CLR = {
    "header_bg":   "1A1A2E",  # dark navy
    "header_font": "FFFFFF",
    "red":         "FEE2E2",  # escalate
    "red_font":    "B91C1C",
    "yellow":      "FEF9C3",  # watch
    "yellow_font": "A16207",
    "green":       "DCFCE7",  # ok
    "green_font":  "15803D",
    "blue_light":  "EFF6FF",  # accent
    "border":      "E4E4E7",
    "subheader":   "F4F4F5",
    "text_muted":  "71717A",
}

THIN = Side(style="thin", color=CLR["border"])
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FONT = Font(name="Calibri", bold=True, color=CLR["header_font"], size=10)
BODY_FONT   = Font(name="Calibri", size=10)
BOLD_FONT   = Font(name="Calibri", bold=True, size=10)
MONO_FONT   = Font(name="Courier New", size=9)

HDR_FILL  = PatternFill("solid", fgColor=CLR["header_bg"])
RED_FILL  = PatternFill("solid", fgColor=CLR["red"])
YEL_FILL  = PatternFill("solid", fgColor=CLR["yellow"])
GRN_FILL  = PatternFill("solid", fgColor=CLR["green"])
SUB_FILL  = PatternFill("solid", fgColor=CLR["subheader"])
BLU_FILL  = PatternFill("solid", fgColor=CLR["blue_light"])

PCT_FMT = "0.00%"
INT_FMT = "#,##0"


def _hdr(ws: Worksheet, row: int, col: int, value: str) -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.font = HEADER_FONT
    c.fill = HDR_FILL
    c.border = BORDER
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _cell(ws: Worksheet, row: int, col: int, value,
          bold: bool = False, fmt: str | None = None,
          fill=None, align: str = "center") -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.font = BOLD_FONT if bold else BODY_FONT
    c.border = BORDER
    c.alignment = Alignment(horizontal=align, vertical="center")
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill


def _status_fill(status: str):
    return {"ESCALATE": RED_FILL, "WATCH": YEL_FILL, "OK": GRN_FILL}.get(status, None)


def _auto_width(ws: Worksheet, min_w: int = 10, max_w: int = 40) -> None:
    for col in ws.columns:
        length = max(
            len(str(c.value)) if c.value is not None else 0
            for c in col
        )
        ws.column_dimensions[get_column_letter(col[0].column)].width = (
            max(min_w, min(length + 3, max_w))
        )


# ── Sheet builders ─────────────────────────────────────────────────────────

def _sheet_summary(ws: Worksheet, anomalies: dict, root: dict, simulated: bool = False) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A4"

    # Title
    ws.merge_cells("A1:H1")
    title = ws["A1"]
    title.value = "AB Fulfillment Defect Intelligence — Weekly Summary"
    title.font = Font(name="Calibri", bold=True, size=14, color=CLR["header_bg"])
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 28

    overall = anomalies["overall"]
    wow     = anomalies["wow"]
    esc     = anomalies["escalation_summary"]

    # KPI row
    ws.merge_cells("A2:H2")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ws["A2"].value = (f"Generated: {ts}  |  Period: {wow['week_range']}"
                      + ("  |  SIMULATED DATA - not real Amazon data" if simulated else ""))
    ws["A2"].font = Font(name="Calibri", size=9, color=CLR["text_muted"])
    ws["A2"].alignment = Alignment(horizontal="left")
    ws.row_dimensions[2].height = 16

    # KPI headers
    kpis = [
        ("Total Shipments", overall["total_shipments"], INT_FMT),
        ("Total Defects",   overall["total_defects"],   INT_FMT),
        ("Overall Defect Rate", overall["overall_defect_rate"], PCT_FMT),
        ("WoW Change",  wow["delta"], PCT_FMT),
        ("WoW Direction", wow["direction"], None),
        ("Nodes to Escalate", esc["n_escalate"], INT_FMT),
        ("Nodes on Watch",   esc["n_watch"],    INT_FMT),
        ("Anomaly Nodes",    len(esc["anomaly_nodes"]), INT_FMT),
    ]
    for i, (label, val, fmt) in enumerate(kpis, 1):
        _hdr(ws, 3, i, label)
        fill = (RED_FILL if i == 6 and esc["n_escalate"] > 0 else
                YEL_FILL if i == 7 and esc["n_watch"] > 0 else None)
        _cell(ws, 4, i, val, bold=True, fmt=fmt, fill=fill)
    ws.row_dimensions[3].height = 30
    ws.row_dimensions[4].height = 22

    # Formula transparency
    ws["A5"].value = f"Formula: defect_rate = total_defects / total_shipments = {overall['total_defects']}/{overall['total_shipments']} = {overall['overall_defect_rate']:.4f}"
    ws["A5"].font = Font(name="Courier New", size=8, color=CLR["text_muted"])
    ws.merge_cells("A5:H5")

    # Node status table
    row = 7
    _hdr(ws, row, 1, "Fulfillment Center")
    for i, h in enumerate(["Total Shipments", "Total Defects", "Defect Rate",
                            "Z-Score", "Status", "Anomaly", "Top Action"], 2):
        _hdr(ws, row, i, h)

    for _, r in anomalies["nodes"].iterrows():
        row += 1
        fill = _status_fill(r["status"])
        _cell(ws, row, 1, r["node"], bold=True, align="left")
        _cell(ws, row, 2, r["total_shipments"], fmt=INT_FMT)
        _cell(ws, row, 3, r["total_defects"],   fmt=INT_FMT)
        _cell(ws, row, 4, r["defect_rate"],      fmt=PCT_FMT, fill=fill)
        _cell(ws, row, 5, r["z_score"])
        _cell(ws, row, 6, r["status"],           fill=fill)
        _cell(ws, row, 7, "YES" if r["anomaly"] else "no",
              fill=RED_FILL if r["anomaly"] else None)
        top = root["node_breakdown"]
        nd = top[top["node"] == r["node"]]
        action = nd["action"].values[0] if len(nd) else ""
        _cell(ws, row, 8, action[:80], align="left")

    _auto_width(ws)


def _sheet_node(ws: Worksheet, anomalies: dict) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.merge_cells("A1:K1")
    ws["A1"].value = "Node-Level Defect Analysis"
    ws["A1"].font = Font(name="Calibri", bold=True, size=12, color=CLR["header_bg"])
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

    headers = ["Node", "Shipments", "Defects", "Defect Rate",
               "Late Delivery", "Missing Pkg", "Damaged", "Wrong Item",
               "Inv Discrepancy", "Failed Pickup", "Status"]
    for i, h in enumerate(headers, 1):
        _hdr(ws, 2, i, h)

    for _, r in anomalies["nodes"].iterrows():
        row = _ + 3
        fill = _status_fill(r["status"])
        vals = [r["node"], r["total_shipments"], r["total_defects"],
                r["defect_rate"],
                r.get("late_delivery", 0), r.get("missing_package", 0),
                r.get("damaged_goods", 0), r.get("wrong_item", 0),
                r.get("inventory_discrepancy", 0), r.get("failed_pickup", 0),
                r["status"]]
        fmts = [None, INT_FMT, INT_FMT, PCT_FMT,
                INT_FMT, INT_FMT, INT_FMT, INT_FMT, INT_FMT, INT_FMT, None]
        for ci, (v, f) in enumerate(zip(vals, fmts), 1):
            _cell(ws, row, ci, v, fmt=f,
                  fill=(fill if ci in (4, 11) else None),
                  align="left" if ci == 1 else "center")

    ws.auto_filter.ref = f"A2:K{2 + len(anomalies['nodes'])}"
    _auto_width(ws)


def _sheet_root_cause(ws: Worksheet, root: dict) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.merge_cells("A1:F1")
    ws["A1"].value = "Root Cause Analysis — Pareto + Weighted Impact"
    ws["A1"].font = Font(name="Calibri", bold=True, size=12, color=CLR["header_bg"])
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

    # Pareto table
    row = 2
    for i, h in enumerate(["Defect Type", "Count", "% of Total",
                             "Cumulative %", "In 80% Pareto", "Escalation Action"], 1):
        _hdr(ws, row, i, h)

    for _, r in root["pareto"].iterrows():
        row = _ + 3
        pareto_fill = GRN_FILL if r["in_pareto_80"] else None
        _cell(ws, row, 1, r["label"], bold=True, align="left")
        _cell(ws, row, 2, r["count"],          fmt=INT_FMT)
        _cell(ws, row, 3, r["pct_of_total"],   fmt=PCT_FMT)
        _cell(ws, row, 4, r["cumulative_pct"], fmt=PCT_FMT, fill=pareto_fill)
        _cell(ws, row, 5, "YES" if r["in_pareto_80"] else "no",
              fill=pareto_fill)
        _cell(ws, row, 6, r["action"], align="left")

    # Weighted impact table
    row += 2
    ws.merge_cells(f"A{row}:F{row}")
    ws[f"A{row}"].value = "Weighted Impact Scores (rate x customer impact weight x 100)"
    ws[f"A{row}"].font = Font(name="Calibri", bold=True, size=11, color=CLR["header_bg"])

    row += 1
    for i, h in enumerate(["Rank", "Defect Type", "Count", "Rate",
                             "Impact Weight", "Impact Score", "Est. Cost $"], 1):
        _hdr(ws, row, i, h)

    for _, r in root["weighted_impact"].iterrows():
        row += 1
        _cell(ws, row, 1, int(r["rank"]), bold=True)
        _cell(ws, row, 2, r["label"],      bold=True, align="left")
        _cell(ws, row, 3, r["count"],      fmt=INT_FMT)
        _cell(ws, row, 4, r["raw_rate"],   fmt=PCT_FMT)
        _cell(ws, row, 5, r["weight"])
        score_fill = (RED_FILL if r["impact_score"] > 0.5 else
                      YEL_FILL if r["impact_score"] > 0.2 else GRN_FILL)
        _cell(ws, row, 6, r["impact_score"], fmt="0.0000", fill=score_fill)
        _cell(ws, row, 7, r.get("est_cost_usd", 0), fmt='"$"#,##0')

    _auto_width(ws)
    ws.column_dimensions["F"].width = 40

    # native Pareto chart on ONE axis: bars = share of defects, line = cumulative share (both %)
    n = len(root["pareto"])
    bar = BarChart()
    bar.title = "Pareto - share of defects by type (bars) and cumulative share (line)"
    bar.height, bar.width = 8, 17
    bar.add_data(Reference(ws, min_col=3, min_row=2, max_row=2 + n), titles_from_data=True)
    bar.set_categories(Reference(ws, min_col=1, min_row=3, max_row=2 + n))
    bar.y_axis.number_format = "0%"
    bar.y_axis.scaling.min, bar.y_axis.scaling.max = 0, 1
    bar.x_axis.delete = False
    bar.y_axis.delete = False
    line = LineChart()
    line.add_data(Reference(ws, min_col=4, min_row=2, max_row=2 + n), titles_from_data=True)
    bar += line
    ws.add_chart(bar, "I2")


def _sheet_carrier(ws: Worksheet, anomalies: dict) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.merge_cells("A1:G1")
    ws["A1"].value = "Carrier Performance Report"
    ws["A1"].font = Font(name="Calibri", bold=True, size=12, color=CLR["header_bg"])
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

    headers = ["Carrier", "Total Shipments", "Total Defects", "Defect Rate",
               "Late Delivery", "Failed Pickup", "Status"]
    for i, h in enumerate(headers, 1):
        _hdr(ws, 2, i, h)

    for _, r in anomalies["carriers"].iterrows():
        row = _ + 3
        fill = _status_fill(r["status"])
        _cell(ws, row, 1, r["carrier"],         bold=True, align="left")
        _cell(ws, row, 2, r["total_shipments"], fmt=INT_FMT)
        _cell(ws, row, 3, r["total_defects"],   fmt=INT_FMT)
        _cell(ws, row, 4, r["defect_rate"],     fmt=PCT_FMT, fill=fill)
        _cell(ws, row, 5, r.get("late_delivery", 0), fmt=INT_FMT)
        _cell(ws, row, 6, r.get("failed_pickup", 0), fmt=INT_FMT)
        _cell(ws, row, 7, r["status"], fill=fill)

    _auto_width(ws)


def _sheet_drilldown(ws: Worksheet, df: pd.DataFrame) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"
    ws.merge_cells("A1:L1")
    ws["A1"].value = "Full Drill Down — Daily Data (auto-filtered)"
    ws["A1"].font = Font(name="Calibri", bold=True, size=12, color=CLR["header_bg"])
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

    cols = ["date", "node", "carrier", "category", "weekday",
            "total_shipments", "total_defects", "defect_rate",
            "late_delivery", "missing_package", "damaged_goods", "failed_pickup"]
    labels = ["Date", "Node", "Carrier", "Category", "Weekday",
              "Shipments", "Defects", "Defect Rate",
              "Late", "Missing", "Damaged", "Failed Pickup"]

    for i, h in enumerate(labels, 1):
        _hdr(ws, 2, i, h)

    sample = df.sort_values("defect_rate", ascending=False).head(500)
    for ri, (_, r) in enumerate(sample.iterrows(), 3):
        fmts = [None, None, None, None, None, INT_FMT, INT_FMT, PCT_FMT,
                INT_FMT, INT_FMT, INT_FMT, INT_FMT]
        for ci, (col, fmt) in enumerate(zip(cols, fmts), 1):
            val = str(r[col]) if col == "date" else r[col]
            fill = (RED_FILL if col == "defect_rate" and r[col] >= 0.05 else
                    YEL_FILL if col == "defect_rate" and r[col] >= 0.03 else None)
            _cell(ws, ri, ci, val, fmt=fmt, fill=fill,
                  align="left" if ci <= 5 else "center")

    ws.auto_filter.ref = f"A2:{get_column_letter(len(cols))}{ 2 + len(sample)}"
    _auto_width(ws, min_w=8, max_w=30)


def _sheet_memo(ws: Worksheet, memo_text: str, wow: dict) -> None:
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:C1")
    ws["A1"].value = "Escalation Memo — AB Fulfillment Operations"
    ws["A1"].font = Font(name="Calibri", bold=True, size=13, color=CLR["header_bg"])
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    ws["A2"].value = f"Week ending: {wow.get('week_range','')}"
    ws["A2"].font = Font(name="Calibri", size=9, color=CLR["text_muted"])

    ws.merge_cells("A3:C3")
    ws.merge_cells("A4:C60")
    ws["A3"].value = "MEMO TEXT (copy and paste to email or Chime):"
    ws["A3"].font = Font(name="Calibri", bold=True, size=10)

    ws["A4"].value = memo_text or "Run Claude-augmented pipeline to generate memo."
    ws["A4"].font  = Font(name="Calibri", size=10)
    ws["A4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[4].height = 400
    ws.column_dimensions["A"].width = 120


# ── Public builder ─────────────────────────────────────────────────────────

def build_workbook(df: pd.DataFrame, anomalies: dict,
                   root: dict, memo_text: str = "",
                   output_path: str | Path | None = None,
                   queue: pd.DataFrame | None = None,
                   supply: dict | None = None,
                   simulated: bool = True) -> Path:
    """
    Build the full Excel workbook and save to output_path.

    queue   escalation queue DataFrame (modules.escalation.build_queue)
    supply  {"policy", "accuracy", "forecast", "daily_demand", "supplier_scorecard"}
    """
    # lazy imports: these modules import helpers from this one
    from modules import excel_formulas as xf
    from modules import excel_supply as xs

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    wk = xf.weekly_data(df)
    report_date = str(df["date"].max())

    sheets = [("Weekly Summary", lambda ws: _sheet_summary(ws, anomalies, root, simulated))]
    if queue is not None:
        sheets.append((xs.SHEET_QUEUE, lambda ws: xs.build_queue_sheet(ws, queue, report_date)))
    sheets += [
        ("Node Analysis", lambda ws: _sheet_node(ws, anomalies)),
        ("Root Cause",    lambda ws: _sheet_root_cause(ws, root)),
        ("Carrier Report", lambda ws: _sheet_carrier(ws, anomalies)),
    ]
    if supply is not None:
        sheets += [
            (xs.SHEET_INVENTORY, lambda ws: xs.build_inventory_sheet(ws, supply["policy"])),
            (xs.SHEET_FORECAST,  lambda ws: xs.build_forecast_sheet(
                ws, supply["daily_demand"], supply["forecast"], supply["accuracy"])),
            (xs.SHEET_SUPPLIER,  lambda ws: xs.build_supplier_sheet(ws, supply["supplier_scorecard"])),
        ]
    data_ws_holder: dict = {}   # pivot formulas need the data sheet's last row

    def _pivot(ws):
        xf.build_pivot_sheet(ws, wk, data_ws_holder["last"], int(df["total_defects"].sum()))

    sheets += [
        (xf.SHEET_PIVOT,  _pivot),
        ("Drill Down",    lambda ws: _sheet_drilldown(ws, df)),
        ("Escalation Memo", lambda ws: _sheet_memo(ws, memo_text, anomalies["wow"])),
        (xf.SHEET_ASSUMP, lambda ws: xf.build_assumptions_sheet(
            ws, simulated,
            ["Pivot tables: openpyxl cannot author native PivotTables; the Formula Pivot sheet reproduces "
             "pivot behaviour with SUMIFS + dropdowns, which also recalculates without refresh.",
             "VBA: this .xlsx contains no macros. Import vba/DefectReportMacros.bas (or run "
             "vba/install_macros.ps1) to get the .xlsm with refresh/format/export macros."])),
    ]

    # data sheet must be populated before the pivot builder runs
    ws_data = wb.create_sheet(xf.SHEET_DATA)
    data_ws_holder["last"] = xf.build_data_sheet(ws_data, wk)

    for name, builder in sheets:
        ws = wb.create_sheet(name)
        builder(ws)

    # order: put Data_Weekly right after the Formula Pivot
    order = [ws.title for ws in wb.worksheets if ws.title != xf.SHEET_DATA]
    order.insert(order.index(xf.SHEET_PIVOT) + 1, xf.SHEET_DATA)
    wb._sheets = [wb[n] for n in order]

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"output/AB_Defect_Report_{ts}.xlsx")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
