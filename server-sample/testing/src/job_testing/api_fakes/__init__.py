"""core-api のポートのメモリ上の Fake と、API の組み立て(build_api)。"""

from __future__ import annotations

from .build_api import DEFAULT_ACCESS, REQUIREMENT_K1, ApiFixture, build_api, submit_body
from .identity import (
    FakeIdentityProvider,
    InMemoryAccessConfigSource,
    InMemoryServiceCredentialRepository,
    InMemorySessionRepository,
)
from .live import SseReader, live_server

__all__ = [
    "DEFAULT_ACCESS",
    "REQUIREMENT_K1",
    "ApiFixture",
    "FakeIdentityProvider",
    "InMemoryAccessConfigSource",
    "InMemoryServiceCredentialRepository",
    "InMemorySessionRepository",
    "SseReader",
    "build_api",
    "live_server",
    "submit_body",
]
