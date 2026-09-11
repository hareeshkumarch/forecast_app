from __future__ import annotations

import asyncio
import json

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
        await user_service.set_status(_Session(), target, AccessStatus.APPROVED, decided_by="boss")
        assert await asyncio.wait_for(theirs.get(), timeout=1) == broadcast.ACCESS
        assert await asyncio.wait_for(admins.get(), timeout=1) == broadcast.PEOPLE


async def test_re_approving_announces_nothing() -> None:
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
        await user_service.set_status(_Session(), target, AccessStatus.APPROVED, decided_by="boss")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(theirs.get(), timeout=0.2)


def test_the_stream_is_reachable_while_still_waiting() -> None:
    from fastapi.routing import APIRoute

    from app.main import app

    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/auth/events")
    guards = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency, "call", None)
    }

    assert "current_user" in guards, "the stream must still require a session"
    assert "approved_user" not in guards, "a waiting account could not open it"


def test_the_stream_does_not_hold_a_pooled_connection() -> None:
    from fastapi.routing import APIRoute

    from app.main import app

    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/auth/events")
    assert "session" not in route.dependant.query_params + route.dependant.path_params
    names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency, "call", None)
    }
    assert "get_session" not in names


class TestAcrossProcesses:
    async def test_a_frame_from_another_process_is_delivered_here(self) -> None:
        async with broadcast.subscribe("access:7") as queue:
            broadcast._accept(
                json.dumps({"origin": "another-process", "topic": "access:7", "event": "access"})
            )
            assert await asyncio.wait_for(queue.get(), timeout=1) == "access"

    async def test_this_process_ignores_the_echo_of_its_own_publish(self) -> None:
        async with broadcast.subscribe("access:7") as queue:
            broadcast._accept(
                json.dumps({"origin": broadcast.ORIGIN, "topic": "access:7", "event": "access"})
            )
            assert queue.empty()

    async def test_a_malformed_frame_does_not_bring_the_relay_down(self) -> None:
        broadcast._accept("not json at all")
        broadcast._accept(json.dumps({"origin": "x"}))

    async def test_nothing_is_announced_anywhere_without_a_channel_to_announce_on(
        self, monkeypatch
    ) -> None:
        pushed: list[str] = []
        monkeypatch.setattr(broadcast.settings, "redis_url", "")
        monkeypatch.setattr(broadcast, "_push", lambda payload: pushed.append(payload))

        async with broadcast.subscribe("t") as queue:
            assert broadcast.publish("t", "access") == 1
            assert await asyncio.wait_for(queue.get(), timeout=1) == "access"

        assert pushed == []
