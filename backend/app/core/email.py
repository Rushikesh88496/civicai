"""Email provider abstraction (Part 21).

Notification email delivery is pluggable and **never hardcodes credentials**.
Two providers ship out of the box:

* ``ConsoleEmailProvider`` — the default. Nothing is ever sent; the would-be
  email is logged so flows work with zero configuration (and are testable).
* ``SmtpEmailProvider`` — real delivery via the Python standard library
  (``smtplib``) over STARTTLS, configured entirely from environment variables
  (``EMAIL_PROVIDER=smtp`` + the ``SMTP_*`` values). Sending runs in a worker
  thread so it never blocks the event loop.

``get_email_provider`` is constructed from settings: when SMTP is requested but
the SMTP host is not configured, it degrades to the console provider and logs a
warning — the app must never fail because email credentials are missing.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

PROVIDER_CONSOLE = "console"
PROVIDER_SMTP = "smtp"


class EmailProvider(Protocol):
    """Gateway for sending notification emails."""

    backend_name: str

    async def send(
        self,
        *,
        to_email: str,
        to_name: str | None = None,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        """Deliver an email. Implementations must never raise on transport
        failures — they log and swallow so notification creation never breaks."""


class ConsoleEmailProvider:
    """Log-only provider used by default (no SMTP server configured)."""

    backend_name = "console"

    async def send(
        self,
        *,
        to_email: str,
        to_name: str | None = None,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        recipient = f"{to_name} <{to_email}>" if to_name else to_email
        logger.info("[email:console] to=%s subject=%r body=%r", recipient, subject, body_text[:200])


class SmtpEmailProvider:
    """SMTP delivery via stdlib ``smtplib`` (credentials from env only)."""

    backend_name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._host = settings.SMTP_HOST
        self._port = settings.SMTP_PORT
        self._user = settings.SMTP_USER or None
        self._password = settings.SMTP_PASSWORD or None
        self._tls = settings.SMTP_TLS
        self._from_addr = settings.EMAIL_FROM
        self._timeout = settings.SMTP_TIMEOUT_SECONDS

    async def send(
        self,
        *,
        to_email: str,
        to_name: str | None = None,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        recipient = f"{to_name} <{to_email}>" if to_name else to_email
        try:
            await asyncio.to_thread(
                self._send_blocking,
                to_email,
                subject,
                body_text,
                body_html,
            )
        except Exception as exc:  # noqa: BLE001 - transport failures must not break the flow
            logger.error("SMTP delivery to %s failed: %s", recipient, exc)

    def _send_blocking(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> None:
        message = EmailMessage()
        message["From"] = self._from_addr
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")

        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
            if self._tls:
                client.starttls()
            if self._user:
                client.login(self._user, self._password)
            client.send_message(message)


@lru_cache
def get_email_provider() -> EmailProvider:
    """Return the configured email provider (degrades to console safely)."""
    settings = get_settings()
    if settings.EMAIL_PROVIDER.lower() == PROVIDER_SMTP:
        if not settings.SMTP_HOST:
            logger.warning(
                "EMAIL_PROVIDER=smtp but SMTP_HOST is unset — falling back to console "
                "delivery. Configure SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD to enable."
            )
            return ConsoleEmailProvider()
        return SmtpEmailProvider(settings)
    return ConsoleEmailProvider()


__all__ = [
    "ConsoleEmailProvider",
    "EmailProvider",
    "PROVIDER_CONSOLE",
    "PROVIDER_SMTP",
    "SmtpEmailProvider",
    "get_email_provider",
]
