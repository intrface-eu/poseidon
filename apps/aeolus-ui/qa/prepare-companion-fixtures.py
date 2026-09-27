"""Prepare browser inputs with the actual Acquisition exporter and pure reader.

Read historical positive/zero packages unchanged. Supplementary exports use only
an owned copy of their synthetic source; never alter an accepted source or DB.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys

from poseidon_acoustic.legacy_export import EpochDeclaration, SegmentMapping, export_segments
from poseidon_acoustic.legacy_export_reader import ExportReadLimits, file_map_resolver, validate_export_bundle
from poseidon_proto.companion import UPLOAD_ROLES


def inspect(directory: Path, label: str, candidates: int, context: str) -> dict:
    receipt = (directory / "export.receipt.json").read_bytes()
    listed = json.loads(receipt)["files"]
    # Basenames come from the reader fixture, not an incoming upload. Fail closed
    # before filesystem reads; the actual reader owns all scientific checks.
    if any(Path(item["path"]).name != item["path"] or "\\" in item["path"] for item in listed):
        raise ValueError("fixture file is not a flat basename")
    files = {item["path"]: (directory / item["path"]).read_bytes() for item in listed}
    result = validate_export_bundle(receipt, file_map_resolver(files), limits=ExportReadLimits())
    return {
        "label": label, "directory": str(directory), "candidates": candidates,
        "context": context, "binding": json.loads(result.file_for_role("binding").data),
        "projection": json.loads(result.projection_bytes),
        "files": [{"role": role, "name": result.file_for_role(role).name,
                   "bytes": result.file_for_role(role).size, "sha256": result.file_for_role(role).sha256}
                  for role in UPLOAD_ROLES],
    }


def prepare(source_root: Path, owned: Path) -> Path:
    owned.mkdir(mode=0o700, parents=True, exist_ok=False)
    metadata = json.loads((source_root / "reader-fixtures.json").read_bytes())
    if metadata["synthetic"] is not True or [item["candidates"] for item in metadata["files"]] != [1, 0]:
        raise ValueError("expected Acquisition-owned positive/zero synthetic fixtures")
    values = [inspect(source_root / name, name, count, "synthetic-ui-companion-context")
              for name, count in (("positive", 1), ("zero-candidate", 0))]
    for value, expected in zip(values, metadata["files"]):
        if value["projection"]["export_receipt_sha256"] != expected["receipt_sha256"]:
            raise ValueError("historical Acquisition fixture identity changed")
    binding = values[0]["binding"]
    source_copy = owned / "source-copy"
    shutil.copytree(source_root / "source", source_copy, ignore=shutil.ignore_patterns(".writer.lock"))
    epoch = EpochDeclaration(**binding["time"]["epoch_declaration"])
    mapping = SegmentMapping(**binding["mapping"])
    changed = owned / "changed-budget"
    export_segments(source_copy, changed, source_id=binding["source_id"], mappings=(mapping,),
                    epoch=epoch, max_bytes=16_777_215)
    changed_value = inspect(changed, "changed-budget", 1, values[0]["context"])
    # Same source/mapping/epoch/binding, distinct reader-valid export budget.
    assert changed_value["binding"] == binding
    assert changed_value["projection"]["export_receipt_sha256"] != values[0]["projection"]["export_receipt_sha256"]
    assert changed_value["projection"]["manifest"] == values[0]["projection"]["manifest"]
    assert changed_value["projection"]["header_sha256"] == values[0]["projection"]["header_sha256"]
    assert changed_value["projection"]["final_sha256"] == values[0]["projection"]["final_sha256"]
    final = source_copy / "segments.acquisition-v1.json"
    final_object = json.loads(final.read_bytes())
    final.chmod(0o600)
    final.write_bytes(json.dumps(final_object, indent=2, sort_keys=True).encode("utf-16"))
    final.chmod(0o400)
    utf16 = owned / "utf16-final"
    export_segments(source_copy, utf16, source_id=binding["source_id"],
                    mappings=(replace(mapping, recording_id="synthetic-reader-ui-utf16"),),
                    epoch=replace(epoch, declared_by="<img src=x onerror=syntheticOnly()>",
                                  evidence_ref="javascript:syntheticOnly()"))
    utf16_value = inspect(utf16, "utf16-final", 1, "synthetic-ui-utf16-context")
    assert (utf16 / "source-final.json").read_bytes().startswith((b"\xff\xfe", b"\xfe\xff"))
    catalog = owned / "browser-fixtures.json"
    catalog.write_text(json.dumps({"reader": "poseidon_acoustic.legacy_export_reader.validate_export_bundle",
                                   "synthetic": True, "fixtures": [*values, utf16_value],
                                   "changed": changed_value}, sort_keys=True) + "\n")
    return catalog


if __name__ == "__main__":
    print(prepare(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
