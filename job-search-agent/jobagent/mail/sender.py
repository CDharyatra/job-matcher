"""SMTP send via Gmail app password. Plain, mobile-friendly, no fake language."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from ..config import get_secret
from ..logging_setup import get_logger

log = get_logger("jobagent.mail.sender")


class Mailer:
    def __init__(self, address: str | None = None, app_password: str | None = None,
                 smtp_host: str = "smtp.gmail.com", smtp_port: int = 587):
        self.address = address or get_secret("GMAIL_ADDRESS")
        # App passwords are shown as "xxxx xxxx xxxx xxxx"; SMTP needs no spaces.
        self.app_password = (app_password or get_secret("GMAIL_APP_PASSWORD") or "").replace(" ", "")
        self.smtp_host = get_secret("SMTP_HOST") or smtp_host
        self.smtp_port = int(get_secret("SMTP_PORT") or smtp_port)

    @property
    def configured(self) -> bool:
        return bool(self.address and self.app_password)

    def send(self, subject: str, body_html: str, body_text: str = "") -> bool:
        if not self.configured:
            log.error("mail not configured; skipping send")
            return False
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = self.address          # to the user, from the user
        msg["Subject"] = subject
        msg.set_content(body_text or _strip_html(body_html))
        msg.add_alternative(body_html, subtype="html")
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls(context=ctx)
                server.login(self.address, self.app_password)
                server.send_message(msg)
            log.info("sent mail: %s", subject)
            return True
        except Exception as e:  # noqa: BLE001
            log.error("send failed: %s", e)
            return False


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()