# VBA macros

`DefectReportMacros.bas` is a standard VBA module. Python builds the workbook; these macros are
what an analyst runs inside Excel afterwards.

| Macro | What it does |
|---|---|
| `RunAll` | FormatReport -> HighlightOverdueItems -> RefreshAndRecalculate -> ExportWeeklyPDF |
| `FormatReport` | Header style, status colours (ESCALATE/P1/STOCKED OUT red, WATCH/P2/REORDER amber, OK/P3/DONE green), width cap, freeze panes on the queue |
| `HighlightOverdueItems` | Open queue items whose Due Date is before today get a red cell; reports the count and how many are P1 |
| `RefreshAndRecalculate` | `CalculateFull`, then reads the reconciliation cell on *Formula Pivot* and warns if it is not `MATCH` |
| `ExportWeeklyPDF` | *Weekly Summary* + *Escalation Queue* to one landscape PDF next to the workbook |
| `DraftEscalationEmail` | Opens an Outlook draft listing open P1 items (late-bound, so no Outlook reference needed) |

## Install

```powershell
powershell -File vba\install_macros.ps1 -Workbook output\AB_Defect_Report.xlsx
```
Creates `output\AB_Defect_Report.xlsm` with the module imported and a **Run Report Macros** button on
*Weekly Summary*. One-time Excel setting needed for the import step only:
File > Options > Trust Center > Trust Center Settings > Macro Settings > **Trust access to the
VBA project object model**. Manual alternative: Alt+F11 > File > Import File > `DefectReportMacros.bas`,
then save as `.xlsm`.

## What was actually tested

Imported into the generated workbook and run in Microsoft Excel (Windows) through automation:
`FormatReport`, `HighlightOverdueItems` (flagged 7 overdue P1 items), `RefreshAndRecalculate`,
`ExportWeeklyPDF` (PDF written), button created. **Not run:** `DraftEscalationEmail` (needs Outlook).
`tests/test_supply_sql_excel.py::TestVBA` checks that every sheet name and column header the
macros look up exists in the generated workbook, so a Python rename cannot silently break a macro.

## Explaining it

Why both? Python makes the report reproducible and schedulable; the macros are the last mile an
analyst can open, tweak and run without Python. If asked to read the code: `FindHeaderCol` locates a
column by its header text (so reordering columns does not break the macros), and the colouring
loops over the used range once per sheet.
