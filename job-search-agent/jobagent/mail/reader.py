"""IMAP read of Gmail for job-alert parsing (backup intake channel)."""

from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header

from ..config import get_secret
from ..logging_setup import get_logger

log = get_logger("jobagent.mail.reader")


@dataclass
class RawEmail:
    uid: str
    subject: str
    sender: str
    html: str
    text: str


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for content, enc in parts:
        if isinstance(content, bytes):
            out.append(content.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(content)
    return "".join(out)


class MailReader:
    def __init__(self, address: str | None = None, app_password: str | None = None,
                 host: str | None = None, port: int | None = None):
        self.address = address or get_secret("GMAIL_ADDRESS")
        self.app_password = (app_password or get_secret("GMAIL_APP_PASSWORD") or "").replace(" ", "")
        self.host = host or get_secret("IMAP_HOST") or "imap.gmail.com"
        self.port = int(port or get_secret("IMAP_PORT") or 993)

    @property
    def configured(self) -> bool:
        return bool(self.address and self.app_password)

    def fetch_alerts(self, folder: str = "JobAlerts", limit: int = 40,
                     only_unread: bool = False) -> list[RawEmail]:
        """Read a Gmail label/folder the user configured for LinkedIn/Naukri alerts."""
        if not self.configured:
            log.error("mail not configured; cannot read alerts")
            return []
        out: list[RawEmail] = []
        try:
            # NOTE: imaplib blocks forever without an explicit timeout.
            with imaplib.IMAP4_SSL(self.host, self.port, timeout=30) as imap:
                imap.login(self.address, self.app_password)
                status, _ = imap.select(folder, readonly=True)
                if status != "OK":
                    log.error("cannot select folder %s", folder)
                    return []
                criteria = "(UNSEEN)" if only_unread else "ALL"
                status, data = imap.search(None, criteria)
                if status != "OK":
                    return []
                uids = data[0].split()[-limit:]
                for uid in uids:
                    status, msg_data = imap.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    html, text = self._body(msg)
                    out.append(RawEmail(
                        uid=uid.decode(),
                        subject=_decode(msg.get("Subject")),
                        sender=_decode(msg.get("From")),
                        html=html, text=text,
                    ))
        except Exception as e:  # noqa: BLE001
            log.error("imap error: %s", e)
            return []
        return out

    @staticmethod
    def _body(msg) -> tuple[str, str]:
        html, text = "", ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/html" and not html:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                elif ctype == "text/plain" and not text:
                    text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
        return html, text