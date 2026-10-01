# CLAUDE.md - AB Fulfillment & Supply Defect Intelligence

Analyst toolkit for a supply chain team (Amazon Business Operations style). All data is SIMULATED;
see README.md for what it does and its limitations. Keep that framing in any text you produce.

## Commands
- `python pipeline_direct.py --out output/AB_Defect_Report.xlsx` - full deterministic run (~10 s)
- `pytest` - 69 tests (includes a real-Excel recalculation test, auto-skipped without Excel)
- `streamlit run dashboard/app.py`
- `powershell -File vba\install_macros.ps1 -Workbook <xlsx>` - builds the .xlsm (needs Excel + VBOM trust)

## Architecture
- `config.py` is the only place for thresholds, defect weights, costs, owners, SLA days, model id.
- `modules/warehouse.py` loads DataFrames into in-memory DuckDB and runs `sql/NN_name.sql`.
  `$name` = bound parameter, `{name}` = integer templating (window frame sizes). Unused params ignored.
- Analytics: `anomaly_detector`, `root_cause` (pandas); `supplier`, `inventory`, `escalation` consume SQL output.
- `reconcile.py` compares the pandas and SQL engines every run - keep both in sync when editing metric logic.
- Excel: `excel_reporter.build_workbook` (+ `excel_formulas`, `excel_supply` imported lazily to avoid a cycle).
  Sheet names and queue headers are looked up by name in `vba/DefectReportMacros.bas`; TestVBA fails if they drift.
- `pipeline_direct.run()` returns serialisable results plus `_frames` (DataFrames) for the dashboard/tests.

## Rules
- Never present simulated numbers as real. Dollar costs and impact weights are assumptions.
- VBA file must stay ASCII with CRLF line endings.
- Charts: one axis, no dual-axis; fixed categorical order.
- Don't hand-write heredocs with quotes in Git Bash here; use file tools for multi-line files.
