"""Outbound email for verification codes.

The provider is chosen with VYAPARI_EMAIL_PROVIDER:
- "smtp": real delivery. Needs VYAPARI_SMTP_HOST, VYAPARI_SMTP_PORT (default 587),
  VYAPARI_SMTP_USERNAME, VYAPARI_SMTP_PASSWORD, VYAPARI_EMAIL_FROM, and optionally
  VYAPARI_SMTP_SECURITY ("starttls", the default, or "ssl").
- "brevo": real delivery through Brevo's HTTPS email API, for hosts that block
  outbound SMTP (such as Railway's Trial and Hobby plans). Needs
  VYAPARI_BREVO_API_KEY and VYAPARI_EMAIL_FROM, where the From address is a sender
  verified in Brevo.
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
from email.utils import parseaddr
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


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


def _brevo_send(to, subject, body):
    api_key = os.getenv("VYAPARI_BREVO_API_KEY", "")
    name, address = parseaddr(os.getenv("VYAPARI_EMAIL_FROM", ""))
    if not api_key or "@" not in address:
        raise DeliveryError("Brevo is not fully configured")
    sender = {"email": address, **({"name": name} if name else {})}
    payload = json.dumps({
        "sender": sender, "to": [{"email": to}], "subject": subject, "textContent": body,
    }).encode("utf-8")
    request = Request(BREVO_SEND_URL, data=payload, method="POST", headers={
        "accept": "application/json", "content-type": "application/json", "api-key": api_key,
    })
    try:
        with urlopen(request, timeout=20) as response:
            response.read()
    except HTTPError as error:
        # Log the status only. The response body can echo the request, which holds the code.
        logger.warning("Brevo delivery failed: HTTP %s", error.code)
        raise DeliveryError("Email delivery failed") from None
    except (URLError, OSError) as error:
        logger.warning("Brevo delivery failed: %s", type(error).__name__)
        raise DeliveryError("Email delivery failed") from None


def email_provider():
    return os.getenv("VYAPARI_EMAIL_PROVIDER", "").strip().lower()


REAL_PROVIDERS = ("smtp", "brevo")


def check_email_configuration():
    """Fail fast at startup when production would be unable to send codes."""
    provider = email_provider()
    if production() and provider not in REAL_PROVIDERS:
        raise RuntimeError("Production requires VYAPARI_EMAIL_PROVIDER=smtp or brevo")
    if provider == "smtp" and not (os.getenv("VYAPARI_SMTP_HOST") and os.getenv("VYAPARI_EMAIL_FROM")):
        raise RuntimeError("VYAPARI_EMAIL_PROVIDER=smtp needs VYAPARI_SMTP_HOST and VYAPARI_EMAIL_FROM")
    if provider == "brevo" and not (os.getenv("VYAPARI_BREVO_API_KEY") and "@" in os.getenv("VYAPARI_EMAIL_FROM", "")):
        raise RuntimeError("VYAPARI_EMAIL_PROVIDER=brevo needs VYAPARI_BREVO_API_KEY and VYAPARI_EMAIL_FROM")
    if provider not in ("", "fake", "dev_file", *REAL_PROVIDERS):
        raise RuntimeError(f"Unknown VYAPARI_EMAIL_PROVIDER: {provider}")


def send_email(to, subject, body):
    provider = email_provider()
    if provider == "smtp":
        _smtp_send(to, subject, body)
    elif provider == "brevo":
        _brevo_send(to, subject, body)
    elif provider == "fake":
        if production():
            raise DeliveryError("The fake email provider is disabled in production")
        FAKE_EMAIL.send(to, subject, body)
    elif provider == "dev_file":
        _dev_file_send(to, subject, body)
    else:
        raise DeliveryError("Email delivery is not configured")
