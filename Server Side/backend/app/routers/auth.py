"""WattWise — Authentication Router."""

from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, UserInteractionLog
from app.security import SlidingWindowRateLimiter
from app.schemas import SignupRequest, LoginRequest, TokenResponse, UserResponse, PushTokenUpdate, ProfileUpdateRequest

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Simple in-memory token denylist for logout.
# Tokens are added on logout and checked by the auth middleware.
# Resets on server restart — use Redis for persistent invalidation in production.
_token_denylist: set[str] = set()


def is_token_denied(token: str) -> bool:
    return token in _token_denylist


login_rate_limiter = SlidingWindowRateLimiter(
    max_attempts=settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)


def _hash_password(password: str) -> str:
    if not settings.ENABLE_PASSWORD_HASHING:
        return password
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def _verify_password(password: str, hashed: str) -> bool:
    if not settings.ENABLE_PASSWORD_HASHING:
        return password == hashed
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, Exception):
        # Fallback: if hashing was just enabled but record is still plaintext
        return password == hashed


def _create_token(user_id: int, is_admin: bool = False) -> str:
    payload = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


async def get_current_user(
    token: str = None,
    db: AsyncSession = Depends(get_db)
) -> User:
    """JWT dependency for protected routes."""
    # Token is injected via Depends(verify_token) in route-level code
    raise HTTPException(status_code=401, detail="Not authenticated")


async def verify_token(
    credentials: "HTTPAuthorizationCredentials" = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    from fastapi import Security
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    bearer = HTTPBearer(auto_error=True)
    async def inner(credentials: HTTPAuthorizationCredentials = Security(bearer)):
        try:
            payload = _decode_token(credentials.credentials)
            user_id = int(payload["sub"])
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    return inner


def _require_request_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(user_id)


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        name=body.name,
        email=body.email,
        password_hash=_hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log = UserInteractionLog(user_id=user.id, interaction_type="LOGIN", screen_name="signup")
    db.add(log)
    await db.commit()

    return TokenResponse(
        access_token=_create_token(user.id, is_admin=bool(user.is_admin)),
        user_id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    limit_key = f"{client_ip}:{body.email.lower()}"

    if await login_rate_limiter.is_limited(limit_key):
        retry_after = await login_rate_limiter.retry_after_seconds(limit_key)
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not _verify_password(body.password, user.password_hash):
        await login_rate_limiter.record_failure(limit_key)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await login_rate_limiter.reset(limit_key)

    user.last_login_at = datetime.utcnow()
    log = UserInteractionLog(user_id=user.id, interaction_type="LOGIN")
    db.add(log)
    await db.commit()

    return TokenResponse(
        access_token=_create_token(user.id, is_admin=bool(user.is_admin)),
        user_id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_request_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=bool(user.is_admin),
        notifications_enabled=bool(user.notifications_enabled),
        daily_energy_goal_kwh=user.daily_energy_goal_kwh,
        weekly_energy_goal_kwh=user.weekly_energy_goal_kwh,
        monthly_budget_gbp=user.monthly_budget_gbp,
        created_at=user.created_at,
    )


@router.patch("/profile", response_model=UserResponse)
async def update_profile(body: ProfileUpdateRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Update user profile fields: monthly_budget_gbp, daily_energy_goal_kwh, notifications_enabled."""
    user_id = _require_request_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.monthly_budget_gbp is not None:
        user.monthly_budget_gbp = body.monthly_budget_gbp
    if body.daily_energy_goal_kwh is not None:
        user.daily_energy_goal_kwh = body.daily_energy_goal_kwh
    if body.notifications_enabled is not None:
        user.notifications_enabled = body.notifications_enabled

    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=bool(user.is_admin),
        notifications_enabled=bool(user.notifications_enabled),
        daily_energy_goal_kwh=user.daily_energy_goal_kwh,
        weekly_energy_goal_kwh=user.weekly_energy_goal_kwh,
        monthly_budget_gbp=user.monthly_budget_gbp,
        created_at=user.created_at,
    )


@router.post("/push-token")
async def update_push_token(body: PushTokenUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    """Update user's Expo push notification token."""
    user_id = _require_request_user_id(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.push_token = body.push_token
    user.notifications_enabled = True
    await db.commit()

    return {"success": True, "message": "Push token updated"}


@router.post("/logout")
async def logout(request: Request):
    _require_request_user_id(request)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        _token_denylist.add(token)
    return {"success": True, "message": "Logged out"}


def _send_reset_email(to_email: str, reset_token: str, user_name: str) -> bool:
    """Send a password-reset email via SMTP. Returns True on success."""
    import os
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_from = os.getenv("SMTP_FROM", "WattWise <noreply@wattwiser.org>")
    base_url  = os.getenv("RESET_BASE_URL", "https://www.talk2futurebuildings.systems")

    if not smtp_user or not smtp_pass:
        logging.getLogger("auth").warning(
            "SMTP not configured — password reset email NOT sent to %s", to_email
        )
        return False

    reset_link = f"{base_url}/reset-password?token={reset_token}"
    body_html = f"""
    <p>Hi {user_name},</p>
    <p>We received a request to reset your WattWise password.</p>
    <p><a href="{reset_link}" style="background:#16a34a;color:#fff;padding:10px 20px;
       border-radius:6px;text-decoration:none;font-weight:bold;">Reset My Password</a></p>
    <p>This link expires in <strong>1 hour</strong>. If you did not request this, ignore this email.</p>
    <p>— WattWise Research Team, Cardiff University</p>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "WattWise — Password Reset"
    msg["From"]    = smtp_from
    msg["To"]      = to_email
    msg.attach(MIMEText(body_html, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=ctx)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, to_email, msg.as_string())
        logging.getLogger("auth").info("Password reset email sent to %s", to_email)
        return True
    except Exception as exc:
        logging.getLogger("auth").error("Failed to send reset email to %s: %s", to_email, exc)
        return False


@router.post("/forgot-password")
async def forgot_password(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a password reset email.

    Generates a signed JWT (1-hour expiry) and emails a reset link.
    Always returns HTTP 200 to prevent user enumeration.
    """
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="Email is required.")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        from datetime import timedelta
        from jose import jwt as _jwt
        reset_payload = {
            "sub": str(user.id),
            "purpose": "password_reset",
            "exp": datetime.utcnow() + timedelta(hours=1),
        }
        reset_token = _jwt.encode(reset_payload, settings.SECRET_KEY, algorithm="HS256")
        _send_reset_email(user.email, reset_token, user.name)

    return {
        "success": True,
        "message": f"If an account exists for {email}, a reset link has been sent.",
    }


@router.post("/reset-password")
async def reset_password(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Consume a password-reset token and set a new password.

    Expects: { "token": "<jwt>", "new_password": "<min 8 chars>" }
    """
    from jose import jwt as _jwt, JWTError as _JWTError

    token       = (body.get("token") or "").strip()
    new_password = (body.get("new_password") or "").strip()

    if not token or not new_password:
        raise HTTPException(status_code=422, detail="token and new_password are required.")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    try:
        payload = _jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("purpose") != "password_reset":
            raise ValueError("Not a reset token")
        user_id = int(payload["sub"])
    except (_JWTError, ValueError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(12)).decode()
    await db.commit()

    logging.getLogger("auth").info("Password reset completed for user_id=%s", user_id)
    return {"success": True, "message": "Password updated. Please log in with your new password."}
