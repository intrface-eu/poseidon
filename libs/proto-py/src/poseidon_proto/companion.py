"""Companion intake transport constants, not acquisition/scientific validation.

The Acquisition-owned legacy_export_reader validates the actual seven-file
export. These definitions bound the HTTP/Hub transport and version its reply.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from types import MappingProxyType

from .models import ModelValidationError

COMPANION_SCHEMA_VERSION = "poseidon.recording-acquisition-companion.v1"
UPLOAD_ROLES = ("wav", "manifest", "binding", "source_receipt", "source_header", "source_final", "export_receipt")
DOCUMENT_ROLES = UPLOAD_ROLES[2:]
PART_LIMITS = MappingProxyType({
    "wav": 8388608,
    "manifest": 16384,
    "binding": 262144,
    "source_receipt": 16384,
    "source_header": 1048576,
    "source_final": 2097152,
    "export_receipt": 65536,
})
MAX_COMPANION_BYTES = 4194304
MULTIPART_OVERHEAD_BYTES = 262144
MAX_REQUEST_BYTES = 12861440
MAX_FILE_PARTS = 7
MAX_SCALAR_FIELDS = 0
MAX_ADMISSIONS = 2
MAX_QUEUE_SLOTS = 32
MAX_RETAINED_COMPANION_BYTES = 268435456

_FILENAME_PATTERNS = {
    "wav": r"chunk-[0-9]{6}\.wav\Z",
    "manifest": r"recording-[0-9]{6}\.v1\.json\Z",
    "binding": r"binding-[0-9]{6}\.json\Z",
    "source_receipt": r"source-receipt-[0-9]{6}\.json\Z",
    "source_header": r"source-header\.json\Z",
    "source_final": r"source-final\.json\Z",
    "export_receipt": r"export\.receipt\.json\Z",
}


def validate_filenames(filenames: Mapping[str, str]) -> dict[str, str]:
    """Check only fixed transport role/name syntax; never resolve a server path.

    Selected-index correspondence and receipt file references remain the
    scientific reader's responsibility, not a second validator here.
    """
    if not isinstance(filenames, Mapping) or set(filenames) != set(UPLOAD_ROLES):
        raise ModelValidationError("companion upload needs exactly seven named file roles")
    result = {}
    for role in UPLOAD_ROLES:
        name = filenames[role]
        if type(name) is not str or re.fullmatch(_FILENAME_PATTERNS[role], name) is None:
            raise ModelValidationError(f"invalid export basename for {role}")
        result[role] = name
    return result
