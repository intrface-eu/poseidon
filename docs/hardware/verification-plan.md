# HW-REF-1.1 verification boundary

The digital package is verifiable on a workstation. Physical and field gates remain open. A test passing below means the named source/calculation/geometry assertion passed, not that equipment was manufactured, energized, pressure-tested, calibrated or deployed.

## Repeatable checks

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hardware/validation/check_reference.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
```

The reference checker compares configuration/revision/units, passive variant population, null physical limits, rail design allocations, positive dimensions and enclosure fit, harness/decision identity, unperformed test coverage and the blank unit traveler. Mutation tests reject invented ratings, release authorization, physical results and impossible geometry allocations. These checks do not validate vendor tables, electrical wiring or physical fit by themselves.

CAD execution, numerical criteria and the locked native toolchain are documented in [the CAD reference](cad-reference.md). Electrical equations, units, source evidence and calculation commands are in [the electrical reference](electrical-reference.md). Those commands are separate from stdlib test discovery: a machine without CadQuery cannot truthfully claim a kernel recompute merely by reading exported metadata. Final review must include clean generation and its numerical kernel/export checks.

## Physical gates

The executable plan record is [`physical-plan.json`](../../hardware/validation/physical-plan.json). All entries are `not_performed`, all results are null, and the physical test count is zero. No external facility, reviewer appointment, permit, quote or calibration certificate is claimed.

| ID | Gate | Required independent evidence |
|---|---|---|
| PV-01 | Incoming parts | Measured exact vendor configuration, dimensions, mount datums and mass. |
| PV-02 | Dry fit/service | As-built tolerance stack, fastener access, lid/tray travel, connector mating and selected cable bend radius. |
| PV-03 | Wet pressure/leak | Facility-approved test of exact bought housing, window, seals and penetrators at the declared envelope. |
| PV-04 | Loads/retrieval | Site load cases, attachment capacity, measured mass/CG/buoyancy, retention and recovery tests. |
| PV-05 | Corrosion/fouling | Representative materials/joints/finishes under approved exposure with measured damage and service limits. |
| PV-06 | Electrical safety | Reviewed wiring, voltage range, conductor/fuse coordination, grounding/isolation and backfeed checks. |
| PV-07 | Power/brownout | Measured steady/peak/inrush rails and recovery using exact pack, converter, USB-C and loads. |
| PV-08 | Thermal/solar | Closed-enclosure temperatures, charging limits and energy reserve over a justified worst-season profile. |
| PV-09 | Receive/timing | Traceable full-chain calibration, channel clock/delay and camera alignment uncertainty. |
| PV-10 | Optional wiper | Guard/travel/jam response, window damage and endurance with the selected drive. |
| PV-11 | Optional output stop | Independent physical stop/watchdog/manual-rearm fault tests with dummy loads before a projector is connected. |
| PV-12 | Optional acoustic branch | Approved calibrated output and exposure evidence; separate controlled ecology/efficacy study before claims. |
| PV-13 | RF/EMC | Exact region/antenna/gateway, authorized operation and complete-system interference/conformity evidence. |
| PV-14 | Manufacturing | Independent assembly from released documents, serial-linked inspection, actual deviations/rework and yield. |

Pressure-test CAD fixtures are positioning cradles only. They do not define pressure equipment, guards, safe test pressure or a pressure-test procedure. An appropriate facility must define those before work begins. No acoustic source level or frequency is approved in this package; the failed Lim Bay pinger is not a reference treatment.

## Evidence record and stop rules

Freeze specimen configuration, instruments/calibration, safety method and numerical acceptance limits before an authorized physical test. A missing numerical limit is a freeze blocker, not permission to choose a convenient limit after observing results. Store raw measurements with units, timestamps, uncertainty, serials and deviations. Separate vendor ratings, calculations, instrument readings and reviewer conclusions.

A changed purchased part, material, cable, firmware timing path or power configuration triggers an impact review and applicable retests. An unperformed or failed gate stays open. A digital result cannot populate the blank unit traveler or close a physical gate.

The root controller owns full-repository `make test`, `make check` and frontend build evidence. This lane runs only focused hardware checks and does not imply those root commands passed.
