"""Weather provider registry.

Each module in this package defines one provider class decorated with @register.
The rest of RBSB-Weather only talks to providers through ProviderManager
(manager.py), so adding a service means adding a module here, plus its tests;
nothing else changes.

Created By Shane BlackbuRn
"""

from __future__ import annotations

from typing import Optional

from .base import FEATURES, KeyMissing, Provider, ProviderInfo

REGISTRY: dict[str, type[Provider]] = {}
PLANNED: dict[str, ProviderInfo] = {}


def register(cls: type[Provider]) -> type[Provider]:
    REGISTRY[cls.info.id] = cls
    return cls


def plan(info: ProviderInfo) -> ProviderInfo:
    PLANNED[info.id] = info
    return info


def info(provider_id: str) -> Optional[ProviderInfo]:
    cls = REGISTRY.get(provider_id)
    return cls.info if cls else PLANNED.get(provider_id)


def integrated_ids() -> list[str]:
    return list(REGISTRY)


def all_infos() -> list[ProviderInfo]:
    """Integrated providers in registration order, then planned ones."""
    return [c.info for c in REGISTRY.values()] + list(PLANNED.values())


# Registration order is the order shown in Settings → Weather Providers.
from . import openmeteo, metno, openweather, weatherapi, visualcrossing, tomorrow, wunderground, planned  # noqa: E402,F401

__all__ = ["FEATURES", "KeyMissing", "PLANNED", "Provider", "ProviderInfo", "REGISTRY",
           "all_infos", "info", "integrated_ids", "plan", "register"]
