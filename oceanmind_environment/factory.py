"""Builds the configured provider. Consumers (preprocessing, services) call `build_provider(cfg)` and see only the EnvironmentalDataProvider interface; which
concrete provider is behind it is decided by `environment_provider.provider` in config.yaml. A future real provider registers itself in PROVIDERS."""
from __future__ import annotations

from functools import lru_cache

from .base import EnvironmentalDataProvider
from .pacific_config import PacificDomainConfig
from .noaa_oisst import NoaaOisstPacificProvider
from .temporary_pacific import TemporaryPacificProvider

PROVIDERS: dict[str, type[EnvironmentalDataProvider]] = {
    "temporary_pacific": TemporaryPacificProvider,
    "noaa_oisst_pacific": NoaaOisstPacificProvider,
}


@lru_cache(maxsize=4)
def _build(config: PacificDomainConfig) -> EnvironmentalDataProvider:
    cls = PROVIDERS[config.provider]
    return cls(config, config.store) if cls is NoaaOisstPacificProvider else cls(config)


def build_provider(cfg) -> EnvironmentalDataProvider:
    """cfg: a loaded project config containing an `environment_provider` section. Providers are cached per configuration."""
    if "environment_provider" not in cfg:
        raise KeyError("config has no 'environment_provider' section; cannot build an environmental data provider")
    config = PacificDomainConfig.from_cfg(cfg)
    if config.provider not in PROVIDERS:
        raise ValueError(f"unknown environment provider {config.provider!r}; registered: {sorted(PROVIDERS)}")
    return _build(config)
