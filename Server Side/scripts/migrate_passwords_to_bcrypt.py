#!/usr/bin/env python3
"""
One-off migration: bcrypt-hash all plaintext passwords in the users table.

Run ONCE on the production server BEFORE setting ENABLE_PASSWORD_HASHING=true.
Safe to re-run — already-hashed rows (starting with $2b$) are skipped.

Usage (from Server Side/):
    docker compose exec backend python3 /app/scripts/migrate_passwords_to_bcrypt.py

Or locally (requires DB access):
    cd "Server Side/backend"
    python3 ../scripts/migrate_passwords_to_bcrypt.py
"""

import asyncio
import logging
import sys

import bcrypt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Allow running from Server Side/backend or from Server Side/scripts/
sys.path.insert(0, "/app")
try:
    from app.config import settings
    from app.models import User
    DATABASE_URL = settings.DATABASE_URL
except ImportError:
    import os
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "mysql+aiomysql://wattwise_app:changeme_app_2026@127.0.0.1:3306/wattwise_db",
    )
    # Minimal User stub — only need id + password_hash
    from sqlalchemy import Column, Integer, String
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        password_hash = Column(String(255))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_passwords")

BCRYPT_ROUNDS = 12


def _is_bcrypt(value: str) -> bool:
    return value.startswith("$2b$") or value.startswith("$2a$") or value.startswith("$2y$")


async def migrate():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(User.id, User.password_hash))
        rows = result.all()

    log.info("Found %d users total.", len(rows))

    to_migrate = [(uid, pw) for uid, pw in rows if pw and not _is_bcrypt(pw)]
    already_hashed = len(rows) - len(to_migrate)
    log.info("%d already bcrypt-hashed (skipped), %d plaintext to migrate.", already_hashed, len(to_migrate))

    if not to_migrate:
        log.info("Nothing to do — all passwords are already hashed.")
        return

    async with async_session() as session:
        migrated = 0
        failed = 0
        for uid, plaintext in to_migrate:
            try:
                new_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()
                await session.execute(
                    update(User).where(User.id == uid).values(password_hash=new_hash)
                )
                migrated += 1
                log.info("  Migrated user_id=%d", uid)
            except Exception as exc:
                failed += 1
                log.error("  FAILED user_id=%d: %s", uid, exc)

        await session.commit()

    log.info("Migration complete: %d migrated, %d failed.", migrated, failed)
    if failed:
        log.error("Some rows failed — check logs above and re-run.")
        sys.exit(1)
    else:
        log.info("All passwords are now bcrypt-hashed. Safe to set ENABLE_PASSWORD_HASHING=true.")


if __name__ == "__main__":
    asyncio.run(migrate())
