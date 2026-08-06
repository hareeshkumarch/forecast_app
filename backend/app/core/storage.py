from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)


async def file_exists(path: str | Path | None) -> bool:
    if not path:
        return False
    return await asyncio.to_thread(Path(path).exists)


async def remove_file(path: str | Path | None) -> bool:
    """
    Deletes a file the database no longer has a name for.

    Reports rather than raises. This is called after the row it belonged to has
    gone, so there is nothing left to retry against and nothing the caller can
    usefully do — a file left behind is disk to reclaim later, while a failed
    request would tell someone their delete did not happen when it did.
    """
    if not path:
        return False

    def unlink() -> bool:
        try:
            Path(path).unlink(missing_ok=True)
            return True
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
            return False

    return await asyncio.to_thread(unlink)
