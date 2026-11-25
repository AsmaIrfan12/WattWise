"""
WattWise — Admin: decisions, campaigns and the alert funnel.

This is the admin's view of the core loop: for every alert (automated or sent by
hand) who received it, who opened it, what they decided, what they reported doing,
and what the measured energy effect was.

All endpoints take `cohort` (all | real | synthetic, default all) — see app.cohorts.
"""
import csv
import io
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cohorts import decision_cohort_clause, normalise_cohort, user_cohort_clause
from app.database import get_db
from app.models import (
    AdminAuditLog, Device, Notification, NotificationCampaign, Persona, User, UserDecision,
)

router = APIRouter(prefix="/api/admin", tags=["Admin — Decisions"])


def _require_admin(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id or not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


# ── Decisions explorer ────────────────────────────────────────

DECISION_COLUMNS = [
    "decision_id", "user_id", "user_name", "user_email", "persona", "is_synthetic", "is_simulated",
    "notification_id", "alert_type", "alert_source", "alert_rule", "campaign_id", "alert_title", "alert_severity",
    "health_tip",
    "alert_created_at", "alert_opened_at", "device_name", "appliance_key",
    "decision_type", "action_taken", "user_feedback_text", "user_satisfaction",
    "decided_at", "updated_at", "response_time_seconds",
    "impact_scope", "energy_before_kwh", "energy_after_kwh", "energy_saved_kwh", "cost_saved_gbp",
    "effectiveness_score", "impact_calculated_at",
]


def _decision_query(
    cohort: str, user_id, decision_type, notification_type, source, persona_id, campaign_id,
    date_from, date_to, simulated, measured,
):
    q = (
        select(UserDecision, User, Notification, Device, Persona.name.label("persona_name"))
        .join(User, User.id == UserDecision.user_id)
        .outerjoin(Notification, Notification.id == UserDecision.notification_id)
        .outerjoin(Device, Device.id == UserDecision.device_id)
        .outerjoin(Persona, Persona.id == User.persona_id)
    )
    for clause in (user_cohort_clause(cohort), decision_cohort_clause(cohort)):
        if clause is not None:
            q = q.where(clause)
    if simulated == "only":
        q = q.where(UserDecision.is_simulated.is_(True))
    elif simulated == "exclude":
        q = q.where(UserDecision.is_simulated.is_(False))
    if user_id is not None:
        q = q.where(UserDecision.user_id == user_id)
    if decision_type:
        q = q.where(UserDecision.decision_type == decision_type)
    if notification_type:
        q = q.where(Notification.notification_type == notification_type)
    if source:
        q = q.where(Notification.source == source)
    if persona_id is not None:
        q = q.where(User.persona_id == persona_id)
    if campaign_id is not None:
        q = q.where(Notification.campaign_id == campaign_id)
    if date_from:
        q = q.where(UserDecision.action_timestamp >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(UserDecision.action_timestamp < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if measured == "yes":
        q = q.where(UserDecision.energy_saved_kwh.isnot(None))
    elif measured == "no":
        q = q.where(UserDecision.energy_saved_kwh.is_(None))
    return q


def _decision_row(d: UserDecision, u: User, n: Optional[Notification], dev: Optional[Device], persona) -> dict:
    return {
        "decision_id": d.id,
        "user_id": u.id, "user_name": u.name, "user_email": u.email,
        "persona": persona, "is_synthetic": bool(u.is_synthetic), "is_simulated": bool(d.is_simulated),
        "notification_id": d.notification_id,
        "alert_type": n.notification_type if n else None,
        "alert_source": n.source if n else None,
        "alert_rule": n.rule_key if n else None,
        "campaign_id": n.campaign_id if n else None,
        "alert_title": n.title if n else None,
        "alert_severity": n.severity if n else None,
        # The health suggestion the user saw with this alert (None for alerts without one).
        "health_tip": (n.metadata_json or {}).get("health_tip") if n and isinstance(n.metadata_json, dict) else None,
        "alert_created_at": _iso(n.created_at) if n else _iso(d.notification_sent_at),
        "alert_opened_at": _iso(n.opened_at) if n else None,
        "device_name": dev.name if dev else None,
        "appliance_key": dev.appliance_key if dev else None,
        "decision_type": d.decision_type,
        "action_taken": d.action_taken,
        "user_feedback_text": d.user_feedback_text,
        "user_satisfaction": d.user_satisfaction,
        "decided_at": _iso(d.action_timestamp),
        "updated_at": _iso(d.updated_at),
        "response_time_seconds": d.response_time_seconds,
        "impact_scope": d.impact_scope,
        "energy_before_kwh": d.energy_before_kwh,
        "energy_after_kwh": d.energy_after_kwh,
        "energy_saved_kwh": d.energy_saved_kwh,
        "cost_saved_gbp": d.cost_saved_gbp,
        "effectiveness_score": d.effectiveness_score,
        "impact_calculated_at": _iso(d.impact_calculated_at),
    }


@router.get("/decisions")
async def list_decisions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cohort: str = Query(default="all"),
    user_id: Optional[int] = Query(default=None),
    decision_type: Optional[str] = Query(default=None, pattern="^(ACCEPTED|REJECTED|DEFERRED|CUSTOM_ACTION)$"),
    notification_type: Optional[str] = Query(default=None, max_length=32),
    source: Optional[str] = Query(default=None, pattern="^(AUTOMATED|ADMIN)$"),
    persona_id: Optional[int] = Query(default=None),
    campaign_id: Optional[int] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    simulated: str = Query(default="any", pattern="^(any|only|exclude)$"),
    measured: str = Query(default="any", pattern="^(any|yes|no)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    """
    Every recorded decision with its alert, user, reported action and measured impact.
    `format=csv` downloads the full filtered set (not just one page) for analysis.
    """
    admin_id = _require_admin(request)
    cohort = normalise_cohort(cohort)
    base = _decision_query(cohort, user_id, decision_type, notification_type, source, persona_id, campaign_id,
                           date_from, date_to, simulated, measured)

    if format == "csv":
        rows = (await db.execute(base.order_by(UserDecision.action_timestamp.desc()))).all()
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        for d, u, n, dev, persona in rows:
            writer.writerow(_decision_row(d, u, n, dev, persona))
        db.add(AdminAuditLog(
            admin_user_id=admin_id, action_type="EXPORT_DATA",
            details_json={"export": "decisions", "cohort": cohort, "rows": len(rows)},
            ip_address=request.client.host if request.client else None,
        ))
        await db.commit()
        filename = f"wattwise-decisions-{cohort}-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.order_by(UserDecision.action_timestamp.desc()).offset((page - 1) * limit).limit(limit)
    )).all()
    return {
        "cohort": cohort, "total": int(total), "page": page, "limit": limit,
        "items": [_decision_row(d, u, n, dev, persona) for d, u, n, dev, persona in rows],
    }


# ── Alert funnel ──────────────────────────────────────────────

def _funnel_columns():
    decided = UserDecision.id.isnot(None)
    return [
        func.count(Notification.id).label("sent"),
        func.sum(case((Notification.is_read, 1), else_=0)).label("seen"),
        func.sum(case((Notification.opened_at.isnot(None), 1), else_=0)).label("opened"),
        func.sum(case((Notification.requires_user_action, 1), else_=0)).label("actionable"),
        func.sum(case((decided, 1), else_=0)).label("decided"),
        func.sum(case((UserDecision.decision_type == "ACCEPTED", 1), else_=0)).label("accepted"),
        func.sum(case((UserDecision.decision_type == "CUSTOM_ACTION", 1), else_=0)).label("custom_action"),
        func.sum(case((UserDecision.decision_type == "DEFERRED", 1), else_=0)).label("deferred"),
        func.sum(case((UserDecision.decision_type == "REJECTED", 1), else_=0)).label("rejected"),
        func.sum(case((UserDecision.energy_saved_kwh.isnot(None), 1), else_=0)).label("measured"),
        func.sum(UserDecision.energy_saved_kwh).label("saved_kwh"),
        func.avg(UserDecision.response_time_seconds).label("avg_response_s"),
        func.avg(UserDecision.user_satisfaction).label("avg_satisfaction"),
    ]


def _funnel_dict(row) -> dict:
    sent = int(row.sent or 0)
    decided = int(row.decided or 0)
    actionable = int(row.actionable or 0)
    return {
        "sent": sent,
        "seen": int(row.seen or 0),
        "opened": int(row.opened or 0),
        "actionable": actionable,
        "decided": decided,
        "accepted": int(row.accepted or 0),
        "custom_action": int(row.custom_action or 0),
        "deferred": int(row.deferred or 0),
        "rejected": int(row.rejected or 0),
        "no_response": max(sent - decided, 0),
        "measured": int(row.measured or 0),
        "saved_kwh": round(float(row.saved_kwh or 0), 3),
        "open_rate": round(100 * int(row.opened or 0) / sent, 1) if sent else None,
        # Share of alerts that asked for a response and got one.
        "response_rate": round(100 * decided / actionable, 1) if actionable else None,
        "avg_response_time_seconds": round(float(row.avg_response_s), 1) if row.avg_response_s is not None else None,
        "avg_satisfaction": round(float(row.avg_satisfaction), 1) if row.avg_satisfaction is not None else None,
    }


def _decision_join(cohort: str):
    """Join condition from an alert to its decision, honouring the cohort's simulated-data rule."""
    cond = UserDecision.notification_id == Notification.id
    clause = decision_cohort_clause(cohort)
    return cond if clause is None else and_(cond, clause)


@router.get("/notifications/funnel")
async def notification_funnel(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cohort: str = Query(default="all"),
    days: int = Query(default=30, ge=1, le=365),
    source: Optional[str] = Query(default=None, pattern="^(AUTOMATED|ADMIN)$"),
):
    """Sent → seen → opened → decided → measured, overall and per alert type."""
    _require_admin(request)
    cohort = normalise_cohort(cohort)
    since = datetime.utcnow() - timedelta(days=days)

    def scoped(q):
        q = (q.join(User, User.id == Notification.user_id)
              .outerjoin(UserDecision, _decision_join(cohort))
              .where(Notification.created_at >= since))
        clause = user_cohort_clause(cohort)
        if clause is not None:
            q = q.where(clause)
        if source:
            q = q.where(Notification.source == source)
        return q

    overall = (await db.execute(scoped(select(*_funnel_columns())))).one()
    by_type_rows = (await db.execute(
        scoped(select(Notification.notification_type, Notification.source, *_funnel_columns()))
        .group_by(Notification.notification_type, Notification.source)
        .order_by(func.count(Notification.id).desc())
    )).all()
    return {
        "cohort": cohort, "days": days, "source": source,
        "overall": _funnel_dict(overall),
        "by_type": [
            {"notification_type": r.notification_type, "source": r.source, **_funnel_dict(r)} for r in by_type_rows
        ],
    }


# ── Campaigns (admin sends) ───────────────────────────────────

def _campaign_dict(c: NotificationCampaign, sender_name: Optional[str] = None) -> dict:
    return {
        "id": c.id, "title": c.title, "message": c.message,
        "notification_type": c.notification_type, "severity": c.severity,
        "requires_user_action": bool(c.requires_user_action),
        "action_hint": c.action_hint, "action_button_text": c.action_button_text,
        "target": c.target_json or {}, "status": c.status,
        "send_at": _iso(c.send_at), "sent_at": _iso(c.sent_at), "created_at": _iso(c.created_at),
        "recipients_targeted": c.recipients_targeted, "notifications_created": c.notifications_created,
        "created_by": c.created_by, "created_by_name": sender_name,
    }


@router.get("/campaigns")
async def list_campaigns(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cohort: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Admin sends, newest first, each with its response funnel."""
    _require_admin(request)
    cohort = normalise_cohort(cohort)
    campaigns = (await db.execute(
        select(NotificationCampaign, User.name)
        .outerjoin(User, User.id == NotificationCampaign.created_by)
        .order_by(NotificationCampaign.created_at.desc()).limit(limit)
    )).all()
    ids = [c.id for c, _ in campaigns]
    funnels = {}
    if ids:
        recipient = User.__table__.alias("recipient")
        q = (
            select(Notification.campaign_id, *_funnel_columns())
            .join(recipient, recipient.c.id == Notification.user_id)
            .outerjoin(UserDecision, _decision_join(cohort))
            .where(Notification.campaign_id.in_(ids))
            .group_by(Notification.campaign_id)
        )
        if cohort == "real":
            q = q.where(recipient.c.is_synthetic.is_(False))
        elif cohort == "synthetic":
            q = q.where(recipient.c.is_synthetic.is_(True))
        funnels = {r.campaign_id: _funnel_dict(r) for r in (await db.execute(q)).all()}
    return {
        "cohort": cohort,
        "campaigns": [{**_campaign_dict(c, name), "funnel": funnels.get(c.id)} for c, name in campaigns],
    }


@router.get("/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: int, request: Request, db: AsyncSession = Depends(get_db), cohort: str = Query(default="all"),
):
    """One admin send with every recipient's status: opened? decided what? reported what? saved what?"""
    _require_admin(request)
    cohort = normalise_cohort(cohort)
    campaign = (await db.execute(
        select(NotificationCampaign).where(NotificationCampaign.id == campaign_id)
    )).scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    q = (
        select(Notification, User, UserDecision, Device.name.label("device_name"))
        .join(User, User.id == Notification.user_id)
        .outerjoin(UserDecision, _decision_join(cohort))
        .outerjoin(Device, Device.id == Notification.device_id)
        .where(Notification.campaign_id == campaign_id)
        .order_by(User.name)
    )
    clause = user_cohort_clause(cohort)
    if clause is not None:
        q = q.where(clause)
    rows = (await db.execute(q)).all()

    recipients = []
    for n, u, d, device_name in rows:
        status = "decided" if d else "opened" if n.opened_at else "seen" if n.is_read else "delivered"
        recipients.append({
            "notification_id": n.id, "user_id": u.id, "user_name": u.name, "user_email": u.email,
            "is_synthetic": bool(u.is_synthetic), "device_name": device_name, "status": status,
            "delivered_at": _iso(n.created_at), "seen_at": _iso(n.read_at), "opened_at": _iso(n.opened_at),
            "decision": None if not d else {
                "id": d.id, "decision_type": d.decision_type, "action_taken": d.action_taken,
                "user_feedback_text": d.user_feedback_text, "user_satisfaction": d.user_satisfaction,
                "decided_at": _iso(d.action_timestamp), "response_time_seconds": d.response_time_seconds,
                "energy_saved_kwh": d.energy_saved_kwh, "effectiveness_score": d.effectiveness_score,
                "impact_scope": d.impact_scope, "is_simulated": bool(d.is_simulated),
            },
        })
    counts = {s: sum(1 for r in recipients if r["status"] == s) for s in ("delivered", "seen", "opened", "decided")}
    return {"campaign": _campaign_dict(campaign), "cohort": cohort, "status_counts": counts, "recipients": recipients}


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Cancel a scheduled send that has not gone out yet."""
    _require_admin(request)
    campaign = (await db.execute(
        select(NotificationCampaign).where(NotificationCampaign.id == campaign_id)
    )).scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "SCHEDULED":
        raise HTTPException(status_code=409, detail=f"Campaign is {campaign.status} and cannot be cancelled")
    campaign.status = "CANCELLED"
    await db.commit()
    return {"id": campaign.id, "status": campaign.status}
