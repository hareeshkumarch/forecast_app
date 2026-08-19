"""A route says what it needs. A role says what it may do."""

from __future__ import annotations

import pytest

from app.core.permissions import (
    EVERYTHING,
    MEMBER_GRANTS,
    Permission,
    allows,
    granted,
    permission_for,
)
from app.models.enums import AccessRole


def test_an_administrator_may_do_everything() -> None:
    assert granted(AccessRole.ADMIN) == EVERYTHING


def test_a_member_keeps_exactly_what_a_member_could_already_do() -> None:
    """The one thing this change must not do is take something away.

    Everybody approved on this deployment is a member today and can do
    everything except manage people. If that set moves, the first anybody
    hears of it is somebody being refused an upload that worked yesterday.
    """
    assert granted(AccessRole.MEMBER) == MEMBER_GRANTS
    assert Permission.USER_MANAGE not in granted(AccessRole.MEMBER)
    assert Permission.AUDIT_READ not in granted(AccessRole.MEMBER)
    for permission in (
        Permission.READ,
        Permission.DATASET_WRITE,
        Permission.DATASET_DELETE,
        Permission.FORECAST_RUN,
        Permission.FORECAST_DELETE,
        Permission.CONNECTOR_MANAGE,
    ):
        assert allows(permission, AccessRole.MEMBER)


def test_a_viewer_may_look_and_nothing_else() -> None:
    assert granted(AccessRole.VIEWER) == {Permission.READ}
    assert not allows(Permission.FORECAST_RUN, AccessRole.VIEWER)
    assert not allows(Permission.DATASET_WRITE, AccessRole.VIEWER)
    assert not allows(Permission.CONNECTOR_MANAGE, AccessRole.VIEWER)


def test_no_role_grants_nothing() -> None:
    """An account with no row is not a member by default."""
    assert granted(None) == frozenset()
    assert not allows(Permission.READ, None)


def test_the_configured_list_outranks_the_column() -> None:
    """The floor that makes it impossible to lock everybody out."""
    assert allows(Permission.USER_MANAGE, AccessRole.VIEWER, configured_admin=True)
    assert granted(None, configured_admin=True) == EVERYTHING


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/datasets", Permission.READ),
        ("POST", "/api/datasets", Permission.DATASET_WRITE),
        ("PATCH", "/api/datasets/x", Permission.DATASET_WRITE),
        ("DELETE", "/api/datasets/x", Permission.DATASET_DELETE),
        ("POST", "/api/forecasts", Permission.FORECAST_RUN),
        ("POST", "/api/forecasts/x/scenarios", Permission.FORECAST_RUN),
        ("DELETE", "/api/forecasts/x", Permission.FORECAST_DELETE),
        ("POST", "/api/connectors", Permission.CONNECTOR_MANAGE),
        ("DELETE", "/api/connectors/x", Permission.CONNECTOR_MANAGE),
        ("GET", "/api/auth/users", Permission.READ),
        ("POST", "/api/auth/invite", Permission.USER_MANAGE),
        ("DELETE", "/api/auth/users/x", Permission.USER_MANAGE),
        ("GET", "/api/dashboard/summary", Permission.READ),
    ],
)
def test_routes_map_to_the_permission_meant_for_them(method, path, expected) -> None:
    assert permission_for(method, path) is expected


def test_a_viewer_can_still_export_what_they_can_read() -> None:
    """Otherwise the role does not mean anything.

    An export is a way of looking at numbers you are already allowed to see,
    whatever verb it arrives on.
    """
    assert permission_for("POST", "/api/exports/csv") is Permission.READ
    assert allows(permission_for("POST", "/api/exports/csv"), AccessRole.VIEWER)


def test_an_unmapped_mutation_is_not_silently_administrator_only() -> None:
    """A route added tomorrow should refuse a viewer, not refuse a member.

    Defaulting to USER_MANAGE would be quiet in the worse direction: the
    person hitting it is a member being refused something they expect to be
    able to do, and nothing in the route says why.
    """
    fallback = permission_for("POST", "/api/something-added-later")

    assert allows(fallback, AccessRole.MEMBER)
    assert not allows(fallback, AccessRole.VIEWER)


def test_every_permission_is_reachable_from_some_role() -> None:
    """A permission no role grants is a route nobody can call."""
    from app.core.permissions import GRANTS

    reachable = frozenset().union(*GRANTS.values())
    assert reachable == EVERYTHING


def test_every_guarded_router_is_behind_the_permission_gate() -> None:
    """Mounted once, so a route added later cannot arrive unguarded.

    This is the check that a per-handler decorator cannot give you: the
    seventeenth handler nobody annotated works, for everybody, which is
    exactly what an unguarded route looks like from the outside.
    """
    from fastapi.routing import APIRoute

    from app.main import app

    unguarded = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if route.path.startswith(("/api/health", "/api/auth")):
            continue
        names = {
            dependency.call.__name__
            for dependency in route.dependant.dependencies
            if getattr(dependency, "call", None)
        }
        if "permitted" not in names:
            unguarded.append(f"{sorted(route.methods)} {route.path}")

    assert not unguarded, f"these routes are not behind the permission gate: {unguarded}"
