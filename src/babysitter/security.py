"""Small rules that keep the assistant on this computer.

Phase 1 only talks to Ollama at 127.0.0.1. It does not phone home.
"""

from __future__ import annotations

LOCAL_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
LOCAL_BINDINGS = {"127.0.0.1", "::1", "localhost"}
# 0.0.0.0 and :: mean "every network interface", which is not private.
PUBLIC_BINDINGS = {"0.0.0.0", "::", ""}


def require_local_host(host: str) -> None:
    if host != LOCAL_HOST:
        raise ValueError(
            "BabySitter only talks to Ollama on this computer (127.0.0.1)."
        )


def bind_is_private(addresses: list[str]) -> bool:
    """True when every listener is loopback, not the whole network."""
    if not addresses:
        return False
    return all(address in LOCAL_BINDINGS for address in addresses)


def bind_is_public(addresses: list[str]) -> bool:
    return any(address in PUBLIC_BINDINGS for address in addresses)
