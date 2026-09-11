from __future__ import annotations

from enum import StrEnum

from app.models.enums import AccessRole


class Permission(StrEnum):
    READ = "read"
    DATASET_WRITE = "dataset:write"
    DATASET_DELETE = "dataset:delete"
    FORECAST_RUN = "forecast:run"
    FORECAST_DELETE = "forecast:delete"
    CONNECTOR_MANAGE = "connector:manage"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"


EVERYTHING: frozenset[Permission] = frozenset(Permission)

MEMBER_GRANTS = frozenset(
    {
        Permission.READ,
        Permission.DATASET_WRITE,
        Permission.DATASET_DELETE,
        Permission.FORECAST_RUN,
        Permission.FORECAST_DELETE,
        Permission.CONNECTOR_MANAGE,
    }
)

VIEWER_GRANTS = frozenset({Permission.READ})

GRANTS: dict[AccessRole, frozenset[Permission]] = {
    AccessRole.ADMIN: EVERYTHING,
    AccessRole.MEMBER: MEMBER_GRANTS,
    AccessRole.VIEWER: VIEWER_GRANTS,
}


def granted(role: AccessRole | None, *, configured_admin: bool = False) -> frozenset[Permission]:
    if configured_admin:
        return EVERYTHING
    if role is None:
        return frozenset()
    return GRANTS.get(role, frozenset())


def allows(
    permission: Permission, role: AccessRole | None, *, configured_admin: bool = False
) -> bool:
    return permission in granted(role, configured_admin=configured_admin)


def permission_for(method: str, path: str) -> Permission:
    reading = method in ("GET", "HEAD", "OPTIONS")

    if path.startswith("/api/auth/"):
        return Permission.READ if reading else Permission.USER_MANAGE

    if path.startswith(("/api/exports", "/api/dashboard", "/api/usage")):
        return Permission.READ

    if reading:
        return Permission.READ

    if path.startswith("/api/forecasts/retention"):
        return Permission.FORECAST_DELETE

    if path.startswith("/api/forecasts"):
        return Permission.FORECAST_DELETE if method == "DELETE" else Permission.FORECAST_RUN
    if path.startswith("/api/datasets"):
        return Permission.DATASET_DELETE if method == "DELETE" else Permission.DATASET_WRITE
    if path.startswith("/api/connectors"):
        return Permission.CONNECTOR_MANAGE

    return Permission.DATASET_WRITE
