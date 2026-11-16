"""
Real vs synthetic cohorts
=========================
The deployment mixes real participants (an RPi in their home) with synthetic
demo homes fed by dummy_data_sender.py, and real decisions with rows written by
the admin "decision simulator". Research analytics must be able to tell them
apart, so every admin analytic takes a `cohort`:

    real       — users with is_synthetic = 0, decisions with is_simulated = 0   (default)
    synthetic  — users with is_synthetic = 1 (simulated decisions included)
    all        — everything

`users.is_synthetic` and `user_decisions.is_simulated` are the only sources of truth.
"""
from typing import Optional

from fastapi import HTTPException

from app.models import User, UserDecision

COHORTS = ("real", "synthetic", "all")
DEFAULT_COHORT = "real"


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
    Real analytics never include simulated decisions, even if one was (wrongly)
    written against a real user.
    """
    if cohort == "real":
        return UserDecision.is_simulated.is_(False)
    return None


def apply_user_cohort(query, cohort: str):
    clause = user_cohort_clause(cohort)
    return query if clause is None else query.where(clause)
