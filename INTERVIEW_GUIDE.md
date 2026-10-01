# Interview guide - Supply Chain Analyst, Amazon Business Operations (Tempe, AZ)

Written for: you, preparing to present this project honestly to a hiring manager.

## 30-second pitch
"I built a toolkit that does what a supply chain analyst's week looks like: pull fulfillment,
inventory and supplier data with SQL, find anomalies and rank root causes, and turn them into a
prioritised list with owners and due dates, plus an Excel report with live formulas and VBA
macros for the last mile. The data is simulated with known seeded problems, so I could test
that the detection actually finds them."

## Map to the role

| What the role asks for | Where to point |
|---|---|
| SQL, data extraction & analysis | `sql/` - 9 queries: CTEs, window functions (`LAG`, rolling same-weekday baseline), `UNPIVOT`, conditional aggregation |
| Advanced Excel | *Formula Pivot*: `SUMIFS`, `AVERAGEIFS`, `RANK`, `INDEX/MATCH`, dropdowns, conditional formatting driven by input cells |
| VBA / macros | `vba/DefectReportMacros.bas` - run in real Excel; be ready to explain `FindHeaderCol` |
| Root cause analysis | Pareto, weighted impact, contribution analysis (excess defects vs network rate) |
| Automation / reduce manual work | Pipeline runs in ~10 s; reconciliation check on every run; macros publish the report |
| Weekly stakeholder reporting | Workbook + PDF export + escalation queue with owners/SLA |
| Inventory & supplier insight | Safety stock/ROP, days of supply, fill rate, forecast backtest, OTIF scorecard |

## Questions you should expect, and honest answers

- **"Is this real data?"** No, simulated. The generator seeds known problems; the tests assert the
  system finds them (exactly the 3 weather events, PHX-7/AMZL, SEA-2 Electronics). On real data I'd
  expect noisier results and I'd retune thresholds with the business.
- **"Why contribution analysis, not just defect rate?"** A small segment can have a high noisy rate.
  Ranking by *excess defects* (actual minus shipments x network rate) ranks by how much it hurts the
  network. At FC level nothing crossed 5%; the problems were visible only at segment level.
- **"How do you know the numbers are right?"** Every run computes key metrics twice, in pandas and
  in SQL, and compares them (9 checks). The workbook also reconciles its pivot to the pipeline total.
- **"Where did the weights and costs come from?"** Assumptions, labelled as such. In practice: customer
  contact and refund data for weights, finance for cost per defect. They live in `config.py`.
- **"Why OTIF this way?"** A PO counts only if it is on time *and* in full (>= 98% of ordered);
  averaging the two separately hides suppliers that fail one or the other.
- **"What does the safety-stock result say?"** The simple cover rule under-stocks unreliable suppliers
  and over-stocks reliable ones; the formula `z*sqrt(LT*sd_d^2 + d^2*sd_LT^2)` moves both ways.
- **"Why didn't you use a native PivotTable?"** The library I used cannot create them, so I built the
  same behaviour with `SUMIFS` + dropdowns. It recalculates without a refresh. Tradeoff: more formulas.
- **"What would you do next?"** Real data, capacity constraints, tie escalations to a ticket system,
  calibrate thresholds per node instead of one global number.
- **"Where does AI fit?"** Optional. Claude only writes the memo from pre-computed JSON; a guard checks
  every number against that JSON (rounding-aware). It does no calculation.

## Resume bullets (accurate - keep "simulated")
- Built a supply chain analytics toolkit (Python, DuckDB SQL, Excel, VBA) on a simulated 12-FC, 90-day
  network; SQL window-function baseline isolated all 3 seeded weather events with no false positives.
- Designed an escalation queue that scores issues by dollar impact and deviation, assigns an owner and
  SLA date, and ranked a seeded carrier and inventory problem first via contribution analysis.
- Implemented safety-stock/reorder-point and demand-forecast modules (backtest WAPE 3.3% vs ~9-10% naive)
  and a supplier OTIF scorecard; added a pandas-vs-SQL reconciliation control and 69 automated tests.
- Built an Excel report with a live SUMIFS pivot (dropdown-driven) and VBA macros for formatting,
  overdue flagging, recalculation checks and PDF export.

## Do not claim
- Real Amazon results or impact numbers.
- VBA "built into the .xlsx" - macros live in the `.xlsm` produced by the install script.
- That the weekday-forecast win generalises; it wins because the simulated data has a weekly cycle.
