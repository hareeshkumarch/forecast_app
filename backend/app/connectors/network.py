from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import settings
from app.core.errors import ConnectorError

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

METADATA = "Connectors cannot reach link-local addresses, which is where cloud instance metadata and its credentials live."
LOOPBACK = "Connectors cannot reach this machine's own loopback address."
PRIVATE = (
    "Connectors cannot reach private addresses in this deployment. "
    "Set CONNECTOR_ALLOW_PRIVATE_HOSTS=true to reach a warehouse on your own network."
)


def _refusal(ip: IpAddress) -> str | None:
    if ip.is_link_local:
        return METADATA
    if ip.is_loopback or ip.is_unspecified:
        return LOOPBACK
    if (ip.is_private or ip.is_reserved or ip.is_multicast) and not (
        settings.connector_allow_private_hosts
    ):
        return PRIVATE
    return None


def assert_reachable(host: str) -> None:
    cleaned = (host or "").strip().strip("[]")
    if not cleaned:
        raise ConnectorError("No host is configured for this connector.")

    try:
        resolved = socket.getaddrinfo(cleaned, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ConnectorError(f"{cleaned} could not be resolved to an address.") from exc

    for entry in resolved:
        address = entry[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        refusal = _refusal(parsed)
        if refusal is not None:
            raise ConnectorError(refusal)


def assert_public_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ConnectorError("No endpoint URL is configured.")

    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ConnectorError("The endpoint must be an http:// or https:// URL.")
    if not parsed.hostname:
        raise ConnectorError("The endpoint URL names no host.")

    assert_reachable(parsed.hostname)
    return cleaned
