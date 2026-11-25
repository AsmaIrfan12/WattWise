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

from app.models import User, UserDecision

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
