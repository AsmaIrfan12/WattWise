"""
WattWise — schema migrations
============================
The database is created once by `Server Side/mysql/init/01-schema.sql` (the
baseline, applied by MySQL on an empty volume). Every schema change after that
baseline lives HERE, as a numbered step, and is applied automatically when the
backend starts. That makes this file the single source of truth for schema
changes: a fresh install is "baseline + all migrations", an existing install is
"whatever it has + the migrations it is missing".

Rules for adding a step
-----------------------
* Append to MIGRATIONS with the next integer version. Never edit or reorder an
  applied step — write a new one.
* MySQL DDL commits implicitly, so a step cannot be rolled back. Every step
  must therefore be idempotent: check `information_schema` (helpers below)
  before each ALTER so a half-applied step can simply be re-run.
* Use the same column types as the baseline (INT UNSIGNED / BIGINT UNSIGNED ids).
* Mirror the change in `app/models.py` in the same commit.

Concurrency: uvicorn starts several workers at once; a MySQL advisory lock makes
exactly one of them apply pending steps while the others wait and then see them
as already applied.
"""
import logging
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger("migrations")

LOCK_NAME = "ww_schema_migrations"
LOCK_TIMEOUT_SECONDS = 120


# ── information_schema helpers ────────────────────────────────

async def table_exists(conn: AsyncConnection, table: str) -> bool:
    return bool((await conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {"t": table})).scalar())


async def column_exists(conn: AsyncConnection, table: str, column: str) -> bool:
    return bool((await conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {"t": table, "c": column})).scalar())


async def column_type(conn: AsyncConnection, table: str, column: str) -> str | None:
    """Full column type as MySQL prints it, e.g. 'bigint unsigned' or "enum('A','B')"."""
    return (await conn.execute(text(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {"t": table, "c": column})).scalar()


async def index_exists(conn: AsyncConnection, table: str, index: str) -> bool:
    return bool((await conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i"
    ), {"t": table, "i": index})).scalar())


async def foreign_keys(conn: AsyncConnection, table: str, column: str) -> list[tuple[str, str, str]]:
    """[(constraint_name, referenced_table, delete_rule)] for FKs on table.column."""
    rows = (await conn.execute(text(
        "SELECT k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME, r.DELETE_RULE "
        "FROM information_schema.KEY_COLUMN_USAGE k "
        "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
        "  ON r.CONSTRAINT_SCHEMA = k.TABLE_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
        "WHERE k.TABLE_SCHEMA = DATABASE() AND k.TABLE_NAME = :t AND k.COLUMN_NAME = :c "
        "  AND k.REFERENCED_TABLE_NAME IS NOT NULL"
    ), {"t": table, "c": column})).all()
    return [(r[0], r[1], r[2]) for r in rows]


async def add_column(conn: AsyncConnection, table: str, column: str, ddl: str) -> None:
    """ALTER TABLE … ADD COLUMN if it is not there yet. `ddl` is everything after the column name."""
    if not await column_exists(conn, table, column):
        await conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}"))


async def add_index(conn: AsyncConnection, table: str, index: str, columns: str, unique: bool = False) -> None:
    if not await index_exists(conn, table, index):
        kind = "UNIQUE INDEX" if unique else "INDEX"
        await conn.execute(text(f"ALTER TABLE `{table}` ADD {kind} `{index}` ({columns})"))


async def extend_enum(conn: AsyncConnection, table: str, column: str, values: list[str], nullable: bool = False,
                      default: str | None = None) -> None:
    """Append any missing values to an ENUM column, keeping the existing ones and their order."""
    current = await column_type(conn, table, column)
    if not current or not current.lower().startswith("enum("):
        return
    existing = [v.strip("'") for v in current[5:-1].split(",")]
    missing = [v for v in values if v not in existing]
    if not missing:
        return
    all_values = ",".join(f"'{v}'" for v in existing + missing)
    null_sql = "NULL" if nullable else "NOT NULL"
    default_sql = f" DEFAULT '{default}'" if default else ""
    await conn.execute(text(f"ALTER TABLE `{table}` MODIFY `{column}` ENUM({all_values}) {null_sql}{default_sql}"))


async def set_fk_on_delete_set_null(conn: AsyncConnection, table: str, column: str, ref_table: str,
                                    fk_name: str) -> None:
    """Make table.column a nullable FK to ref_table(id) with ON DELETE SET NULL."""
    fks = [fk for fk in await foreign_keys(conn, table, column) if fk[1] == ref_table]
    if fks and all(rule == "SET NULL" for _, _, rule in fks):
        return
    for name, _, _ in fks:
        await conn.execute(text(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{name}`"))
    col_type = await column_type(conn, table, column)
    await conn.execute(text(f"ALTER TABLE `{table}` MODIFY `{column}` {col_type} NULL"))
    await conn.execute(text(
        f"ALTER TABLE `{table}` ADD CONSTRAINT `{fk_name}` FOREIGN KEY (`{column}`) "
        f"REFERENCES `{ref_table}`(id) ON DELETE SET NULL"
    ))


# ── Migration steps ───────────────────────────────────────────

async def m001_keep_decisions_when_notifications_expire(conn: AsyncConnection) -> None:
    """
    user_decisions / decision_observed_actions referenced notifications with
    ON DELETE CASCADE, so the 90-day notification cleanup silently deleted the
    research record of what users decided. Decisions now outlive their alert.
    """
    await set_fk_on_delete_set_null(conn, "user_decisions", "notification_id", "notifications",
                                    "fk_decisions_notification")
    if await table_exists(conn, "decision_observed_actions"):
        await set_fk_on_delete_set_null(conn, "decision_observed_actions", "notification_id", "notifications",
                                        "fk_doa_notification")


async def m002_audit_action_types(conn: AsyncConnection) -> None:
    """The admin budget endpoint wrote an action_type the ENUM did not contain, failing the audit insert."""
    await extend_enum(conn, "admin_audit_logs", "action_type", [
        "UPDATE_USER_BUDGET", "SIMULATE_DECISIONS", "PROVISION_HOME", "ROTATE_CREDENTIALS", "DELETE_DEVICE",
    ])


Migration = tuple[int, str, Callable[[AsyncConnection], Awaitable[None]]]

MIGRATIONS: list[Migration] = [
    (1, "keep_decisions_when_notifications_expire", m001_keep_decisions_when_notifications_expire),
    (2, "audit_action_types", m002_audit_action_types),
]


# ── Runner ────────────────────────────────────────────────────

def pending(applied: set[int], migrations: list[Migration] | None = None) -> list[Migration]:
    """Steps not yet applied, in version order."""
    migrations = MIGRATIONS if migrations is None else migrations
    return sorted((m for m in migrations if m[0] not in applied), key=lambda m: m[0])


async def run_migrations(engine: AsyncEngine) -> list[int]:
    """Apply every pending migration. Returns the versions applied by this call."""
    if engine.dialect.name != "mysql":
        logger.info("Skipping migrations on dialect %s", engine.dialect.name)
        return []

    applied_now: list[int] = []
    async with engine.connect() as conn:
        got = (await conn.execute(
            text("SELECT GET_LOCK(:n, :t)"), {"n": LOCK_NAME, "t": LOCK_TIMEOUT_SECONDS}
        )).scalar()
        if not got:
            raise RuntimeError("Could not acquire the schema-migration lock; another process is stuck migrating")
        try:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INT NOT NULL PRIMARY KEY,"
                " name VARCHAR(128) NOT NULL,"
                " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ") ENGINE=InnoDB"
            ))
            await conn.commit()
            applied = {int(r[0]) for r in (await conn.execute(text("SELECT version FROM schema_migrations"))).all()}

            for version, name, step in pending(applied):
                logger.info("Applying migration %03d %s", version, name)
                await step(conn)
                await conn.execute(
                    text("INSERT INTO schema_migrations (version, name) VALUES (:v, :n)"),
                    {"v": version, "n": name},
                )
                await conn.commit()
                applied_now.append(version)
        finally:
            await conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK_NAME})
            await conn.commit()

    if applied_now:
        logger.info("Migrations applied: %s", applied_now)
    return applied_now
