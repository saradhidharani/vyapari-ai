"""Email verification, verified sign-in, password recovery, rate limits, and
verified invitation acceptance. Codes travel through the in-memory fake provider."""
import logging
import sqlite3
import time
import uuid
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD, headers, latest_code, ok, register

NEW_PASSWORD = "a-brand-new-password-42"


def fake_messages(email):
    from notifications import FAKE_EMAIL
    return [message for message in FAKE_EMAIL.messages if message["to"] == email]


def unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@auth-test.example"


def db_execute(client, sql, params=()):
    with closing(sqlite3.connect(client.database_path)) as db, db:
        return db.execute(sql, params).fetchall()


def make_legacy(client, email):
    """Simulate an account created before verification existed."""
    db_execute(client, "UPDATE users SET email_verified_at = NULL WHERE email = ?", (email,))


def allow_new_code(client, email):
    """Skip the one-per-minute burst limit by ageing earlier requests for an address."""
    import verification
    for name in ("code_destination_burst", "code_destination"):
        db_execute(client, "UPDATE auth_rate_events SET created_at = created_at - 120 WHERE key_hash = ?",
                   (verification.rate_key(name, email),))


@pytest.fixture
def fresh_ip(client):
    """A client with its own IP address, for testing per-IP limits."""
    from main import app
    return TestClient(app, client=(f"203.0.113.{uuid.uuid4().int % 250 + 1}", 50000))


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

def test_signup_requires_verified_email_and_keeps_codes_out_of_responses(client, caplog):
    email = unique("signup")
    caplog.set_level(logging.DEBUG)
    started = client.post("/api/auth/signup/start", json={"email": email.upper()})
    assert started.status_code == 202
    assert started.json()["destination"].endswith("@auth-test.example") and "*" in started.json()["destination"]
    code = latest_code(email)
    assert code not in started.text

    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": wrong}).status_code == 400
    verified = ok(client.post("/api/auth/signup/verify", json={"email": email, "code": code}))
    assert code not in str(verified)
    # The code is single-use.
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": code}).status_code == 400

    account = ok(client.post("/api/auth/signup/complete", json={
        "ticket": verified["ticket"], "password": PASSWORD, "business_name": "Verified Stores"}), 201)
    assert (account["email"], account["business_name"], account["role"]) == (email, "Verified Stores", "owner")
    ok(client.get("/api/products", headers=headers(account["token"])))
    # The ticket is single-use too.
    assert client.post("/api/auth/signup/complete", json={
        "ticket": verified["ticket"], "password": PASSWORD, "business_name": "Again"}).status_code == 400
    assert code not in caplog.text


def test_unverified_signup_endpoint_is_gone(client):
    response = client.post("/api/auth/register", json={
        "email": unique("old"), "password": PASSWORD, "business_name": "Old flow"})
    assert response.status_code in (404, 405)


def test_signup_for_existing_email_looks_the_same_but_sends_no_code(client):
    email = unique("existing")
    register(client, email, "Existing Business")
    allow_new_code(client, email)
    before = len(fake_messages(email))
    response = client.post("/api/auth/signup/start", json={"email": email})
    assert response.status_code == 202
    assert set(response.json()) == {"sent", "destination", "expires_in"}
    notice = fake_messages(email)[before:]
    assert len(notice) == 1 and "already have an account" in notice[0]["body"]
    assert "Your code is" not in notice[0]["body"]


def test_code_expiry_and_replacement(client):
    email = unique("expiry")
    ok(client.post("/api/auth/signup/start", json={"email": email}), 202)
    first = latest_code(email)
    db_execute(client, "UPDATE auth_codes SET expires_at = ? WHERE destination = ?", (int(time.time()) - 1, email))
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": first}).status_code == 400

    allow_new_code(client, email)
    ok(client.post("/api/auth/signup/start", json={"email": email}), 202)
    second = latest_code(email)
    allow_new_code(client, email)
    ok(client.post("/api/auth/signup/start", json={"email": email}), 202)
    third = latest_code(email)
    if second != third:
        # Requesting a new code cancels the previous one.
        assert client.post("/api/auth/signup/verify", json={"email": email, "code": second}).status_code == 400
    ok(client.post("/api/auth/signup/verify", json={"email": email, "code": third}))


def test_five_wrong_attempts_cancel_a_code(client):
    email = unique("attempts")
    ok(client.post("/api/auth/signup/start", json={"email": email}), 202)
    code = latest_code(email)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(5):
        assert client.post("/api/auth/signup/verify", json={"email": email, "code": wrong}).status_code == 400
    assert client.post("/api/auth/signup/verify", json={"email": email, "code": code}).status_code == 400


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------

def test_code_requests_are_limited_per_address(client, monkeypatch):
    import verification
    email = unique("burst")
    ok(client.post("/api/auth/signup/start", json={"email": email}), 202)
    limited = client.post("/api/auth/signup/start", json={"email": email})
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0

    monkeypatch.setitem(verification.LIMITS, "code_destination_burst", (100, 60))
    for _ in range(4):
        ok(client.post("/api/auth/password-reset/start", json={"email": email}), 202)
    assert client.post("/api/auth/password-reset/start", json={"email": email}).status_code == 429


def test_code_requests_are_limited_per_ip(fresh_ip, monkeypatch):
    import verification
    monkeypatch.setitem(verification.LIMITS, "code_ip", (3, 3600))
    for _ in range(3):
        ok(fresh_ip.post("/api/auth/signup/start", json={"email": unique("ip")}), 202)
    assert fresh_ip.post("/api/auth/signup/start", json={"email": unique("ip")}).status_code == 429


def test_wrong_codes_are_limited_per_ip(fresh_ip, monkeypatch):
    import verification
    monkeypatch.setitem(verification.LIMITS, "verify_ip", (3, 900))
    email = unique("guess")
    ok(fresh_ip.post("/api/auth/signup/start", json={"email": email}), 202)
    code = latest_code(email)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(3):
        assert fresh_ip.post("/api/auth/signup/verify", json={"email": email, "code": wrong}).status_code == 400
    # Even the right code is refused while this address is limited.
    assert fresh_ip.post("/api/auth/signup/verify", json={"email": email, "code": code}).status_code == 429


def test_failed_sign_ins_are_limited_per_account(client):
    email = unique("lockout")
    register(client, email, "Lockout Test")
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 401
    limited = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_failed_sign_ins_are_limited_per_ip(fresh_ip, monkeypatch):
    import verification
    monkeypatch.setitem(verification.LIMITS, "login_ip", (3, 900))
    for _ in range(3):
        assert fresh_ip.post("/api/auth/login", json={"email": unique("spray"), "password": "wrong-password-123"}).status_code == 401
    assert fresh_ip.post("/api/auth/login", json={"email": unique("spray"), "password": "wrong-password-123"}).status_code == 429


# ---------------------------------------------------------------------------
# Existing accounts created before verification
# ---------------------------------------------------------------------------

def test_existing_account_verifies_on_next_sign_in_and_keeps_its_data(client):
    email = unique("legacy")
    account = register(client, email, "Legacy Traders")
    h = headers(account["token"], account["business_id"])
    ok(client.post("/api/products", headers=h, json={"name": "Legacy Saree", "price": 500, "stock": 4}), 201)
    staff_email = unique("legacy-staff")
    register(client, staff_email, "Staff Home")
    ok(client.post("/api/workspaces/members", headers=h, json={"email": staff_email, "role": "sales"}), 201)
    make_legacy(client, email)
    allow_new_code(client, email)

    # Sessions from before the change no longer grant access to an unverified account.
    assert client.get("/api/products", headers=h).status_code == 401
    # A wrong password reveals nothing and sends no code.
    before = len(fake_messages(email))
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 401
    assert len(fake_messages(email)) == before

    prompt = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert prompt.status_code == 403 and prompt.json()["detail"]["code"] == "verification_required"
    code = latest_code(email)
    assert code not in prompt.text
    # The code alone is not enough: the password is checked again.
    assert client.post("/api/auth/login/verify", json={
        "email": email, "password": "wrong-password-123", "code": code}).status_code == 401
    session = ok(client.post("/api/auth/login/verify", json={"email": email, "password": PASSWORD, "code": code}))
    assert (session["business_id"], session["role"]) == (account["business_id"], "owner")
    h = headers(session["token"], account["business_id"])
    assert "Legacy Saree" in client.get("/api/products", headers=h).text
    members = ok(client.get("/api/workspaces/members", headers=h))
    assert {m["email"] for m in members} == {email, staff_email}
    # Verified now: the next sign-in needs no code.
    ok(client.post("/api/auth/login", json={"email": email, "password": PASSWORD}))


def test_retrying_sign_in_soon_keeps_asking_for_the_code(client):
    email = unique("retry")
    register(client, email, "Retry Traders")
    make_legacy(client, email)
    allow_new_code(client, email)
    first = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert first.status_code == 403 and "most recent" not in first.json()["detail"]["message"]
    again = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert again.status_code == 403 and "most recent code" in again.json()["detail"]["message"]


# ---------------------------------------------------------------------------
# Password recovery
# ---------------------------------------------------------------------------

def test_password_reset_replaces_password_and_signs_out_other_sessions(client):
    email = unique("reset")
    account = register(client, email, "Reset Stores")
    old_session = headers(account["token"])
    allow_new_code(client, email)
    ok(client.post("/api/auth/password-reset/start", json={"email": email}), 202)
    code = latest_code(email)
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    assert client.post("/api/auth/password-reset/complete", json={
        "email": email, "code": wrong, "password": NEW_PASSWORD}).status_code == 400
    session = ok(client.post("/api/auth/password-reset/complete", json={
        "email": email, "code": code, "password": NEW_PASSWORD}))
    assert session["business_id"] == account["business_id"]
    assert client.get("/api/auth/me", headers=old_session).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    ok(client.post("/api/auth/login", json={"email": email, "password": NEW_PASSWORD}))
    assert client.post("/api/auth/password-reset/complete", json={
        "email": email, "code": code, "password": PASSWORD}).status_code == 400


def test_password_reset_does_not_reveal_unknown_accounts(client):
    email = unique("nobody")
    response = client.post("/api/auth/password-reset/start", json={"email": email})
    assert response.status_code == 202 and set(response.json()) == {"sent", "destination", "expires_in"}
    assert fake_messages(email) == []


def test_password_reset_verifies_an_existing_unverified_account(client):
    email = unique("legacy-reset")
    register(client, email, "Legacy Reset")
    make_legacy(client, email)
    allow_new_code(client, email)
    ok(client.post("/api/auth/password-reset/start", json={"email": email}), 202)
    ok(client.post("/api/auth/password-reset/complete", json={
        "email": email, "code": latest_code(email), "password": NEW_PASSWORD}))
    ok(client.post("/api/auth/login", json={"email": email, "password": NEW_PASSWORD}))


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

def invite(client, owner, email, role="sales"):
    return ok(client.post("/api/workspaces/invitations", headers=headers(owner["token"], owner["business_id"]),
                          json={"email": email, "role": role}), 201)


def test_verified_account_accepts_with_password_into_invited_workspace_only(client):
    owner = register(client, unique("inviter"), "Inviting Business")
    other = register(client, unique("other-owner"), "Other Business")
    email = unique("invitee")
    invitee = register(client, email, "Invitee Home")
    link = invite(client, owner, email, "website_editor")
    preview = ok(client.post("/api/auth/invitations/preview", json={"token": link["token"]}))
    assert (preview["existing_account"], preview["verification_required"]) == (True, False)
    joined = ok(client.post("/api/auth/invitations/accept", json={"token": link["token"], "password": PASSWORD}))
    assert (joined["business_id"], joined["role"], joined["website_ids"]) == (owner["business_id"], "website_editor", [])
    workspaces = ok(client.get("/api/workspaces", headers=headers(joined["token"])))
    assert {w["id"] for w in workspaces} == {owner["business_id"], invitee["business_id"]}
    assert other["business_id"] not in {w["id"] for w in workspaces}
    assert client.post("/api/auth/invitations/accept", json={"token": link["token"], "password": PASSWORD}).status_code == 404


def test_new_account_must_verify_the_invited_email(client):
    owner = register(client, unique("inviter"), "Inviting Business")
    email = unique("new-invitee")
    link = invite(client, owner, email)
    preview = ok(client.post("/api/auth/invitations/preview", json={"token": link["token"]}))
    assert (preview["existing_account"], preview["verification_required"]) == (False, True)
    assert client.post("/api/auth/invitations/accept", json={"token": link["token"], "password": PASSWORD}).status_code == 422

    # A code sent to a different address cannot be used.
    intruder = unique("intruder")
    ok(client.post("/api/auth/signup/start", json={"email": intruder}), 202)
    assert client.post("/api/auth/invitations/accept", json={
        "token": link["token"], "password": PASSWORD, "code": latest_code(intruder)}).status_code == 400
    assert not db_execute(client, "SELECT 1 FROM users WHERE email = ?", (email,))

    sent = ok(client.post("/api/auth/invitations/send-code", json={"token": link["token"]}), 202)
    assert latest_code(email) not in str(sent)
    joined = ok(client.post("/api/auth/invitations/accept", json={
        "token": link["token"], "password": PASSWORD, "code": latest_code(email)}))
    assert (joined["business_id"], joined["role"], joined["email"]) == (owner["business_id"], "sales", email)
    # The new account is verified and signs in normally afterwards.
    ok(client.post("/api/auth/login", json={"email": email, "password": PASSWORD}))


def test_unverified_existing_account_needs_password_and_code_to_accept(client):
    owner = register(client, unique("inviter"), "Inviting Business")
    email = unique("legacy-invitee")
    register(client, email, "Legacy Invitee")
    make_legacy(client, email)
    allow_new_code(client, email)
    link = invite(client, owner, email, "manager")
    assert ok(client.post("/api/auth/invitations/preview", json={"token": link["token"]}))["verification_required"] is True
    ok(client.post("/api/auth/invitations/send-code", json={"token": link["token"]}), 202)
    code = latest_code(email)
    assert client.post("/api/auth/invitations/accept", json={
        "token": link["token"], "password": "wrong-password-123", "code": code}).status_code == 401
    assert client.post("/api/auth/invitations/accept", json={
        "token": link["token"], "password": PASSWORD}).status_code == 422
    joined = ok(client.post("/api/auth/invitations/accept", json={"token": link["token"], "password": PASSWORD, "code": code}))
    assert (joined["business_id"], joined["role"]) == (owner["business_id"], "manager")
    ok(client.post("/api/auth/login", json={"email": email, "password": PASSWORD}))


# ---------------------------------------------------------------------------
# Delivery configuration
# ---------------------------------------------------------------------------

def test_code_requests_fail_clearly_without_an_email_provider(client, monkeypatch):
    monkeypatch.setenv("VYAPARI_EMAIL_PROVIDER", "")
    assert client.post("/api/auth/signup/start", json={"email": unique("noprovider")}).status_code == 503


def test_production_refuses_test_and_file_providers(monkeypatch, tmp_path):
    import notifications
    monkeypatch.setenv("VYAPARI_ENV", "production")
    for provider in ("fake", "dev_file", ""):
        monkeypatch.setenv("VYAPARI_EMAIL_PROVIDER", provider)
        with pytest.raises(RuntimeError):
            notifications.check_email_configuration()
    monkeypatch.setenv("VYAPARI_DEV_OUTBOX", str(tmp_path / "outbox.jsonl"))
    for provider in ("fake", "dev_file"):
        monkeypatch.setenv("VYAPARI_EMAIL_PROVIDER", provider)
        with pytest.raises(notifications.DeliveryError):
            notifications.send_email("someone@example.test", "Subject", "Body")


def test_smtp_provider_uses_tls_and_server_side_credentials(monkeypatch, caplog):
    import smtplib
    import notifications
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["server"] = (host, port)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def starttls(self, context):
            sent["tls"] = True
        def login(self, username, password):
            sent["login"] = (username, password)
        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("VYAPARI_EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("VYAPARI_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("VYAPARI_SMTP_USERNAME", "mailer")
    monkeypatch.setenv("VYAPARI_SMTP_PASSWORD", "server-side-secret")
    monkeypatch.setenv("VYAPARI_EMAIL_FROM", "Vyapari AI <no-reply@example.test>")
    notifications.check_email_configuration()
    notifications.send_email("owner@example.test", "Your code", "Your code is 123456")
    assert sent["server"] == ("smtp.example.test", 587) and sent["tls"] is True
    assert sent["login"] == ("mailer", "server-side-secret")
    assert sent["message"]["To"] == "owner@example.test"

    class FailingSMTP(FakeSMTP):
        def send_message(self, message):
            raise smtplib.SMTPDataError(550, b"rejected: Your code is 654321")

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(notifications.DeliveryError) as failure:
        notifications.send_email("owner@example.test", "Your code", "Your code is 654321")
    assert "654321" not in str(failure.value) and "654321" not in caplog.text


def test_forwarded_visitor_address_is_trusted_only_with_the_proxy_key(monkeypatch):
    from starlette.requests import Request
    import verification

    def request(headers):
        return Request({"type": "http", "client": ("10.0.0.5", 1234),
                        "headers": [(k.encode(), v.encode()) for k, v in headers.items()]})

    key = "k" * 40
    monkeypatch.setenv("VYAPARI_PROXY_KEY", key)
    forwarded = {"x-vyapari-proxy-key": key, "x-vyapari-client-ip": "198.51.100.7"}
    assert verification.client_ip(request(forwarded)) == "198.51.100.7"
    assert verification.client_ip(request({**forwarded, "x-vyapari-proxy-key": "w" * 40})) == "10.0.0.5"
    assert verification.client_ip(request({"x-vyapari-client-ip": "198.51.100.7"})) == "10.0.0.5"
    assert verification.client_ip(request({**forwarded, "x-vyapari-client-ip": "not-an-ip"})) == "10.0.0.5"
    monkeypatch.setenv("VYAPARI_PROXY_KEY", "short")
    assert verification.client_ip(request(forwarded)) == "10.0.0.5"
