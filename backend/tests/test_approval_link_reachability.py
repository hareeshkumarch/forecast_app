"""The emailed decision link, exercised the way a mail client uses it.

This file exists because of a bug that every other test missed. The endpoint
worked, the signature verified, the service updated the row — and the link was
unusable, because it had been mounted behind the session guard. Clicking it
from an inbox answered 401.

Nothing that tests the function can see that. Only asking the application what
it exposes can.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from app.core.config import settings
from app.main import app

DECIDE = "/api/auth/decide"


def _route() -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == DECIDE:
            return route
    raise AssertionError(f"{DECIDE} is not registered at all")


def test_the_link_does_not_require_a_session() -> None:
    """It is opened from an email. There is no session to present."""
    guards = {
        dependency.call.__name__
        for dependency in _route().dependant.dependencies
        if getattr(dependency, "call", None)
    }

    assert "current_user" not in guards
    assert "approved_user" not in guards


async def test_an_unsigned_request_reaches_the_endpoint(client: AsyncClient) -> None:
    """A bad token must be answered as a bad token, not as 'who are you'.

    401 here would mean the link cannot be used from an inbox at all, whatever
    the signature on it says.
    """
    original = settings.auth_enabled
    settings.auth_enabled = True
    try:
        response = await client.get(DECIDE, params={"token": "not.a.real.token"})
    finally:
        settings.auth_enabled = original

    assert response.status_code != 401, "the emailed link is unreachable without signing in"
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["/api/auth/users", "/api/auth/invite", "/api/auth/me"])
def test_everything_else_on_the_auth_router_still_needs_a_session(path: str) -> None:
    """The exemption is for one endpoint, and must not have widened."""
    route = next(
        r for r in app.routes if isinstance(r, APIRoute) and r.path == path
    )
    guards = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency, "call", None)
    }

    assert "current_user" in guards, f"{path} lost its guard"
