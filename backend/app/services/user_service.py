from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, broadcast, email_templates, mailer
from app.core.auth import AuthenticatedUser
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.database.base import utcnow
from app.models.entities import AccessAudit, AppUser
from app.models.enums import AccessRole, AccessStatus

logger = get_logger(__name__)


def is_configured_admin(email: str) -> bool:
    """Named in AUTH_ADMIN_EMAILS.

    The floor under the role column: whatever the database says, these
    accounts are administrators. It is what makes it impossible to end up with
    a deployment nobody can administer — demote everyone in the UI and the
    configured account still gets in on its next sign-in.
    """
    return bool(email) and email.lower() in settings.auth_admin_emails


def is_admin(email: str, role: AccessRole | None = None) -> bool:
    return role is AccessRole.ADMIN or is_configured_admin(email)


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

    # No row for this subject, but there may be an invitation waiting under the
    # address. Claiming it here is what makes an invited person walk straight
    # in rather than joining the queue they were invited to skip.
    invited = False
    if row is None and user.email:
        row = await session.scalar(
            select(AppUser).where(AppUser.email == user.email, AppUser.subject.is_(None))
        )
        if row is not None:
            row.subject = user.id
            invited = True

    created = row is None

    if row is None:
        row = AppUser(
            subject=user.id,
            email=user.email,
            status=_initial_status(user.email),
            role=AccessRole.ADMIN if is_configured_admin(user.email) else AccessRole.MEMBER,
        )
        session.add(row)

    # Refreshed every time: a display name or avatar changed at Google should
    # follow the person here rather than freeze at whatever it was the day
    # they first signed in.
    row.email = user.email or row.email
    row.name = user.name or row.name
    row.picture_url = user.picture or row.picture_url
    row.last_seen_at = utcnow()

    # An account added to the configured list after it first signed in is let
    # through on its next visit, rather than having to approve itself.
    if is_configured_admin(row.email):
        row.role = AccessRole.ADMIN
        if row.status is not AccessStatus.APPROVED:
            row.status = AccessStatus.APPROVED
            row.decided_at = utcnow()
            row.decided_by = "administrator list"
            _record(session, APPROVED, row, detail="named in AUTH_ADMIN_EMAILS")

    await session.flush()

    if created and row.status is AccessStatus.PENDING:
        _record(session, REQUESTED, row)
        await request_approval(session, row)
        _announce(row)
    elif invited:
        logger.info("%s claimed the invitation waiting for that address.", row.email)

    return row


def _app_url() -> str:
    return settings.public_api_base_url.rstrip("/") + "/dashboard"


def _as_mail(message: email_templates.Message) -> dict[str, str]:
    return {"subject": message.subject, "text": message.text, "html": message.html}


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

    mailer.queue(
        session,
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
    return True


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


async def everyone(session: AsyncSession) -> list[AppUser]:
    """All accounts, most recently seen first.

    Pending ones lead, because the list exists to be acted on rather than
    browsed — somebody waiting is the only row that needs a decision.
    """
    result = await session.execute(
        select(AppUser).order_by(
            (AppUser.status != AccessStatus.PENDING),
            AppUser.created_at.desc(),
        )
    )
    return list(result.scalars().all())


class LastAdminError(AppError):
    status_code = 409
    code = "last_administrator"


async def set_status(
    session: AsyncSession, target: AppUser, status: AccessStatus, *, decided_by: str
) -> AppUser:
    if status is not AccessStatus.APPROVED and is_configured_admin(target.email):
        raise LastAdminError(
            f"{target.email} is named in this deployment's administrator list and cannot be "
            "refused from here. Remove them from AUTH_ADMIN_EMAILS first."
        )

    was = target.status
    target.status = status
    target.decided_at = utcnow()
    target.decided_by = decided_by
    await session.flush()

    # Only on a change. Re-approving somebody already approved should not send
    # them a second "you're in".
    if status is not was:
        if status is AccessStatus.APPROVED:
            action = RESTORED if was is AccessStatus.REJECTED else APPROVED
        else:
            action = REVOKED if was is AccessStatus.APPROVED else REJECTED
        _record(session, action, target, actor=decided_by, detail=f"from {was.value}")
        await _tell_decision(session, target, status, was)
        _announce(target)
    return target


REQUESTED = "requested"
APPROVED = "approved"
REJECTED = "rejected"
REVOKED = "revoked"
RESTORED = "restored"
PROMOTED = "promoted"
DEMOTED = "demoted"
INVITED = "invited"
REMOVED = "removed"


def _record(
    session: AsyncSession,
    action: str,
    row: AppUser,
    *,
    actor: str | None = None,
    detail: str | None = None,
) -> None:
    """Append, in the transaction that did the thing.

    Written here rather than in the route so it cannot be skipped by a caller
    that went straight to the service — the emailed approve/reject link does
    exactly that, and it is the path least likely to be watched.
    """
    session.add(
        AccessAudit(
            action=action,
            subject_email=row.email,
            subject_id=row.id,
            actor_email=actor,
            detail=detail,
        )
    )


async def history(session: AsyncSession, limit: int = 200) -> list[AccessAudit]:
    result = await session.execute(
        select(AccessAudit).order_by(AccessAudit.at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def _announce(row: AppUser) -> None:
    """Tell the person it happened to, and the list the administrators watch.

    Only a topic name goes out. Everything the screens then show is refetched
    through the endpoints that check permission, so this cannot become a way
    to learn something about an account you could not already ask about.
    """
    _announce_id(row.id)


def _announce_id(user_id: object) -> None:
    broadcast.publish(broadcast.topic_for_user(user_id), broadcast.ACCESS)
    broadcast.publish(broadcast.PEOPLE, broadcast.PEOPLE)


async def _tell_decision(
    session: AsyncSession, row: AppUser, status: AccessStatus, was: AccessStatus
) -> None:
    """Four outcomes, not two.

    Losing access you were using is a different event from being turned away
    at the door, and being let back in is different from being let in for the
    first time. Sending the door message to somebody mid-way through their
    work reads as a bug and sends them looking for one.
    """
    if status is AccessStatus.APPROVED:
        message = (
            email_templates.access_restored(_app_url())
            if was is AccessStatus.REJECTED
            else email_templates.access_approved(_app_url())
        )
    else:
        message = (
            email_templates.access_revoked()
            if was is AccessStatus.APPROVED
            else email_templates.access_refused()
        )
    mailer.queue(session, [row.email], **_as_mail(message))


async def invite(session: AsyncSession, email: str, *, invited_by: str) -> AppUser:
    """Give somebody access before they have ever signed in.

    The row is created approved and without a subject; whoever next signs in
    with that address claims it. That is the whole mechanism, and it is why
    the address has to be one only they can receive mail at.
    """
    address = email.strip().lower()
    existing = await session.scalar(select(AppUser).where(AppUser.email == address))

    if existing is not None:
        # Already known. Re-inviting is how somebody refused by mistake is let
        # back in, so it approves rather than refusing to act.
        existing.status = AccessStatus.APPROVED
        existing.decided_at = utcnow()
        existing.decided_by = invited_by
        existing.invited_at = utcnow()
        existing.invited_by = invited_by
        await session.flush()
        _record(session, INVITED, existing, actor=invited_by, detail="re-invited")
        mailer.queue(
            session, [address], **_as_mail(email_templates.invitation(invited_by, _app_url()))
        )
        _announce(existing)
        return existing

    row = AppUser(
        subject=None,
        email=address,
        status=AccessStatus.APPROVED,
        role=AccessRole.MEMBER,
        decided_at=utcnow(),
        decided_by=invited_by,
        invited_at=utcnow(),
        invited_by=invited_by,
    )
    session.add(row)
    await session.flush()

    _record(session, INVITED, row, actor=invited_by)
    mailer.queue(
        session, [address], **_as_mail(email_templates.invitation(invited_by, _app_url()))
    )
    _announce(row)
    return row


async def set_role(
    session: AsyncSession, target: AppUser, role: AccessRole, *, decided_by: str
) -> AppUser:
    if role is not AccessRole.ADMIN and is_configured_admin(target.email):
        raise LastAdminError(
            f"{target.email} is named in this deployment's administrator list, so removing the "
            "role here would not take effect. Remove them from AUTH_ADMIN_EMAILS instead."
        )

    if role is not AccessRole.ADMIN and await _admin_count(session) <= 1:
        raise LastAdminError(
            "This is the only administrator left. Promote somebody else before stepping down, "
            "or nobody will be able to approve anyone again."
        )

    was = target.role
    target.role = role
    # Promoting somebody who is still waiting approves them: an administrator
    # who cannot get in is not one.
    if role is AccessRole.ADMIN and target.status is not AccessStatus.APPROVED:
        target.status = AccessStatus.APPROVED
        target.decided_at = utcnow()
    target.decided_by = decided_by
    await session.flush()

    if role is not was:
        _record(
            session,
            PROMOTED if role is AccessRole.ADMIN else DEMOTED,
            target,
            actor=decided_by,
            detail=f"{was.value} -> {role.value}",
        )
        # Only the promotion. Being told you have gained powers you did not
        # know about is worth an email; being told you have lost some is an
        # indignity with nothing attached for the reader to do, and the app
        # shows it either way the moment it happens.
        if role is AccessRole.ADMIN:
            mailer.queue(session, [target.email], **_as_mail(email_templates.promoted(_app_url())))
        _announce(target)
    return target


async def remove(session: AsyncSession, target: AppUser, *, removed_by: str | None = None) -> None:
    """Forget an account entirely.

    Distinct from refusing one. Refusing is a decision that is kept — the row
    stays, the reason stays, and a second sign-in is turned away. Removing is
    for rows that should not be in the list at all: an invitation sent to the
    wrong address, a duplicate, somebody who never arrived. If they sign in
    again afterwards they are a new request, not a refused one.
    """
    if is_configured_admin(target.email):
        raise LastAdminError(
            f"{target.email} is named in this deployment's administrator list. Remove them from "
            "AUTH_ADMIN_EMAILS first, or they will simply return on their next sign-in."
        )

    if target.role is AccessRole.ADMIN and await _admin_count(session) <= 1:
        raise LastAdminError(
            "This is the only administrator left. Promote somebody else first, or nobody will "
            "be able to approve anyone again."
        )

    # Somebody who was actually using this deployment should hear that it
    # stopped, exactly as they would on a refusal. An invitation sent to the
    # wrong address is the case this skips: that row has no subject because
    # nobody ever signed in with it, and mailing it would be the original
    # mistake repeated.
    tell = target.subject is not None and target.status is AccessStatus.APPROVED
    email = target.email
    identifier = target.id

    # Recorded before the delete, and the record outlives it: an audit trail
    # that disappears with its subject cannot answer the question it is for.
    _record(session, REMOVED, target, actor=removed_by, detail=f"was {target.status.value}")

    await session.delete(target)
    await session.flush()

    if tell:
        mailer.queue(session, [email], **_as_mail(email_templates.access_revoked()))
    _announce_id(identifier)


async def _admin_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.role == AccessRole.ADMIN, AppUser.status == AccessStatus.APPROVED)
        )
        or 0
    )
