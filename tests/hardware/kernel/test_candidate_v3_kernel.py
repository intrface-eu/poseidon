"""Live CadQuery/OCP negative tests for the passive-v3 candidate.

This directory has no __init__.py, so `make test-hardware` (discovery from
tests/hardware) never collects it and never records a skip. It runs only where a
CAD kernel exists: `make test-hardware-kernel` locally against
hardware/cad/.venv, and inside `make verify-cad-candidate` against the fresh
locked environment (POSEIDON_CAD_PYTHON). A missing kernel is a failure here,
not a skip: the stdlib audit in tests/hardware is not kernel evidence.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
CAD = ROOT / "hardware/candidates/passive-v3/cad"
KERNEL = Path(os.environ.get("POSEIDON_CAD_PYTHON") or ROOT / "hardware/cad/.venv/bin/python")
KERNEL_TIMEOUT_S = int(os.environ.get("POSEIDON_CAD_KERNEL_TIMEOUT_S", "900"))


class CandidateV3KernelTests(unittest.TestCase):
    def test_kernel_interpreter_exists(self):
        self.assertTrue(KERNEL.is_file(), f"CAD kernel interpreter missing: {KERNEL}. Set POSEIDON_CAD_PYTHON or create hardware/cad/.venv.")

    def test_live_kernel_rejects_interference_source_scale_invalid_brep_and_wrong_step(self):
        # A real child interpreter executes the same model/check functions as the
        # generator. Geometry mutations are in memory; the sole output is a fresh
        # STEP in a system temp directory. No source exports are overwritten.
        with tempfile.TemporaryDirectory(prefix="v3-live-negative-") as tmp:
            code = f'''
import sys, json
from pathlib import Path
sys.path.insert(0, {str(CAD)!r})
import cadquery as cq
import v3_contract as c, v3_model as m
from v3_export import step_roundtrip
model = m.build(c.load())
dome = next(p.shape for p in model.parts if p.name == "V3_DOME_POLYCARBONATE_BR107201")
before = m.bbox(dome)
dome.tessellate(0.3, 0.35)
assert m.bbox(dome) == before, "Display meshing changed analytic CAD bbox"
hydro = next(p for p in model.parts if p.name == "V3_AS1_RECEIVE_ONLY_SOURCE_ENVELOPE")
hydro.shape = hydro.shape.translate((-39, 0, 0))
model.source_shapes["tube"] = model.source_shapes["tube"].scale(1.01)
records = m.geometry_checks(model)
failed = [r["id"] for r in records if not r["passed"]]
assert any(r.startswith("interference:") and "AS1_RECEIVE" in r for r in failed), failed
assert "source_bbox:tube" in failed, failed
assert any(r.startswith("placed_source_bbox:V3_TUBE") for r in failed), failed
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid
builder = BRep_Builder()
shell, solid = TopoDS_Shell(), TopoDS_Solid()
builder.MakeShell(shell)
builder.Add(shell, cq.Face.makePlane(10, 10).wrapped)
builder.MakeSolid(solid)
builder.Add(solid, shell)
bad = cq.Shape.cast(solid)
assert not m.valid(bad), "Open one-face solid incorrectly treated as valid"
path = Path({tmp!r}) / "wrong.step"
cq.exporters.export(cq.Workplane("XY").box(1, 1, 1), str(path))
result = step_roundtrip(path, hydro.shape)
assert not result["passed"], result
print(json.dumps({{"kernel_executed": True, "all_pair_checks_executed": 300, "source_scale_rejected": True, "physical_interference_rejected": True, "invalid_brep_rejected": True, "wrong_step_rejected": True}}))
'''
            run = subprocess.run([str(KERNEL), "-c", code], capture_output=True, text=True, timeout=KERNEL_TIMEOUT_S, cwd=tmp, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            result = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertTrue(result["kernel_executed"])
            self.assertEqual(result["all_pair_checks_executed"], 300)


if __name__ == "__main__":
    unittest.main()
