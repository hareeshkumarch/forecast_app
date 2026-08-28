"""A decision has to reach the screen it is about, without being asked for."""

from __future__ import annotations

import asyncio

import pytest

from app.core import broadcast


async def test_a_nudge_reaches_a_subscriber() -> None:
    async with broadcast.subscribe("t") as queue:
        assert broadcast.publish("t", "access") == 1
        assert await asyncio.wait_for(queue.get(), timeout=1) == "access"


async def test_a_nudge_reaches_every_subscriber_of_a_topic() -> None:
    async with broadcast.subscribe("t") as one, broadcast.subscribe("t") as two:
        assert broadcast.publish("t", "access") == 2
        assert await asyncio.wait_for(one.get(), timeout=1) == "access"
        assert await asyncio.wait_for(two.get(), timeout=1) == "access"


async def test_a_topic_nobody_listens_to_costs_nothing() -> None:
    assert broadcast.publish("nobody", "access") == 0


async def test_subscribers_are_forgotten_on_the_way_out() -> None:
    """Left behind, this leaks one entry per account that ever connected."""
    async with broadcast.subscribe("t"):
        assert broadcast.subscriber_count("t") == 1
    assert broadcast.subscriber_count("t") == 0


async def test_a_browser_that_stopped_reading_does_not_grow_a_queue() -> None:
    async with broadcast.subscribe("t"):
        for _ in range(broadcast.QUEUE_LIMIT * 4):
            broadcast.publish("t", "access")
        assert broadcast.subscriber_count("t") == 1


async def test_a_decision_announces_to_the_person_and_the_list(monkeypatch) -> None:
    from app.models.enums import AccessRole, AccessStatus
    from app.services import user_service

    from tests.test_access_approval import _Account

    monkeypatch.setattr(user_service.mailer, "queue", lambda *a, **k: None)
    user_service.settings.auth_admin_emails_raw = ""

    target = _Account("someone@example.com", AccessRole.MEMBER, AccessStatus.PENDING)
    target.id = "user-1"

    class _Session:
        async def flush(self):
            return None

        def add(self, _row):
            return None

    async with (
        broadcast.subscribe(broadcast.topic_for_user("user-1")) as theirs,
        broadcast.subscribe(broadcast.PEOPLE) as admins,
    ):
        await user_service.set_status(
            _Session(), target, AccessStatus.APPROVED, decided_by="boss"
        )
        assert await asyncio.wait_for(theirs.get(), timeout=1) == broadcast.ACCESS
        assert await asyncio.wait_for(admins.get(), timeout=1) == broadcast.PEOPLE


async def test_re_approving_announces_nothing() -> None:
    """Nothing changed, so no screen needs to do anything about it."""
    from app.models.enums import AccessRole, AccessStatus
    from app.services import user_service

    from tests.test_access_approval import _Account

    user_service.settings.auth_admin_emails_raw = ""
    target = _Account("someone@example.com", AccessRole.MEMBER, AccessStatus.APPROVED)
    target.id = "user-2"

    class _Session:
        async def flush(self):
            return None

        def add(self, _row):
            return None

    async with broadcast.subscribe(broadcast.topic_for_user("user-2")) as theirs:
        await user_service.set_status(
            _Session(), target, AccessStatus.APPROVED, decided_by="boss"
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(theirs.get(), timeout=0.2)


def test_the_stream_is_reachable_while_still_waiting() -> None:
    """The screen that needs this most is the one that is not in yet.

    Mounted behind the approval gate the endpoint would answer 403 to exactly
    the people it exists for, and the waiting card would go back to polling
    forever. Nothing that tests the handler can see that — only asking the
    application what it exposes.
    """
    from fastapi.routing import APIRoute

    from app.main import app

    route = next(
        r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/auth/events"
    )
    guards = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency, "call", None)
    }

    assert "current_user" in guards, "the stream must still require a session"
    assert "approved_user" not in guards, "a waiting account could not open it"


def test_the_stream_does_not_hold_a_pooled_connection() -> None:
    """One open tab would otherwise pin a database connection for hours.

    A session from the dependency lives as long as the request, and this
    request lives as long as the browser tab. A handful of open pages would
    exhaust the pool while doing nothing at all.
    """
    from fastapi.routing import APIRoute

    from app.main import app

    route = next(
        r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/auth/events"
    )
    assert "session" not in route.dependant.query_params + route.dependant.path_params
    names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency, "call", None)
    }
    assert "get_session" not in names
