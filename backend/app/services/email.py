"""SES email service wrapping aioboto3.

One instance per process (constructed from settings at startup). All methods
are async. Uses `endpoint_url` override for LocalStack in dev.

Renders HTML + plain-text bodies from Jinja2 templates in app/templates/.
"""

import logging
from pathlib import Path
from typing import Any

import aioboto3
import jinja2

from app.config import Settings, get_settings

_log = logging.getLogger(__name__)
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class EmailService:
    def __init__(
        self,
        *,
        region: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        sender: str,
    ) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._endpoint_url = endpoint_url
        self._sender = sender
        self._jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            enable_async=False,
        )

    def _client(self):  # type: ignore[no-untyped-def]
        return self._session.client("ses", endpoint_url=self._endpoint_url)

    @property
    def sender(self) -> str:
        return self._sender

    async def verify_sender_identity(self) -> None:
        """Dev/LocalStack: verify the sender email so send_email works."""
        async with self._client() as ses:  # type: ignore[no-untyped-call]
            await ses.verify_email_identity(EmailAddress=self._sender)

    async def send(
        self,
        *,
        to: str,
        template: str,
        context: dict[str, Any],
        subject: str,
    ) -> str:
        """Send an email using the given template name. Returns the SES MessageId.

        Renders `<template>.html` and `<template>.txt` from app/templates/.
        """
        html_body = self._jinja.get_template(f"{template}.html").render(**context)
        text_body = self._jinja.get_template(f"{template}.txt").render(**context)

        async with self._client() as ses:  # type: ignore[no-untyped-call]
            resp = await ses.send_email(
                Source=self._sender,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                    },
                },
            )
        return resp["MessageId"]  # type: ignore[no-any-return]


# Module-level singleton pattern (same as storage/queue)
_email_service: EmailService | None = None


def get_email_service(settings: Settings | None = None) -> EmailService:
    global _email_service
    if _email_service is None:
        s = settings or get_settings()
        _email_service = EmailService(
            region=s.aws_region,
            endpoint_url=s.aws_ses_endpoint_url,
            access_key=s.aws_access_key_id,
            secret_key=s.aws_secret_access_key,
            sender=s.ses_sender,
        )
    return _email_service


def reset_email_service() -> None:
    """Reset the singleton (for tests)."""
    global _email_service
    _email_service = None
