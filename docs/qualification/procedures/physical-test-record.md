# Specialist test handoff and qualification dossier record

Document `QUAL-02`, revision 0.2, 2026-09-08. **Unperformed protocol shell with populated references; not a physical test instruction, calibration certificate or safety approval.** No physical proof is supplied. Use reference software/simulation only in this tranche; do not operate equipment to fill these forms.

## 1. Authority and configuration

The physical method/limits belong to hardware and competent facilities under [hardware/validation/physical-plan.json](../../../hardware/validation/physical-plan.json), `PV-01`–`PV-14`. Acoustics/acquisition/ecology/statistics owners set scientific endpoints and measurement uncertainty; this procedure does not invent another set. The [requirements register](../../requirements/production-requirements.md), [hazards](../../safety/initial-hazard-register.md) and [EVT/DVT/PVT route](evt-dvt-pvt.md) control acceptance and phase dependencies.

Populated reference: `reference-v1 / HW-REF-1.1`, interface status `PROVISIONAL_REFERENCE_NOT_FOR_FABRICATION`; passive monitor, no projector/amplifier/powered wiper, above-water radio/power with wired wet instruments. A provisional component name, model dimension, nominal rail, calculation or software fixture is not a verified specimen or test limit. All exact specimen serials, work authorizations, reviewer appointments, equipment/calibration certificates, physical measurements, uncertainty values and physical results are missing.

Revision review, 2026-09-08: explicitly rebound to `HW-REF-1.1` for source-verified pin mappings, corrected battery/panel envelopes and the withdrawn panel-discontinuation interpretation; [MFG-01 records the changes](../../manufacturing/reference-build-and-eol.md). Test-readiness review must use the revised configuration and still resolve power/harness, fit/service allowances and procurement availability. This is not independent physical acceptance; all tests and forms remain unperformed.

`QUAL-01`, `TEST-01`, `LIMIT-01` and `EVID-01` forms in [unperformed-records.json](../../manufacturing/templates/unperformed-records.json) are blank masters. Do not alter a blank master into a passed record. Create a separately controlled actual record only for later approved work; preserve raw data, including failures and aborted runs.

## 2. Test-readiness review (`TRR-01`)

Before any later physical test, the qualified owner and independent reviewer must resolve each item below in an actual approved plan. A missing item is `blocked`, not `not applicable` by default.

| Required input | Record content and current gap |
|---|---|
| Claim/requirement/hazard | Exact REQ/HAZ and `PV`/roadmap verification IDs, variant and bounded intended claim. Factory EOL is not biological efficacy evidence. |
| Specimen and representativeness | Actual unit/subassembly serial, BOM/drawing/wiring/material/process/software/configuration/calibration hashes, service/rework/cycle history; selection/sample count rationale; destructive-use restrictions. None exists yet. |
| Envelope and method | Frozen site/lab conditions, operating and test ranges, stress/dwell/cycle/sequence details owned by specialists, method revision and uncertainty/decision rule. Present physical limits are null. |
| Facility and competence | Facility/competent operator/reviewer identities, specific authorization, approved safety/guarding/energy-isolation/emergency method, permits and validity where applicable. No facility or operator is booked or authorized. |
| Instruments and fixtures | Instrument/fixture IDs, range/resolution/bandwidth/uncertainty and traceability, genuine calibration certificate hashes and validity at execution; fixture approval and known-failure detection check. No certificate is provided. |
| Acceptance and stop rules | Numeric/categorical criterion and source revision frozen before test; guard band and uncertainty treatment; abort/stop/retest rules; safe disposition. No agent-selected physical thresholds. |
| Evidence capture | Raw file formats, logging clock/time quality, units/reference, sampling/drop accounting, storage/custody, privacy and secrets policy, hashes and reviewer access. No raw measurements exist. |
| Authorization and change review | Named work/budget approvals, input hash lock, pre-run check of changed configuration/limits/calibration/permissions, signature/date and independent review. All actual approvals absent. |

If an input changes after readiness approval, stop at the controlled hold point and perform impact review before continuation. Record the change, affected runs and whether retesting is required; do not mix configurations or reinterpret observations under a later limit.

## 3. Competent-facility pressure/leak handoff (`PV-03`)

This section tells the responsible parties what must be approved and recorded. **It supplies no pressure setpoint, proof multiplier, medium, ramp, dwell, venting/disassembly sequence or DIY setup.** Do not improvise an occupied-area, pneumatic or hydraulic pressure test. A CAD cradle is a positioning aid, not containment, guarding, a pressure source or proof of pressure safety.

Before the facility may plan authorized work, hardware supplies the exact purchased housing/endcap/window/seal/penetrator configuration and vendor instructions/ratings; serial and previous exposure/repair history; material/finish and assembly/seal records; proposed service depth, immersion time and environmental/load envelope. Those selections and limits are currently unresolved. A bare IP68 label or one nominal housing rating cannot cover an unreviewed assembled configuration.

The competent facility and mechanical reviewer define and approve method suitability, specimen/sample plan, test medium/pressure/cycles and temperature, rated guarded equipment, remote observation, calibration/uncertainty, leak detection sensitivity and acceptance, safe handling of trapped/stored energy, emergency/abort conditions, pre/post inspection, disposition and report scope. No application code or factory operator may infer these from CAD or a requested deployment depth.

The actual report must include configuration, operator/facility, authorization, calibrated instrument/certificate IDs, method/limit revisions, actual time-history values and units/uncertainty, actual leakage and inspection findings, interruptions/deviations, pre/post photos where appropriate, specimen disposition and independent acceptance. Retain raw files and hashes. A pass applies only to the tested configuration and accepted envelope; a failure or aborted exposure holds the specimen and triggers NCR. Opening a boundary, replacing a seal/penetrator/window or exceeding approved reuse/cycle limits triggers mechanical review and any required retest. Unknown limits block opening/rework, not just final shipment.

## 4. Physical/scientific method boundaries and evidence map

| Method family | Requirement / hazard links | Specialist-controlled proof and unresolved decisions |
|---|---|---|
| Incoming, fit, independent assembly `PV-01/02/14` | REQ-MECH-001/MFG-001; HAZ-005/007/008/017 | Exact purchased datums/tolerances, fastener/seal instructions, cable bends/tool access, actual second-assembler steps and labor. Reference CAD is not physical fit. |
| Load/retrieval/environment `PV-04/05` | REQ-SITE-002/MECH-001/PERM-001; HAZ-007–009 | Site current/wind/wave/handling loads, restraint/attachment, material/finish/corrosion, approved recovery method/weather limits, exposure and maintenance interval. No independent field authority here. |
| Electrical/power/thermal `PV-06/07/08` | REQ-POWER-001; HAZ-005/006/013 | Exact pack/BMS/charger/fuse/wire/source/connector, safe test voltage/current, battery extrema, inrush/backfeed/brownout, temperature and autonomy profiles, uncertainty. Nominal 12 V/3.3 V/5 V are not safe test instructions. |
| Receive/timing/probes `PV-09` | REQ-SAF-002/SYNC-001/DET-001/DATA-*; HAZ-002/011/012 | Receive band/sample rate/channel/clock/sensitivity/geometry; full chain serials and calibration; camera timing and visibility; local held-out scientific performance with preregistered thresholds and uncertainty. Digital RMS/peak is not underwater SPL. |
| Conditional wiper `PV-10` | REQ-MECH-001/SW-002; HAZ-005/007/013 | Selected drive/window, guarding/jam/travel/force/current/time/scratch/endurance limits. Wiper is not populated in passive reference. |
| Conditional output `PV-11/12` | REQ-SAF-001/002/EFF-001/PERM-001; HAZ-001–004/014/015 | Independent electrical stop/dummy-load fault proof before separately authorized calibrated water work; exact projector/amp and permitted program, exposure/particle-motion/uncertainty as appropriate, observers/abort rules. No output hardware selected, connected or authorized. |
| RF/EMC `PV-13` | REQ-ARCH-001/NET-001/COMP-001; HAZ-005/013/016 | Exact regional radio/antenna/gateway, spectrum and final-system lab methods, co-location and airtime conditions. No underwater RF or bulk-media LoRa premise. |
| Lifecycle and batch route | REQ-MFG-001/LIFE-001/SEC-001; HAZ-006/008–010/014/015/017 | Actual serial/lot/image/key-reference/calibration records, station validation, rework limits, pilot/sample/yield/cost criteria, repair and trace drills, funded support and independently reviewed legal duties. |

Scientific data/analysis/protocols stay owned by acquisition/research. This dossier records their exact accepted references and unresolved endpoints rather than writing competing criteria. Active efficacy must measure approved sustained feeding/stock-loss outcomes, habituation and non-target effects against controls; startle or fewer camera detections do not prove protection. The failed 2019 Lim Bay DDD03L trial is negative prior evidence, not a Poseidon frequency/source-level default. A failed active gate blocks deterrence claims, not passive research; flora remains a separate research branch.

## 5. Actual run and report structure (`TEST-01`)

For a future authorized run, record readiness approval/input hashes; actual specimen and installed configuration; date/time/time quality; operator/witness; facility/equipment/calibration validity; exact method/sequence and applied conditions; raw observed values with units and uncertainty; file/row/time-range references; expected criterion/source; abort/deviation/failure and containment; result and independent review. Keep measurement truth separate from disposition: an operator's recorded observation, an instrument output and an accepted result are different records.

For time-series tests preserve original data, acquisition settings, dropped/corrupt intervals and analysis code/environment/hash. Do not retain only a screenshot or favorable summary. Every analysis reports excluded observations and pre-approved rationale. No zero-filled blank, copied vendor value or synthetic observation may be labeled measured. For mixed evidence, mark each artifact's class; software/simulation portions cannot upgrade the physical portion.

The reviewer verifies specimen/condition coverage, equipment validity, raw-data-to-summary reproduction, uncertainty/decision-rule application, deviations, repeatability and report scope. If a criterion was undefined before execution, retain the data as exploratory only; do not retroactively call it acceptance testing. Failure, incomplete coverage or invalid equipment leaves the gate open and triggers the approved NCR/retest route. Changes to raw records are amendments, never erasure.

## 6. Qualification dossier assembly and missing proofs

This is a populated index of required evidence categories, not empty directories and not an accepted technical file. The assurance lead's wider compliance dossier can link these categories without claiming that a file's existence closes a gate.

| Dossier item | Existing project input | Missing acceptance proof and accountable role |
|---|---|---|
| QD-01 Intended use/configuration | Roadmap/requirements and `reference-v1 / HW-REF-1.1`, passive exclusions | Frozen final variant/site/envelope/claims and configuration hashes; product owner with specialists |
| QD-02 Hazard/control argument | Initial HAZ-001–017 register, `PV` plan and above method map | Qualified severity/likelihood/risk criteria, implemented control evidence and residual-risk acceptance; domain safety owners |
| QD-03 Component/process evidence | Reference interface/vendor source references, MFG incoming/change controls | Exact released BOM/drawings/wiring, accepted supplier documents/lots, material/process limits, no unreviewed substitution; hardware/quality |
| QD-04 Verification and qualification | QUAL-01/02 with requirement/test/owner/dependency links | Authorized signed methods, real specimens, raw reports/calibration/uncertainty, independent decisions for EVT/DVT/PVT; specialists/quality |
| QD-05 Measurement and scientific claims | Requirements for local ground truth, timing, holdout, calibrated receive and separate efficacy | Approved protocols/endpoints, lawful actual recordings, calibration, locked splits/results and independent review; acquisition/ecology/statistics/acoustics |
| QD-06 Production control | MFG-01/02, blank templates and PVT/yield structure | Actual independent build, station approval, traceability, EOL, first-pass/final yield, NCR/rework/cost; manufacturing/quality |
| QD-07 Lifecycle and lawful release | MFG-03/04 and roadmap P9/compliance requirements | Actual legal applicability closure/reports/labels/instructions, site permissions, funded support/terms, service/security/recall drills and user commercial approval; compliance/product/service/security |

Keep the raw data, certificates, reports, reviews and release decisions distinguishable with IDs and hashes. Link restrictions and retention/custodians so an independent reviewer can actually obtain the evidence. Source-verified component data, calculations, reference software tests and simulation may populate their own categories only. Every listed physical proof, actual manufacturing yield and final approval is currently absent.
