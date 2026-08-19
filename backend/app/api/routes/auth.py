from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, SessionDep
from app.core import approvals, broadcast
from app.core.auth import AuthenticatedUser, ForbiddenError
from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.database.session import session_scope
from app.models.entities import AppUser
from app.models.enums import AccessRole, AccessStatus
from app.schemas.common import StrictModel
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])

#: Mounted without the session guard, because the one endpoint on it is opened
#: from a mail client that has no session to present. Its authority comes from
#: the signature on the link instead — which is the entire point of signing it.
#: Everything else belongs on `router`.
unauthenticated_router = APIRouter(prefix="/auth", tags=["auth"])


class CurrentUserRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    #: pending, approved or rejected. Null when nobody is signed in.
    status: AccessStatus | None = None
    role: AccessRole | None = None
    is_admin: bool = False
    id: str | None = None
    email: str | None = None
    name: str | None = None
    picture: str | None = None


class PendingUserRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    name: str | None
    requested_at: str | None


class ManagedUserRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    name: str | None
    picture: str | None
    status: AccessStatus
    role: AccessRole
    requested_at: str | None
    decided_at: str | None
    decided_by: str | None
    last_seen_at: str | None
    invited_by: str | None
    #: True for an invitation nobody has signed in to yet — the row exists,
    #: the person has not arrived.
    subject_pending: bool
    #: True for the account making the request, so the UI can stop somebody
    #: refusing or demoting themselves by accident.
    is_self: bool


class DecisionRequest(StrictModel):
    status: AccessStatus


class RoleRequest(StrictModel):
    role: AccessRole


#: Deliberately loose. The only test that means anything is whether the mail
#: arrives, and a stricter pattern would reject valid addresses to no benefit —
#: an invitation nobody can receive is self-correcting.
EMAIL_SHAPE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


#: Capped so one request cannot walk the whole table. Well above any list
#: somebody selects by hand.
UserIds = Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]


class BulkRequest(StrictModel):
    user_ids: UserIds


class BulkDecisionRequest(StrictModel):
    user_ids: UserIds
    status: AccessStatus


class BulkResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed: int
    #: Accounts the request named and did not touch, and why — a guard that
    #: refused, or an id that is not there. Reported rather than swallowed, so
    #: selecting twelve and changing nine is visible.
    skipped: dict[str, str]


class InviteRequest(StrictModel):
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=EMAIL_SHAPE)]


@router.get(
    "/me",
    response_model=CurrentUserRead,
    summary="Who this session belongs to, and whether they are let in",
    description=(
        "Answers while an account is still waiting, which is what lets the app tell "
        "'waiting for approval' apart from 'signed out'. With authentication switched off "
        "it answers `authenticated: false` rather than failing."
    ),
)
async def get_me(session: SessionDep, user: CurrentUser) -> CurrentUserRead:
    if not settings.auth_enabled or user.is_anonymous:
        return CurrentUserRead(authenticated=False)

    row = await user_service.resolve(session, user)
    return CurrentUserRead(
        authenticated=True,
        status=row.status if row else AccessStatus.APPROVED,
        role=row.role if row else None,
        is_admin=user_service.is_admin(user.email, row.role if row else None),
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
    )


@unauthenticated_router.get(
    "/decide",
    response_class=HTMLResponse,
    summary="Approve or reject an account from an emailed link",
    description=(
        "The link carries its own authority, signed with the deployment's key, so an "
        "administrator can act on a request from their mail without holding a session. It "
        "grants nothing beyond the one decision it names, and expires."
    ),
)
async def decide(session: SessionDep, token: str = Query(min_length=8)) -> HTMLResponse:
    row, action = await user_service.decide(session, token)
    approved = action == approvals.APPROVE
    headline = "Access approved" if approved else "Access refused"
    body = (
        f"{row.email} can now sign in."
        if approved
        else f"{row.email} has been refused, and will be told to contact you."
    )
    return HTMLResponse(_page(headline, body))


@router.get(
    "/pending",
    response_model=list[PendingUserRead],
    summary="Accounts waiting for a decision",
    description=(
        "The way back when the approval mail never arrives — a mail server being down "
        "should delay access, not lose the request. Administrators only."
    ),
)
async def list_pending(session: SessionDep, user: CurrentUser) -> list[PendingUserRead]:
    await _assert_admin(session, user)

    return [
        PendingUserRead(
            id=str(row.id),
            email=row.email,
            name=row.name,
            requested_at=row.requested_at.isoformat() if row.requested_at else None,
        )
        for row in await user_service.pending(session)
    ]


@router.get(
    "/users",
    response_model=list[ManagedUserRead],
    summary="Everyone who has ever signed in",
    description=(
        "Pending accounts first, because the list exists to be acted on rather than browsed. "
        "Administrators only."
    ),
)
async def list_users(session: SessionDep, user: CurrentUser) -> list[ManagedUserRead]:
    await _assert_admin(session, user)
    return [_managed(row, user) for row in await user_service.everyone(session)]


@router.post(
    "/users/{user_id}/decision",
    response_model=ManagedUserRead,
    summary="Approve or refuse an account",
)
async def decide_in_app(
    user_id: uuid.UUID, payload: DecisionRequest, session: SessionDep, user: CurrentUser
) -> ManagedUserRead:
    await _assert_admin(session, user)
    target = await _target(session, user_id)

    if target.subject == user.id and payload.status is not AccessStatus.APPROVED:
        raise ForbiddenError(
            "You cannot refuse your own account. Ask another administrator if you mean to."
        )

    updated = await user_service.set_status(session, target, payload.status, decided_by=user.email)
    return _managed(updated, user)


@router.post(
    "/users/{user_id}/role",
    response_model=ManagedUserRead,
    summary="Make somebody an administrator, or stop them being one",
)
async def change_role(
    user_id: uuid.UUID, payload: RoleRequest, session: SessionDep, user: CurrentUser
) -> ManagedUserRead:
    await _assert_admin(session, user)
    target = await _target(session, user_id)

    if target.subject == user.id and payload.role is not AccessRole.ADMIN:
        raise ForbiddenError(
            "You cannot remove your own administrator role. Promote somebody else and ask them."
        )

    updated = await user_service.set_role(session, target, payload.role, decided_by=user.email)
    return _managed(updated, user)


@router.post(
    "/invite",
    response_model=ManagedUserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Give somebody access before they have signed in",
    description=(
        "Creates an approved account with no sign-in attached to it yet and emails an "
        "invitation. Whoever next signs in with that address claims it and walks straight in "
        "— so it must be an address only they can receive mail at. Inviting somebody already "
        "known re-approves them, which is how an account refused by mistake is let back in."
    ),
)
async def invite_person(
    payload: InviteRequest, session: SessionDep, user: CurrentUser
) -> ManagedUserRead:
    await _assert_admin(session, user)
    row = await user_service.invite(session, payload.email, invited_by=user.email)
    return _managed(row, user)


@router.post(
    "/users/decisions",
    response_model=BulkResult,
    summary="Approve or refuse several accounts at once",
)
async def decide_many(
    payload: BulkDecisionRequest, session: SessionDep, user: CurrentUser
) -> BulkResult:
    await _assert_admin(session, user)
    return await _each(
        session,
        user,
        payload.user_ids,
        lambda target: user_service.set_status(
            session, target, payload.status, decided_by=user.email
        ),
    )


@router.post(
    "/users/removals",
    response_model=BulkResult,
    summary="Forget several accounts at once",
)
async def remove_many(payload: BulkRequest, session: SessionDep, user: CurrentUser) -> BulkResult:
    await _assert_admin(session, user)
    return await _each(
        session, user, payload.user_ids, lambda target: user_service.remove(session, target)
    )


async def _each(
    session: SessionDep,
    user: CurrentUser,
    user_ids: list[uuid.UUID],
    act: Callable[[AppUser], Awaitable[object]],
) -> BulkResult:
    """Apply one action across many accounts, one at a time.

    Not a single UPDATE, because every guard that protects a single account
    protects it here too — the last administrator does not stop being the last
    one because twelve rows were selected. A refusal is recorded against that
    account and the rest carry on.
    """
    changed = 0
    skipped: dict[str, str] = {}

    for user_id in user_ids:
        target = await session.get(AppUser, user_id)
        if target is None:
            skipped[str(user_id)] = "no longer exists"
            continue
        if target.subject is not None and target.subject == user.id:
            skipped[target.email] = "this is your own account"
            continue
        try:
            await act(target)
            changed += 1
        except AppError as refused:
            skipped[target.email] = refused.message

    return BulkResult(changed=changed, skipped=skipped)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Forget an account",
    description=(
        "Deletes the record rather than refusing it. Refusing is a decision that is kept and "
        "turns away the next sign-in; removing is for rows that should not be in the list at "
        "all — an invitation sent to the wrong address, a duplicate. Somebody removed who signs "
        "in again arrives as a new request."
    ),
)
async def remove_person(user_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    await _assert_admin(session, user)
    target = await _target(session, user_id)

    if target.subject == user.id:
        raise ForbiddenError("You cannot remove your own account.")

    await user_service.remove(session, target)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _assert_admin(session: SessionDep, user: CurrentUser) -> None:
    row = await user_service.status_of(session, user)
    if not user_service.is_admin(user.email, row.role if row else None):
        raise ForbiddenError("Only an administrator can manage who has access.")


async def _target(session: SessionDep, user_id: uuid.UUID):
    row = await session.get(AppUser, user_id)
    if row is None:
        raise NotFoundError(f"No account with id {user_id}.")
    return row


def _managed(row: AppUser, viewer: AuthenticatedUser) -> ManagedUserRead:
    def when(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return ManagedUserRead(
        id=str(row.id),
        email=row.email,
        name=row.name,
        picture=row.picture_url,
        status=row.status,
        role=row.role,
        requested_at=when(row.requested_at),
        decided_at=when(row.decided_at),
        decided_by=row.decided_by,
        last_seen_at=when(row.last_seen_at),
        invited_by=row.invited_by,
        subject_pending=row.subject is None,
        is_self=row.subject is not None and row.subject == viewer.id,
    )


#: Long enough that an idle stream costs nothing, short enough that a proxy
#: which drops silent connections never gets the chance. Vercel's is the one
#: in the path here.
KEEPALIVE_SECONDS = 25.0


@router.get(
    "/events",
    response_class=StreamingResponse,
    summary="Server-Sent Events stream of access changes",
    description=(
        "Opens while an account is still waiting, which is the case it exists for: the "
        "decision is made on somebody else's screen and has to arrive on this one without "
        "a reload. Carries a topic name and nothing else — the client answers it by "
        "refetching through the ordinary endpoints, so the stream can never show anybody "
        "more than they could already ask for."
    ),
)
async def stream_access(user: CurrentUser) -> StreamingResponse:
    if not settings.auth_enabled or user.is_anonymous:
        # Nothing can change, so hold nothing open. An empty stream that closes
        # at once is a clearer answer to the client than a connection that
        # never says anything.
        return StreamingResponse(iter([b"event: idle\ndata: {}\n\n"]), media_type="text/event-stream")

    # Deliberately not SessionDep. A dependency-provided session lives as long
    # as the request, and this request lives as long as the browser tab — one
    # open page would hold a pooled connection for hours, and a handful would
    # exhaust the pool while doing nothing at all. Read what is needed, give
    # the connection back, then stream.
    async with session_scope() as session:
        row = await user_service.status_of(session, user)
        topics = [broadcast.topic_for_user(row.id)] if row is not None else []
        is_admin = row is not None and user_service.is_admin(user.email, row.role)
    # Administrators also watch the list itself, so a request arriving lands on
    # the page they were told to look at.
    if is_admin:
        topics.append(broadcast.PEOPLE)

    async def events() -> AsyncIterator[bytes]:
        async with broadcast.subscribe(*topics) as queue:
            # Said once on connect. A client that reconnects after missing a
            # decision refetches immediately rather than waiting for the next
            # thing to happen, which may be never.
            yield b"event: sync\ndata: {}\n\n"
            while True:
                try:
                    topic = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                yield f"event: {topic}\ndata: {{}}\n\n".encode()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _page(headline: str, body: str) -> str:
    """A plain page, because this one is opened in a mail client's browser.

    No stylesheet to fetch and no script to run: whatever opens it may be an
    in-app webview with neither.
    """
    return (
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{headline}</title>"
        '<div style="font:16px/1.5 system-ui,sans-serif;max-width:32rem;'
        'margin:16vh auto;padding:0 1.5rem;color:#111512">'
        f'<h1 style="font-size:1.25rem;margin:0 0 .5rem">{headline}</h1>'
        f'<p style="color:#4e554e;margin:0">{body}</p></div>'
    )
