# Passive-v2 digital verification

Executed2026-09-08 on macOS arm64. Candidate `passive-v2` / `HW-CAND-2.0` remains `NON_ADOPTED_NOT_BUILD_AUTHORIZED`. Lead and both bounded children used `unspecified implementation`; no fallback or further delegation. The144 frozen HW-REF-1.1 files remain byte-identical, including the failed reference calculations, CAD, documents and tests.

## Commands and results

| ID | Command executed from repository root | Actual result |
|---|---|---|
| V2-01 | `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v` | Exit0;179 tests passed, no failures/skips.117 preserved tests plus25 candidateCAD,17 candidatepower,14 candidatethermal and6 preservation/wind tests. |
| V2-02 | `PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python hardware/candidates/passive-v2/cad/generate.py --output /tmp/hardware-verification/reports/hardware-wave2-clean-cad` | Exit0;230/230 actual generation/BRep/contact/clearance/export checks passed in a new owned directory. |
| V2-03 | `PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python hardware/candidates/passive-v2/cad/check.py /tmp/hardware-verification/reports/hardware-wave2-clean-cad --geometry` | Exit0;230/230 fresh runtime checks passed, including six fresh STEP imports, rebuilt cable sweeps, two physical panel bodies and144 unchanged baseline hashes. |
| V2-04 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/cad/check.py hardware/candidates/passive-v2/cad/generated/passive-v2` | Exit0;25 artifact hashes,3 assemblies and230 archived checks audited. This stdlib mode explicitly does not execute the geometry kernel. |
| V2-05 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/thermal/model.py --output /tmp/hardware-verification/reports/hardware-wave2-thermal-recheck.json` | Exit0; `cmp` against `thermal/results.json` returned0, byte-identical26case output. |
| V2-06 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/power/calculate.py > /tmp/hardware-verification/reports/hardware-wave2-power-recheck.json` | Exit0; `cmp` against `power/evidence.json` returned0, byte-identical sourced power/control/ancillary evidence. |
| V2-07 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/check_candidate.py --output /tmp/hardware-verification/reports/hardware-wave2-review-recheck.json` | Exit0; `cmp` against `review-results.json` returned0.144 historical files verified unchanged; panel-area/load changes reproduced. |

The output paths above now contain evidence; use new owned destinations for another run. The existing locked CAD environment was reused read-only. Canonical and independent candidate parameters, source hashes, units, baseline records, part/bounding-box/keepout/check records agree exactly across all3assemblies; timestamps and STEP headers need not be byte-identical.

Canonical candidate CAD manifest SHA256:
`31b7875b78c7934d46e306b214fc30de569ef5156db238609de86fa84a9402a9`

Candidate power evidence SHA256:
`69476a459c0ac305dedc78d44df9df0d974d2f205bdf37b3d1fc16aa9faa57c0`

Preserved failed baseline power evidence SHA256:
`dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f`

## Reviewed artifacts

Canonical CAD under `hardware/candidates/passive-v2/cad/generated/passive-v2/` contains3assemblies,6STEPfiles,3dimensionedDXFs,15SVGdrawings/views andBOMlinks:25hashed artifacts plusmanifest. NoSTL orpressureparts. Source-backed overall geometry is separate from unverified fin/casting/contact/connector detail.

The lead reviewed candidate construction/export checks, primary thermal drawings/data, power-source records and executable equations. Four final engineering images were rendered with local `rsvg-convert` and inspected: HUB orthographic, REEF orthographic, HUB exploded and TOP assembly. Candidate/revision/non-adoption labels, dimensions, two separate panels/gap and source-sized thermal-path/shade bodies are visible. No parent redraw loop, browser or persistent service was used. The fin occupancy block is deliberately not a manufactured fin profile.

## Resulting pass/fail/unknown decision

| ID | Screen | Decision |
|---|---|---|
| S2-01 | Digital geometry/source consistency | PASS for the tested source/parameter set: two actual668×425×25mm panels,50mm gap,668×900mm panel-pair footprint,0.5678m² panel area, actual series/free-lead bends, thermal-interface geometry and service volumes. Not physical fit or load approval. |
| S2-02 |80W2S1P catalog voltage/current screens | PASS for retained temperature/controller assumptions. ColdVoc50.40025V; hotVoc37.82825V exceeds19.4V startup screen; current/power fit catalog screens. Tolerance, loaded startup, actual cable/protection and shading remain unqualified. |
| S2-03 | Actual REEF energy/autonomy | UNKNOWN.42.12Wh/day modeled load-side harvest; retain27.5247475Wh/day baseline and add2.94912Wh/day catalog-nominal ancillary overlay. Another0.5W unresolved overhead produces−0.3538675Wh/day. Do not omit losses or call zero-extra an achieved condition. |
| S2-04 | Installed thermal performance | UNKNOWN. Source sink/pad/geometry inputs support a model, but package contacts, capture fraction, clamping/flatness, wall spreading, installed sink boundaries and shade coupling remain unknown. An ideal full-capture/zero-sun conditional result is not acceptance. |
| S2-05 | Field DC-to-Pi power/protection | BLOCKED on exact source data. Public industrialUSB-C source attempts did not establish CC/source-role, numerical protection thresholds or11.2V operation. Verified externalACbench PSU does not resolve fieldDC. |
| S2-06 | Fuse/holder and fault coordination | BLOCKED on retrieved ratings/geometry plus prospectivefault/current, wire, connector and let-through evidence. Failed retrieval/index snippets are not verified manufacturer data. |
| S2-07 | Physical qualification/adoption | NOTPERFORMED / NOTADOPTED. No fabrication, energization, pressure, thermal, load, corrosion, RF, acoustic, field or conformity test occurred. |

Thermal/source precision is the reason for stopping this bounded candidate wave, not permission to reduce assumptions until a row passes. The candidate now supplies a concrete heat-path/two-panel/power design study and exact review/measurement/source gaps. The current1.1 reference and assurance bindings are unchanged.

Assurance received the additive candidate commands and explicit revision distinction; its baseline remains HW-REF-1.1. Root-owned `make check`, `make test` and frontend builds were not run by this lane. No other-workstream or root integration file was edited.
