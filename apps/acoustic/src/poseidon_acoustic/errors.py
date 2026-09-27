"""Errors safe to show as command-line diagnostics."""


class AcousticError(Exception):
    """Base error for passive replay input, storage, and output failures."""


class InputError(AcousticError):
    """The supplied manifest, WAV, or detector setting is invalid."""


class StoreError(AcousticError):
    """The SQLite evidence store cannot be used without losing provenance."""


class DemoError(AcousticError):
    """The synthetic demo output path is unsafe or unavailable."""
