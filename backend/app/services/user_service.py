from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, mailer
from app.core.auth import AuthenticatedUser
from app.core.config import settings
from app.core.logging import get_logger
from app.database.base import utcnow
from app.models.entities import AppUser
from app.models.enums import AccessStatus

logger = get_logger(__name__)


def is_admin(email: str) -> bool:
    return bool(email) and email.lower() in settings.auth_admin_emails


async def status_of(session: AsyncSession, user: AuthenticatedUser) -> AppUser | None:
    """This account as it stands, read and not written.

    The admission gate runs on every request, and `resolve` writes — a
    last-seen stamp and a flush per API call is a write for every read the
    platform serves. This asks the question the gate actually has, which is
    what the status is right now.
    """
    if user.is_anonymous or not user.id:
        return None
    return await session.scalar(select(AppUser).where(AppUser.subject == user.id))


async def resolve(session: AsyncSession, user: AuthenticatedUser) -> AppUser | None:
    """The row for this identity, created the first time it is seen.

    Returns None when nobody is signed in, so callers stamp a null owner
    rather than inventing a user to own the work.
    """
    if user.is_anonymous or not user.id:
        return None

    row = await session.scalar(select(AppUser).where(AppUser.subject == user.id))
    created = row is None

    if row is None:
        row = AppUser(subject=user.id, email=user.email, status=_initial_status(user.email))
        session.add(row)

    # Refreshed every time: a display name or avatar changed at Google should
    # follow the person here rather than freeze at whatever it was the day
    # they first signed in.
    row.email = user.email or row.email
    row.name = user.name or row.name
    row.picture_url = user.picture or row.picture_url
    row.last_seen_at = utcnow()

    # An administrator added to the list after they first signed in is let
    # through on their next visit, rather than having to approve themselves.
    if row.status is AccessStatus.PENDING and is_admin(row.email):
        row.status = AccessStatus.APPROVED
        row.decided_at = utcnow()
        row.decided_by = "administrator list"

    await session.flush()

    if created and row.status is AccessStatus.PENDING:
        await request_approval(session, row)

    return row


def _initial_status(email: str) -> AccessStatus:
    if not settings.auth_require_approval or is_admin(email):
        return AccessStatus.APPROVED
    return AccessStatus.PENDING


async def request_approval(session: AsyncSession, row: AppUser) -> bool:
    """Ask an administrator to let this person in.

    Best effort by design. If the mail cannot be sent the account still exists
    and still shows up in the pending list, so a failure here delays access
    rather than losing the request.
    """
    admins = list(settings.auth_admin_emails)
    if not admins:
        logger.warning(
            "%s is waiting for approval but no AUTH_ADMIN_EMAILS is set, so nobody was told.",
            row.email,
        )
        return False

    row.requested_at = utcnow()
    await session.flush()

    who = f"{row.name} <{row.email}>" if row.name else row.email
    approve = approvals.link(row.id, approvals.APPROVE)
    reject = approvals.link(row.id, approvals.REJECT)

    sent = await mailer.send(
        admins,
        subject=f"Access request: {row.email}",
        text=(
            f"{who} signed in and is waiting for access.\n\n"
            f"Approve: {approve}\n"
            f"Reject:  {reject}\n\n"
            "These links work once each and expire in "
            f"{settings.auth_approval_link_ttl_hours} hours."
        ),
        html=(
            f"<p><strong>{who}</strong> signed in and is waiting for access.</p>"
            f'<p><a href="{approve}">Approve</a> &nbsp;|&nbsp; '
            f'<a href="{reject}">Reject</a></p>'
            f'<p style="color:#666;font-size:12px">These links expire in '
            f"{settings.auth_approval_link_ttl_hours} hours.</p>"
        ),
    )
    if not sent:
        logger.warning("Access request for %s could not be emailed.", row.email)
    return sent


async def decide(session: AsyncSession, token: str) -> tuple[AppUser, str]:
    decision = approvals.verify(token)
    row = await session.get(AppUser, decision.user_id)
    if row is None:
        raise approvals.InvalidApprovalLink("This link is for an account that no longer exists.")

    row.status = (
        AccessStatus.APPROVED if decision.action == approvals.APPROVE else AccessStatus.REJECTED
    )
    row.decided_at = utcnow()
    row.decided_by = row.decided_by or "approval link"
    await session.flush()
    return row, decision.action


async def pending(session: AsyncSession) -> list[AppUser]:
    result = await session.execute(
        select(AppUser)
        .where(AppUser.status == AccessStatus.PENDING)
        .order_by(AppUser.created_at.desc())
    )
    return list(result.scalars().all())


async def owner_id(session: AsyncSession, user: AuthenticatedUser) -> uuid.UUID | None:
    row = await resolve(session, user)
    return row.id if row is not None else None
