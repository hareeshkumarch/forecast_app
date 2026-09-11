from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ANONYMOUS, AuthenticatedUser, AuthError, ForbiddenError, verify_token
from app.core.config import settings
from app.core.errors import ValidationError
from app.core.permissions import Permission, allows, permission_for
from app.database.session import get_session
from app.schemas.dashboard import DashboardQuery

SessionDep = Annotated[AsyncSession, Depends(get_session)]

BEARER_PREFIX = "bearer "


STREAM_SUFFIX = "/events"


def query_token_allowed(method: str, path: str) -> bool:
    return method.upper() == "GET" and path.endswith(STREAM_SUFFIX)


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith(BEARER_PREFIX):
        return header[len(BEARER_PREFIX) :].strip() or None

    if not query_token_allowed(request.method, request.url.path):
        return None

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
    user = await current_user(request)
    if user.is_anonymous or not settings.auth_require_approval:
        return user

    from app.models.enums import AccessStatus
    from app.services import user_service

    row = await user_service.status_of(session, user)
    if row is not None and row.status is AccessStatus.APPROVED:
        return user

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


def require(permission: Permission) -> Callable[..., Awaitable[AuthenticatedUser]]:
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
