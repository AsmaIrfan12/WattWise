###############################################################################
# WattWise — Export 15 Test Accounts to Excel
# Usage: .\export_accounts_excel.ps1
# Requires: ImportExcel module (auto-installed if missing)
###############################################################################

# ── Install ImportExcel if not present ───────────────────────────────────────
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
    Write-Host "Installing ImportExcel module (one-time)..." -ForegroundColor Yellow
    Install-Module -Name ImportExcel -Force -Scope CurrentUser -AllowClobber
}
Import-Module ImportExcel -ErrorAction Stop

# ── Account data ──────────────────────────────────────────────────────────────
$accounts = @(
    [PSCustomObject]@{
        No            = 1
        Type          = "REAL (RPi Live Data)"
        Name          = "Asma Irfan"
        Email         = "IrfanA1@cardiff.ac.uk"
        Password      = "WattWise2024!"
        Address       = "14 Roath Park Road, Cardiff CF24 3AA"
        Location      = "Roath, Cardiff"
        Occupants     = 4
        HomeType      = "Terraced"
        Devices       = "Air Fryer, Dishwasher, Kettle, Microwave, Toaster, Washing Machine"
        DeviceCount   = 6
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = "Real account — RPi sends live data to this home"
    },
    [PSCustomObject]@{
        No            = 2
        Type          = "Dummy"
        Name          = "Liam Jenkins"
        Email         = "liam.jenkins@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "5 Cathedral Road, Pontcanna, Cardiff CF11 9LJ"
        Location      = "Pontcanna, Cardiff"
        Occupants     = 2
        HomeType      = "Terraced"
        Devices       = "Kettle, Microwave, Washing Machine"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 3
        Type          = "Dummy"
        Name          = "Priya Sharma"
        Email         = "priya.sharma@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "22 Albany Road, Roath, Cardiff CF24 3RD"
        Location      = "Roath, Cardiff"
        Occupants     = 3
        HomeType      = "Semi-Detached"
        Devices       = "Air Fryer, Kettle, Dishwasher"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 4
        Type          = "Dummy"
        Name          = "Owen Davies"
        Email         = "owen.davies@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "8 Whitchurch Road, Gabalfa, Cardiff CF14 3JP"
        Location      = "Gabalfa, Cardiff"
        Occupants     = 4
        HomeType      = "Detached"
        Devices       = "Microwave, Toaster, Kettle, Washing Machine"
        DeviceCount   = 4
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 5
        Type          = "Dummy"
        Name          = "Sophie Williams"
        Email         = "sophie.williams@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "31 City Road, Roath, Cardiff CF24 3BP"
        Location      = "Roath, Cardiff"
        Occupants     = 2
        HomeType      = "Flat"
        Devices       = "Air Fryer, Dishwasher, Microwave"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 6
        Type          = "Dummy"
        Name          = "Mohammed Hassan"
        Email         = "m.hassan@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "12 Newport Road, Roath, Cardiff CF24 1DJ"
        Location      = "Roath, Cardiff"
        Occupants     = 5
        HomeType      = "Terraced"
        Devices       = "Kettle, Toaster, Washing Machine, Microwave"
        DeviceCount   = 4
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 7
        Type          = "Dummy"
        Name          = "Emma Thomas"
        Email         = "emma.thomas@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "7 Pontcanna Street, Pontcanna, Cardiff CF11 9HS"
        Location      = "Pontcanna, Cardiff"
        Occupants     = 3
        HomeType      = "Terraced"
        Devices       = "Dishwasher, Kettle, Washing Machine"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 8
        Type          = "Dummy"
        Name          = "Cian Murphy"
        Email         = "c.murphy@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "44 Crwys Road, Cathays, Cardiff CF24 4NN"
        Location      = "Cathays, Cardiff"
        Occupants     = 2
        HomeType      = "Flat"
        Devices       = "Air Fryer, Microwave, Toaster"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 9
        Type          = "Dummy"
        Name          = "Aisha Patel"
        Email         = "aisha.patel@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "3 North Road, Cardiff CF10 3DY"
        Location      = "Cathays, Cardiff"
        Occupants     = 4
        HomeType      = "Terraced"
        Devices       = "Dishwasher, Kettle, Microwave, Washing Machine"
        DeviceCount   = 4
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 10
        Type          = "Dummy"
        Name          = "Jack Roberts"
        Email         = "j.roberts@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "19 Wellfield Road, Roath, Cardiff CF24 3PA"
        Location      = "Roath, Cardiff"
        Occupants     = 3
        HomeType      = "Semi-Detached"
        Devices       = "Air Fryer, Toaster, Kettle"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 11
        Type          = "Dummy"
        Name          = "Fatima Al-Rashid"
        Email         = "f.alrashid@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "6 Llanishen Street, Cardiff CF14 5EZ"
        Location      = "Llanishen, Cardiff"
        Occupants     = 5
        HomeType      = "Detached"
        Devices       = "Microwave, Washing Machine, Dishwasher"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 12
        Type          = "Dummy"
        Name          = "Rhys Evans"
        Email         = "r.evans@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "28 Mackintosh Place, Roath, Cardiff CF24 4RQ"
        Location      = "Roath, Cardiff"
        Occupants     = 2
        HomeType      = "Flat"
        Devices       = "Kettle, Air Fryer, Dishwasher, Toaster"
        DeviceCount   = 4
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 13
        Type          = "Dummy"
        Name          = "Nadia Kowalski"
        Email         = "n.kowalski@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "15 De Burgh Street, Pontcanna, Cardiff CF11 9NG"
        Location      = "Pontcanna, Cardiff"
        Occupants     = 3
        HomeType      = "Terraced"
        Devices       = "Microwave, Toaster, Kettle"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 14
        Type          = "Dummy"
        Name          = "Tom Hughes"
        Email         = "t.hughes@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "9 Romilly Road, Canton, Cardiff CF5 1FN"
        Location      = "Canton, Cardiff"
        Occupants     = 4
        HomeType      = "Semi-Detached"
        Devices       = "Washing Machine, Dishwasher, Air Fryer"
        DeviceCount   = 3
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    },
    [PSCustomObject]@{
        No            = 15
        Type          = "Dummy"
        Name          = "Mei Lin"
        Email         = "m.lin@wattwise-test.co.uk"
        Password      = "WattTest2024!"
        Address       = "37 Heathwood Road, Whitchurch, Cardiff CF14 4JL"
        Location      = "Whitchurch, Cardiff"
        Occupants     = 3
        HomeType      = "Semi-Detached"
        Devices       = "Kettle, Toaster, Microwave, Washing Machine"
        DeviceCount   = 4
        ServerURL     = "https://www.talk2futurebuildings.systems"
        Port          = 443
        Notes         = ""
    }
)

# ── Output path ───────────────────────────────────────────────────────────────
$outPath = "$PSScriptRoot\WattWise_Test_Accounts.xlsx"

# ── Build Excel with formatting ───────────────────────────────────────────────
$excelParams = @{
    Path          = $outPath
    WorksheetName = "Test Accounts"
    AutoSize      = $true
    BoldTopRow    = $true
    FreezeTopRow  = $true
    TableName     = "WattWiseAccounts"
    TableStyle    = "Medium6"
    Title         = "WattWise Community Energy Platform — Test Accounts"
    TitleBold     = $true
    TitleSize     = 14
    ClearSheet    = $true
}

$excel = $accounts | Export-Excel @excelParams -PassThru

# ── Conditional formatting: highlight real account row ───────────────────────
$ws = $excel.Workbook.Worksheets["Test Accounts"]

# Real account row (row 3 = title row 1 + header row 2 + data row 1)
$realRow = 3
for ($col = 1; $col -le $ws.Dimension.Columns; $col++) {
    $ws.Cells[$realRow, $col].Style.Fill.PatternType = [OfficeOpenXml.Style.ExcelFillStyle]::Solid
    $ws.Cells[$realRow, $col].Style.Fill.BackgroundColor.SetColor([System.Drawing.Color]::FromArgb(198, 239, 206))  # light green
    $ws.Cells[$realRow, $col].Style.Font.Bold = $true
}

# Header row styling (row 2 because Title is row 1)
$headerRow = 2
for ($col = 1; $col -le $ws.Dimension.Columns; $col++) {
    $ws.Cells[$headerRow, $col].Style.Fill.PatternType = [OfficeOpenXml.Style.ExcelFillStyle]::Solid
    $ws.Cells[$headerRow, $col].Style.Fill.BackgroundColor.SetColor([System.Drawing.Color]::FromArgb(31, 78, 121))   # dark blue
    $ws.Cells[$headerRow, $col].Style.Font.Color.SetColor([System.Drawing.Color]::White)
    $ws.Cells[$headerRow, $col].Style.Font.Bold = $true
}

# ── Add a second sheet: Device Entity IDs reference ───────────────────────────
$wsDevices = $excel.Workbook.Worksheets.Add("Device Entity IDs")

$devHeaders = @("Appliance Key", "Display Name", "Entity ID (InfluxDB)", "Rated Wattage (W)", "Location")
for ($col = 1; $col -le $devHeaders.Count; $col++) {
    $wsDevices.Cells[1, $col].Value = $devHeaders[$col - 1]
    $wsDevices.Cells[1, $col].Style.Font.Bold = $true
    $wsDevices.Cells[1, $col].Style.Fill.PatternType = [OfficeOpenXml.Style.ExcelFillStyle]::Solid
    $wsDevices.Cells[1, $col].Style.Fill.BackgroundColor.SetColor([System.Drawing.Color]::FromArgb(31, 78, 121))
    $wsDevices.Cells[1, $col].Style.Font.Color.SetColor([System.Drawing.Color]::White)
}

$deviceData = @(
    @("airfryer",        "Air Fryer",       "airfryer_current_consumption",        1500, "Kitchen"),
    @("dishwasher",      "Dishwasher",      "dishwasher_current_consumption",      1800, "Kitchen"),
    @("kettle",          "Kettle",          "kettle_current_consumption",          2200, "Kitchen"),
    @("microwave",       "Microwave",       "microwave_current_consumption",        900, "Kitchen"),
    @("toaster",         "Toaster",         "toaster_current_consumption",          800, "Kitchen"),
    @("washing_machine", "Washing Machine", "washing_machine_current_consumption", 2000, "Utility Room")
)

for ($row = 0; $row -lt $deviceData.Count; $row++) {
    for ($col = 0; $col -lt $deviceData[$row].Count; $col++) {
        $wsDevices.Cells[$row + 2, $col + 1].Value = $deviceData[$row][$col]
    }
}
$wsDevices.Cells[$wsDevices.Dimension.Address].AutoFitColumns()

# ── Add a third sheet: quick login reference ──────────────────────────────────
$wsLogin = $excel.Workbook.Worksheets.Add("Quick Login")

$loginHeaders = @("No", "Name", "Email", "Password", "App Server URL", "Port")
for ($col = 1; $col -le $loginHeaders.Count; $col++) {
    $wsLogin.Cells[1, $col].Value = $loginHeaders[$col - 1]
    $wsLogin.Cells[1, $col].Style.Font.Bold = $true
    $wsLogin.Cells[1, $col].Style.Fill.PatternType = [OfficeOpenXml.Style.ExcelFillStyle]::Solid
    $wsLogin.Cells[1, $col].Style.Fill.BackgroundColor.SetColor([System.Drawing.Color]::FromArgb(31, 78, 121))
    $wsLogin.Cells[1, $col].Style.Font.Color.SetColor([System.Drawing.Color]::White)
}

for ($i = 0; $i -lt $accounts.Count; $i++) {
    $acc = $accounts[$i]
    $wsLogin.Cells[$i + 2, 1].Value = $acc.No
    $wsLogin.Cells[$i + 2, 2].Value = $acc.Name
    $wsLogin.Cells[$i + 2, 3].Value = $acc.Email
    $wsLogin.Cells[$i + 2, 4].Value = $acc.Password
    $wsLogin.Cells[$i + 2, 5].Value = $acc.ServerURL
    $wsLogin.Cells[$i + 2, 6].Value = $acc.Port
    if ($acc.No -eq 1) {
        for ($col = 1; $col -le 6; $col++) {
            $wsLogin.Cells[$i + 2, $col].Style.Fill.PatternType = [OfficeOpenXml.Style.ExcelFillStyle]::Solid
            $wsLogin.Cells[$i + 2, $col].Style.Fill.BackgroundColor.SetColor([System.Drawing.Color]::FromArgb(198, 239, 206))
            $wsLogin.Cells[$i + 2, $col].Style.Font.Bold = $true
        }
    }
}
$wsLogin.Cells[$wsLogin.Dimension.Address].AutoFitColumns()

# ── Save ──────────────────────────────────────────────────────────────────────
Close-ExcelPackage $excel

Write-Host ""
Write-Host "✅  Excel file saved: $outPath" -ForegroundColor Green
Write-Host ""
Write-Host "Sheets:" -ForegroundColor Cyan
Write-Host "  1. Test Accounts     — all 15 accounts with full details" -ForegroundColor White
Write-Host "  2. Device Entity IDs — InfluxDB entity_id reference table" -ForegroundColor White
Write-Host "  3. Quick Login       — condensed login credentials for Android app" -ForegroundColor White
Write-Host ""
Write-Host "Real account (highlighted green): Asma Irfan — IrfanA1@cardiff.ac.uk" -ForegroundColor Yellow
