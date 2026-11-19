# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider discovery through Python entry points (group ``annona.providers``).

A plugin package declares, in its ``pyproject.toml``::

    [project.entry-points."annona.providers"]
    mystore = "my_package:MyStoreProvider"

The target is a class (or factory) with a class attribute ``info: ProviderInfo`` and a constructor
accepting keyword configuration. Opt-in providers are only created with ``accept_notice=True``.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import Any

from .base import NoticeNotAcceptedError, ProviderError, ProviderInfo, SupermarketProvider

GROUP = "annona.providers"


def _entry_points() -> dict[str, EntryPoint]:
    return {ep.name: ep for ep in entry_points(group=GROUP)}


def available_providers() -> list[ProviderInfo]:
    """Metadata of every installed provider, sorted by id."""
    infos = []
    for name, ep in sorted(_entry_points().items()):
        info = ep.load().info
        if info.id != name:
            raise ProviderError(f"entry point {name!r} declares provider id {info.id!r}")
        infos.append(info)
    return infos


def create_provider(
    provider_id: str, *, accept_notice: bool = False, **config: Any
) -> SupermarketProvider:
    """Instantiate a provider. Opt-in providers require ``accept_notice=True``."""
    eps = _entry_points()
    if provider_id not in eps:
        raise ProviderError(f"unknown provider {provider_id!r}; installed: {sorted(eps)}")
    factory = eps[provider_id].load()
    if factory.info.opt_in and not accept_notice:
        raise NoticeNotAcceptedError(
            f"{provider_id} is an opt-in provider; the user must accept its notice:\n"
            f"{factory.info.notice}"
        )
    provider = factory(**config)
    if not isinstance(provider, SupermarketProvider):
        raise ProviderError(f"{provider_id} does not implement SupermarketProvider")
    return provider
