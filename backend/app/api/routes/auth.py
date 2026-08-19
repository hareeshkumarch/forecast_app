from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, SessionDep
from app.core import approvals
from app.core.auth import ForbiddenError
from app.core.config import settings
from app.models.enums import AccessStatus
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


class CurrentUserRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    #: pending, approved or rejected. Null when nobody is signed in.
    status: AccessStatus | None = None
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
        is_admin=user_service.is_admin(user.email),
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
    )


@router.get(
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
    if not user_service.is_admin(user.email):
        raise ForbiddenError("Only an administrator can see who is waiting.")

    return [
        PendingUserRead(
            id=str(row.id),
            email=row.email,
            name=row.name,
            requested_at=row.requested_at.isoformat() if row.requested_at else None,
        )
        for row in await user_service.pending(session)
    ]


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
