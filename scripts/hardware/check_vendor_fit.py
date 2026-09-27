#!/usr/bin/env python3
"""Compare original fit proxies with separately cached supplier STEP envelopes."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "hardware/candidates/passive-v3"
sys.path.insert(0, str(CANDIDATE / "cad"))
from v3_proxy import build  # noqa: E402
from v3_model import bbox  # noqa: E402
import cadquery as cq  # noqa: E402

def cylindrical_diameter_delta(proxy, vendor, diameter):
    def nearest(shape):
        return min(abs(2 * face._geomAdaptor().Cylinder().Radius() - diameter)
                   for face in shape.Faces() if face.geomType() == "CYLINDER")
    return nearest(proxy), nearest(vendor)


def cap_hole_centers(shape, diameter):
    points = set()
    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        cylinder = face._geomAdaptor().Cylinder()
        if abs(2 * cylinder.Radius() - diameter) < 0.02:
            origin = cylinder.Axis().Location()
            points.add((round(origin.X(), 5), round(origin.Y(), 5)))
    return sorted(points)




def main():
    interface = json.loads((CANDIDATE / "interface.json").read_text())
    register = json.loads((CANDIDATE / "sources/source-register.json").read_text())
    proxies = build(interface["dimensions"], register)
    for key, proxy in proxies.items():
        record = register["vendor_models"][key]
        path = ROOT / "hardware/.vendor-cache/passive-v3" / record["file"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing private vendor STEP: {path}. Run make fetch-vendor-sources first.")
        source = register["records"][record["file"]]
        import hashlib
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Vendor STEP cache hash mismatch: " + record["file"])
        vendor = cq.importers.importStep(str(path)).val()
        actual = bbox(vendor)["size_mm"]
        expected = bbox(proxy)["size_mm"]
        deltas = [round(expected[i] - actual[i], 5) for i in range(3)]
        if max(abs(x) for x in deltas) > record["proxy_envelope_tolerance_mm"]:
            raise ValueError(f"Proxy exceeds recorded envelope allowance: {key} {deltas}")
        print(f"{key}: proxy-minus-vendor XYZ mm = {deltas}")
        for trace, part, diameter in (
            ("tube.od", "tube", interface["dimensions"]["tube.od"]),
            ("tube.id", "tube", interface["dimensions"]["tube.id"]),
            ("flange.od", "flange", interface["dimensions"]["flange.od"]),
            ("flange.piston_diameter", "flange", interface["dimensions"]["flange.piston_diameter"]),
            ("aft_cap.penetrator_hole_diameter", "aft_cap", interface["dimensions"]["aft_cap.penetrator_hole_diameter"]),
        ):
            if key != part:
                continue
            proxy_error, vendor_error = cylindrical_diameter_delta(proxy, vendor, diameter)
            if max(proxy_error, vendor_error) > 0.02:
                raise ValueError(f"Supplier/fit bore mismatch: {trace}")
            print(f"{trace}: proxy/source nominal diameter error mm = "
                  f"{[round(proxy_error, 5), round(vendor_error, 5)]}")
        if key == "aft_cap":
            diameter = interface["dimensions"]["aft_cap.penetrator_hole_diameter"]
            centers = cap_hole_centers(proxy, diameter)
            original = cap_hole_centers(vendor, diameter)
            if len(centers) != 5 or len(original) != 5:
                raise ValueError("Supplier/proxy cap through-hole count differs")
            error = max(abs(a[i] - b[i]) for a, b in zip(centers, original) for i in (0, 1))
            if error > 0.02:
                raise ValueError("Supplier/proxy cap mounting centers differ")
            print(f"aft_cap five penetration centers: max proxy-minus-vendor delta mm = {round(error, 5)}")


if __name__ == "__main__":
    main()
