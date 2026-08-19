from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ANONYMOUS, AuthenticatedUser, AuthError, ForbiddenError, verify_token
from app.core.permissions import Permission, allows, permission_for
from app.core.config import settings
from app.core.errors import ValidationError
from app.database.session import get_session
from app.schemas.dashboard import DashboardQuery

SessionDep = Annotated[AsyncSession, Depends(get_session)]

BEARER_PREFIX = "bearer "


def bearer_token(request: Request) -> str | None:
    """The token on this request, from the header or — for SSE — the query.

    EventSource cannot set headers, so the one endpoint a browser opens that
    way has no other way to present a token. It is accepted from the query
    string for that reason and no other; a token there is visible in access
    logs, so nothing else should rely on it.
    """
    header = request.headers.get("Authorization", "")
    if header.lower().startswith(BEARER_PREFIX):
        return header[len(BEARER_PREFIX) :].strip() or None

    token = request.query_params.get("access_token")
    return token.strip() or None if token else None


async def current_user(request: Request) -> AuthenticatedUser:
    if not settings.auth_enabled:
        return ANONYMOUS

    token = bearer_token(request)
    if not token:
        raise AuthError("This request carried no session. Sign in and try again.")

    user = await verify_token(token)
    request.state.user = user
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]


async def approved_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    """A signed-in account that an administrator has let in.

    Separate from `current_user` because /auth/me has to answer *while*
    somebody is waiting for approval — a gate that refuses everything would
    leave the frontend unable to tell "waiting" from "signed out", and the
    person staring at a sign-in button they have already used.
    """
    user = await current_user(request)
    if user.is_anonymous or not settings.auth_require_approval:
        return user

    from app.models.enums import AccessStatus
    from app.services import user_service

    # Read, never write: this runs on every request, and recording a visit here
    # would put a database write behind every read the platform serves. The
    # account is created and stamped by /auth/me, which runs once a session.
    row = await user_service.status_of(session, user)
    if row is not None and row.status is AccessStatus.APPROVED:
        return user

    # No row means this account has never been registered, which is not the
    # same as being approved. Treating the absence as permission would let a
    # new sign-in skip /auth/me and walk straight past the gate.
    if row is None:
        raise ForbiddenError(
            "This account is not registered on this deployment yet.",
            detail={"status": AccessStatus.PENDING.value},
        )

    if row.status is AccessStatus.REJECTED:
        raise ForbiddenError(
            "This account was not given access to this deployment.",
            detail={"status": row.status.value},
        )
    raise ForbiddenError(
        "This account is waiting for an administrator to approve it.",
        detail={"status": row.status.value},
    )


ApprovedUser = Annotated[AuthenticatedUser, Depends(approved_user)]


async def permitted(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AuthenticatedUser:
    """The permission this request needs, decided from what it is.

    Mounted once on the guarded routers rather than annotated on each handler,
    so a route added later is covered by the table in permissions.py instead of
    by somebody remembering. Wraps `approved_user`, so it is still one gate: a
    request that has no business here is refused before the permission question
    is even asked.
    """
    user = await approved_user(request, session)
    if user.is_anonymous or not settings.auth_enabled:
        return user

    from app.services import user_service

    permission = permission_for(request.method, request.url.path)
    row = await user_service.status_of(session, user)
    if allows(
        permission,
        row.role if row else None,
        configured_admin=user_service.is_configured_admin(user.email),
    ):
        return user

    raise ForbiddenError(
        f"This account is not allowed to {_ENGLISH.get(permission, permission.value)}.",
        detail={"permission": permission.value},
    )


def require(permission: Permission):
    """A route saying what it needs rather than who it trusts.

    Returns a dependency, so it reads as
    `dependencies=[Depends(require(Permission.FORECAST_RUN))]` on the router or
    the handler. The check is a database read on every call, deliberately:
    permissions carried in a token would mean a demotion or a revocation
    taking effect whenever that token happened to expire, and this platform's
    revocation is expected to bite on the next request.
    """

    async def guard(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> AuthenticatedUser:
        user = await approved_user(request, session)
        if user.is_anonymous or not settings.auth_enabled:
            return user

        from app.services import user_service

        row = await user_service.status_of(session, user)
        if allows(
            permission,
            row.role if row else None,
            configured_admin=user_service.is_configured_admin(user.email),
        ):
            return user

        raise ForbiddenError(
            f"This account is not allowed to {_ENGLISH.get(permission, permission.value)}.",
            detail={"permission": permission.value},
        )

    return guard


#: The message somebody actually reads. "not allowed to forecast:run" is a
#: log line; "not allowed to start forecasts" is an answer.
_ENGLISH = {
    Permission.READ: "see this",
    Permission.DATASET_WRITE: "add or change datasets",
    Permission.DATASET_DELETE: "delete datasets",
    Permission.FORECAST_RUN: "start forecasts",
    Permission.FORECAST_DELETE: "delete forecast runs",
    Permission.CONNECTOR_MANAGE: "manage connectors",
    Permission.USER_MANAGE: "manage who has access",
    Permission.AUDIT_READ: "read the audit log",
}



VALID_VIEWS = ("base", "best", "worst")


def dashboard_query(
    run_id: uuid.UUID | None = Query(
        default=None, description="Forecast run to read. Defaults to the latest completed run."
    ),
    start: date | None = Query(default=None, description="Inclusive start of the date range."),
    end: date | None = Query(default=None, description="Inclusive end of the date range."),
    view: str = Query(default="base", description="Scenario: base, best or worst."),
) -> DashboardQuery:
    if view not in VALID_VIEWS:
        raise ValidationError(
            f"'{view}' is not a valid forecast view. Choose one of: {', '.join(VALID_VIEWS)}."
        )

    if start is not None and end is not None and start > end:
        raise ValidationError(
            f"The start date ({start}) is after the end date ({end}).",
            detail={"start": str(start), "end": str(end)},
        )

    return DashboardQuery(run_id=run_id, start=start, end=end, view=view)


DashboardQueryDep = Annotated[DashboardQuery, Depends(dashboard_query)]
