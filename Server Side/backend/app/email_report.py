"""
WattWise Weekly Email Report Service
======================================
Generates and sends a weekly energy summary email to all registered users.
Uses Python's built-in smtplib — no third-party mail library required.

Integrates with the scheduler.py APScheduler cron framework.
Called every Monday at 08:00 UTC.

Report includes:
  - Week's total kWh usage
  - Cost in GBP
  - Efficiency score and community ranking
  - Top-consuming device
  - Goal achievement summary
  - Personalised tip

Author : Mr. Suhas Devmane, Cardiff University, UK
Version: 1.0.0
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import User, Home, HomeDailyTotal, EnergyRanking, DailySummary, Device

logger = logging.getLogger("email_report")


# ── SMTP Configuration (from environment) ────────────────────────────────────

SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "WattWise <noreply@wattwiser.org>")
SMTP_ENABLED  = bool(SMTP_USER and SMTP_PASSWORD)


# ── Weekly Energy Summary Data ────────────────────────────────────────────────

class WeeklySummary:
    """Holds computed weekly stats for a single home/user."""

    def __init__(self):
        self.user_name         : str    = ""
        self.user_email        : str    = ""
        self.week_start        : date   = date.today() - timedelta(days=7)
        self.week_end          : date   = date.today() - timedelta(days=1)
        self.total_kwh         : float  = 0.0
        self.total_cost_gbp    : float  = 0.0
        self.avg_daily_kwh     : float  = 0.0
        self.peak_day_kwh      : float  = 0.0
        self.peak_day          : Optional[date] = None
        self.efficiency_score  : float  = 0.0
        self.rank_position     : Optional[int]  = None
        self.total_users       : Optional[int]  = None
        self.top_device_name   : str    = "Unknown"
        self.top_device_kwh    : float  = 0.0
        self.goal_kwh          : Optional[float] = None
        self.goal_met_days     : int    = 0
        self.tip               : str    = ""


# ── Data Fetcher ──────────────────────────────────────────────────────────────

async def gather_weekly_data(user: User, db: AsyncSession) -> WeeklySummary:
    """Fetch all data needed to build a user's weekly email report."""

    summary = WeeklySummary()
    summary.user_name  = user.name
    summary.user_email = user.email
    summary.week_start = date.today() - timedelta(days=7)
    summary.week_end   = date.today() - timedelta(days=1)
    summary.goal_kwh   = user.weekly_energy_goal_kwh

    # Get the user's primary home
    home_result = await db.execute(
        select(Home).where(Home.user_id == user.id, Home.is_active == True).limit(1)
    )
    home = home_result.scalar_one_or_none()
    if not home:
        return summary

    # Weekly totals from home_daily_totals
    totals_result = await db.execute(
        select(
            func.sum(HomeDailyTotal.total_kwh).label("kwh"),
            func.sum(HomeDailyTotal.total_cost_gbp).label("cost"),
            func.max(HomeDailyTotal.total_kwh).label("peak_kwh"),
            func.avg(HomeDailyTotal.total_kwh).label("avg_kwh"),
        ).where(
            HomeDailyTotal.home_id == home.id,
            HomeDailyTotal.day_date >= summary.week_start,
            HomeDailyTotal.day_date <= summary.week_end,
        )
    )
    row = totals_result.one()
    summary.total_kwh      = round(float(row.kwh or 0), 2)
    summary.total_cost_gbp = round(float(row.cost or 0), 2)
    summary.avg_daily_kwh  = round(float(row.avg_kwh or 0), 2)
    summary.peak_day_kwh   = round(float(row.peak_kwh or 0), 2)

    # Find peak day date
    if summary.peak_day_kwh > 0:
        peak_result = await db.execute(
            select(HomeDailyTotal.day_date).where(
                HomeDailyTotal.home_id == home.id,
                HomeDailyTotal.day_date >= summary.week_start,
                HomeDailyTotal.total_kwh == summary.peak_day_kwh,
            ).limit(1)
        )
        summary.peak_day = peak_result.scalar_one_or_none()

    # Latest weekly ranking (use daily ranking for last day of week)
    rank_result = await db.execute(
        select(EnergyRanking).where(
            EnergyRanking.user_id == user.id,
            EnergyRanking.period_type == "DAILY",
            EnergyRanking.period_start == summary.week_end,
        ).limit(1)
    )
    ranking = rank_result.scalar_one_or_none()
    if ranking:
        summary.efficiency_score = ranking.efficiency_score or 0.0
        summary.rank_position    = ranking.rank_position
        summary.total_users      = ranking.total_users

    # Top consuming device this week
    top_device_result = await db.execute(
        select(
            Device.name,
            func.sum(DailySummary.total_kwh).label("device_kwh"),
        )
        .join(Device, DailySummary.device_id == Device.id)
        .where(
            DailySummary.home_id == home.id,
            DailySummary.day_date >= summary.week_start,
            DailySummary.day_date <= summary.week_end,
        )
        .group_by(Device.id)
        .order_by(func.sum(DailySummary.total_kwh).desc())
        .limit(1)
    )
    top_row = top_device_result.one_or_none()
    if top_row:
        summary.top_device_name = top_row[0]
        summary.top_device_kwh  = round(float(top_row[1] or 0), 2)

    # Goal met days
    if user.daily_energy_goal_kwh:
        goal_met_result = await db.execute(
            select(func.count()).where(
                DailySummary.home_id == home.id,
                DailySummary.day_date >= summary.week_start,
                DailySummary.goal_met == True,
            )
        )
        summary.goal_met_days = goal_met_result.scalar() or 0

    # Pick a personalised tip
    summary.tip = _pick_tip(summary)

    return summary


def _pick_tip(s: WeeklySummary) -> str:
    """Return a contextual energy-saving tip based on the week's data."""
    if s.total_kwh == 0:
        return "Start tracking your appliances to get personalised insights!"
    if s.top_device_kwh > 5:
        return (
            f"Your {s.top_device_name} used {s.top_device_kwh} kWh this week. "
            "Try scheduling it during off-peak hours (before 4 PM or after 7 PM) to cut costs."
        )
    if s.goal_kwh and s.total_kwh > s.goal_kwh:
        over = round(s.total_kwh - s.goal_kwh, 1)
        return (
            f"You were {over} kWh over your weekly goal. "
            "Small changes — like fully loading the dishwasher before running — can help."
        )
    if s.efficiency_score >= 80:
        return (
            "Excellent efficiency this week! 🌟 "
            "Keep it up — your choices are making a real difference for the community."
        )
    return (
        "Did you know? Running appliances on off-peak tariff (before 4 PM or after 7 PM) "
        "can reduce your electricity bill by up to 20%."
    )


# ── HTML Email Builder ────────────────────────────────────────────────────────

def build_html_email(s: WeeklySummary) -> str:
    """Render a rich HTML weekly report email."""

    rank_text = (
        f"🏆 #{s.rank_position} of {s.total_users} homes"
        if s.rank_position and s.total_users else "N/A"
    )
    goal_text = (
        f"{s.goal_met_days}/7 days goal met"
        if s.goal_kwh else "No weekly goal set"
    )
    peak_text = (
        f"{s.peak_day.strftime('%A, %d %b')} — {s.peak_day_kwh} kWh"
        if s.peak_day else "N/A"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>WattWise Weekly Energy Report</title>
</head>
<body style="margin:0;padding:0;background:#0F172A;font-family:system-ui,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0F172A;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#1E293B;border-radius:16px;overflow:hidden;max-width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#10B981,#0EA5E9);padding:32px;text-align:center;">
            <div style="font-size:48px;margin-bottom:8px;">⚡</div>
            <div style="color:#fff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">WattWise</div>
            <div style="color:rgba(255,255,255,0.85);font-size:14px;margin-top:4px;">
              Weekly Energy Report · {s.week_start.strftime('%d %b')} – {s.week_end.strftime('%d %b %Y')}
            </div>
          </td>
        </tr>

        <!-- Greeting -->
        <tr>
          <td style="padding:28px 32px 8px;">
            <div style="color:#94A3B8;font-size:14px;">Hi {s.user_name.split()[0]},</div>
            <div style="color:#E2E8F0;font-size:16px;margin-top:6px;">
              Here's your energy summary for the week. Let's see how you did!
            </div>
          </td>
        </tr>

        <!-- Key Stats -->
        <tr>
          <td style="padding:16px 32px;">
            <table width="100%" cellpadding="0" cellspacing="8">
              <tr>
                <td width="50%" style="padding:4px;">
                  <div style="background:#0F172A;border-radius:12px;padding:20px;text-align:center;">
                    <div style="color:#10B981;font-size:32px;font-weight:700;">{s.total_kwh}</div>
                    <div style="color:#64748B;font-size:12px;margin-top:4px;">kWh total used</div>
                  </div>
                </td>
                <td width="50%" style="padding:4px;">
                  <div style="background:#0F172A;border-radius:12px;padding:20px;text-align:center;">
                    <div style="color:#F59E0B;font-size:32px;font-weight:700;">£{s.total_cost_gbp:.2f}</div>
                    <div style="color:#64748B;font-size:12px;margin-top:4px;">estimated cost</div>
                  </div>
                </td>
              </tr>
              <tr>
                <td width="50%" style="padding:4px;">
                  <div style="background:#0F172A;border-radius:12px;padding:16px;text-align:center;">
                    <div style="color:#818CF8;font-size:24px;font-weight:700;">{s.efficiency_score:.0f}</div>
                    <div style="color:#64748B;font-size:12px;margin-top:4px;">efficiency score</div>
                  </div>
                </td>
                <td width="50%" style="padding:4px;">
                  <div style="background:#0F172A;border-radius:12px;padding:16px;text-align:center;">
                    <div style="color:#34D399;font-size:16px;font-weight:600;">{rank_text}</div>
                    <div style="color:#64748B;font-size:12px;margin-top:4px;">community rank</div>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Details -->
        <tr>
          <td style="padding:0 32px 16px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#0F172A;border-radius:12px;">
              <tr>
                <td style="padding:16px 20px;border-bottom:1px solid #1E293B;">
                  <span style="color:#94A3B8;font-size:13px;">📅 Daily average</span>
                  <span style="color:#E2E8F0;font-size:13px;float:right;font-weight:600;">{s.avg_daily_kwh} kWh</span>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 20px;border-bottom:1px solid #1E293B;">
                  <span style="color:#94A3B8;font-size:13px;">🔴 Peak day</span>
                  <span style="color:#E2E8F0;font-size:13px;float:right;font-weight:600;">{peak_text}</span>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 20px;border-bottom:1px solid #1E293B;">
                  <span style="color:#94A3B8;font-size:13px;">🔌 Top appliance</span>
                  <span style="color:#E2E8F0;font-size:13px;float:right;font-weight:600;">{s.top_device_name} ({s.top_device_kwh} kWh)</span>
                </td>
              </tr>
              <tr>
                <td style="padding:16px 20px;">
                  <span style="color:#94A3B8;font-size:13px;">🎯 Weekly goal</span>
                  <span style="color:#E2E8F0;font-size:13px;float:right;font-weight:600;">{goal_text}</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Tip -->
        <tr>
          <td style="padding:0 32px 24px;">
            <div style="background:linear-gradient(135deg,rgba(16,185,129,0.15),rgba(14,165,233,0.15));
                        border:1px solid rgba(16,185,129,0.3);border-radius:12px;padding:20px;">
              <div style="color:#10B981;font-size:13px;font-weight:600;margin-bottom:8px;">💡 THIS WEEK'S TIP</div>
              <div style="color:#CBD5E1;font-size:14px;line-height:1.5;">{s.tip}</div>
            </div>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:0 32px 32px;text-align:center;">
            <a href="https://app.wattwiser.org"
               style="display:inline-block;background:#10B981;color:#fff;
                      text-decoration:none;padding:14px 32px;border-radius:10px;
                      font-weight:600;font-size:15px;">
              Open WattWise Dashboard →
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 32px;border-top:1px solid #334155;text-align:center;">
            <div style="color:#475569;font-size:11px;line-height:1.6;">
              WattWise Community Energy Platform<br />
              PhD Research — Mr. Suhas Devmane, Cardiff University, Wales, UK<br />
              School of Computer Science &amp; Informatics (COMSC)<br /><br />
              <a href="https://app.wattwiser.org/unsubscribe" style="color:#10B981;text-decoration:none;">
                Unsubscribe from weekly reports
              </a>
            </div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_text_email(s: WeeklySummary) -> str:
    """Plain-text fallback for the weekly email."""
    rank = f"#{s.rank_position} of {s.total_users}" if s.rank_position else "N/A"
    return f"""WattWise — Weekly Energy Report
{s.week_start.strftime('%d %b')} – {s.week_end.strftime('%d %b %Y')}

Hi {s.user_name.split()[0]},

WEEKLY SUMMARY
  Total usage  : {s.total_kwh} kWh
  Estimated cost: £{s.total_cost_gbp:.2f}
  Daily average: {s.avg_daily_kwh} kWh
  Efficiency   : {s.efficiency_score:.0f} / 100
  Community rank: {rank}
  Top appliance: {s.top_device_name} ({s.top_device_kwh} kWh)

THIS WEEK'S TIP:
{s.tip}

Open your dashboard: https://app.wattwiser.org

--
WattWise Community Energy Platform
PhD Research — Mr. Suhas Devmane, Cardiff University, Wales, UK
"""


# ── SMTP Sender ───────────────────────────────────────────────────────────────

def send_email(to_address: str, subject: str, html: str, text: str) -> bool:
    """
    Send a multipart email via SMTP.
    Returns True on success, False on failure.
    """
    if not SMTP_ENABLED:
        logger.info(f"SMTP not configured — skipping email to {to_address}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = to_address

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_address, msg.as_string())

        logger.info(f"✅ Weekly report sent to {to_address}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed — check SMTP_USER / SMTP_PASSWORD in .env")
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_address}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending email to {to_address}: {e}")

    return False


# ── Scheduler Entry Point ─────────────────────────────────────────────────────

async def send_weekly_reports():
    """
    Called by APScheduler every Monday at 08:00 UTC.
    Sends personalised weekly energy summary emails to all opted-in users.
    """
    logger.info("📧 Sending weekly energy report emails...")

    sent    = 0
    skipped = 0
    errors  = 0

    async with AsyncSessionLocal() as db:
        # Only send to users who have notifications enabled
        result = await db.execute(
            select(User).where(
                User.notifications_enabled == True,
                User.email.is_not(None),
            )
        )
        users = result.scalars().all()

    logger.info(f"Found {len(users)} eligible users for weekly report")

    for user in users:
        try:
            async with AsyncSessionLocal() as db:
                summary = await gather_weekly_data(user, db)

            if summary.total_kwh == 0:
                logger.debug(f"Skipping {user.email} — no data this week")
                skipped += 1
                continue

            week_label = summary.week_start.strftime('%d %b')
            html = build_html_email(summary)
            text = build_text_email(summary)

            ok = send_email(
                to_address = user.email,
                subject    = f"⚡ Your WattWise Weekly Report — w/c {week_label}",
                html       = html,
                text       = text,
            )

            if ok:
                sent += 1
            else:
                skipped += 1

        except Exception as e:
            logger.error(f"Failed to send weekly report to {user.email}: {e}")
            errors += 1

    logger.info(
        f"Weekly reports done: {sent} sent, {skipped} skipped, {errors} errors"
    )
