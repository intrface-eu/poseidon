#!/usr/bin/env python3
"""Generate Poseidon Trident passive-v3 by Intrface into a NEW or EMPTY output."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
from v3_contract import CANDIDATE, SCHEMA, STATUS, baseline_check, digest, load, prepare_output, source_bindings, stack_budget, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--interface", type=Path, default=CANDIDATE / "interface.json")
    args = parser.parse_args(argv)
    try:
        p = load(args.interface)
        baseline = baseline_check()
        prepare_output(args.output)  # Refusal works with stdlib before importing CAD.
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    try:
        import v3_model
        from v3_export import export
        model = v3_model.build(p)
        print(f"Built {len(model.parts)} physical parts and {len(model.empty)} EMPTY allocations", flush=True)
        checks = v3_model.geometry_checks(model)
        failed = [c for c in checks if not c["passed"]]
        if failed:
            write_json(args.output / "failed-checks.json", failed)
            raise ValueError("Kernel geometry checks failed: " + json.dumps(failed))
        print(f"Kernel geometry checks: {len(checks)} passed", flush=True)
        checks += export(model, args.output)
        mechanics = v3_model.mass_displacement(model)
        write_json(args.output / "mass-displacement.json", mechanics)
        failures = [c for c in checks if not c["passed"]]
        manifest = {
            "schema": SCHEMA, "product": "Poseidon Trident", "company": "Intrface", "reuse_rights": p["reuse_rights"], "configuration": "passive-v3", "revision": "HW-CAND-3.0", "status": STATUS,
            "generated_utc": datetime.now(timezone.utc).isoformat(), "adopted": False, "build_authorized": False, "procurement_authorized": False,
            "active_emission_hardware_populated": False, "physical_tests_performed": [], "units": p["units"], "interface": p,
            "baseline": baseline, "source_files": source_bindings(), "stack_budget": stack_budget(p),
            "runtime": {"python": platform.python_version(), "cadquery": importlib.metadata.version("cadquery"), "cadquery_ocp": importlib.metadata.version("cadquery-ocp"), "ezdxf": importlib.metadata.version("ezdxf"), "environment": "Existing hardware/cad/.venv reused read-only; no install/sync/config changes", "model_identity": "Not inferred by generator; child execution report records actual runtime context"},
            "parts": [part.metadata() for part in model.parts], "empty_nonphysical": [part.metadata() for part in model.empty],
            "physical_bbox": v3_model.bbox(model.compound()), "mass_displacement": mechanics,
            "checks": {"kernel_executed": True, "total": len(checks), "passed": len(checks)-len(failures), "failed": len(failures), "physical_pair_checks": len(model.parts)*(len(model.parts)-1)//2},
            "check_records": checks, "canonical_glb": "INTRFACE_PASSIVE_V3.glb", "hierarchy": "hierarchy.json",
            "printable_whitelist": [], "open_gates": p["open_gates"],
            "boundary": p["required_sentence"],
        }
        manifest["artifacts"] = [{"path": str(f.relative_to(args.output)), "sha256": digest(f), "bytes": f.stat().st_size} for f in sorted(args.output.rglob("*")) if f.is_file()]
        if baseline_check() != baseline:
            raise ValueError("Immutable baseline changed during generation")
        write_json(args.output / "manifest.json", manifest)
        if failures:
            raise ValueError("Export checks failed: " + json.dumps(failures))
        # This audit also validates metre-scale GLB geometry, hierarchy and mass
        # arithmetic; it does not claim a second kernel run.
        import check as checker
        audit = checker.audit(args.output)
        print(json.dumps({"generation": manifest["checks"], "audit": audit}, sort_keys=True), flush=True)
        return 0
    except Exception as error:
        print("Candidate generation failed; partial output preserved: " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
