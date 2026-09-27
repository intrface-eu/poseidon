#!/usr/bin/env python3
"""Generate an additive NON-ADOPTED passive-v2 candidate into a clean owned directory."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
from candidate_parameters import CAD, CONFIGURATION, REVISION, STATUS, arithmetic, baseline_check, digest, load


def prepare_output(output):
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError("Output must be a NEW or EMPTY owned directory; no overwrite of candidate or1.1 files")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("step", "keepouts", "drawings", "views"):
        (output/name).mkdir()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--parameters",type=Path,default=CAD/"parameters.json")
    args=parser.parse_args(argv)
    try:
        p=load(args.parameters)
        frozen=baseline_check()
        prepare_output(args.output)
    except (ValueError,OSError,KeyError,TypeError) as error:
        parser.error(str(error))
    import model
    from exporter import export
    hub,reef=model.build_hub(p),model.build_reef(p)
    top,placements=model.build_top(hub,reef,p)
    records=[]
    for a in (hub,reef,top):
        print(f"Exporting {a.id}: {len(a.parts)} parts, {len(a.keepouts)} keepouts",flush=True)
        records.append(export(a,args.output))
    checks=[check for a in records for check in a["checks"]]
    failed=[c for c in checks if not c["passed"]]
    mechanical={}
    for a in (hub,reef):
        for part in a.parts:
            key=a.id+"/"+part.bom_id
            record=mechanical.setdefault(key,{"id":part.bom_id,"assembly":a.id,"geometry_instances":[],"description":part.description,"procurement_authorized":False,
                                               "quantity_note":"Model fragments can share a purchased parent; only V2-PV-001 distinct panel bodies establish quantity2, not junction allocations."})
            record["geometry_instances"].append(part.id)
    (args.output/"bom-links.json").write_text(json.dumps({"revision":REVISION,"status":STATUS,"parts":list(mechanical.values()),
        "purchased_panel_quantity":2,"panel_bom_id":"V2-PV-001","panel_quantity_instances":["C2-REEF-PV-1","C2-REEF-PV-2"],
        "top_placements_excluded_from_quantities":True},indent=2)+"\n")
    manifest={"schema":"poseidon.cad.candidate.v2","configuration":CONFIGURATION,"revision":REVISION,"status":STATUS,
              "generated_at_utc":datetime.now(timezone.utc).isoformat(),"units":{"length":"mm","area":"mm2","volume":"mm3","mass":"kg"},
              "adopted":False,"build_authorized":False,"procurement_authorized":False,"active_hardware_populated":False,"physical_tests_performed":[],
              "baseline":frozen,"baseline_modified":False,"parameters":p,"arithmetic":arithmetic(p),"assembly_translations_mm":placements,
              "assemblies":records,"printable_whitelist":[],"stl_exports":[],
              "runtime":{"python":platform.python_version(),"cadquery":importlib.metadata.version("cadquery"),"cadquery_ocp":importlib.metadata.version("cadquery-ocp"),"ezdxf":importlib.metadata.version("ezdxf"),
                         "environment":"hardware/cad/.venv reused read-only; no environment or baseline source/lock mutations"},
              "source_files":{name:digest(CAD/name) for name in ("candidate_parameters.py","parameters.json","model.py","exporter.py","generate.py","baseline-lock.json")},
              "checks":{"runtime_executed":True,"total":len(checks),"passed":len(checks)-len(failed),"failed":len(failed)},
              "thermal_claims":{"whole_box_air_pass":None,"pi_junction_pass":None,"component_heat_capture_fraction":None,"residual_solar_fraction":None,
                                "note":"Geometric collector/TIM/wall/sink contacts only. Parent source/calculation package owns analytical screens; no fitted whole-box thermal resistance or zero-sun assumption."},
              "remaining_gates":["No adoption, build, purchase or physical qualification","Exact panel clamp zones/fasteners, stock cut, joints, wind/fatigue/corrosion and farm supports",
                                 "Panel junction/terminal coordinates, cable conductor/connector/protection/strain and safe disconnect procedure",
                                 "Thermal component heat capture, source-to-collector path, TIM pressure/flatness/creep, installed sink performance and shaded solar coupling",
                                 "Complete field USB-C source/protection/inline cable envelope and ingress-preserving enclosure modifications",
                                 "Power part drawing conflicts, terminal/ventilation/charge-disable cable and complete electrical fit review"]}
    manifest["artifacts"]=[{"path":str(f.relative_to(args.output)),"bytes":f.stat().st_size,"sha256":digest(f)} for f in sorted(args.output.rglob("*")) if f.is_file()]
    after=baseline_check()
    if after!=frozen:
        raise ValueError("Frozen baseline changed during generation")
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n")
    print(json.dumps(manifest["checks"]),flush=True)
    if failed:
        for failure in failed:
            print(json.dumps(failure),file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
