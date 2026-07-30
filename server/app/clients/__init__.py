"""Provider client factory — honors MOCK_APIS."""
from __future__ import annotations

from functools import lru_cache

from ..config import get_settings


@lru_cache
def get_wavespeed():
    if get_settings().mock_apis:
        from .mocks import MockWaveSpeedClient
        return MockWaveSpeedClient()
    from .wavespeed import WaveSpeedClient
    return WaveSpeedClient()


@lru_cache
def get_tripo():
    if get_settings().mock_apis:
        from .mocks import MockTripoClient
        return MockTripoClient()
    from .tripo import TripoClient
    return TripoClient()
