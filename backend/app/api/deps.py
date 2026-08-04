
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.database.session import get_session
from app.schemas.dashboard import DashboardQuery

SessionDep = Annotated[AsyncSession, Depends(get_session)]

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
