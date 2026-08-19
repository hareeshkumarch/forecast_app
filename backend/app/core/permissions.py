"""What each role may do, in one table anybody can read.

Two roles enforced a single question — administrator or not — spread across
every route that cared. Naming the capabilities separately means a route says
what it needs rather than who it trusts, and a new role is a line here instead
of an audit of every handler.

Deliberately derived from the role rather than stored per account. A
permissions table is the right answer when customers define their own roles;
it is a join and a migration and an admin screen to maintain when there are
three roles and one deployment. This can become that later without any route
changing, because the routes ask `has(permission)` either way.

Not put in the token, either. Permissions in a JWT claim mean revoking
somebody takes effect when their token expires — an hour, on the Supabase
default — and this platform's revocation is expected to bite on the next
request. The check costs one indexed read of a table with a handful of rows.
"""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import AccessRole


class Permission(StrEnum):
    #: Read the dashboard, the runs, the series, the exports.
    READ = "read"
    #: Upload a file or edit a dataset's mapping.
    DATASET_WRITE = "dataset:write"
    DATASET_DELETE = "dataset:delete"
    #: Start a forecast. Separated from writing because it is the expensive
    #: one: a run is a minute of both vCPUs on this instance.
    FORECAST_RUN = "forecast:run"
    FORECAST_DELETE = "forecast:delete"
    #: Add or edit a connector, which means handling credentials.
    CONNECTOR_MANAGE = "connector:manage"
    #: Approve, refuse, invite, promote, remove.
    USER_MANAGE = "user:manage"
    #: Read who did what.
    AUDIT_READ = "audit:read"


EVERYTHING = frozenset(Permission)

#: What a member could already do, named rather than changed. Anybody approved
#: on this deployment today has exactly this set, so nothing anyone can do
#: right now stops working the day this lands.
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

#: New, and nobody holds it until somebody is given it. For the person who
#: needs the numbers and has no business spending the box's CPU or touching a
#: credential — the role every deployment eventually wants and cannot express
#: with a boolean.
VIEWER_GRANTS = frozenset({Permission.READ})

GRANTS: dict[AccessRole, frozenset[Permission]] = {
    AccessRole.ADMIN: EVERYTHING,
    AccessRole.MEMBER: MEMBER_GRANTS,
    AccessRole.VIEWER: VIEWER_GRANTS,
}


def granted(role: AccessRole | None, *, configured_admin: bool = False) -> frozenset[Permission]:
    """Everything this role may do.

    `configured_admin` is the floor from AUTH_ADMIN_EMAILS: whatever the
    database says, a named account is an administrator. It is what makes it
    impossible to end up with a deployment nobody can administer.
    """
    if configured_admin:
        return EVERYTHING
    if role is None:
        return frozenset()
    return GRANTS.get(role, frozenset())


def allows(
    permission: Permission, role: AccessRole | None, *, configured_admin: bool = False
) -> bool:
    return permission in granted(role, configured_admin=configured_admin)


#: Routes are mapped here rather than decorated one by one. Seventeen handlers
#: carrying their own annotation is seventeen chances to forget one, and the
#: one forgotten is invisible — it works, for everybody, which is exactly what
#: an unguarded route looks like. One table can also be read in full by
#: somebody deciding whether a role is safe to hand out.
def permission_for(method: str, path: str) -> Permission:
    reading = method in ("GET", "HEAD", "OPTIONS")

    if path.startswith("/api/auth/"):
        return Permission.READ if reading else Permission.USER_MANAGE

    # An export and an insight are ways of looking at what you can already
    # see, whatever verb they arrive on. A viewer who cannot download the
    # numbers they are allowed to read has been given a role that does not
    # mean anything.
    if path.startswith(("/api/exports", "/api/dashboard", "/api/usage")):
        return Permission.READ

    if reading:
        return Permission.READ

    if path.startswith("/api/forecasts"):
        return Permission.FORECAST_DELETE if method == "DELETE" else Permission.FORECAST_RUN
    if path.startswith("/api/datasets"):
        return Permission.DATASET_DELETE if method == "DELETE" else Permission.DATASET_WRITE
    if path.startswith("/api/connectors"):
        return Permission.CONNECTOR_MANAGE

    # Anything not named above. DATASET_WRITE rather than READ because the
    # request is changing something, and rather than USER_MANAGE because a
    # route added tomorrow should not silently become administrator-only —
    # that failure is quiet in the other direction, and the person hitting it
    # is a member being refused something they used to be able to do.
    return Permission.DATASET_WRITE
