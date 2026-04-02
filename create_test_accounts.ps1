###############################################################################
# WattWise — Create 15 Test Accounts (PowerShell)
# Usage: .\create_test_accounts.ps1 [-Remote]
#   Default : hits localhost:8000 (fast — Docker running locally)
#   -Remote : hits https://www.talk2futurebuildings.systems (slow — Cloudflare)
###############################################################################
param([switch]$Remote)

$BASE = if ($Remote) { "https://www.talk2futurebuildings.systems" } else { "http://localhost:8000" }

# ── Device catalogue (entity_id maps to InfluxDB measurement names) ──────────
$DEVICE_CATALOGUE = @{
    airfryer       = @{ name = "Air Fryer";      appliance_key = "airfryer";       entity_id = "airfryer_current_consumption";       rated_wattage = 1500 }
    dishwasher     = @{ name = "Dishwasher";     appliance_key = "dishwasher";     entity_id = "dishwasher_current_consumption";     rated_wattage = 1800 }
    kettle         = @{ name = "Kettle";         appliance_key = "kettle";         entity_id = "kettle_current_consumption";         rated_wattage = 2200 }
    microwave      = @{ name = "Microwave";      appliance_key = "microwave";      entity_id = "microwave_current_consumption";      rated_wattage = 900 }
    toaster        = @{ name = "Toaster";        appliance_key = "toaster";        entity_id = "toaster_current_consumption";        rated_wattage = 800 }
    washing_machine= @{ name = "Washing Machine";appliance_key = "washing_machine";entity_id = "washing_machine_current_consumption";rated_wattage = 2000 }
}

# ── Account definitions ───────────────────────────────────────────────────────
$ACCOUNTS = @(
    @{
        name     = "Asma Irfan"
        email    = "IrfanA1@cardiff.ac.uk"
        password = "WattWise2024!"
        home     = @{ home_name = "Asma Irfan Home"; address = "14 Roath Park Road, Cardiff CF24 3AA"; location_desc = "Roath, Cardiff"; num_occupants = 4; home_type = "terraced" }
        devices  = @("airfryer","dishwasher","kettle","microwave","toaster","washing_machine")
    },
    @{
        name     = "Liam Jenkins"
        email    = "liam.jenkins@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Jenkins Household"; address = "5 Cathedral Road, Pontcanna, Cardiff CF11 9LJ"; location_desc = "Pontcanna, Cardiff"; num_occupants = 2; home_type = "terraced" }
        devices  = @("kettle","microwave","washing_machine")
    },
    @{
        name     = "Priya Sharma"
        email    = "priya.sharma@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Sharma Household"; address = "22 Albany Road, Roath, Cardiff CF24 3RD"; location_desc = "Roath, Cardiff"; num_occupants = 3; home_type = "semi-detached" }
        devices  = @("airfryer","kettle","dishwasher")
    },
    @{
        name     = "Owen Davies"
        email    = "owen.davies@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Davies Household"; address = "8 Whitchurch Road, Gabalfa, Cardiff CF14 3JP"; location_desc = "Gabalfa, Cardiff"; num_occupants = 4; home_type = "detached" }
        devices  = @("microwave","toaster","kettle","washing_machine")
    },
    @{
        name     = "Sophie Williams"
        email    = "sophie.williams@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Williams Household"; address = "31 City Road, Roath, Cardiff CF24 3BP"; location_desc = "Roath, Cardiff"; num_occupants = 2; home_type = "flat" }
        devices  = @("airfryer","dishwasher","microwave")
    },
    @{
        name     = "Mohammed Hassan"
        email    = "m.hassan@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Hassan Household"; address = "12 Newport Road, Roath, Cardiff CF24 1DJ"; location_desc = "Roath, Cardiff"; num_occupants = 5; home_type = "terraced" }
        devices  = @("kettle","toaster","washing_machine","microwave")
    },
    @{
        name     = "Emma Thomas"
        email    = "emma.thomas@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Thomas Household"; address = "7 Pontcanna Street, Pontcanna, Cardiff CF11 9HS"; location_desc = "Pontcanna, Cardiff"; num_occupants = 3; home_type = "terraced" }
        devices  = @("dishwasher","kettle","washing_machine")
    },
    @{
        name     = "Cian Murphy"
        email    = "c.murphy@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Murphy Household"; address = "44 Crwys Road, Cathays, Cardiff CF24 4NN"; location_desc = "Cathays, Cardiff"; num_occupants = 2; home_type = "flat" }
        devices  = @("airfryer","microwave","toaster")
    },
    @{
        name     = "Aisha Patel"
        email    = "aisha.patel@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Patel Household"; address = "3 North Road, Cardiff CF10 3DY"; location_desc = "Cathays, Cardiff"; num_occupants = 4; home_type = "terraced" }
        devices  = @("dishwasher","kettle","microwave","washing_machine")
    },
    @{
        name     = "Jack Roberts"
        email    = "j.roberts@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Roberts Household"; address = "19 Wellfield Road, Roath, Cardiff CF24 3PA"; location_desc = "Roath, Cardiff"; num_occupants = 3; home_type = "semi-detached" }
        devices  = @("airfryer","toaster","kettle")
    },
    @{
        name     = "Fatima Al-Rashid"
        email    = "f.alrashid@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Al-Rashid Household"; address = "6 Llanishen Street, Cardiff CF14 5EZ"; location_desc = "Llanishen, Cardiff"; num_occupants = 5; home_type = "detached" }
        devices  = @("microwave","washing_machine","dishwasher")
    },
    @{
        name     = "Rhys Evans"
        email    = "r.evans@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Evans Household"; address = "28 Mackintosh Place, Roath, Cardiff CF24 4RQ"; location_desc = "Roath, Cardiff"; num_occupants = 2; home_type = "flat" }
        devices  = @("kettle","airfryer","dishwasher","toaster")
    },
    @{
        name     = "Nadia Kowalski"
        email    = "n.kowalski@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Kowalski Household"; address = "15 De Burgh Street, Pontcanna, Cardiff CF11 9NG"; location_desc = "Pontcanna, Cardiff"; num_occupants = 3; home_type = "terraced" }
        devices  = @("microwave","toaster","kettle")
    },
    @{
        name     = "Tom Hughes"
        email    = "t.hughes@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Hughes Household"; address = "9 Romilly Road, Canton, Cardiff CF5 1FN"; location_desc = "Canton, Cardiff"; num_occupants = 4; home_type = "semi-detached" }
        devices  = @("washing_machine","dishwasher","airfryer")
    },
    @{
        name     = "Mei Lin"
        email    = "m.lin@wattwise-test.co.uk"
        password = "WattTest2024!"
        home     = @{ home_name = "Lin Household"; address = "37 Heathwood Road, Whitchurch, Cardiff CF14 4JL"; location_desc = "Whitchurch, Cardiff"; num_occupants = 3; home_type = "semi-detached" }
        devices  = @("kettle","toaster","microwave","washing_machine")
    }
)

# ── Results table ─────────────────────────────────────────────────────────────
$results = @()

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  WattWise — Provisioning 15 Test Accounts" -ForegroundColor Cyan
Write-Host "  Server: $BASE" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$i = 0
foreach ($account in $ACCOUNTS) {
    $i++
    Write-Host "[$i/15] Creating account: $($account.name) ($($account.email))" -ForegroundColor Yellow

    # ── Step 1: Signup, or login if email already exists ─────────────────────
    $TOKEN   = $null
    $USER_ID = $null

    try {
        $signupBody = @{
            name     = $account.name
            email    = $account.email
            password = $account.password
        } | ConvertTo-Json -Compress

        $signupResp = Invoke-RestMethod `
            -Uri "$BASE/api/auth/signup" `
            -Method Post `
            -ContentType "application/json" `
            -Body $signupBody `
            -ErrorAction Stop

        $TOKEN   = $signupResp.access_token
        $USER_ID = $signupResp.user_id
        Write-Host "  ✅ New account created — user_id=$USER_ID" -ForegroundColor Green
    }
    catch {
        # 409 = email already registered — login instead and add home+devices on top
        Write-Host "  ℹ️  Email exists, logging in to add home & devices..." -ForegroundColor Cyan
        try {
            $loginBody = @{
                email    = $account.email
                password = $account.password
            } | ConvertTo-Json -Compress

            $loginResp = Invoke-RestMethod `
                -Uri "$BASE/api/auth/login" `
                -Method Post `
                -ContentType "application/json" `
                -Body $loginBody `
                -ErrorAction Stop

            $TOKEN   = $loginResp.access_token
            $USER_ID = $loginResp.user_id
            Write-Host "  ✅ Logged in — user_id=$USER_ID (existing account)" -ForegroundColor Green
        }
        catch {
            Write-Host "  ❌ Login failed (wrong password?): $_" -ForegroundColor Red
            $results += [PSCustomObject]@{ "#" = $i; Name = $account.name; Email = $account.email; Password = $account.password; HomeID = "FAILED"; Devices = 0; Status = "AUTH_FAILED" }
            continue
        }
    }

    $authHeaders = @{ Authorization = "Bearer $TOKEN" }

    # ── Step 2: Create home ──────────────────────────────────────
    try {
        $homeBody = $account.home | ConvertTo-Json -Compress

        $homeResp = Invoke-RestMethod `
            -Uri "$BASE/api/homes" `
            -Method Post `
            -ContentType "application/json" `
            -Headers $authHeaders `
            -Body $homeBody `
            -ErrorAction Stop

        $HOME_ID = $homeResp.id
        Write-Host "  ✅ Home created — home_id=$HOME_ID ($($account.home.home_name))" -ForegroundColor Green
    }
    catch {
        Write-Host "  ❌ Home creation failed: $_" -ForegroundColor Red
        $results += [PSCustomObject]@{ "#" = $i; Name = $account.name; Email = $account.email; Password = $account.password; HomeID = "FAILED"; Devices = 0; Status = "HOME_FAILED" }
        continue
    }

    # ── Step 3: Add devices ──────────────────────────────────────
    $deviceCount = 0
    foreach ($deviceKey in $account.devices) {
        $dev = $DEVICE_CATALOGUE[$deviceKey]
        try {
            $deviceBody = @{
                name           = $dev.name
                appliance_key  = $dev.appliance_key
                entity_id      = $dev.entity_id
                device_type    = "appliance"
                rated_wattage  = $dev.rated_wattage
                location       = "Kitchen"
            } | ConvertTo-Json -Compress

            Invoke-RestMethod `
                -Uri "$BASE/api/homes/$HOME_ID/devices" `
                -Method Post `
                -ContentType "application/json" `
                -Headers $authHeaders `
                -Body $deviceBody `
                -ErrorAction Stop | Out-Null

            $deviceCount++
            Write-Host "  ✅   Device: $($dev.name) (entity: $($dev.entity_id))" -ForegroundColor DarkGreen
        }
        catch {
            Write-Host "  ⚠️   Device $($dev.name) failed: $_" -ForegroundColor DarkYellow
        }
    }

    $results += [PSCustomObject]@{
        "#"      = $i
        Name     = $account.name
        Email    = $account.email
        Password = $account.password
        HomeID   = $HOME_ID
        Devices  = $deviceCount
        Status   = "OK"
    }

    Write-Host ""
}

# ── Final credentials table ───────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  CREDENTIALS TABLE — 15 WattWise Test Accounts" -ForegroundColor Cyan
Write-Host "  Server: $BASE  |  Port: 443 (HTTPS)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host ("{0,-3}  {1,-18}  {2,-42}  {3,-16}  {4,-8}  {5,-8}  {6}" -f "#", "Name", "Email", "Password", "HomeID", "Devices", "Status")
Write-Host ("-" * 110)
foreach ($r in $results) {
    $color = if ($r.Status -eq "OK") { "White" } else { "Red" }
    Write-Host ("{0,-3}  {1,-18}  {2,-42}  {3,-16}  {4,-8}  {5,-8}  {6}" -f $r."#", $r.Name, $r.Email, $r.Password, $r.HomeID, $r.Devices, $r.Status) -ForegroundColor $color
}
Write-Host ""
Write-Host "NOTE: User 1 (Asma Irfan) is the REAL account — RPi sends data to this home." -ForegroundColor Yellow
Write-Host "NOTE: Users 2-15 are dummy accounts for testing only." -ForegroundColor DarkYellow
Write-Host ""

# ── Save results to CSV ───────────────────────────────────────────────────────
$csvPath = "$PSScriptRoot\wattwise_credentials.csv"
$results | Export-Csv -Path $csvPath -NoTypeInformation
Write-Host "Credentials saved to: $csvPath" -ForegroundColor Green
