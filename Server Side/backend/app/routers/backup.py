"""WattWise — Admin Backup Router."""
import asyncio
import gzip
import io
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("backup")
router = APIRouter(prefix="/api/admin/backup", tags=["Backup"])

BACKUPS_DIR = "/backups"


def _require_admin(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if not user_id or not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


def _backup_settings(backups_dir: str = BACKUPS_DIR) -> dict:
    d = Path(backups_dir)
    enabled = not (d / ".backup_disabled").exists()
    gz_files = sorted(d.glob("*.sql.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    last_file = gz_files[0] if gz_files else None
    return {
        "enabled": enabled,
        "backup_count": len(gz_files),
        "last_backup_file": last_file.name if last_file else None,
        "last_backup_size_mb": round(last_file.stat().st_size / 1_048_576, 2) if last_file else None,
    }


def _set_backup_enabled(enabled: bool, backups_dir: str = BACKUPS_DIR) -> None:
    flag = Path(backups_dir) / ".backup_disabled"
    if enabled:
        flag.unlink(missing_ok=True)
    else:
        flag.touch()


def _list_backups(backups_dir: str = BACKUPS_DIR) -> list[dict]:
    d = Path(backups_dir)
    gz_files = sorted(d.glob("*.sql.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "size_mb": round(f.stat().st_size / 1_048_576, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in gz_files
    ]


def _run_mysqldump_sync() -> bytes:
    raw_url = settings.DATABASE_URL.replace("mysql+aiomysql://", "mysql://")
    parsed = urlparse(raw_url)
    db_user = parsed.username
    db_host = parsed.hostname or "mysql"
    db_name = parsed.path.lstrip("/")
    db_pass = parsed.password or ""
    result = subprocess.run(
        ["mysqldump", "-h", db_host, "-u", db_user, db_name],
        env={**os.environ, "MYSQL_PWD": db_pass},
        capture_output=True,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"mysqldump failed: {err}")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(result.stdout)
    return buf.getvalue()


class BackupSettingsUpdate(BaseModel):
    enabled: bool


@router.get("/settings")
async def get_backup_settings(request: Request):
    _require_admin(request)
    if not Path(BACKUPS_DIR).exists():
        return {
            "enabled": False,
            "backup_count": 0,
            "last_backup_file": None,
            "last_backup_size_mb": None,
            "warning": "Backup volume not mounted — run with docker-compose.production.yml",
        }
    return _backup_settings()


@router.post("/settings")
async def update_backup_settings(body: BackupSettingsUpdate, request: Request):
    _require_admin(request)
    if not Path(BACKUPS_DIR).exists():
        raise HTTPException(status_code=503, detail="Backup volume not mounted — run with docker-compose.production.yml")
    _set_backup_enabled(body.enabled)
    logger.info("Auto-backup %s by admin user_id=%s", "enabled" if body.enabled else "disabled", request.state.user_id)
    return {"enabled": body.enabled, "message": f"Auto-backup {'enabled' if body.enabled else 'disabled'}"}


@router.get("/list")
async def list_backups(request: Request):
    _require_admin(request)
    if not Path(BACKUPS_DIR).exists():
        return []
    return _list_backups()


@router.get("/download")
async def download_backup(request: Request):
    _require_admin(request)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"wattwise-ondemand-{ts}.sql.gz"
    try:
        data = await asyncio.to_thread(_run_mysqldump_sync)
    except RuntimeError as exc:
        logger.error("On-demand backup failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
