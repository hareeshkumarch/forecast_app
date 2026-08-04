from __future__ import annotations

import asyncio
from pathlib import Path


async def file_exists(path: str | Path | None) -> bool:
    if not path:
        return False
    return await asyncio.to_thread(Path(path).exists)
