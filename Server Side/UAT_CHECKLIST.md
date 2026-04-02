# WattWise UAT Checklist

## Objective

Validate end-to-end release readiness for API, admin dashboard, user dashboard, and data ingestion before deployment.

## Automated UAT

Run from `Server Side/`:

```bash
python scripts/uat_verify.py \
  --api-base http://localhost:8000 \
  --admin-url http://localhost:3000 \
  --user-url http://localhost:3001 \
  --admin-email admin@wattwise.co.uk \
  --admin-password admin \
  --user-email liam.jenkins@wattwise-test.co.uk \
  --user-password WattTest2024! \
  --output UAT_REPORT.latest.json
```

Pass criteria:

- UAT script exits with code `0`
- `UAT_REPORT.latest.json` status is `PASS`
- Smoke checks also pass via `scripts/smoke_check.py --require-slo-ok`

## Manual UX Validation

1. Admin dashboard login and key widgets populate.
2. User dashboard shows devices, trend chart, and alerts.
3. Trigger one finite sender cycle and verify no failed sends:
   `python ../dummy_data_sender.py --no-backfill --interval 2 --live-cycles 1 --admin-email admin@wattwise.co.uk --admin-password admin`
4. Verify `/metrics` counters increase after test traffic.
5. Verify `/health/slo` remains `ok` or no error-rate breach.

## Release Gate

- [ ] Backend tests passing
- [ ] CI lint + security audit passing
- [ ] Smoke check strict mode passing
- [ ] UAT automated check passing
- [ ] Manual UX validation done
- [ ] Rollback procedure verified in runbook
