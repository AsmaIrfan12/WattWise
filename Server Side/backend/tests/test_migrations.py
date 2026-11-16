"""
Tests for the migration runner's bookkeeping. The steps themselves run against
MySQL (information_schema) and are exercised by the integration suite / on deploy.
"""
import asyncio

from app import migrations
from app.migrations import MIGRATIONS, pending


class TestMigrationRegistry:
    def test_versions_are_unique(self):
        versions = [m[0] for m in MIGRATIONS]
        assert len(versions) == len(set(versions))

    def test_versions_are_contiguous_from_one(self):
        assert [m[0] for m in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))

    def test_names_are_unique_and_short(self):
        names = [m[1] for m in MIGRATIONS]
        assert len(names) == len(set(names))
        assert all(len(n) <= 128 for n in names)

    def test_every_step_is_a_coroutine_function(self):
        assert all(asyncio.iscoroutinefunction(m[2]) for m in MIGRATIONS)


class TestPending:
    async def _noop(self, conn):
        return None

    def _fake(self, *versions):
        return [(v, f"step_{v}", self._noop) for v in versions]

    def test_nothing_applied_returns_all_in_order(self):
        assert [m[0] for m in pending(set(), self._fake(3, 1, 2))] == [1, 2, 3]

    def test_applied_steps_are_skipped(self):
        assert [m[0] for m in pending({1, 2}, self._fake(1, 2, 3, 4))] == [3, 4]

    def test_everything_applied_returns_empty(self):
        assert pending({1, 2, 3}, self._fake(1, 2, 3)) == []

    def test_gap_in_applied_is_filled(self):
        # version 2 was skipped on some install; it must still be applied
        assert [m[0] for m in pending({1, 3}, self._fake(1, 2, 3))] == [2]


class TestRunnerSkipsNonMysql:
    def test_non_mysql_dialect_is_a_noop(self):
        class _Dialect:
            name = "sqlite"

        class _Engine:
            dialect = _Dialect()

        assert asyncio.run(migrations.run_migrations(_Engine())) == []
