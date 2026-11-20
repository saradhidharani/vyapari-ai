"""Outbound email for verification codes.

The provider is chosen with VYAPARI_EMAIL_PROVIDER:
- "smtp": real delivery. Needs VYAPARI_SMTP_HOST, VYAPARI_SMTP_PORT (default 587),
  VYAPARI_SMTP_USERNAME, VYAPARI_SMTP_PASSWORD, VYAPARI_EMAIL_FROM, and optionally
  VYAPARI_SMTP_SECURITY ("starttls", the default, or "ssl").
- "fake": keeps messages in memory for automated tests. Never use in production.
- "dev_file": appends messages to VYAPARI_DEV_OUTBOX for local manual testing.
  Refused when VYAPARI_ENV=production.
Unset means email is not configured and code requests fail with 503.

Credentials stay in environment variables on the server. Message bodies, which
contain one-time codes, are never logged."""
import json
import logging
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from pathlib import Path


logger = logging.getLogger("vyapari.notifications")


class DeliveryError(Exception):
    """Delivery failed. The message deliberately excludes the email body."""


def production():
    return os.getenv("VYAPARI_ENV", "").strip().lower() == "production"


class FakeEmail:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def send(self, to, subject, body):
        with self.lock:
            self.messages.append({"to": to, "subject": subject, "body": body})

    def clear(self):
        with self.lock:
            self.messages.clear()


FAKE_EMAIL = FakeEmail()


def _smtp_send(to, subject, body):
    host = os.getenv("VYAPARI_SMTP_HOST")
    sender = os.getenv("VYAPARI_EMAIL_FROM")
    if not host or not sender:
        raise DeliveryError("SMTP is not fully configured")
    port = int(os.getenv("VYAPARI_SMTP_PORT", "587"))
    security = os.getenv("VYAPARI_SMTP_SECURITY", "starttls").strip().lower()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            if security != "ssl":
                server.starttls(context=context)
            username = os.getenv("VYAPARI_SMTP_USERNAME")
            if username:
                server.login(username, os.getenv("VYAPARI_SMTP_PASSWORD", ""))
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        # Log the failure type only: never the recipient's code or the server reply body.
        logger.warning("SMTP delivery failed: %s", type(error).__name__)
        raise DeliveryError("Email delivery failed") from None


def _dev_file_send(to, subject, body):
    if production():
        raise DeliveryError("The dev_file email provider is disabled in production")
    path = os.getenv("VYAPARI_DEV_OUTBOX")
    if not path:
        raise DeliveryError("Set VYAPARI_DEV_OUTBOX to use the dev_file email provider")
    record = {"to": to, "subject": subject, "body": body, "sent_at": int(time.time())}
    with Path(path).open("a", encoding="utf-8") as outbox:
        outbox.write(json.dumps(record, ensure_ascii=False) + "\n")


def email_provider():
    return os.getenv("VYAPARI_EMAIL_PROVIDER", "").strip().lower()


def check_email_configuration():
    """Fail fast at startup when production would be unable to send codes."""
    provider = email_provider()
    if production() and provider != "smtp":
        raise RuntimeError("Production requires VYAPARI_EMAIL_PROVIDER=smtp")
    if provider == "smtp" and not (os.getenv("VYAPARI_SMTP_HOST") and os.getenv("VYAPARI_EMAIL_FROM")):
        raise RuntimeError("VYAPARI_EMAIL_PROVIDER=smtp needs VYAPARI_SMTP_HOST and VYAPARI_EMAIL_FROM")
    if provider not in ("", "smtp", "fake", "dev_file"):
        raise RuntimeError(f"Unknown VYAPARI_EMAIL_PROVIDER: {provider}")


def send_email(to, subject, body):
    provider = email_provider()
    if provider == "smtp":
        _smtp_send(to, subject, body)
    elif provider == "fake":
        if production():
            raise DeliveryError("The fake email provider is disabled in production")
        FAKE_EMAIL.send(to, subject, body)
    elif provider == "dev_file":
        _dev_file_send(to, subject, body)
    else:
        raise DeliveryError("Email delivery is not configured")
