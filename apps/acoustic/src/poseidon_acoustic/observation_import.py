"""Offline, lossless binding of accepted Platform independent observations.

The caller exports stored rows and supplies explicit protocol acceptance. This
module does not contact the API, authenticate an export, or approve a protocol.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from poseidon_proto import canonical_json
from poseidon_proto.platform import parse_utc, validate_contract

from .dataset import exact, identifier, number, read_json, text, write_new_json
from .errors import InputError

EXPORT_FORMAT = "poseidon-platform-observation-export-v1"
IMPORT_FORMAT = "poseidon-platform-observation-import-v1"
POLICY_KEYS = {"protocol_id", "acceptance_ref", "accepted_by", "accept_feeding_observed_as_feeding",
               "accept_no_feeding_observed_as_reviewed_negative", "allow_limited_visibility",
               "max_sync_uncertainty_s", "confidence"}


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def convert_observations(export: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    exact(export, {"format", "recording_id", "recording_sha256", "source_kind", "observations"}, "export")
    if export["format"] != EXPORT_FORMAT:
        raise InputError("unsupported Platform observation export")
    identifier(export["recording_id"], "recording_id")
    sha = export["recording_sha256"]
    if type(sha) is not str or len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
        raise InputError("invalid exported recording checksum")
    if export["source_kind"] not in ("synthetic", "field"):
        raise InputError("legacy recording evaluation cannot silently map bench provenance")
    exact(policy, POLICY_KEYS, "explicit protocol acceptance")
    identifier(policy["protocol_id"], "protocol_id")
    text(policy["acceptance_ref"], "acceptance_ref")
    text(policy["accepted_by"], "accepted_by")
    for key in ("accept_feeding_observed_as_feeding", "accept_no_feeding_observed_as_reviewed_negative",
                "allow_limited_visibility"):
        if type(policy[key]) is not bool:
            raise InputError(f"{key} requires an explicit boolean decision")
    maximum = number(policy["max_sync_uncertainty_s"], "max_sync_uncertainty_s")
    if policy["confidence"] not in ("high", "medium", "low"):
        raise InputError("protocol acceptance must declare the mapped confidence grade")
    rows = export["observations"]
    if type(rows) is not list or len(rows) > 10000:
        raise InputError("export supports at most 10000 stored observation rows")
    mapped, excluded, seen = [], [], set()
    export_digest = _digest(export)
    for row in rows:
        request_keys = {"id", "start_s", "end_s", "label", "notes", "observer", "expected_revision"}
        stored_keys = {"recording_id", "revision", "actor_subject", "auth_mode", "created_at", "updated_at", "provenance"}
        if type(row) is not dict:
            raise InputError("stored observation must be an object")
        optional = {"review_context"} if "review_context" in row else set()
        exact(row, request_keys | stored_keys | optional, "stored observation")
        request = validate_contract("independent-observation", {key: row[key] for key in request_keys | optional})
        if row["id"] in seen:
            raise InputError("select one explicit revision per observation; history cannot be scored twice")
        seen.add(row["id"])
        if row["recording_id"] != export["recording_id"]:
            raise InputError("observation recording mismatch")
        exact(row["provenance"], {"recording_sha256", "source_kind"}, "stored provenance")
        if row["provenance"] != {"recording_sha256": sha, "source_kind": export["source_kind"]}:
            raise InputError("observation source provenance mismatch")
        if (type(row["revision"]) is not int or row["revision"] < 1
                or row["revision"] != row["expected_revision"] + 1):
            raise InputError("stored observation revision must follow expected_revision")
        text(row["actor_subject"], "actor_subject")
        if row["auth_mode"] not in ("local_development_key", "scoped_token"):
            raise InputError("unsupported authentication provenance")
        parse_utc(row["created_at"])
        parse_utc(row["updated_at"])
        context = request.get("review_context")
        reasons = []
        if context is None:
            reasons.append("missing_review_context")
        else:
            if context["reviewed_coverage"] is not True:
                reasons.append("not_independently_reviewed_coverage")
            if context["protocol_id"] != policy["protocol_id"]:
                reasons.append("unaccepted_protocol")
            if not context["evidence_refs"]:
                reasons.append("missing_evidence_reference")
            if context["sync_uncertainty_s"] is None:
                reasons.append("unknown_sync_uncertainty")
            elif context["sync_uncertainty_s"] > maximum:
                reasons.append("excess_sync_uncertainty")
            if request["label"] in ("feeding_observed", "no_feeding_observed"):
                visible = context["visibility"] == "clear" or (
                    context["visibility"] == "limited" and policy["allow_limited_visibility"])
                if not visible:
                    reasons.append("unaccepted_visibility")
        if request["label"] == "feeding_observed" and not policy["accept_feeding_observed_as_feeding"]:
            reasons.append("feeding_mapping_not_accepted")
        if request["label"] == "no_feeding_observed" and not policy["accept_no_feeding_observed_as_reviewed_negative"]:
            reasons.append("negative_mapping_not_accepted")
        if reasons:
            excluded.append({"id": row["id"], "revision": row["revision"], "reasons": reasons})
            continue
        label = {"feeding_observed": "observed_predation", "no_feeding_observed": "hard_negative",
                 "uncertain": "unknown", "not_visible": "unusable"}[request["label"]]
        visibility = {"clear": "visible", "limited": "limited", "not_visible": "not_visible",
                      "unknown": "not_applicable"}[context["visibility"]]
        mapped.append({
            "observation_id": row["id"], "start_s": row["start_s"], "end_s": row["end_s"],
            "label": label, "observer_id": "observer_" + hashlib.sha256(row["observer"].encode()).hexdigest(),
            "evidence_ref": f"platform-export:{export_digest}#{row['id']}@{row['revision']}",
            "confidence": policy["confidence"], "visibility": visibility,
            "timing_uncertainty_s": context["sync_uncertainty_s"],
        })
    ordered = sorted(rows, key=lambda row: (row["start_s"], row["end_s"], row["id"]))
    # Even excluded masks cannot overlap accepted intervals without adjudication.
    for first, second in zip(ordered, ordered[1:]):
        if second["start_s"] < first["end_s"]:
            raise InputError("overlapping Platform observations require explicit adjudication")
    mapped.sort(key=lambda row: (row["start_s"], row["end_s"], row["observation_id"]))
    result = {"format": IMPORT_FORMAT, "source_export": export, "source_export_sha256": export_digest,
              "protocol_acceptance": policy, "protocol_acceptance_sha256": _digest(policy),
              "observations": mapped, "excluded": excluded,
              "permission_verified": False, "authenticated_export_verified": False,
              "stock_loss_claim": False}
    result["import_id"] = "observation_import_" + _digest(result)
    return result


def import_file(export_path: Path, policy_path: Path, output_path: Path) -> dict[str, Any]:
    result = convert_observations(read_json(export_path), read_json(policy_path))
    write_new_json(output_path, result)
    return result


def validate_import(path: Path, recording_id: str, source_sha256: str, source_kind: str) -> dict[str, Any]:
    data = read_json(path)
    if "source_export" not in data or "protocol_acceptance" not in data:
        raise InputError("observation import lacks source and protocol acceptance")
    regenerated = convert_observations(data["source_export"], data["protocol_acceptance"])
    if canonical_json(data) != canonical_json(regenerated):
        raise InputError("observation import content mismatch")
    export = data["source_export"]
    if (export["recording_id"], export["recording_sha256"], export["source_kind"]) != (
            recording_id, source_sha256, source_kind):
        raise InputError("observation import does not bind this recording")
    return data
