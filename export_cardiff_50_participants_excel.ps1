###############################################################################
# WattWise - Export Cardiff Participants CSV to Excel
#
# Usage:
#   .\export_cardiff_50_participants_excel.ps1
#   .\export_cardiff_50_participants_excel.ps1 -CsvPath .\wattwise_cardiff_participants_20260403-220000.csv
#   .\export_cardiff_50_participants_excel.ps1 -OutputPath .\WattWise_Cardiff_50.xlsx
#
# Behavior:
#   - If CsvPath is not supplied, picks latest wattwise_cardiff_participants_*.csv
#   - Creates formatted Excel workbook with summary sheet + participant data
###############################################################################

param(
    [string]$CsvPath,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

# Install ImportExcel if missing
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
    Write-Host "Installing ImportExcel module (one-time)..." -ForegroundColor Yellow
    Install-Module -Name ImportExcel -Force -Scope CurrentUser -AllowClobber
}
Import-Module ImportExcel -ErrorAction Stop

# Resolve CSV path
if ([string]::IsNullOrWhiteSpace($CsvPath)) {
    $latest = Get-ChildItem -Path $PSScriptRoot -Filter "wattwise_cardiff_participants_*.csv" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $latest) {
        throw "No CSV found. Run create_cardiff_50_participants.ps1 first or pass -CsvPath explicitly."
    }

    $CsvPath = $latest.FullName
}

if (-not (Test-Path $CsvPath)) {
    throw "CSV file not found: $CsvPath"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputPath = Join-Path $PSScriptRoot "WattWise_Cardiff_Participants_$stamp.xlsx"
}

# Load rows
$rows = Import-Csv -Path $CsvPath
if (-not $rows -or $rows.Count -eq 0) {
    throw "CSV has no rows: $CsvPath"
}

# Build summary
$total = $rows.Count
$ok = ($rows | Where-Object { $_.Status -eq "OK" }).Count
$failed = $total - $ok
$avgDevices = [Math]::Round((($rows | Measure-Object -Property Devices -Average).Average), 2)

$summary = @(
    [PSCustomObject]@{ Metric = "Total Participants"; Value = $total },
    [PSCustomObject]@{ Metric = "Successful"; Value = $ok },
    [PSCustomObject]@{ Metric = "Failed"; Value = $failed },
    [PSCustomObject]@{ Metric = "Average Devices Added"; Value = $avgDevices },
    [PSCustomObject]@{ Metric = "Source CSV"; Value = $CsvPath },
    [PSCustomObject]@{ Metric = "Generated At"; Value = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") }
)

# Export sheets
$rows |
    Export-Excel -Path $OutputPath -WorksheetName "Participants" -AutoSize -TableName "Participants" -FreezeTopRow -BoldTopRow

$summary |
    Export-Excel -Path $OutputPath -WorksheetName "Summary" -AutoSize -TableName "Summary" -BoldTopRow

# Add light conditional formatting on status column in Participants sheet
$excel = Open-ExcelPackage -Path $OutputPath
$ws = $excel.Workbook.Worksheets["Participants"]

# Find status column index dynamically
$headerMap = @{}
for ($c = 1; $c -le $ws.Dimension.End.Column; $c++) {
    $header = [string]$ws.Cells[1, $c].Value
    if (-not [string]::IsNullOrWhiteSpace($header)) { $headerMap[$header] = $c }
}

if ($headerMap.ContainsKey("Status")) {
    $statusCol = $headerMap["Status"]
    $range = "{0}2:{0}{1}" -f ([OfficeOpenXml.ExcelCellAddress]::GetColumnLetter($statusCol)), $ws.Dimension.End.Row

    Add-ConditionalFormatting -Worksheet $ws -Address $range -RuleType ContainsText -Text "OK" -BackgroundColor "#E6FFED" -ForegroundColor "#116329"
    Add-ConditionalFormatting -Worksheet $ws -Address $range -RuleType NotContainsText -Text "OK" -BackgroundColor "#FFECEC" -ForegroundColor "#8A1F11"
}

Close-ExcelPackage $excel

Write-Host "Excel exported: $OutputPath" -ForegroundColor Green
Write-Host "Summary -> Total: $total, Successful: $ok, Failed: $failed" -ForegroundColor Cyan
