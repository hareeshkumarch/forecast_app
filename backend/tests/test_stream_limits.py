from __future__ import annotations

import uuid
from typing import ClassVar

import pytest

from app.core import streams
from app.core.config import settings
from app.core.streams import TooManyStreamsError


@pytest.fixture(autouse=True)
def _ceilings():
    before = (settings.sse_max_streams_per_client, settings.sse_max_streams_total)
    settings.sse_max_streams_per_client = 2
    settings.sse_max_streams_total = 3
    yield
    settings.sse_max_streams_per_client, settings.sse_max_streams_total = before


def test_a_client_may_hold_up_to_its_ceiling() -> None:
    held = [streams.registry.acquire("user:a", "access") for _ in range(2)]

    assert streams.registry.for_client("user:a") == 2
    for lease in held:
        lease.release()
    assert streams.registry.for_client("user:a") == 0


def test_one_past_the_ceiling_is_refused_with_something_to_wait_for() -> None:
    first = streams.registry.acquire("user:a", "access")
    second = streams.registry.acquire("user:a", "access")

    with pytest.raises(TooManyStreamsError) as refused:
        streams.registry.acquire("user:a", "access")

    assert refused.value.status_code == 429
    assert refused.value.headers["Retry-After"]
    first.release()
    second.release()


def test_releasing_gives_the_slot_back() -> None:
    first = streams.registry.acquire("user:a", "access")
    streams.registry.acquire("user:a", "forecast").release()

    streams.registry.acquire("user:a", "forecast").release()
    first.release()
    assert streams.registry.total == 0


def test_releasing_twice_does_not_free_somebody_else_s_slot() -> None:
    lease = streams.registry.acquire("user:a", "access")
    lease.release()
    lease.release()

    assert streams.registry.total == 0
    assert streams.registry.for_client("user:a") == 0


def test_two_accounts_behind_one_address_do_not_share_a_ceiling() -> None:
    streams.registry.acquire("user:a", "access")
    streams.registry.acquire("user:a", "access")

    streams.registry.acquire("user:b", "access")
    assert streams.registry.for_client("user:b") == 1


def test_the_process_ceiling_refuses_a_client_still_under_its_own() -> None:
    streams.registry.acquire("user:a", "access")
    streams.registry.acquire("user:a", "access")
    streams.registry.acquire("user:b", "access")

    with pytest.raises(TooManyStreamsError) as refused:
        streams.registry.acquire("user:c", "access")
    assert "as many live connections" in refused.value.message


def test_a_refusal_before_the_response_does_not_leak_the_slot() -> None:
    class _Request:
        headers: ClassVar[dict[str, str]] = {}
        client = None

    with pytest.raises(RuntimeError), streams.leased(_Request(), "a", "access"):  # type: ignore[arg-type]
        raise RuntimeError("the response could not be built")

    assert streams.registry.total == 0


def test_a_frame_is_shaped_the_way_an_event_source_reads_it() -> None:
    assert streams.frame(event="sync") == b"event: sync\ndata: {}\n\n"
    assert streams.frame('{"a":1}', event_id="7") == b'id: 7\ndata: {"a":1}\n\n'


def test_a_multi_line_payload_stays_one_event() -> None:
    assert streams.frame("one\ntwo") == b"data: one\ndata: two\n\n"


def test_the_browser_is_told_how_long_to_wait_before_reconnecting() -> None:
    assert streams.preamble() == f"retry: {settings.sse_retry_hint_ms}\n\n".encode()


def test_a_deadline_that_has_not_passed_reports_time_left() -> None:
    deadline = streams.Deadline(seconds=30)

    assert not deadline.passed
    assert 0 < deadline.remaining <= 30


def test_a_deadline_in_the_past_has_passed() -> None:
    assert streams.Deadline(seconds=-1).passed


async def test_a_lease_is_given_back_when_the_stream_is_exhausted() -> None:
    lease = streams.registry.acquire("user:a", "access")

    async def body():
        yield b"one"

    assert [chunk async for chunk in streams.released_after(body(), lease)] == [b"one"]
    assert streams.registry.total == 0


async def test_a_lease_is_given_back_when_the_browser_goes_away_mid_stream() -> None:
    lease = streams.registry.acquire("user:a", "access")

    async def body():
        while True:
            yield b": keep-alive\n\n"

    stream = streams.released_after(body(), lease)
    await stream.__anext__()
    await stream.aclose()

    assert streams.registry.total == 0


async def test_the_endpoint_refuses_before_it_looks_the_run_up(client) -> None:
    settings.sse_max_streams_total = 1
    held = streams.registry.acquire("someone-else", "forecast")

    try:
        response = await client.get(f"/api/forecasts/{uuid.uuid4()}/events")
    finally:
        held.release()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_streams"
    assert response.headers["Retry-After"]
