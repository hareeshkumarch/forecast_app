from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser
from app.database.base import utcnow
from app.models.entities import AppUser


async def resolve(session: AsyncSession, user: AuthenticatedUser) -> AppUser | None:
    """The row for this identity, created the first time it is seen.

    Returns None when nobody is signed in, so callers stamp a null owner rather
    than inventing a user to own the work.
    """
    if user.is_anonymous or not user.id:
        return None

    row = await session.scalar(select(AppUser).where(AppUser.subject == user.id))
    if row is None:
        row = AppUser(subject=user.id, email=user.email)
        session.add(row)

    # Refreshed every time: a display name or avatar changed at Google should
    # follow the person here rather than freeze at whatever it was on the day
    # they first signed in.
    row.email = user.email or row.email
    row.name = user.name or row.name
    row.picture_url = user.picture or row.picture_url
    row.last_seen_at = utcnow()

    await session.flush()
    return row


async def owner_id(session: AsyncSession, user: AuthenticatedUser) -> uuid.UUID | None:
    row = await resolve(session, user)
    return row.id if row is not None else None
