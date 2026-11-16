"""Transactional email: a Protocol, a logging null object, and Resend."""

import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class NullMailer:
    async def send(self, to: str, subject: str, body: str) -> None:
        log.info("email disabled; would send %r to %s", subject, to)


class ResendMailer:
    def __init__(
        self,
        api_key: str,
        from_addr: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._from = from_addr
        self._transport = transport

    async def send(self, to: str, subject: str, body: str) -> None:
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"from": self._from, "to": [to], "subject": subject, "text": body},
            )
            resp.raise_for_status()
