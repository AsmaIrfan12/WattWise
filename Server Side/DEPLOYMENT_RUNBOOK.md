# WattWise Deployment Runbook

## Production Deploy Flow

The CI/CD pipeline deploy job now performs:

1. Capture current server commit as rollback point.
2. Fast-forward server workspace to `origin/main`.
3. Rebuild and restart stack from `Server Side/docker-compose.yml`.
4. Run smoke checks via `scripts/smoke_check.py`.
5. If smoke fails: rollback to previous commit and rebuild stack automatically.

## Manual Smoke Check

Run from `Server Side/`:

```bash
python3 scripts/smoke_check.py --api-base http://localhost:8000 --admin-url http://localhost:3000 --user-url http://localhost:3001
```

Use strict SLO enforcement when validating a fresh deployment:

```bash
python3 scripts/smoke_check.py --api-base http://localhost:8000 --admin-url http://localhost:3000 --user-url http://localhost:3001 --require-slo-ok
```

Expected result:

- `/health` returns `{"status": "ok"}`
- `/health/dependencies` returns `status: ok`
- `/health/slo` returns `status: ok`
- Admin frontend (3000) responds HTTP 200
- User frontend (3001) responds HTTP 200

## Manual Rollback

If CI rollback is not available, run on server:

```bash
cd /opt/wattwise
git log --oneline -n 5
# pick previous known-good commit
git reset --hard <commit>
cd "Server Side"
docker compose up -d --build --remove-orphans
python3 scripts/smoke_check.py --api-base http://localhost:8000 --admin-url http://localhost:3000 --user-url http://localhost:3001
```

## Post-Deploy Verification

- Verify `docker compose ps` reports backend healthy.
- Verify `GET /metrics` returns counters and scheduler structure.
- Verify `GET /health/slo` status is `ok`.
- Run one finite sender cycle to confirm ingestion path:

```bash
python dummy_data_sender.py --no-backfill --interval 2 --live-cycles 1 --admin-email admin@wattwise.co.uk --admin-password admin
```
