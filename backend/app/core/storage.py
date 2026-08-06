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
