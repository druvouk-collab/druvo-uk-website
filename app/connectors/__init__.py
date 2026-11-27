"""Marketplace connectors that run in the cloud (no Mac required).

A connector is registered here once its platform API code exists in the cloud *and* credentials are stored.
eBay and Amazon connectors will be ported from the existing DRUVO Manager after the code audit (not rebuilt
from scratch). Vinted/Depop connectors depend on platform approval (Vinted Pro Integrations / Depop Selling API).
"""

from __future__ import annotations

from app.connectors.base import Connector, ConnectorError, PublishResult, readiness_problems

_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    _REGISTRY[cls.channel_code] = cls
    return cls


def connector_for(channel_code: str) -> Connector | None:
    """Return a live connector only if code exists AND credentials are stored for this platform."""
    cls = _REGISTRY.get(channel_code)
    if cls is None:
        return None
    from app.services.credentials import load_credentials

    creds = load_credentials(channel_code)
    if creds is None:
        return None
    return cls(creds)


def registered_codes() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["Connector", "ConnectorError", "PublishResult", "connector_for", "readiness_problems", "register",
           "registered_codes"]
