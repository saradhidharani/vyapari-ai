"""Email verification, verified sign-in, and password recovery.

Rules:
- One-time codes are 6 digits, expire after 10 minutes, and work once. A new code
  for the same purpose and address cancels earlier ones. Five wrong attempts
  cancel a code.
- Codes are stored as HMAC-SHA256 digests keyed with VYAPARI_SECRET_KEY. They are
  never logged or returned by the API.
- Code requests, code checks, and failed sign-ins are rate-limited by address and
  by client IP. Rate-limit keys are stored as keyed hashes.
- Signup and password-reset requests return the same response whether or not an
  account exists. Email is sent in a background task so timing is uniform.
- Accounts created before verification existed keep their data and memberships.
  They verify their email on the next sign-in with their password plus an emailed
  code, or by resetting their password.
"""
import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
import time
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import Identity, SignIn, create_session, normalize_email, password_hash, workspace_account
from database import get_db
from notifications import DeliveryError, email_provider, production, send_email


logger = logging.getLogger("vyapari.verification")
router = APIRouter(prefix="/api/auth", tags=["Authentication"])

CODE_TTL = 10 * 60
SIGNUP_TICKET_TTL = 15 * 60
MAX_CODE_ATTEMPTS = 5
Purpose = Literal["signup", "login", "password_reset", "invitation"]

# (limit, window in seconds). Tests may adjust these values.
LIMITS = {
    "code_destination_burst": (1, 60),
    "code_destination": (5, 60 * 60),
    "code_ip": (20, 60 * 60),
    "verify_ip": (30, 15 * 60),
    "login_email": (10, 15 * 60),
    "login_ip": (50, 15 * 60),
}

_secret = os.getenv("VYAPARI_SECRET_KEY", "").encode()


def secret_key():
    global _secret
    if not _secret:
        if production():
            raise RuntimeError("Set VYAPARI_SECRET_KEY in production")
        # Development only: outstanding codes stop working when the server restarts.
        _secret = secrets.token_bytes(32)
        logger.warning("VYAPARI_SECRET_KEY is not set. Using a temporary development key.")
    return _secret


def initialize_verification():
    if production() and len(os.getenv("VYAPARI_SECRET_KEY", "")) < 32:
        raise RuntimeError("Set VYAPARI_SECRET_KEY to at least 32 random characters in production")
    secret_key()
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS auth_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purpose TEXT NOT NULL CHECK(purpose IN ('signup', 'login', 'password_reset', 'invitation')),
                channel TEXT NOT NULL CHECK(channel IN ('email', 'sms')),
                destination TEXT NOT NULL,
                code_hash BLOB NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                verified_at INTEGER,
                consumed_at INTEGER,
                ticket_hash BLOB UNIQUE
            );
            CREATE INDEX IF NOT EXISTS auth_codes_lookup ON auth_codes (purpose, destination, id DESC);
            CREATE TABLE IF NOT EXISTS auth_rate_events (
                key_hash BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS auth_rate_events_key ON auth_rate_events (key_hash, created_at);
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "email_verified_at" not in columns:
            # Existing accounts start unverified and verify on their next sign-in.
            db.execute("ALTER TABLE users ADD COLUMN email_verified_at INTEGER")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def client_ip(request: Request):
    """The visitor's address for rate limiting.

    The hosted frontend wrapper proxies API calls, so every request reaches FastAPI
    from the wrapper's address. The wrapper sends the visitor's address with a
    shared secret (VYAPARI_PROXY_KEY). The header is trusted only when the secret
    matches, so visitors cannot choose their own address."""
    expected = os.getenv("VYAPARI_PROXY_KEY", "")
    supplied = request.headers.get("x-vyapari-proxy-key", "")
    forwarded = request.headers.get("x-vyapari-client-ip", "")
    if len(expected) >= 32 and supplied and hmac.compare_digest(supplied.encode(), expected.encode()):
        try:
            return str(ipaddress.ip_address(forwarded.strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def rate_key(name, value):
    return hmac.new(secret_key(), f"{name}:{value}".encode(), hashlib.sha256).digest()


def rate_exceeded(db, name, value, now):
    """Return seconds to wait if the limit is reached, otherwise None."""
    limit, window = LIMITS[name]
    rows = db.execute("""
        SELECT created_at FROM auth_rate_events WHERE key_hash = ? AND created_at > ?
        ORDER BY created_at
    """, (rate_key(name, value), now - window)).fetchall()
    if len(rows) >= limit:
        return max(1, rows[len(rows) - limit]["created_at"] + window - now)
    return None


def record_rate(db, name, value, now):
    db.execute("INSERT INTO auth_rate_events (key_hash, created_at) VALUES (?, ?)", (rate_key(name, value), now))


def too_many(wait, message="Too many attempts"):
    minutes = max(1, -(-wait // 60))
    return HTTPException(
        status_code=429, headers={"Retry-After": str(wait)},
        detail=f"{message}. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
    )


def check_limits(db, checks, now):
    waits = [wait for name, value in checks if (wait := rate_exceeded(db, name, value, now))]
    return max(waits) if waits else None


# ---------------------------------------------------------------------------
# One-time codes
# ---------------------------------------------------------------------------

def code_digest(purpose, destination, code):
    return hmac.new(secret_key(), f"{purpose}:{destination}:{code}".encode(), hashlib.sha256).digest()


def mask_email(email):
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'*' * max(1, min(len(name) - 1, 5))}@{domain}"


MESSAGES = {
    "signup": ("Your Vyapari AI verification code",
               "Use this code to verify your email and create your Vyapari AI account."),
    "login": ("Verify your email for Vyapari AI",
              "Use this code to verify your email and finish signing in to Vyapari AI."),
    "password_reset": ("Reset your Vyapari AI password", "Use this code to reset your Vyapari AI password."),
    "invitation": ("Accept your Vyapari AI invitation",
                   "Use this code to verify your email and accept your Vyapari AI invitation."),
}


def deliver(to, subject, body):
    try:
        send_email(to, subject, body)
    except DeliveryError as error:
        logger.warning("Verification email not delivered: %s", error)


def require_email_delivery():
    if not email_provider():
        raise HTTPException(status_code=503, detail="Email delivery is not configured on this server")


def request_code(background: BackgroundTasks, request: Request, purpose, email, *, send=True, notice=None):
    """Rate-limit and record a code request. When `send` is false no code is
    created, but the request is counted and gets the same response. `notice`
    sends a message without a code instead, such as "account already exists"."""
    require_email_delivery()
    now = int(time.time())
    ip = client_ip(request)
    checks = (("code_destination_burst", email), ("code_destination", email), ("code_ip", ip))
    code = None
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        wait = check_limits(db, checks, now)
        if wait is None:
            for name, value in checks:
                record_rate(db, name, value, now)
            db.execute("DELETE FROM auth_rate_events WHERE created_at < ?", (now - 24 * 60 * 60,))
            db.execute("DELETE FROM auth_codes WHERE expires_at < ?", (now - 24 * 60 * 60,))
            if send:
                db.execute("""
                    UPDATE auth_codes SET consumed_at = ?
                    WHERE purpose = ? AND destination = ? AND consumed_at IS NULL
                """, (now, purpose, email))
                code = f"{secrets.randbelow(10**6):06d}"
                db.execute("""
                    INSERT INTO auth_codes (purpose, channel, destination, code_hash, created_at, expires_at)
                    VALUES (?, 'email', ?, ?, ?, ?)
                """, (purpose, email, code_digest(purpose, email, code), now, now + CODE_TTL))
    if wait is not None:
        raise too_many(wait, "Too many code requests")
    subject, intro = MESSAGES[purpose]
    if code:
        background.add_task(deliver, email, subject, (
            f"{intro}\n\nYour code is {code}\n\nIt expires in 10 minutes and can be used once. "
            "If you did not request it, you can ignore this email."))
    elif notice:
        background.add_task(deliver, email, notice[0], notice[1])
    return {"sent": True, "destination": mask_email(email), "expires_in": CODE_TTL}


def consume_code(request: Request, purpose, email, code, *, ticket_hash=None):
    """Check a code. On success it is marked used, or exchanged for a ticket.
    Failed attempts are committed before the error is raised."""
    now = int(time.time())
    ip = client_ip(request)
    error = None
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        wait = rate_exceeded(db, "verify_ip", ip, now)
        if wait is not None:
            error = too_many(wait, "Too many incorrect codes")
        else:
            row = db.execute("""
                SELECT id, code_hash, attempts FROM auth_codes
                WHERE purpose = ? AND destination = ? AND consumed_at IS NULL AND verified_at IS NULL
                  AND expires_at > ?
                ORDER BY id DESC LIMIT 1
            """, (purpose, email, now)).fetchone()
            matches = (row is not None and re.fullmatch(r"[0-9]{6}", code or "") is not None
                       and hmac.compare_digest(row["code_hash"], code_digest(purpose, email, code)))
            if matches:
                if ticket_hash is None:
                    db.execute("UPDATE auth_codes SET consumed_at = ? WHERE id = ?", (now, row["id"]))
                else:
                    db.execute("UPDATE auth_codes SET verified_at = ?, ticket_hash = ? WHERE id = ?",
                               (now, ticket_hash, row["id"]))
            else:
                record_rate(db, "verify_ip", ip, now)
                if row is not None:
                    attempts = row["attempts"] + 1
                    db.execute("UPDATE auth_codes SET attempts = ?, consumed_at = ? WHERE id = ?",
                               (attempts, now if attempts >= MAX_CODE_ATTEMPTS else None, row["id"]))
                error = HTTPException(status_code=400,
                                      detail="That code is incorrect or has expired. Request a new code.")
    if error:
        raise error


# ---------------------------------------------------------------------------
# Sign-in helpers
# ---------------------------------------------------------------------------

def record_login_failure(email, ip):
    now = int(time.time())
    with get_db() as db:
        record_rate(db, "login_email", email, now)
        record_rate(db, "login_ip", ip, now)


def find_user(db, email):
    return db.execute("""
        SELECT users.*, platform_admins.user_id IS NOT NULL AS is_platform_admin
        FROM users LEFT JOIN platform_admins ON platform_admins.user_id = users.id
        WHERE users.email = ?
    """, (email,)).fetchone()


def password_matches(user, password):
    """The same scrypt work runs whether or not the account exists."""
    hashed = password_hash(password, user["salt"] if user else bytes(16))
    return user is not None and hmac.compare_digest(user["password_hash"], hashed)


def identity_for(user):
    return Identity(user_id=user["id"], email=user["email"], home_business_id=user["business_id"],
                    is_platform_admin=bool(user["is_platform_admin"]))


def sign_in_response(db, user, business_id=None):
    account = workspace_account(db, identity_for(user), business_id)
    return SignIn(**account.model_dump(), token=create_session(db, user["id"]))


def verify_password_or_fail(request, email, password, message="Invalid email or password"):
    """Apply sign-in rate limits, then check the password. Returns the user row."""
    ip = client_ip(request)
    now = int(time.time())
    with get_db() as db:
        wait = check_limits(db, (("login_email", email), ("login_ip", ip)), now)
        user = None if wait else find_user(db, email)
    if wait:
        raise too_many(wait, "Too many sign-in attempts")
    if not password_matches(user, password):
        record_login_failure(email, ip)
        raise HTTPException(status_code=401, detail=message)
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def password_field():
    return Field(min_length=12, max_length=128)


def code_field():
    return Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class EmailAddress(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class CodeSent(BaseModel):
    sent: bool
    destination: str
    expires_in: int


class EmailCode(EmailAddress):
    code: str = code_field()


class SignupTicket(BaseModel):
    ticket: str
    expires_in: int


class SignupComplete(BaseModel):
    ticket: str = Field(min_length=20, max_length=100)
    password: str = password_field()
    business_name: str = Field(min_length=1, max_length=100)


class LoginBody(EmailAddress):
    password: str = Field(min_length=1, max_length=128)


class LoginVerify(LoginBody):
    code: str = code_field()


class PasswordReset(EmailCode):
    password: str = password_field()


@router.post("/signup/start", response_model=CodeSent, status_code=202)
def start_signup(body: EmailAddress, request: Request, background: BackgroundTasks):
    email = normalize_email(body.email)
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is not None
    # The same response either way, so signup cannot be used to discover accounts.
    return request_code(background, request, "signup", email, send=not exists, notice=(
        "Your Vyapari AI account",
        "Someone tried to create a Vyapari AI account with this email. You already have an account. "
        "Sign in, or use Forgot password to reset your password. If this wasn't you, you can ignore this email.",
    ) if exists else None)


@router.post("/signup/verify", response_model=SignupTicket)
def verify_signup(body: EmailCode, request: Request):
    email = normalize_email(body.email)
    ticket = secrets.token_urlsafe(32)
    consume_code(request, "signup", email, body.code, ticket_hash=hashlib.sha256(ticket.encode()).digest())
    return SignupTicket(ticket=ticket, expires_in=SIGNUP_TICKET_TTL)


@router.post("/signup/complete", response_model=SignIn, status_code=201)
def complete_signup(body: SignupComplete):
    business_name = body.business_name.strip()
    if not business_name:
        raise HTTPException(status_code=422, detail="Enter a business name")
    salt = secrets.token_bytes(16)
    hashed = password_hash(body.password, salt)
    now = int(time.time())
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""
            SELECT id, destination FROM auth_codes
            WHERE purpose = 'signup' AND ticket_hash = ? AND consumed_at IS NULL AND verified_at > ?
        """, (hashlib.sha256(body.ticket.encode()).digest(), now - SIGNUP_TICKET_TTL)).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="Your verification expired. Start again to get a new code.")
        email = row["destination"]
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="This email already has an account. Sign in instead.")
        db.execute("UPDATE auth_codes SET consumed_at = ? WHERE id = ?", (now, row["id"]))
        first_business = db.execute("SELECT NOT EXISTS (SELECT 1 FROM businesses)").fetchone()[0]
        business_id = db.execute("INSERT INTO businesses (name) VALUES (?)", (business_name,)).lastrowid
        user_id = db.execute("""
            INSERT INTO users (email, password_hash, salt, business_id, email_verified_at) VALUES (?, ?, ?, ?, ?)
        """, (email, hashed, salt, business_id, now)).lastrowid
        db.execute("INSERT INTO business_memberships (business_id, user_id, role) VALUES (?, ?, 'owner')",
                   (business_id, user_id))
        if first_business:
            db.execute("UPDATE products SET business_id = ? WHERE business_id IS NULL", (business_id,))
        return sign_in_response(db, find_user(db, email), business_id)


@router.post("/login", response_model=SignIn, responses={403: {"description": "Email verification required"}})
def login(body: LoginBody, request: Request, background: BackgroundTasks):
    email = body.email.strip().casefold()
    user = verify_password_or_fail(request, email, body.password)
    if user["email_verified_at"] is None:
        # Accounts created before verification: correct password, then an emailed code.
        destination = mask_email(email)
        message = f"Enter the code we sent to {destination} to verify your email."
        try:
            request_code(background, request, "login", email)
        except HTTPException as error:
            if error.status_code != 429:
                raise
            # A code was sent recently: keep asking for it rather than sending another.
            message = f"Enter the most recent code we sent to {destination}. You can request another code shortly."
        # Returned rather than raised: FastAPI skips background tasks, and so the
        # code email, when an exception is raised.
        return JSONResponse(status_code=403, background=background, content={"detail": {
            "code": "verification_required", "message": message, "destination": destination,
        }})
    with get_db() as db:
        return sign_in_response(db, user)


@router.post("/login/verify", response_model=SignIn)
def verify_login(body: LoginVerify, request: Request):
    email = body.email.strip().casefold()
    user = verify_password_or_fail(request, email, body.password)
    if user["email_verified_at"] is None:
        consume_code(request, "login", email, body.code)
        with get_db() as db:
            db.execute("UPDATE users SET email_verified_at = ? WHERE id = ? AND email_verified_at IS NULL",
                       (int(time.time()), user["id"]))
    with get_db() as db:
        return sign_in_response(db, find_user(db, email))


@router.post("/password-reset/start", response_model=CodeSent, status_code=202)
def start_password_reset(body: EmailAddress, request: Request, background: BackgroundTasks):
    email = normalize_email(body.email)
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is not None
    return request_code(background, request, "password_reset", email, send=exists)


@router.post("/password-reset/complete", response_model=SignIn)
def complete_password_reset(body: PasswordReset, request: Request):
    email = normalize_email(body.email)
    consume_code(request, "password_reset", email, body.code)
    salt = secrets.token_bytes(16)
    hashed = password_hash(body.password, salt)
    now = int(time.time())
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        user = find_user(db, email)
        if user is None:
            raise HTTPException(status_code=400, detail="That code is incorrect or has expired. Request a new code.")
        # The code proves control of the email, so the address is verified too.
        # Every existing session is signed out.
        db.execute("""
            UPDATE users SET password_hash = ?, salt = ?, email_verified_at = COALESCE(email_verified_at, ?)
            WHERE id = ?
        """, (hashed, salt, now, user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        return sign_in_response(db, find_user(db, email))
