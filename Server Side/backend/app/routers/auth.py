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
from app.schemas import SignupRequest, LoginRequest, TokenResponse, UserResponse, PushTokenUpdate

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


@router.post("/forgot-password")
async def forgot_password(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a password reset email for the given address.

    Security note: Always returns HTTP 200 regardless of whether the email exists
    to prevent user enumeration attacks.

    In production, replace the stub below with an SMTP/SendGrid call to send the
    actual reset link. The reset token should be a signed JWT with short expiry
    stored in the `password_reset_token` column (add via migration if needed).
    """
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="Email is required.")

    # Lookup user (we don't leak whether they exist)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        # TODO: Generate a signed reset token and send via SMTP
        # reset_token = _create_token(user.id, is_admin=False)
        # await send_password_reset_email(email, reset_token)
        import logging
        logging.getLogger("auth").info(
            "Password reset requested for user_id=%s email=%s", user.id, email
        )

    # Always return 200 — prevents user enumeration
    return {
        "success": True,
        "message": f"If an account exists for {email}, a reset link has been sent.",
    }
