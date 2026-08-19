from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


class CurrentUserRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    id: str | None = None
    email: str | None = None
    name: str | None = None
    picture: str | None = None


@router.get(
    "/me",
    response_model=CurrentUserRead,
    summary="Who this session belongs to",
    description=(
        "Returns the signed-in account and records it, so the platform can say who uploaded "
        "a file or started a run. With authentication switched off it answers "
        "`authenticated: false` rather than failing, which is what lets the frontend tell "
        "the difference between 'not signed in' and 'this deployment has no sign-in'."
    ),
)
async def get_me(session: SessionDep, user: CurrentUser) -> CurrentUserRead:
    if not settings.auth_enabled or user.is_anonymous:
        return CurrentUserRead(authenticated=False)

    await user_service.resolve(session, user)
    return CurrentUserRead(
        authenticated=True,
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
    )
