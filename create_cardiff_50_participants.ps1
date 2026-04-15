###############################################################################
# WattWise - Create up to 50 Cardiff Participants (PowerShell)
#
# Usage examples:
#   .\create_cardiff_50_participants.ps1
#   .\create_cardiff_50_participants.ps1 -Count 50 -BaseUrl "http://129.212.138.248"
#   .\create_cardiff_50_participants.ps1 -Count 30 -BaseUrl "https://www.talk2futurebuildings.systems"
#
# What it does per participant:
#   1) Signup (or login if account already exists)
#   2) Create home details for a Cardiff area location
#   3) Add 3-6 devices to the home
#   4) Save credentials + provisioning summary to CSV
###############################################################################

param(
    [ValidateRange(1, 50)]
    [int]$Count = 50,

    [string]$BaseUrl = "http://129.212.138.248",

    [string]$EmailDomain = "wattwise-cardiff.co.uk"
)

$ErrorActionPreference = "Stop"

# Device catalogue (entity_id aligned to project conventions)
$DEVICE_CATALOGUE = @{
    airfryer        = @{ name = "Air Fryer";       appliance_key = "airfryer";        entity_id = "airfryer_current_consumption";        rated_wattage = 1500 }
    dishwasher      = @{ name = "Dishwasher";      appliance_key = "dishwasher";      entity_id = "dishwasher_current_consumption";      rated_wattage = 1800 }
    kettle          = @{ name = "Kettle";          appliance_key = "kettle";          entity_id = "kettle_current_consumption";          rated_wattage = 2200 }
    microwave       = @{ name = "Microwave";       appliance_key = "microwave";       entity_id = "microwave_current_consumption";       rated_wattage = 900  }
    toaster         = @{ name = "Toaster";         appliance_key = "toaster";         entity_id = "toaster_current_consumption";         rated_wattage = 800  }
    washing_machine = @{ name = "Washing Machine"; appliance_key = "washing_machine"; entity_id = "washing_machine_current_consumption"; rated_wattage = 2000 }
}

$DEVICE_KEYS = @("airfryer", "dishwasher", "kettle", "microwave", "toaster", "washing_machine")

# 50 participant names
$PARTICIPANT_NAMES = @(
    "Aled Morgan", "Bethan Hughes", "Carys Evans", "Dylan Price", "Elen Jones",
    "Ffion Roberts", "Gareth Thomas", "Hannah Williams", "Iwan Davies", "Jasmine Patel",
    "Kieran Lewis", "Lowri Jenkins", "Megan Rees", "Nia Griffiths", "Owain Pritchard",
    "Phoebe Collins", "Rhys Ahmed", "Sian Edwards", "Tomos Bennett", "Umair Khan",
    "Violet Ward", "Will Owen", "Xanthe Morris", "Yusuf Rahman", "Zara Ali",
    "Aron Phillips", "Branwen Lloyd", "Catrin Harper", "Dafydd Powell", "Eira Cooper",
    "Farah Shah", "Gethin Hall", "Heledd Green", "Idris Bailey", "Jaya Singh",
    "Keira Foster", "Llyr Murphy", "Mali Clarke", "Noah Fisher", "Olwen Wood",
    "Pari Ahmed", "Quinn Wallace", "Rhiannon Grant", "Seren Bell", "Tariq Hussain",
    "Ursula Ward", "Vaughan Scott", "Wyn Evans", "Yasmin Brooks", "Zain Malik"
)

# Cardiff locations with street and postcode templates
$CARDIFF_LOCATIONS = @(
    @{ area = "Roath";        street = "Albany Road";      postcode = "CF24 3"; home_type = "terraced" },
    @{ area = "Cathays";      street = "Crwys Road";       postcode = "CF24 4"; home_type = "flat" },
    @{ area = "Pontcanna";    street = "Cathedral Road";   postcode = "CF11 9"; home_type = "terraced" },
    @{ area = "Canton";       street = "Cowbridge Road";   postcode = "CF5 1";  home_type = "semi-detached" },
    @{ area = "Llanishen";    street = "Station Road";     postcode = "CF14 5"; home_type = "detached" },
    @{ area = "Whitchurch";   street = "Merthyr Road";     postcode = "CF14 1"; home_type = "semi-detached" },
    @{ area = "Heath";        street = "Allensbank Road";  postcode = "CF14 3"; home_type = "semi-detached" },
    @{ area = "Grangetown";   street = "Corporation Road"; postcode = "CF11 7"; home_type = "terraced" },
    @{ area = "Splott";       street = "Splott Road";      postcode = "CF24 2"; home_type = "terraced" },
    @{ area = "Adamsdown";    street = "City Road";        postcode = "CF24 3"; home_type = "flat" }
)

function New-ParticipantProfile {
    param(
        [int]$Index,
        [string]$Name,
        [string]$EmailDomain
    )

    $location = $CARDIFF_LOCATIONS[$Index % $CARDIFF_LOCATIONS.Count]
    $houseNo = 2 + ($Index * 3)
    $postSuffix = [char](65 + ($Index % 26))
    $address = "$houseNo $($location.street), $($location.area), Cardiff, Wales, UK $($location.postcode)$postSuffix"

    $emailHandle = ($Name.ToLower() -replace "[^a-z]", ".") -replace "\.+", "."
    $emailHandle = $emailHandle.Trim(".")
    $email = "{0}.{1}@{2}" -f $emailHandle, ($Index + 1), $EmailDomain

    $occupants = 1 + (($Index % 5) + 1)  # 2..6
    $password = "CardiffWW2026!{0:D2}" -f ($Index + 1)

    # Pick a rotating device count between 3 and 6.
    $deviceCount = 3 + ($Index % 4)
    $shuffled = $DEVICE_KEYS | Get-Random -Count $DEVICE_KEYS.Count
    $devices = $shuffled[0..($deviceCount - 1)]

    return @{
        name = $Name
        email = $email
        password = $password
        home = @{
            home_name = "$Name Household"
            address = $address
            location_desc = "$($location.area), Cardiff"
            num_occupants = $occupants
            home_type = $location.home_type
        }
        devices = $devices
    }
}

$participants = @()
for ($i = 0; $i -lt $Count; $i++) {
    $participants += (New-ParticipantProfile -Index $i -Name $PARTICIPANT_NAMES[$i] -EmailDomain $EmailDomain)
}

function Get-RequestFailureInfo {
    param(
        [Parameter(Mandatory = $true)]
        $ErrorRecord
    )

    $statusCode = $null
    try {
        if ($null -ne $ErrorRecord.Exception.Response) {
            $statusCode = [int]$ErrorRecord.Exception.Response.StatusCode
        }
    }
    catch {
        $statusCode = $null
    }

    $detail = $ErrorRecord.ErrorDetails.Message
    if ([string]::IsNullOrWhiteSpace($detail)) {
        $detail = $ErrorRecord.Exception.Message
    }

    return @{
        StatusCode = $statusCode
        Detail = $detail
    }
}

$results = @()

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WattWise - Provisioning $Count Cardiff Participants" -ForegroundColor Cyan
Write-Host " Server: $BaseUrl" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

for ($i = 0; $i -lt $participants.Count; $i++) {
    $p = $participants[$i]
    Write-Host "[$($i+1)/$Count] $($p.name) - $($p.email)" -ForegroundColor Yellow

    $token = $null
    $userId = $null
    $homeId = $null
    $authSource = "signup"
    $errorDetail = ""

    # Step 1: Signup, fallback to login if account already exists
    try {
        $signupBody = @{ name = $p.name; email = $p.email; password = $p.password } | ConvertTo-Json -Compress
        $signupResp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/signup" -Method Post -ContentType "application/json" -Body $signupBody
        $token = $signupResp.access_token
        $userId = $signupResp.user_id
        Write-Host "  OK signup user_id=$userId" -ForegroundColor Green
    }
    catch {
        $signupFailure = Get-RequestFailureInfo -ErrorRecord $_

        if ($signupFailure.StatusCode -ne 409) {
            $errorDetail = $signupFailure.Detail
            Write-Host "  FAIL signup [$($signupFailure.StatusCode)]: $errorDetail" -ForegroundColor Red
            $results += [PSCustomObject]@{
                Number     = $i + 1
                Name       = $p.name
                Email      = $p.email
                Password   = $p.password
                Address    = $p.home.address
                Location   = $p.home.location_desc
                Occupants  = $p.home.num_occupants
                HomeType   = $p.home.home_type
                UserID     = "FAILED"
                HomeID     = "FAILED"
                Devices    = 0
                AuthSource = "signup"
                Status     = if ($signupFailure.StatusCode -eq 429) { "SIGNUP_RATE_LIMITED" } else { "SIGNUP_FAILED" }
                ErrorDetail = $errorDetail
            }
            continue
        }

        try {
            $loginBody = @{ email = $p.email; password = $p.password } | ConvertTo-Json -Compress
            $loginResp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -ContentType "application/json" -Body $loginBody
            $token = $loginResp.access_token
            $userId = $loginResp.user_id
            $authSource = "login"
            Write-Host "  OK login existing user_id=$userId" -ForegroundColor Green
        }
        catch {
            $loginFailure = Get-RequestFailureInfo -ErrorRecord $_
            $errorDetail = $loginFailure.Detail
            Write-Host "  FAIL login [$($loginFailure.StatusCode)]: $errorDetail" -ForegroundColor Red
            $results += [PSCustomObject]@{
                Number     = $i + 1
                Name       = $p.name
                Email      = $p.email
                Password   = $p.password
                Address    = $p.home.address
                Location   = $p.home.location_desc
                Occupants  = $p.home.num_occupants
                HomeType   = $p.home.home_type
                UserID     = "FAILED"
                HomeID     = "FAILED"
                Devices    = 0
                AuthSource = "login"
                Status     = if ($loginFailure.StatusCode -eq 429) { "LOGIN_RATE_LIMITED" } else { "LOGIN_FAILED" }
                ErrorDetail = $errorDetail
            }
            continue
        }
    }

    $headers = @{ Authorization = "Bearer $token" }

    if ($authSource -eq "login") {
        try {
            $existingHomes = Invoke-RestMethod -Uri "$BaseUrl/api/homes" -Method Get -Headers $headers
            if ($existingHomes -and $existingHomes.Count -gt 0) {
                $homeId = $existingHomes[0].id
                Write-Host "  OK using existing home_id=$homeId" -ForegroundColor Green
            }
        }
        catch {
            $lookupFailure = Get-RequestFailureInfo -ErrorRecord $_
            Write-Host "  WARN homes lookup [$($lookupFailure.StatusCode)]: $($lookupFailure.Detail)" -ForegroundColor DarkYellow
        }
    }

    # Step 2: Create home
    if (-not $homeId) {
        try {
            $homeBody = $p.home | ConvertTo-Json -Compress
            $homeResp = Invoke-RestMethod -Uri "$BaseUrl/api/homes" -Method Post -ContentType "application/json" -Headers $headers -Body $homeBody
            $homeId = $homeResp.id
            Write-Host "  OK home home_id=$homeId" -ForegroundColor Green
        }
        catch {
            $homeFailure = Get-RequestFailureInfo -ErrorRecord $_
            $errorDetail = $homeFailure.Detail
            Write-Host "  FAIL home [$($homeFailure.StatusCode)]: $errorDetail" -ForegroundColor Red
            $results += [PSCustomObject]@{
                Number     = $i + 1
                Name       = $p.name
                Email      = $p.email
                Password   = $p.password
                Address    = $p.home.address
                Location   = $p.home.location_desc
                Occupants  = $p.home.num_occupants
                HomeType   = $p.home.home_type
                UserID     = $userId
                HomeID     = "FAILED"
                Devices    = 0
                AuthSource = $authSource
                Status     = "HOME_FAILED"
                ErrorDetail = $errorDetail
            }
            continue
        }
    }

    # Step 3: Add devices
    $added = 0
    foreach ($deviceKey in $p.devices) {
        $d = $DEVICE_CATALOGUE[$deviceKey]
        try {
            $deviceBody = @{
                name          = $d.name
                appliance_key = $d.appliance_key
                entity_id     = $d.entity_id
                device_type   = "appliance"
                rated_wattage = $d.rated_wattage
                location      = "Kitchen"
            } | ConvertTo-Json -Compress

            Invoke-RestMethod -Uri "$BaseUrl/api/homes/$homeId/devices" -Method Post -ContentType "application/json" -Headers $headers -Body $deviceBody | Out-Null
            $added++
        }
        catch {
            Write-Host "  WARN device $($d.name): $($_.Exception.Message)" -ForegroundColor DarkYellow
        }
    }

    Write-Host "  OK devices added=$added" -ForegroundColor DarkGreen

    $results += [PSCustomObject]@{
        Number     = $i + 1
        Name       = $p.name
        Email      = $p.email
        Password   = $p.password
        Address    = $p.home.address
        Location   = $p.home.location_desc
        Occupants  = $p.home.num_occupants
        HomeType   = $p.home.home_type
        UserID     = $userId
        HomeID     = $homeId
        Devices    = $added
        AuthSource = $authSource
        Status     = "OK"
        ErrorDetail = ""
    }

    Write-Host ""
}

# Final summary table
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Provisioning Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$results | Format-Table Number, Name, Email, HomeID, Devices, Status -AutoSize

# Save to CSV
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$csvPath = "$PSScriptRoot\wattwise_cardiff_participants_$timestamp.csv"
$results | Export-Csv -Path $csvPath -NoTypeInformation

Write-Host ""
Write-Host "Saved participant credentials + details to: $csvPath" -ForegroundColor Green
Write-Host "Done." -ForegroundColor Green



## .\create_cardiff_50_participants.ps1 -Count 50 -BaseUrl "http://129.212.138.248"

### to create using single command