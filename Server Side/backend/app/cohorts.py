"""
Account groups (cohorts)
========================
WattWise treats every account the same way: real participants and synthetic homes are
ranked together, analysed together and alerted by the same rules. That is the default
everywhere (`cohort=all`).

`users.is_synthetic` and `user_decisions.is_simulated` are kept as labels, so an admin
can still NARROW a view on request:

    all        every account and every decision                        (default)
    real       users with is_synthetic = 0, decisions with is_simulated = 0
    synthetic  users with is_synthetic = 1

Nothing in the system filters on these labels unless a caller asks for it.
"""
from typing import Optional

from fastapi import HTTPException

from sqlalchemy import select

from app.models import Device, Home, User, UserDecision

COHORTS = ("real", "synthetic", "all")
DEFAULT_COHORT = "all"


def normalise_cohort(cohort: Optional[str]) -> str:
    cohort = (cohort or DEFAULT_COHORT).lower()
    if cohort not in COHORTS:
        raise HTTPException(status_code=422, detail=f"cohort must be one of {', '.join(COHORTS)}")
    return cohort


def user_cohort_clause(cohort: str):
    """SQLAlchemy WHERE clause on User for a cohort, or None for 'all'."""
    if cohort == "real":
        return User.is_synthetic.is_(False)
    if cohort == "synthetic":
        return User.is_synthetic.is_(True)
    return None


def decision_cohort_clause(cohort: str):
    """
    WHERE clause on UserDecision for a cohort, or None when nothing is excluded.
    Only the explicit "real" filter leaves simulated decisions out.
    """
    if cohort == "real":
        return UserDecision.is_simulated.is_(False)
    return None


def apply_user_cohort(query, cohort: str):
    clause = user_cohort_clause(cohort)
    return query if clause is None else query.where(clause)


class CohortScope:
    """
    The admin's "Show" choice as WHERE clauses, so every view can honour it the same way.

    Each method returns a LIST to splat into `.where(...)`: empty for "all" (nothing is
    filtered: the default), one IN-clause for "real" or "synthetic".

        scope = CohortScope(cohort)
        select(...).where(HourlySummary.hour_start >= since, *scope.devices(HourlySummary.device_id))
    """

    def __init__(self, cohort: Optional[str]):
        self.cohort = normalise_cohort(cohort)
        self._user = user_cohort_clause(self.cohort)

    @property
    def active(self) -> bool:
        return self._user is not None

    def user_rows(self) -> list:
        """For a query that already selects from / joins `users`."""
        return [] if self._user is None else [self._user]

    def users(self, column) -> list:
        """`column` holds a user id."""
        return [] if self._user is None else [column.in_(select(User.id).where(self._user))]

    def homes(self, column) -> list:
        """`column` holds a home id."""
        if self._user is None:
            return []
        return [column.in_(select(Home.id).join(User, User.id == Home.user_id).where(self._user))]

    def devices(self, column) -> list:
        """`column` holds a device id."""
        if self._user is None:
            return []
        return [column.in_(
            select(Device.id).join(Home, Device.home_id == Home.id).join(User, User.id == Home.user_id).where(self._user)
        )]
