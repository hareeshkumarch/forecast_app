from __future__ import annotations

import asyncio
import contextlib

from app.core.config import settings
from app.core.logging import get_logger
from app.core.mailer import flush_outbox
from app.database.session import session_scope

logger = get_logger(__name__)

INTERVAL_SECONDS = 5.0

STARTUP_DELAY_SECONDS = 3.0


class MailSender:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="mail-sender")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(STARTUP_DELAY_SECONDS)
        while True:
            try:
                async with session_scope() as session:
                    sent, failed = await flush_outbox(session)
                if sent or failed:
                    logger.info("Outbox: %d sent, %d given up on.", sent, failed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("The outbox pass failed; carrying on.")
            await asyncio.sleep(INTERVAL_SECONDS)


sender = MailSender()


def configured() -> bool:
    return settings.smtp_configured
