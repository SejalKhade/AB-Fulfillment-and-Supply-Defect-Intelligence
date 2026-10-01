# AB Fulfillment & Supply Defect Intelligence

An analyst toolkit for a supply chain team: it finds where fulfillment, inventory and
suppliers are going wrong, ranks the causes, and turns them into an owned, dated
escalation list plus an Excel report that keeps working inside Excel.

> **All data is simulated.** The generator seeds known problems (a carrier issue at one FC,
> an inventory-accuracy problem, three weather events, three unreliable suppliers) so the
> tests can prove the detection finds them. Nothing here is real Amazon data or a real finding.
> You can run it on your own CSVs instead (see *Bring your own data*).

## What it does

| Area | Method | Where |
|---|---|---|
| Defect rate by FC / carrier / category | SQL aggregation, cross-node z-score, thresholds | `sql/01`, `modules/anomaly_detector.py` |
| Anomalies | Same-weekday rolling baseline (window functions) | `sql/02` |
| Week-over-week | Conditional aggregation; `LAG()` weekly trend | `sql/03`, `sql/04` |
| Root cause | Pareto, weighted impact + USD cost, **contribution analysis** (excess defects vs network rate) | `sql/05`, `sql/06`, `modules/root_cause.py` |
| Supplier performance | OTIF (on-time **and** in-full per PO), lead-time mean/SD | `sql/07`, `modules/supplier.py` |
| Inventory | Days of supply, fill rate, **safety stock & reorder point**, stockout cost | `sql/08`, `modules/inventory.py` |
| Demand forecast | Moving avg / exp. smoothing / weekday-index, chosen by backtest (WAPE) | `modules/inventory.py` |
| Escalation | One scored queue: owner, SLA due date, action, $ impact | `modules/escalation.py` |
| Data quality | pandas vs SQL reconciliation, run on every pipeline run | `modules/reconcile.py` |
| Excel | 13 sheets, live `SUMIFS` pivot with dropdowns, conditional formatting, native charts | `modules/excel_*.py` |
| VBA | Real macros: format, flag overdue, recalc + reconcile, PDF export, Outlook draft | `vba/` |
| AI memo (optional) | Claude writes the memo from computed JSON; every number is checked | `pipeline_claude.py`, `modules/hallucination_guard.py` |

## Run it

```bash
pip install -r requirements.txt
python pipeline_direct.py --out output/AB_Defect_Report.xlsx   # ~10 s, no API key
streamlit run dashboard/app.py                                  # 5-tab dashboard
pytest                                                          # 69 tests
set ANTHROPIC_API_KEY=...  &  python pipeline_claude.py         # optional memo
```

Add the real macros (Windows + Excel): `powershell -File vba\install_macros.ps1 -Workbook output\AB_Defect_Report.xlsx`
(details and the one Excel setting it needs are in [vba/README.md](vba/README.md)).

## What a run produces (seed 42, 90 days, simulated)

- 51,840 daily rows, 5.54M shipments, 183k defects, **3.31%** overall rate
- Cross-node view: 4 FCs on WATCH, none at the 5% ESCALATE line, because the seeded problems
  live in *segments*, not whole FCs. That is why contribution analysis exists: it ranks
  **PHX-7 / AMZL** and **SEA-2 / Electronics** first.
- Rolling baseline flags **15 node-days: exactly the 3 seeded weather events, no false positives**
- Late Delivery is the top weighted-impact cause; Inventory Discrepancy is #2 by *volume* but
  low by *impact* (weight 0.03), the volume-vs-impact distinction Pareto alone hides
- Supplier OTIF: Electronics supplier 1%, IT Hardware 37%, Furniture 62%; network 72.9%
- Forecast median WAPE 3.3% vs ~9-10% for a flat naive forecast. The weekday-index method wins
  every series *because the simulated volume has a weekly cycle*; real data may not behave this way
- Safety-stock result worth noting: the old "1.15 x lead-time demand" rule is too *low* for the
  unreliable suppliers and too *high* for reliable ones. The recommendation moves both ways.
- 18 escalation items (7 P1), each with owner, due date and dollar impact

## How the escalation score works

`score = 100 x (0.5 x impact + 0.5 x deviation)`; impact is dollars vs a per-domain materiality cap,
deviation is distance from benchmark (rate ratio, OTIF gap, fill-rate gap, excess over baseline).
P1 >= 70, P2 >= 40. Owners and SLA days are in [config.py](config.py). The weights, costs and caps
are **assumptions** you would set with finance/ops; they are labelled as such in the workbook's
`Assumptions` sheet.

## Honest limitations

- Simulated data; seeded problems make the detection look better than it would on messy real data.
- Customer-impact weights and per-defect costs are illustrative placeholders.
- `openpyxl` cannot create native PivotTables, so *Formula Pivot* reproduces pivot behaviour with
  `SUMIFS` + dropdowns (it recalculates without a refresh). The `.xlsx` itself contains no macros;
  the `.xlsm` comes from the install script.
- The VBA was run in real Excel (see `vba/README.md`), but the Outlook draft macro was not executed.
- The dashboard was smoke-tested headlessly (no exceptions); layout was not visually reviewed.
- Single-echelon inventory model; no capacity, transshipment, or demand-correlation effects.

## Bring your own data

```bash
python pipeline_direct.py --csv fulfillment.csv [--inventory-csv inv.csv --po-csv pos.csv]
```
Schemas are documented at the top of [modules/data_loader.py](modules/data_loader.py). Without
inventory/PO files, the supply sheets are skipped. Missing defect-type columns default to 0, so
root-cause output is only meaningful if you supply them.

## Layout

```
config.py                 every threshold / weight / cost / owner / SLA
sql/                      9 named queries (CTEs, windows, UNPIVOT, conditional aggregation)
modules/                  generators, warehouse, analytics, escalation, Excel writers, guard
vba/                      DefectReportMacros.bas, install_macros.ps1, README
pipeline_direct.py        deterministic pipeline (CLI)
pipeline_claude.py        adds the AI memo
dashboard/app.py          Streamlit
tests/                    69 tests (incl. a real-Excel recalculation check when Excel exists)
```
