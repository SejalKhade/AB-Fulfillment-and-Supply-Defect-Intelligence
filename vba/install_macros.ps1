<#
.SYNOPSIS
  Turns the generated .xlsx into a macro-enabled .xlsm by importing
  DefectReportMacros.bas and adding a "Run Report Macros" button.

.USAGE
  powershell -File vba\install_macros.ps1 -Workbook output\AB_Defect_Report.xlsx
  (writes output\AB_Defect_Report.xlsm next to it)

.REQUIRES
  Microsoft Excel on Windows, and in Excel:
  File > Options > Trust Center > Trust Center Settings > Macro Settings >
  tick "Trust access to the VBA project object model".
  (Only needed for THIS import step; running macros later does not need it.)
#>
param(
    [Parameter(Mandatory = $true)][string]$Workbook,
    [string]$Out
)

$ErrorActionPreference = "Stop"
$bas = Join-Path $PSScriptRoot "DefectReportMacros.bas"
$src = (Resolve-Path $Workbook).Path
if (-not $Out) { $Out = [System.IO.Path]::ChangeExtension($src, ".xlsm") }

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
    $wb = $xl.Workbooks.Open($src)
    try {
        $null = $wb.VBProject.VBComponents.Import($bas)
    } catch {
        throw "Cannot import the macro module. Enable 'Trust access to the VBA project object model' in Excel's Trust Center and run again."
    }

    $ws = $wb.Worksheets.Item("Weekly Summary")
    $left = $ws.Cells.Item(1, 10).Left
    $btn = $ws.Buttons().Add($left, 4, 150, 24)
    $btn.Caption = "Run Report Macros"
    $btn.OnAction = "RunAll"

    $wb.SaveAs($Out, 52)    # 52 = xlOpenXMLWorkbookMacroEnabled
    $wb.Close($false)
    Write-Output "Created $Out"
} finally {
    $xl.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
}
