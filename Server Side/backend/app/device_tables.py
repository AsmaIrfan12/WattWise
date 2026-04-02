"""Per-device readings tables — dynamic creation and access.

Each registered home/device gets its own readings table:
    readings_<device_id>   (e.g. readings_00000000db5b17e8)

This isolates raw sensor data per household while shared tables
(hourly_summary, daily_summary, mould_assessments, etc.) still
reference homes.id for cross-home comparison and ranking.
"""

import re
import logging

from sqlalchemy import (
    Table, Column, BigInteger, Float, DateTime, MetaData, Index, text,
)
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("device_tables")

_metadata = MetaData()
_table_cache: dict[str, Table] = {}

_DEVICE_ID_RE = re.compile(r"^[a-fA-F0-9]{1,32}$")


def _validate_device_id(device_id: str) -> str:
    """Ensure device_id contains only hex characters (RPi serial format)."""
    if not _DEVICE_ID_RE.match(device_id):
        raise ValueError(f"Invalid device_id format: {device_id}")
    return device_id.lower()


def get_table_name(device_id: str) -> str:
    """Return the per-device table name, e.g. readings_00000000db5b17e8."""
    return f"readings_{_validate_device_id(device_id)}"


def get_readings_table(device_id: str) -> Table:
    """Get a SQLAlchemy Table object for the given device (cached)."""
    table_name = get_table_name(device_id)
    if table_name in _table_cache:
        return _table_cache[table_name]

    tbl = Table(
        table_name,
        _metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("recorded_at", DateTime, nullable=False),
        Column("pm1", Float),
        Column("pm25", Float),
        Column("pm10", Float),
        Column("co2", Float),
        Column("temperature", Float),
        Column("humidity", Float),
        Column("created_at", DateTime, nullable=False),
        Index(f"idx_{table_name}_recorded", "recorded_at"),
        extend_existing=True,
    )
    _table_cache[table_name] = tbl
    return tbl


async def ensure_device_table(engine: AsyncEngine, device_id: str) -> str:
    """Create the per-device readings table if it doesn't exist.

    Returns the table name.
    """
    table_name = get_table_name(device_id)
    ddl = text(
        f"CREATE TABLE IF NOT EXISTS `{table_name}` ("
        "  id              BIGINT AUTO_INCREMENT PRIMARY KEY,"
        "  recorded_at     DATETIME     NOT NULL,"
        "  pm1             FLOAT        DEFAULT NULL,"
        "  pm25            FLOAT        DEFAULT NULL,"
        "  pm10            FLOAT        DEFAULT NULL,"
        "  co2             FLOAT        DEFAULT NULL,"
        "  temperature     FLOAT        DEFAULT NULL,"
        "  humidity        FLOAT        DEFAULT NULL,"
        "  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "  INDEX idx_recorded (recorded_at)"
        ") ENGINE=InnoDB;"
    )
    async with engine.begin() as conn:
        await conn.execute(ddl)
    logger.info("Ensured table %s exists", table_name)
    # Warm the cache
    get_readings_table(device_id)
    return table_name


async def rename_device_table(engine: AsyncEngine, old_device_id: str, new_device_id: str) -> tuple[str, str]:
    """Rename per-device readings table when a device_id changes.

    Returns old and new table names.
    """
    old_table_name = get_table_name(old_device_id)
    new_table_name = get_table_name(new_device_id)

    if old_table_name == new_table_name:
        return old_table_name, new_table_name

    ddl = text(f"RENAME TABLE `{old_table_name}` TO `{new_table_name}`;")
    async with engine.begin() as conn:
        await conn.execute(ddl)

    # Keep cache consistent after rename.
    _table_cache.pop(old_table_name, None)
    get_readings_table(new_device_id)
    logger.info("Renamed table %s -> %s", old_table_name, new_table_name)
    return old_table_name, new_table_name


async def drop_device_table(engine: AsyncEngine, device_id: str) -> str:
    """Drop the per-device readings table if it exists.

    Returns the table name.
    """
    table_name = get_table_name(device_id)
    ddl = text(f"DROP TABLE IF EXISTS `{table_name}`;")
    async with engine.begin() as conn:
        await conn.execute(ddl)

    _table_cache.pop(table_name, None)
    logger.info("Dropped table %s (if existed)", table_name)
    return table_name
