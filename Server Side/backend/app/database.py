"""Async SQLAlchemy database engine for WattWise."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=False,   # aiomysql 0.2.0 ping() signature incompatible with SA pre_ping probe
    # MySQL drops idle connections after wait_timeout (8 h). Without recycling, the
    # first query on a stale pooled connection fails with a sporadic 500.
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db():
    """Dependency injection for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Bring the schema up to date on startup.

    The baseline schema comes from mysql/init/01-schema.sql; every later change is a
    numbered step in app/migrations.py and is applied here. create_all() is kept only
    as a safety net for tables that exist in the models but in neither of those.
    """
    from app.migrations import run_migrations
    from app.models import Base
    await run_migrations(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
