Attribute VB_Name = "DefectReportMacros"
Option Explicit

'==========================================================================
' AB Fulfillment Defect Intelligence - report macros
'
' Python builds the workbook; these macros are what an analyst runs inside
' Excel to keep it tidy and to publish it:
'
'   RunAll                  FormatReport -> HighlightOverdueItems ->
'                           RefreshAndRecalculate -> ExportWeeklyPDF
'   FormatReport            consistent header style, status colours, widths,
'                           freeze panes on the escalation queue
'   HighlightOverdueItems   flags open items whose Due Date is before today
'   RefreshAndRecalculate   full recalculation + reconciliation check
'   ExportWeeklyPDF         Weekly Summary + Escalation Queue to one PDF
'   DraftEscalationEmail    opens an Outlook draft listing open P1 items
'
' Sheet names must match the workbook produced by the Python pipeline
' (a unit test checks this).
'==========================================================================

Private Const SHEET_SUMMARY As String = "Weekly Summary"
Private Const SHEET_QUEUE As String = "Escalation Queue"
Private Const SHEET_PIVOT As String = "Formula Pivot"
Private Const HEADER_ROW As Long = 2
Private Const MAX_COL_WIDTH As Double = 60

Private gSilent As Boolean

Public Sub SetSilent(ByVal value As Boolean)
    gSilent = value
End Sub

Private Sub Notify(ByVal msg As String)
    If gSilent Then
        Debug.Print msg
    Else
        MsgBox msg, vbInformation, "AB Defect Intelligence"
    End If
End Sub

Private Function SheetExists(ByVal sheetName As String) As Boolean
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(sheetName)
    On Error GoTo 0
    SheetExists = Not ws Is Nothing
End Function

Private Function FindHeaderCol(ByVal ws As Worksheet, ByVal hdrRow As Long, ByVal headerText As String) As Long
    Dim c As Long, lastCol As Long
    lastCol = ws.Cells(hdrRow, ws.Columns.Count).End(xlToLeft).Column
    For c = 1 To lastCol
        If StrComp(Trim$(CStr(ws.Cells(hdrRow, c).Value)), headerText, vbTextCompare) = 0 Then
            FindHeaderCol = c
            Exit Function
        End If
    Next c
    FindHeaderCol = 0
End Function

Private Function LastUsedRow(ByVal ws As Worksheet, ByVal col As Long) As Long
    LastUsedRow = ws.Cells(ws.Rows.Count, col).End(xlUp).Row
End Function

Private Sub ColorStatusColumn(ByVal ws As Worksheet, ByVal headerText As String)
    Dim col As Long, r As Long, lastRow As Long, v As String
    col = FindHeaderCol(ws, HEADER_ROW, headerText)
    If col = 0 Then Exit Sub
    lastRow = LastUsedRow(ws, col)
    For r = HEADER_ROW + 1 To lastRow
        v = UCase$(Trim$(CStr(ws.Cells(r, col).Value)))
        Select Case v
            Case "ESCALATE", "P1", "STOCKED OUT", "BLOCKED"
                ws.Cells(r, col).Interior.Color = RGB(254, 226, 226)
                ws.Cells(r, col).Font.Color = RGB(185, 28, 28)
            Case "WATCH", "P2", "REORDER", "EXCESS", "IN PROGRESS"
                ws.Cells(r, col).Interior.Color = RGB(254, 249, 195)
                ws.Cells(r, col).Font.Color = RGB(161, 98, 7)
            Case "OK", "P3", "DONE"
                ws.Cells(r, col).Interior.Color = RGB(220, 252, 231)
                ws.Cells(r, col).Font.Color = RGB(21, 128, 61)
        End Select
        ws.Cells(r, col).Font.Bold = True
    Next r
End Sub

Private Sub StyleHeaderRow(ByVal ws As Worksheet)
    Dim lastCol As Long
    lastCol = ws.Cells(HEADER_ROW, ws.Columns.Count).End(xlToLeft).Column
    If lastCol < 2 Then Exit Sub
    With ws.Range(ws.Cells(HEADER_ROW, 1), ws.Cells(HEADER_ROW, lastCol))
        .Interior.Color = RGB(26, 26, 46)
        .Font.Color = RGB(255, 255, 255)
        .Font.Bold = True
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .WrapText = True
    End With
End Sub

Private Sub CapColumnWidths(ByVal ws As Worksheet)
    Dim c As Long, lastCol As Long
    lastCol = ws.UsedRange.Columns.Count
    For c = 1 To lastCol
        If ws.Columns(c).ColumnWidth > MAX_COL_WIDTH Then ws.Columns(c).ColumnWidth = MAX_COL_WIDTH
    Next c
End Sub

'--------------------------------------------------------------------------
Public Sub FormatReport()
    Dim nm As Variant, ws As Worksheet
    Application.ScreenUpdating = False

    For Each nm In Array(SHEET_QUEUE, "Node Analysis", "Carrier Report", "Inventory", "Supplier Scorecard")
        If SheetExists(CStr(nm)) Then
            Set ws = ThisWorkbook.Worksheets(CStr(nm))
            StyleHeaderRow ws
            ColorStatusColumn ws, "Status"
            ColorStatusColumn ws, "Priority"
            ColorStatusColumn ws, "Workflow Status"
            CapColumnWidths ws
        End If
    Next nm

    If SheetExists(SHEET_QUEUE) Then
        Set ws = ThisWorkbook.Worksheets(SHEET_QUEUE)
        ws.Activate
        ActiveWindow.FreezePanes = False
        ws.Range("C3").Select
        ActiveWindow.FreezePanes = True
        ws.Range("A1").Select
    End If

    If SheetExists(SHEET_SUMMARY) Then ThisWorkbook.Worksheets(SHEET_SUMMARY).Activate
    Application.ScreenUpdating = True
    Notify "Report formatted."
End Sub

'--------------------------------------------------------------------------
Public Sub HighlightOverdueItems()
    Dim ws As Worksheet, dueCol As Long, stCol As Long, prCol As Long
    Dim r As Long, lastRow As Long, nOver As Long, nP1 As Long, dueVal As Variant

    If Not SheetExists(SHEET_QUEUE) Then Exit Sub
    Set ws = ThisWorkbook.Worksheets(SHEET_QUEUE)
    dueCol = FindHeaderCol(ws, HEADER_ROW, "Due Date")
    stCol = FindHeaderCol(ws, HEADER_ROW, "Workflow Status")
    prCol = FindHeaderCol(ws, HEADER_ROW, "Priority")
    If dueCol = 0 Or stCol = 0 Then
        Notify "Escalation Queue columns not found."
        Exit Sub
    End If

    lastRow = LastUsedRow(ws, dueCol)
    For r = HEADER_ROW + 1 To lastRow
        dueVal = ws.Cells(r, dueCol).Value
        If IsDate(dueVal) And UCase$(CStr(ws.Cells(r, stCol).Value)) <> "DONE" Then
            If CDate(dueVal) < Date Then
                ws.Cells(r, dueCol).Interior.Color = RGB(185, 28, 28)
                ws.Cells(r, dueCol).Font.Color = RGB(255, 255, 255)
                ws.Cells(r, dueCol).Font.Bold = True
                nOver = nOver + 1
                If prCol > 0 Then
                    If CStr(ws.Cells(r, prCol).Value) = "P1" Then nP1 = nP1 + 1
                End If
            End If
        End If
    Next r
    Notify nOver & " open item(s) are past their due date (" & nP1 & " are P1)."
End Sub

'--------------------------------------------------------------------------
Public Sub RefreshAndRecalculate()
    Dim ws As Worksheet, txt As String
    Application.CalculateFull
    If Not SheetExists(SHEET_PIVOT) Then Exit Sub
    Set ws = ThisWorkbook.Worksheets(SHEET_PIVOT)
    txt = CStr(ws.Range("F9").Value)
    If Left$(txt, 5) = "MATCH" Then
        Notify "Recalculated. Reconciliation: " & txt
    Else
        Notify "WARNING: pivot data does not reconcile with the pipeline total (" & txt & ")."
    End If
End Sub

'--------------------------------------------------------------------------
Public Function ExportWeeklyPDF() As String
    Dim path As String, nm As Variant, sel As Variant

    path = ThisWorkbook.Path
    If Len(path) = 0 Then path = CurDir$
    path = path & Application.PathSeparator & "AB_Weekly_Report_" & Format$(Date, "yyyymmdd") & ".pdf"

    If SheetExists(SHEET_QUEUE) Then
        sel = Array(SHEET_SUMMARY, SHEET_QUEUE)
    Else
        sel = Array(SHEET_SUMMARY)
    End If

    For Each nm In sel
        On Error Resume Next
        With ThisWorkbook.Worksheets(CStr(nm)).PageSetup
            .Orientation = xlLandscape
            .Zoom = False
            .FitToPagesWide = 1
            .FitToPagesTall = False
        End With
        On Error GoTo 0
    Next nm

    ThisWorkbook.Worksheets(sel).Select
    ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, Filename:=path, _
        Quality:=xlQualityStandard, IgnorePrintAreas:=False, OpenAfterPublish:=False
    ThisWorkbook.Worksheets(SHEET_SUMMARY).Select

    ExportWeeklyPDF = path
    Notify "Exported: " & path
End Function

'--------------------------------------------------------------------------
Public Sub DraftEscalationEmail()
    Dim ws As Worksheet, r As Long, lastRow As Long
    Dim idC As Long, prC As Long, enC As Long, isC As Long, owC As Long, duC As Long, stC As Long
    Dim body As String, n As Long
    Dim olApp As Object, olMail As Object

    If Not SheetExists(SHEET_QUEUE) Then Exit Sub
    Set ws = ThisWorkbook.Worksheets(SHEET_QUEUE)
    idC = FindHeaderCol(ws, HEADER_ROW, "ID")
    prC = FindHeaderCol(ws, HEADER_ROW, "Priority")
    enC = FindHeaderCol(ws, HEADER_ROW, "Entity")
    isC = FindHeaderCol(ws, HEADER_ROW, "Issue")
    owC = FindHeaderCol(ws, HEADER_ROW, "Owner")
    duC = FindHeaderCol(ws, HEADER_ROW, "Due Date")
    stC = FindHeaderCol(ws, HEADER_ROW, "Workflow Status")

    lastRow = LastUsedRow(ws, idC)
    body = "Team," & vbCrLf & vbCrLf & "Open P1 escalations from this week's defect report:" & vbCrLf & vbCrLf
    For r = HEADER_ROW + 1 To lastRow
        If CStr(ws.Cells(r, prC).Value) = "P1" And UCase$(CStr(ws.Cells(r, stC).Value)) <> "DONE" Then
            n = n + 1
            body = body & n & ". [" & ws.Cells(r, idC).Value & "] " & ws.Cells(r, enC).Value & vbCrLf & _
                   "   " & ws.Cells(r, isC).Value & vbCrLf & _
                   "   Owner: " & ws.Cells(r, owC).Value & "   Due: " & ws.Cells(r, duC).Value & vbCrLf & vbCrLf
        End If
    Next r
    body = body & "Full detail is in the attached workbook." & vbCrLf & vbCrLf & "Supply Chain Analytics"

    If n = 0 Then
        Notify "No open P1 items."
        Exit Sub
    End If

    On Error GoTo NoOutlook
    Set olApp = CreateObject("Outlook.Application")
    Set olMail = olApp.CreateItem(0)
    olMail.Subject = "Weekly defect report - " & n & " open P1 escalation(s)"
    olMail.Body = body
    olMail.Display
    Exit Sub

NoOutlook:
    Debug.Print body
    Notify "Outlook is not available. The email text was written to the Immediate window (Ctrl+G)."
End Sub

'--------------------------------------------------------------------------
Public Sub RunAll()
    FormatReport
    HighlightOverdueItems
    RefreshAndRecalculate
    ExportWeeklyPDF
End Sub
