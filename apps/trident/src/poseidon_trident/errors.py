"""Public errors for the local Trident monitor hub."""

from __future__ import annotations


class HubError(Exception):
    """A safe, structured error from the monitor workspace."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
