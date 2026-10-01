# WattWise Quick Start

Version: 2026-03-30

This is the shortest path to bring WattWise up and verify core functionality.

## 1. Start The Platform

From the repository root:

```bash
cd "Server Side"
docker compose up -d --build
docker compose ps
```

Expected: backend, mysql, influxdb, mosquitto, user-dashboard, admin-dashboard, nginx-proxy are running.

## 2. Health Checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

For production:

```bash
curl https://www.talk2futurebuildings.systems/health
```

## 3. Verify Auth APIs

```bash
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"Test User","email":"test.user@example.com","password":"SecurePass123!"}'
```

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test.user@example.com","password":"SecurePass123!"}'
```

Capture access_token and test:

```bash
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <TOKEN>"
```

```bash
curl -X POST http://localhost:8000/api/auth/push-token \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"push_token":"ExponentPushToken[demo]"}'
```

```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -H "Authorization: Bearer <TOKEN>"
```

## 4. Verify Dashboards

- User dashboard: http://localhost:3001
- Admin dashboard: http://localhost:3000

User dashboard supports:
- Login overlay (email/password).
- Token bootstrap via URL fragment #ww_token=... (for Android WebView flow).

## 5. Verify User Dashboard Container Parity

Run when you changed Server Side/user-frontend/static/index.html.

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

If PARITY=NO:

```bash
docker compose build --no-cache user-dashboard
docker compose up -d --force-recreate user-dashboard
```

## 6. Raspberry Pi Publisher Smoke Check

On RPi:

```bash
python3 rpi_mqtt_publisher.py --config /etc/wattwise/publisher.yaml
```

Expected: successful MQTT connection and periodic publish logs.

## 7. Most Common Fixes

- Login fails for admin seed account:
  - Ensure admin email is admin@wattwise.co.uk in database.
- /api/auth/me returns 401:
  - Verify Bearer token format and token freshness.
- Dashboard appears outdated:
  - Rebuild/recreate user-dashboard and run parity check.

## 8. Next Read

- Full setup and operations: WATTWISE_SETUP_GUIDE.md
- Release validation steps: DEPLOY_CHECKLIST.md
