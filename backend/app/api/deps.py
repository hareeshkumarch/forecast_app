from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ANONYMOUS, AuthenticatedUser, AuthError, verify_token
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
