# WattWise Deploy Checklist

Version: 2026-03-30
Purpose: Pre-release and post-deploy validation checklist for stable production behavior.

## A. Pre-Deploy

1. Configuration
- Server Side/.env contains production credentials and strong SECRET_KEY.
- No placeholder hashes or default secrets remain.
- Cloudflare tunnel points to Nginx correctly.

2. Database
- Admin seed/login email is admin@wattwise.co.uk.
- Migrations are up-to-date for backend schema.

3. Code Readiness
- Backend auth endpoints available: signup/login/me/push-token/logout.
- User dashboard includes login overlay and token bootstrap logic.
- Android MainViewModel and MainScreen include webUrl token fragment handoff.

4. Build Plan
- Decide services to rebuild (minimum changed set).
- Confirm rollback image tags or previous commit available.

## B. Deploy Steps

From Server Side:

```bash
docker compose build backend user-dashboard admin-dashboard nginx-proxy
docker compose up -d --force-recreate backend user-dashboard admin-dashboard nginx-proxy
docker compose ps
```

## C. Immediate Post-Deploy Validation

1. Infrastructure

```bash
docker compose ps
curl https://www.talk2futurebuildings.systems/health
```

2. Backend Auth
- POST /api/auth/login returns 200 for valid user.
- GET /api/auth/me returns expected identity with bearer token.
- POST /api/auth/push-token returns success.
- POST /api/auth/logout returns success.

3. User Dashboard Runtime Parity

```powershell
$src='C:\Users\suhas\Documents\GitHub\WattWise\Server Side\user-frontend\static\index.html'
$srcHash=(Get-FileHash -Algorithm SHA256 $src).Hash.ToLower()
Set-Location 'C:\Users\suhas\Documents\GitHub\WattWise\Server Side'
$cid=(docker compose ps -q user-dashboard)
$ctrHash=(docker exec $cid sh -lc "sha256sum /usr/share/nginx/html/index.html | cut -d ' ' -f1").Trim().ToLower()
"SOURCE=$srcHash"
"CONTAINER=$ctrHash"
if($srcHash -eq $ctrHash){'PARITY=YES'} else {'PARITY=NO'}
```

Expected: PARITY=YES.

4. Web User Journey
- Open https://www.talk2futurebuildings.systems/
- Login overlay appears for signed-out users.
- Login with non-admin user succeeds.
- Dashboard cards load readings and ranking.
- Logout returns to login overlay.

5. Android User Journey
- Login in Android app.
- Main WebView opens authenticated dashboard without manual web login.
- Token fragment is consumed and removed from URL.

6. MQTT + Ingestion
- Confirm publisher still connected.
- Confirm new readings appear in API and database.

## D. Rollback Triggers

Rollback or hotfix immediately if any of these fail:
- /health not ok.
- auth/me fails for valid token.
- user-dashboard parity check remains NO after rebuild.
- Android users cannot open authenticated dashboard.
- MQTT ingestion stops for active homes.

## E. Rollback Actions

1. Re-deploy previous known-good images or commit.
2. Force recreate impacted services.
3. Re-run sections C.1 through C.3 before reopening traffic.

## F. Sign-Off

Deploy is complete only when all checks in section C pass and no critical errors appear in logs for at least 15 minutes.
