"""Live surface-v3 kernel checks. A missing interpreter fails; no skipped tests."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
CAD = ROOT/"hardware/candidates/surface-v3/cad"
KERNEL = Path(os.environ.get("POSEIDON_CAD_PYTHON") or ROOT/"hardware/cad/.venv/bin/python")
TIMEOUT = int(os.environ.get("POSEIDON_CAD_KERNEL_TIMEOUT_S", "900"))


class SurfaceV3KernelTests(unittest.TestCase):
    def scratch(self):
        parent = Path(os.environ.get("POSEIDON_SURFACE_V3_TEST_TMP") or tempfile.gettempdir()).resolve()
        return tempfile.TemporaryDirectory(prefix="surface-v3-kernel-", dir=parent)

    def run_code(self, code, cwd=None):
        preamble = f"import sys; sys.dont_write_bytecode=True; sys.path.insert(0,{str(CAD)!r})\n"
        result = subprocess.run([str(KERNEL), "-c", preamble+code], text=True, capture_output=True, timeout=TIMEOUT,
                                cwd=cwd, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        return result.stdout

    def test_01_kernel_preflight_is_real_solid(self):
        self.assertTrue(KERNEL.is_file(), "Required existing CadQuery interpreter missing")
        self.run_code("import cadquery as cq; s=cq.Workplane('XY').box(1,2,3).val(); assert s.isValid() and abs(s.Volume()-6)<1e-9")

    def test_02_archive_independently_rebuilt(self):
        output = self.run_code(f"from check import audit\nimport json\nr=audit({str(CAD/'generated/surface-v3')!r},True)\nassert r['kernel_executed'] and r['kernel_failed']==0 and r['coinstalled_pair_checks']==441\nprint(json.dumps(r))")
        result = json.loads(output.strip().splitlines()[-1])
        self.assertEqual(result["physical_parts"], 17)
        self.assertEqual(result["allocations"], 6)

    def test_02b_socket_bounds_ignore_display_mesh(self):
        self.run_code('''
from surface_contract import load
from surface_model import build, bbox
socket = build(load()).get("SV3_MAST_SOCKET").shape
analytic = bbox(socket)
socket.mesh(0.3, 0.35)
# OCCT's default BoundingBox includes cached tessellation tolerance and can
# differ between platforms; the archived dimensions must be analytic BRep.
assert socket.BoundingBox().xlen > analytic["size_mm"][0] + 0.1
assert bbox(socket) == analytic
''')

    def test_02c_socket_metadata_precision_and_diagnostics(self):
        self.run_code('''
from surface_contract import load, values
from surface_model import build
from check import close, metadata_differences
p = load()
socket = build(p).get("SV3_MAST_SOCKET")
archived = socket.metadata(values(p)["freeboard_mm"])
# Cross-drilled fused rings have platform-sensitive OCCT extrema (~1e-7 mm)
# and boolean volume in their last digits. Record 1e-6 mm / 1 mm3;
# raw solids still face BRep, interference, STEP and DXF comparisons.
assert archived["source_bbox_mm"]["min_mm"] == [-70, -70, -120]
assert archived["source_bbox_mm"]["max_mm"] == [70, 70, 0]
assert archived["volume_mm3"] == round(socket.shape.Volume())
socket.shape = socket.shape.scale(1.01)
rebuilt = socket.metadata(values(p)["freeboard_mm"])
assert not close(archived, rebuilt, 1e-7)
diff = "; ".join(metadata_differences(archived, rebuilt, 1e-7))
assert "bbox." in diff and "volume_mm3:" in diff, diff
assert "archived=" in diff and "rebuilt=" in diff and "absolute_delta=" in diff and "relative_delta=" in diff
''')

    def test_02d_socket_step_roundtrip_uses_recorded_volume_precision(self):
        with self.scratch() as tmp:
            self.run_code(f'''
from pathlib import Path
import shutil
import cadquery as cq
from surface_contract import load, values
from surface_export import step_check
step = Path({str(CAD/'generated/surface-v3/step/SV3_MAST_SOCKET.step')!r})
original = cq.importers.importStep(str(step)).val()
volume = original.Volume()
height = values(load())["freeboard_mm"]
def changed_by(delta):
    # Scale about the socket's local origin: bbox stays within STEP's 0.0001 mm
    # tolerance while the volume exposes its stricter, formerly failing limit.
    return original.translate((0, 0, -height)).scale((1 + delta/volume)**(1/3)).translate((0, 0, height))
sub_mm3 = changed_by(0.37)
same_precision = step_check(step, sub_mm3)
assert 0.36 < same_precision["volume_delta_mm3"] < 0.38
# The socket records whole mm3; a round-trip smaller than that quantum is
# legitimate across OCCT builds. All other parts retain the old raw limit.
assert same_precision["passed"], same_precision
control = Path({tmp!r})/"generic.step"
shutil.copyfile(step, control)
assert not step_check(control, sub_mm3)["passed"]
assert not step_check(step, changed_by(1.1))["passed"]
''', tmp)

    def test_03_interference_and_source_scale_mutations_rejected(self):
        self.run_code('''
from surface_contract import load
import surface_model as m
model=m.build(load())
base=m.geometry_checks(model)
assert all(r['passed'] for r in base)
pairs=[r for r in base if r['id'].startswith('interference:')]
assert len(pairs)==441
assert not any('SV3_FLOAT_COLLAR' in r['id'] and ('SV3_POLE_60MM' in r['id'] or 'SV3_SEABED_FOOTING' in r['id']) for r in pairs)
# Move one purchased envelope into its neighbour without touching source parameters.
model.get('SV3_PANEL_A').shape=model.get('SV3_PANEL_A').shape.translate((0,80,0))
model.get('SV3_HUB_HAMMOND_1550WJ').source_shape=model.get('SV3_HUB_HAMMOND_1550WJ').source_shape.scale(1.01)
failed=[r['id'] for r in m.geometry_checks(model) if not r['passed']]
assert any(x.startswith('interference:') and 'SV3_PANEL_A:SV3_PANEL_B' in x for x in failed),failed
assert 'sourced_dimensions:SV3_HUB_HAMMOND_1550WJ' in failed,failed
assert 'source_transform:SV3_PANEL_A' in failed,failed
assert 'source_transform:SV3_HUB_HAMMOND_1550WJ' in failed,failed
''')

    def test_04_open_solid_and_wrong_step_are_not_valid_evidence(self):
        with self.scratch() as tmp:
            self.run_code(f'''
from pathlib import Path
import cadquery as cq
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid
from surface_model import valid, build
from surface_contract import load
from surface_export import step_check
builder=BRep_Builder(); shell=TopoDS_Shell(); solid=TopoDS_Solid()
builder.MakeShell(shell); builder.Add(shell,cq.Face.makePlane(10,10).wrapped)
builder.MakeSolid(solid); builder.Add(solid,shell)
assert not valid(cq.Shape.cast(solid)), 'Open shell promoted to valid solid'
path=Path({tmp!r})/'wrong.step'
cq.exporters.export(cq.Workplane('XY').box(1,1,1),str(path))
assert not step_check(path,build(load()).get('SV3_TRAY_PLATE').shape)['passed']
''', tmp)

    def test_05_cross_bolt_bores_are_real_not_ignored_overlaps(self):
        self.run_code('''
from surface_contract import load,values,layout
import surface_model as m
p=load(); v=values(p); d=layout(p); model=m.build(p)
# Restore undrilled pole tube only: the allocated bolts must now collide with it.
model.get('SV3_POLE_60MM').shape=m.ring(v['pole_od_mm'],v['pole_od_mm']-2*v['pole_wall_mm'],d['pole_length_mm']).translate((0,0,-v['site_depth_mm']))
failed=[r['id'] for r in m.geometry_checks(model) if not r['passed']]
assert any(x.startswith('interference:pole:') and 'CROSS_BOLT_ALLOCATION_1' in x and 'SV3_POLE_60MM' in x for x in failed),failed
assert any(x.startswith('interference:pole:') and 'CROSS_BOLT_ALLOCATION_2' in x and 'SV3_POLE_60MM' in x for x in failed),failed
''')

    def test_06_float_clearance_uses_its_installed_surface_pose(self):
        self.run_code('''
from surface_contract import load
import surface_model as m
model=m.build(load())
# Move the collar into the actual float-pose hub; pole-mode common geometry is elsewhere.
model.get('SV3_FLOAT_COLLAR').shape=model.get('SV3_FLOAT_COLLAR').shape.translate((0,300,0))
failed=[r['id'] for r in m.geometry_checks(model) if not r['passed']]
assert any(x.startswith('interference:float:') and 'SV3_FLOAT_COLLAR' in x for x in failed),failed
assert not any(x.startswith('interference:pole:') and 'SV3_FLOAT_COLLAR' in x for x in failed),failed
''')

    def test_07_parameterized_fresh_generation_and_geometry_check(self):
        with self.scratch() as tmp:
            out = Path(tmp)/"generated"
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            command = [str(KERNEL), str(CAD/"generate.py"), "--output", str(out), "--water-depth-m", "7.2", "--tilt-deg", "3"]
            result = subprocess.run(command, text=True, capture_output=True, timeout=TIMEOUT, cwd=tmp, env=env)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.run_code(f"from check import audit\nfrom surface_contract import read_json\nr=audit({str(out)!r},True)\nm=read_json({str(out/'manifest.json')!r})\np=next(x for x in m['parts'] if x['name']=='SV3_POLE_60MM')\nassert abs(p['bbox']['size_mm'][2]-7700)<1e-6\nassert r['kernel_executed']", tmp)
            # Regeneration into evidence is refused without changing the original bytes.
            before = (out/"manifest.json").read_bytes()
            refused = subprocess.run(command, text=True, capture_output=True, timeout=TIMEOUT, cwd=tmp, env=env)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("new or empty", refused.stderr)
            self.assertEqual((out/"manifest.json").read_bytes(), before)

    def test_08_dxf_units_and_dimensions_are_reopened(self):
        with self.scratch() as tmp:
            self.run_code(f'''
from pathlib import Path
import ezdxf
from surface_contract import load
from surface_model import build
from surface_export import drawing,drawing_check
p=load(); shape=build(p).get('SV3_TRAY_PLATE').shape
path=Path({tmp!r})/'view.dxf'
assert drawing(path,shape,p)['passed']
doc=ezdxf.readfile(path); doc.units=ezdxf.units.M; doc.saveas(path)
assert not drawing_check(path,shape)['passed']
''', tmp)


if __name__ == "__main__":
    unittest.main()
