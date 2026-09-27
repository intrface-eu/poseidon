"""Pure domain-separated platform signing bytes, without Hub or crypto imports."""
from __future__ import annotations

import re

from .models import ModelValidationError
from .platform import canonical_json

_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def signing_bytes(payload: dict, key_id: str) -> bytes:
    """Serialize exactly the approved poseidon-json-v1 signed payload domain.

    Callers validate the signed-manifest contract before signature verification.
    This function does not sign, load keys, or assert artifact compatibility.
    """
    if type(key_id) is not str or not _KEY_ID.fullmatch(key_id):
        raise ModelValidationError("key_id must be a safe ASCII identifier")
    return b"poseidon.signed-manifest.v1\0" + key_id.encode("ascii") + b"\0" + canonical_json(payload)
