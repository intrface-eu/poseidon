#!/usr/bin/env python3
"""Generate the non-adopted surface-v3 into --output NEW_OR_EMPTY_DIRECTORY."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
import copy
from datetime import datetime, timezone
import importlib.metadata
from pathlib import Path
import platform
import json
from surface_contract import (CAD, CANDIDATE, ROOT, STATUS, SENTENCE, GLB_NAME, values, load, validate,
                              baseline_check, prepare_output, write_json, digest, mechanics)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--interface", type=Path, default=CANDIDATE/"interface.json")
    parser.add_argument("--water-depth-m", type=float, help="Illustrative water depth; pole length = depth + freeboard")
    parser.add_argument("--freeboard-m", type=float, help="Tray underside/pole top elevation above water")
    parser.add_argument("--tilt-deg", type=float, help="Panel drainage slope, 3 to 5 degrees")
    args = parser.parse_args(argv)
    try:
        p = copy.deepcopy(load(args.interface))
        for value, name, factor in ((args.water_depth_m, "site_depth_mm", 1000),
                                    (args.freeboard_m, "freeboard_mm", 1000), (args.tilt_deg, "panel_tilt_deg", 1)):
            if value is not None:
                p["parameters"][name]["value"] = value*factor
                p["parameters"][name]["basis"] += " Runtime CLI design-assumption override; not a site measurement."
        validate(p)
        baseline = baseline_check()
        # Fail before creating output if the required kernel is missing or broken.
        import cadquery as cq
        probe = cq.Workplane("XY").box(1, 2, 3).val()
        if not probe.isValid() or abs(probe.Volume()-6) > 1e-9:
            raise ValueError("CadQuery valid-solid preflight failed; no substitution")
        out = prepare_output(args.output)
        from surface_model import build, geometry_checks, bbox
        from surface_export import export
        from check import audit, SOURCE_FILES
        model = build(p)
        parts = model.metadata()  # Capture analytic bounds before display meshing.
        checks = geometry_checks(model)
        failures = [r for r in checks if not r["passed"]]
        if failures:
            write_json(out/"failed-checks.json", failures)
            raise ValueError("Model checks failed: "+str(failures))
        print(f"Built {len(parts)} parts/allocations; {len(checks)} construction checks passed", flush=True)
        mass = mechanics(p, parts)
        assembly_bounds = {variant: bbox(model.compound(variant)) for variant in ("pole", "float")}
        write_json(out/"interface-used.json", p)
        write_json(out/"mass-displacement.json", mass)
        checks.extend(export(model, out, parts, mass))
        failures = [r for r in checks if not r["passed"]]
        if failures:
            raise ValueError("Export checks failed: "+str(failures))
        manifest = {"schema": "poseidon.surface-v3.manifest.v1", "configuration": "surface-v3", "revision": p["revision"],
                    "status": STATUS, "adopted": False, "build_authorized": False, "physical_tests_performed": 0,
                    "generated_utc": datetime.now(timezone.utc).isoformat(), "boundary": SENTENCE,
                    "interface": p, "baseline": baseline,
                    "construction_sources": {str((CANDIDATE/f).relative_to(ROOT)): digest(CANDIDATE/f) for f in SOURCE_FILES},
                    "runtime": {"python": platform.python_version(), "cadquery": importlib.metadata.version("cadquery"),
                                "cadquery_ocp": importlib.metadata.version("cadquery-ocp"), "ezdxf": importlib.metadata.version("ezdxf"),
                                "kernel_preflight": "isValid 1x2x3 mm box, volume 6 mm3", "new_installs": 0},
                    "parts": parts, "assembly_bounds_mm": assembly_bounds, "mass_displacement": mass,
                    "canonical_glb": GLB_NAME, "hierarchy": "hierarchy.json", "open_gates": p["open_gates"],
                    "checks": {"kernel_executed": True, "total": len(checks), "failed": 0}, "check_records": checks,
                    "artifacts": [{"path": str(f.relative_to(out)), "sha256": digest(f), "bytes": f.stat().st_size}
                                  for f in sorted(out.rglob("*")) if f.is_file()]}
        if baseline_check() != baseline:
            raise ValueError("Frozen source changed during generation")
        write_json(out/"manifest.json", manifest)
        result = audit(out)
        print(json.dumps({"generation_checks": len(checks), "audit": result}, indent=2), flush=True)
        return 0
    except Exception as error:
        print("FAIL (partial new output retained): "+str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
