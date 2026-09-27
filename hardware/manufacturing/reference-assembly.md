# HW-REF-1.1 assembly and inspection package

`reference-v1` is a digital engineering reference. Do not fabricate, buy, energize, immerse or deploy from this package until the relevant reviewer and root/user authorize that activity. Geometry marked PROVISIONAL is not a released fabrication drawing. This wave supplies no assembled-unit, measured-fit, pressure, acoustic or production-yield evidence.

## Document authority

| ID | Record | Authority |
|---|---|---|
| MR-01 | `hardware/interfaces/reference-v1.json` | Physical reference revision, variant population, signal reservations and open operating limits. |
| MR-02 | `hardware/cad/` editable source, parameters, generated part metadata and drawings | Geometry and design assumptions only. A purchased-part envelope omits details unless explicitly modeled and sourced. |
| MR-03 | `hardware/bom/`, `hardware/wiring/`, `hardware/electronics/` | Reference COTS identification, sourced electrical inputs, interconnect design and executable assumed-load calculations. Open selections and missing quotes block purchase release. |
| MR-04 | `hardware/validation/physical-plan.json` | Unperformed physical verification gates. Every gate needs a frozen specimen, method and acceptance limits before execution. |
| MR-05 | `hardware/manufacturing/unit-traveler-template.json` | Blank traceability record, not a manufactured unit. Fill only from actual work after authorization. |

## Build order after release and authorization

| ID | Assembly | Work instruction | Hold point |
|---|---|---|---|
| AS-01 | All | Freeze configuration and quantities. Match part markings and vendor revisions to the BOM. Record substitutions as deviations before assembly. Measure purchased mating features rather than cutting to an unsourced envelope. | PV-01; no unreviewed substitution. |
| AS-02 | HUB | Inspect the unpowered enclosure and tray. Trial-fit Pi mounts, converter, DAQ/storage reservation and cable exits with inert parts. Preserve underside board clearance and all modeled connector/tool/ventilation space. Remove burrs; use approved insulating standoffs and restraint. | PV-02; tray/part drawings control hole locations, not overall visual fit. |
| AS-03 | HUB power | Fit selected fuses, disconnect, DC converter, bonding/isolation provisions and terminal guards only from a reviewed electrical design. Keep diagnostics on the passive supply. Do not improvise a USB-C supply lead from a bare DC output or parallel USB and external board supplies. | PV-06 before any energization; BMS, cutoff and USB-C gates must be closed. |
| AS-04 | WET | Inspect the exact purchased housing, optical window, seals and penetrators against vendor instructions. Keep sealing surfaces free from burrs, debris and unsupported sealants. Mount using the defined non-pressure support datums without distorting the pressure boundary. | PV-03 remains open until the facility qualifies the exact configuration. Do not print or machine substitute pressure parts from this model. |
| AS-05 | Receive/camera | Fit the selected receive instrument/camera and routed cables using released connector and bend-radius data. Provide independent strain relief before cable entry; do not transmit retrieval load to penetrators, sensors or connectors. Keep receive cables away from noisy power/radio routes per reviewed grounding design. | PV-02 and PV-09; no calibrated or synchronized claim from the fixture geometry. |
| AS-06 | ARRAY option | Assemble only if the array research option is selected. Measure and record each hydrophone center in the released coordinate frame after actual assembly. Preserve common-clock/cabling requirements independently of mount spacing. | PV-09; a configurable pitch does not establish localization performance. |
| AS-07 | WIPER option | Fit inert arm, guards and travel reference for dry clearance checks. No drive, shaft seal or window contact pressure is approved by the geometry. Verify the full blade/arm swept volume against the actual window, camera view and guard before selecting a drive. | PV-10 and explicit powered-motion authorization; passive variant leaves the drive absent. |
| AS-08 | PROJECTOR option | Leave mount unpopulated in the passive variant. A research dummy mass may be used only after load review and authorization. Review isolation pads, corrosion couples, cable exit and restraint for the actual projector before population. | PV-11 then PV-12; no acoustic emitter is selected or connected. |
| AS-09 | REEF | Mount the panel, electronics and battery with their measured envelopes and independent load restraints. Protect battery terminals and preserve lug/tool/bend access. Use a selected nonconductive terminal cover. Keep panel wiring and antenna above water; provide drips/strain relief without obstructing service. | PV-02, PV-04, PV-06 and PV-08; external battery management and solar charge/load disconnect are unresolved until reviewed. |
| AS-10 | FARM | Fit only to an approved surveyed attachment using reviewed marine load paths and independent retention/recovery hardware. Isolate dissimilar metals with reviewed details. Do not hang the system by instrument cables, glands, provisional clamps or printed parts. | PV-04 and site permission before installation. |
| AS-11 | JIG | Use assembly/calibration cradles as inert positioning fixtures within approved loads. Pressure-test positioning cradles locate equipment inside a separate facility-rated setup; they are never pressure containment or a safety barrier. | Fixture load/material review; PV-03 governs the facility, not this cradle. |
| AS-12 | Final | Photograph actual harnesses and restraints, record torque where a released value exists, identify unit and firmware/software revisions, inspect service paths and close each approved end-of-line check. Keep blank/missing results unresolved. | PV-14; independent assembler review before any manufacturing claim. |

## Material, process and finish controls

CAD material densities are calculation inputs, not material certificates. The part metadata identifies candidate materials and which parts are printable. Only those explicitly identified printable non-pressure/non-primary-load parts receive STL exports. STEP is the exchange authority; Python parameters and construction source remain editable authority.

For fit prototypes, record polymer grade, printer/process, orientation, layer/contour settings, conditioning and actual dimensions. Do not transfer isotropic stock properties to printed parts. Wet/UV exposure, creep, water uptake and cleaning compatibility need separate review. No pressure seal, terminal-insulation rating, primary restraint strength or marine life is established by a mesh check.

For fabricated metal parts, the reviewer must freeze alloy/temper, stock thickness, weld/machining detail, coating/passivation, edge finish and inspection datums. Protect seal surfaces and optical windows from abrasive finishing. Stainless steel can suffer crevice corrosion; mixed aluminum/stainless/copper joints require a reviewed isolation and maintenance design rather than an assumed universal material choice.

Fastener identity includes standard, size/pitch, length, material/property class, washer stack, locking method and thread engagement. A geometric hole diameter or fastener envelope is not a complete purchase callout. Torque depends on the actual screw/joint, material, lubricant and vendor instructions; no generic torque is released here. Record every missing fastener callout as a release hold. Do not use adhesive, potting or threadlocker near seals/electronics unless compatibility and rework instructions have been reviewed.

## Inspection and service controls

Measure the worst-case tolerance stack, not only nominal fit: part tolerance, hole location, mounting alignment, coating and thermal movement can consume a CAD margin. For each selected cable, preserve vendor bend radius in assembled, opening, removal and retrieval positions; the assumed cable radius used in CAD is only a reference-design criterion.

Seals, penetrators, windows, corrosion interfaces, strain relief, fasteners, terminals, antenna connections and battery restraints need an inspection interval tied to measured service exposure. No interval is released before environmental evidence. Record replacement part lots and vendor lubrication/assembly directions. Isolate all energy sources and confirm safe residual energy before service under a reviewed procedure; reconnecting power must not rearm an optional output branch.
