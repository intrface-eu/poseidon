# Passive-v2 digital candidate

Configuration `passive-v2`, revision `HW-CAND-2.0`, status **NON_ADOPTED_NOT_BUILD_AUTHORIZED**. This candidate does not replace HW-REF-1.1. The historical hardware/reference file lock excludes supplier captures and still checks every listed file by SHA-256. No purchase, fabrication, energization, site placement, pressure test or acoustic operation is authorized.

## Reproduce with the existing locked CAD environment

Run from the repository root. The CAD interpreter/environment established for wave1 is reused read-only; do not change its source manifest, lockfile or environment during candidate verification. Choose a new output directory for every run.

```sh
OUT="$(mktemp -d /tmp/poseidon-passive-v2.XXXXXX)"
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python hardware/candidates/passive-v2/cad/generate.py --output "$OUT/cad"
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python hardware/candidates/passive-v2/cad/check.py "$OUT/cad" --geometry
PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/thermal/model.py --output "$OUT/thermal.json"
PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/power/calculate.py > "$OUT/power.json"
PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/check_candidate.py --output "$OUT/review.json"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
printf 'Candidate outputs: %s\n' "$OUT"
```

The baseline's pinned CadQuery/OCP toolchain is recorded in `hardware/cad/pyproject.toml` and `uv.lock`. Its setup instructions remain in the unchanged `HARDWARE.md`. Output into a new owned directory; none of the commands above adopts a candidate or changes the baseline. Stdlib manifest audits alone do not execute CAD geometry; run the explicit `--geometry` command.

## What changed digitally

| ID | Artifact | Change and evidence boundary |
|---|---|---|
| C2-01 | `interface.json`, `sources/thermal-sources.json` | Supplier URL/hash/date and extracted dimensions for the Hammond enclosure, Wakefield sink-stock/profile and Henkel interface material; private source documents are fetched on demand. |
| C2-02 | `cad/` | Editable candidate HUB/REEF/TOP source, actual STEP assemblies, dimensioned DXF/SVG views and checks. No pressure parts or STL. The fin-field block reserves source-sized space; it does not invent a manufactured fin profile. |
| C2-03 | `power/` | Separate sourced BMS/regulators/disconnect/control-cable/connector candidate, BOM, wire schedule, two-series-panel calculations, ancillary demand and precise source/protection blockers. |
| C2-04 | `thermal/` | Dimension/material/contact/sink/shade network and26 sensitivity cases at unchanged35°C ambient,21.857142857W enclosed heat and48W potential absorbed sun. Installed thermal acceptance remains UNKNOWN. |
| C2-05 | `check_candidate.py`, `review-results.json` | Historical hash preservation and wind-area/force comparison. Two physical panel bodies,50mm gap,668×900mm panel-pair footprint and0.5678m² total panel area. |

The real two-panel candidate uses2×SPM040401200 in2S1P, not one-panel CAD with doubled software watts. The unchanged1PSH/27.5247475Wh/day baseline comparison remains visible. Selected ancillary overhead and unknown control-cable, switch and conversion losses must not disappear from the candidate energy decision. The panel-only illustrative25m/s normal-force result doubles from130.4166N to260.8331N; that is not a site load or structural approval.

## Read the detailed records

- [Candidate CAD](../../../docs/hardware/passive-v2-cad.md): source geometry, cable/contact/service checks, exact rebuild commands and open mechanical interfaces.
- [Candidate thermal model](../../../docs/hardware/passive-v2-thermal.md): source data, dimensional equations, contact-force/heat-capture/shade sensitivities and unknown installed performance.
- [Candidate power path](../../../docs/hardware/passive-v2-power.md): primary sources, protection/control topology, energy accounting and source blockers.
- [Executed verification](../../../docs/hardware/passive-v2-verification.md):179 hardware tests,230 clean generation checks,230 fresh runtime checks and preserved baseline evidence.

The thermal network does not assign a favorable whole-box Rtheta. Catalog0.5K/W applies only to the vendor's3in natural-convection reference; actual mounting, thermal contacts, material/flatness, heat-capture fraction and solar coupling remain unknown. A limiting zero-solar/full-capture result is not an accepted operating case. The roof alone cannot establish full shading for all sun angles, and datasheet pad pressure cannot be applied to an unsupported PCB or thin cast wall without a reviewed load path.

A complete field12V-to-Pi USB-C source/protection path and coordinated fuse/fault-current data remain exact source blockers. An exact official external dry-bench PSU is not a substitute for that field path. Candidate geometry, nominal rail checks and COTS device markings do not establish assembled thermal/electrical/ingress/marine safety or production readiness.
