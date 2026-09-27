#!/usr/bin/env python3
"""Candidate evidence audit. Stdlib by default; --geometry explicitly reexecutes CAD."""
from __future__ import annotations
import sys
sys.dont_write_bytecode=True
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from candidate_parameters import CAD,ROOT,CONFIGURATION,REVISION,STATUS,arithmetic,baseline_check,digest,require,validate


def artifact_path(out,name):
    relative=Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts,"Unsafe artifact path")
    path=out/relative
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(out.resolve()),"Missing or unsafe artifact")
    return path


def audit(out):
    m=json.loads((out/"manifest.json").read_text())
    require(m.get("schema")=="poseidon.cad.candidate.v2","Wrong candidate manifest schema")
    require(m.get("configuration")==CONFIGURATION and m.get("revision")==REVISION,"Candidate must not rebind frozen1.1 identity")
    require(m.get("status")==STATUS and m.get("adopted") is False and m.get("build_authorized") is False and m.get("procurement_authorized") is False,"Candidate is non-adopted, not build/procurement authorized")
    require(m.get("active_hardware_populated") is False and m.get("physical_tests_performed")==[],"Physical/active boundary violated")
    require(m.get("units")=={"length":"mm","area":"mm2","volume":"mm3","mass":"kg"},"Candidate units mismatch")
    require(m.get("baseline_modified") is False and m["baseline"]==baseline_check(),"Frozen baseline binding drift")
    validate(m["parameters"])
    require(m["arithmetic"]==arithmetic(m["parameters"]),"Candidate area/quantity/bend arithmetic differs")
    for name,expected in m["source_files"].items():
        require(Path(name).name==name and digest(CAD/name)==expected,"Candidate source changed since generation: "+name)
    require(m["printable_whitelist"]==[] and m["stl_exports"]==[],"No pressure/primary-load or other STL exports allowed in candidate")
    require(m["thermal_claims"]["whole_box_air_pass"] is None and m["thermal_claims"]["pi_junction_pass"] is None and m["thermal_claims"]["residual_solar_fraction"] is None,"CAD cannot establish thermal or zero-sun acceptance")
    artifacts=m["artifacts"]
    names=[record["path"] for record in artifacts]
    require(len(names)==len(set(names)),"Duplicate artifact names")
    for record in artifacts:
        path=artifact_path(out,record["path"])
        require(path.stat().st_size==record["bytes"]>0 and digest(path)==record["sha256"],"Artifact checksum/size mismatch: "+record["path"])
        require(path.suffix.lower() not in (".stl",".3mf"),"Candidate has no printable parts")
        if path.suffix==".svg":
            require(ET.parse(path).getroot().tag.endswith("svg"),"Invalid SVG")
    actual={str(path.relative_to(out)) for path in out.rglob("*") if path.is_file() and path.name!="manifest.json"}
    require(actual==set(names),"Unlisted or missing candidate artifacts")
    assemblies={a["id"]:a for a in m["assemblies"]}
    require(len(assemblies)==len(m["assemblies"]) and set(assemblies)=={"C2-HUB","C2-REEF","C2-TOP"},"Changed candidate assembly coverage mismatch")
    checks=[]
    for a in assemblies.values():
        require(a["parts"],"Empty assembly")
        for key in ("step","drawing_dxf","drawing_svg"):
            require(a[key] in names,"Missing STEP or dimensioned drawing")
        step=artifact_path(out,a["step"]).read_text(errors="replace")
        require("MANIFOLD_SOLID_BREP" in step and "SI_UNIT(.MILLI.,.METRE.)" in step,"STEP lacks BRep or explicit mm units")
        for p in a["parts"]:
            require(p["revision"]==REVISION and p["status"]==STATUS,"Part candidate identity drift")
            require(p["printable"] is False and p["pressure_boundary"] is False,"Forbidden printable/pressure classification")
            require(p["bom_id"] and p["source_status"],"Part missing source/BOM identity")
            require(p["volume_mm3"]>0 and all(math.isfinite(n) and n>0 for n in p["bbox"]["size_mm"]),"Invalid part volume or bbox")
            if p["density_assumed_kg_m3"] is None:
                require(p["solid_equivalent_mass_kg"] is None,"No density-derived vendor envelope mass")
            else:
                require(abs(p["solid_equivalent_mass_kg"]-p["volume_mm3"]*p["density_assumed_kg_m3"]/1e9)<1e-8,"Mass arithmetic mismatch")
            for k in range(3):
                require(abs(p["bbox"]["max_mm"][k]-p["bbox"]["min_mm"][k]-p["bbox"]["size_mm"][k])<1e-5,"Inconsistent bbox dimensions")
        checks.extend(a["checks"])
    panels=[p for p in assemblies["C2-REEF"]["parts"] if p["id"] in ("C2-REEF-PV-1","C2-REEF-PV-2")]
    require(len(panels)==2 and all(p["bom_id"]=="V2-PV-001" for p in panels),"Exactly2 distinct physical panels required")
    for p in panels:
        require(all(abs(a-b)<1e-5 for a,b in zip(p["bbox"]["size_mm"],[668,425,25])),"One panel geometry does not match sourced dimensions")
    gap=panels[1]["bbox"]["min_mm"][1]-panels[0]["bbox"]["max_mm"][1]
    require(abs(gap-50)<1e-5,"Physical panel service gap drift")
    series=next(p for p in assemblies["C2-REEF"]["parts"] if p["id"]=="C2-REEF-SERIES-LINK")
    require(series["features"]["from"]=="PV1_POS" and series["features"]["to"]=="PV2_NEG" and series["features"]["arc_count"]==4,"Missing real series jumper topology/service loop")
    require(all(c.get("passed") is True for c in checks),"Stored CAD checks contain failure")
    require(m["checks"]=={"runtime_executed":True,"total":len(checks),"passed":len(checks),"failed":0},"Stored check counts inconsistent")
    require(not any(p["id"].startswith(("WET","ARRAY","PROJECTOR","WIPER")) for a in assemblies.values() for p in a["parts"]),"Baseline wet/active assemblies are out of candidate scope")
    return {"mode":"stdlib_candidate_evidence_audit","geometry_runtime_executed":False,"baseline_files_unchanged":m["baseline"]["files_checked"],
            "assemblies":len(assemblies),"artifacts":len(artifacts),"archived_runtime_checks":len(checks),"note":"Hashes, source/dimension/quantity arithmetic and archived evidence checked; OCP/STEP runtime did not execute in this audit."}


def geometry_audit(out):
    import cadquery as cq
    import model
    from exporter import roundtrip
    m=json.loads((out/"manifest.json").read_text())
    p=m["parameters"]
    hub,reef=model.build_hub(p),model.build_reef(p)
    top,_=model.build_top(hub,reef,p)
    checks=[]
    for a in (hub,reef,top):
        checks.extend(model.geometry_checks(a))
        checks.append(roundtrip(out/"step"/f"{a.id}.step",a.compound()))
        if a.keepouts:
            checks.append(roundtrip(out/"keepouts"/f"{a.id}_keepouts.step",cq.Compound.makeCompound([ko["shape"] for ko in a.keepouts.values()])))
    failures=[c for c in checks if not c["passed"]]
    require(not failures,"Runtime CAD checks failed: "+json.dumps(failures))
    panels=[p for p in reef.parts if p.id in ("C2-REEF-PV-1","C2-REEF-PV-2")]
    require(len(panels)==2 and abs(sum(p.shape.Volume() for p in panels)-2*668*425*25)<1e-5,"Actual panel solids/volume inconsistent")
    require(baseline_check()==m["baseline"],"Baseline changed during runtime audit")
    return {"mode":"candidate_cad_runtime_reexecution","geometry_runtime_executed":True,"checks":len(checks),"passed":len(checks),"failed":0,
            "panel_physical_count":len(panels),"step_files_reimported":6,"stl_exports":0,"note":"Rebuilt solids and cable sweeps, checked BRep/interference/contact/clearance and actual STEP roundtrips."}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    parser.add_argument("--geometry",action="store_true")
    args=parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.directory),sort_keys=True))
        if args.geometry:
            print(json.dumps(geometry_audit(args.directory),sort_keys=True))
    except (OSError,ValueError,TypeError,KeyError,ImportError,StopIteration) as error:
        print("Candidate CAD audit failed: "+str(error),file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
