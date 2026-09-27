"""Publish synthetic REEF cross-language vectors without exercising radios."""
import json
from pathlib import Path

from poseidon_proto.reef import encode_frame, json_fields

ROOT = Path(__file__).resolve().parents[2]
frames = {
    "synthetic-unsynchronized-raw": [1, 1, 0, 60, 0, None, 3700, 0, 0, 1, 1234, 0, None],
    "synthetic-calibrated-claim": [1, 2, 8, 3600, 2, 1788825600, 4100, 5200, 0, 1, 2150, 1, 7],
    "synthetic-uint64-boundary": [1, 18446744073709551615, 4294967295, 4294967295, 1, 4294967295, 65535, 65535, 2, 3, -2147483648, 1, 65535],
    "synthetic-invalid-sensor": [1, 3, 0, 0, 0, None, None, None, 2, 2, None, 2, None],
}
vectors = [{"name": name, "source_kind": "synthetic", "hex": encode_frame(fields).hex(), "fields": json_fields(fields)} for name, fields in frames.items()]
valid = encode_frame(frames["synthetic-unsynchronized-raw"]).hex()
negatives = [
    {"name": "trailing-byte", "hex": valid + "00"},
    {"name": "nonminimal-version", "hex": "8d1801" + valid[4:]},
    {"name": "truncated", "hex": valid[:-2]},
    {"name": "indefinite-array", "hex": "9f" + valid[2:] + "ff"},
    {"name": "float", "hex": "8dfb3ff0000000000000" + valid[4:]},
]
output = ROOT / "contracts/v1/fixtures/reef-cbor-vectors.json"
output.write_text(json.dumps({"profile": "poseidon.reef-cbor.v1", "fport": 10, "evidence": "Synthetic codec vectors, not field packets or calibration evidence", "valid": vectors, "invalid": negatives}, indent=2) + "\n")
print(f"Emitted {len(vectors)} synthetic wire vectors and {len(negatives)} negative vectors")
