"""Local monitor-only workspace and durable replay queue."""

from .errors import HubError
from .hub import Hub

__all__ = ["Hub", "HubError"]
