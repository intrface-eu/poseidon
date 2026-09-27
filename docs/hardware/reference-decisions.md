# HW-REF-1.1 reference decisions

Configuration `reference-v1`, issued 2026-09-08. This is a passive-first engineering reference, not a purchase list approved for order, a fabrication release, or permission to operate. Source-backed component data and designed clearances do not establish marine suitability. Exact farm/site, budget and operating envelope remain open.

The machine-readable physical input is [`hardware/interfaces/reference-v1.json`](../../hardware/interfaces/reference-v1.json). Its revision covers this wave's issued reference. CAD and electrical records identify their source dates, units and assumptions separately. Later changes to released interface values require a new revision and controller review; null values must not become silent defaults in adapters.

| ID | Decision | Basis and limit | Freeze gate |
|---|---|---|---|
| RD-01 | Keep hub, radio, solar and battery above water; wire wet instruments. | Approved staged arrangement. RF operation underwater is not assumed. Top-level CAD is an illustrative arrangement, not surveyed placement. | Farm survey, site permission, wave/current loads, attachment and recovery plan. |
| RD-02 | Select Raspberry Pi 4 Model B 4GB as the reference CPU. No accelerator. | Vendor specifications give 5 V DC USB-C input with a minimum 3 A supply and two USB 3.0/two USB 2.0 ports. CAD source evidence owns board outline and mounting-hole dimensions. This does not establish Linux capture-driver compatibility or compute capacity. | ARM64 workload, capture, storage, brownout and thermal bench evidence. |
| RD-03 | Keep hydrophone/DAQ band, channel count, sampling clock and calibrated gain open. | The target event spectrum and local detectability are not established. A configurable array fixture is a research option, not proof of synchronized acquisition or localization. | Acquisition specialist selects the receive chain from local passive evidence and calibration requirements. |
| RD-04 | Model a purchased rated wet camera boundary as an integration reference, not a printed pressure hull. | No exact tube/endcap/window/penetrator configuration is released. A vendor rating applies only to the specified assembly and use conditions. Provisional cylinder dimensions are not copied vendor geometry. | Exact vendor assembly/drawing, authorized pressure/leak protocol, material compatibility and independent review. |
| RD-05 | Use ESP32-DevKitC-32E and RAK3272S as the REEF controller/radio reference. | Board/model selection is not approval for radio operation. UART and I2C logical reservations are separate from connector pin positions and power limits. The electrical source schedule records verified pins. | Regional part/antenna, gateway/network server, power path, harness and firmware review. |
| RD-06 | Use a protected above-water nominal 12 V class battery bus and separate regulated hub/logic rails. | Nominal voltage is not the allowable range. Exact pack, BMS, charger, cutoff, backfeed and USB-C source path must be reviewed together. Calculated load states are assumed, not measured. | Electrical design review, conductor/fuse coordination, charging and measured peak/inrush/thermal evidence. |
| RD-07 | Omit amplifier, projector and powered wiper from the default build. | Missing hardware provides passive separation. A GPIO-low claim is not a physical inhibit. Optional mounts reserve space only. The failed 2019 Lim Bay pinger profile is not a design target. | Independent normally-off output path, manual rearm, hardware watchdog, fault tests, acoustic calibration, permissions and controlled biological evidence. |
| RD-08 | Produce parametric non-pressure mounts, frames and test-positioning fixtures now. | Designed geometry can be checked before field values are known, but manufactured fit, load strength, corrosion and service life cannot. Printed fixtures are not pressure boundaries or primary moorings. | Purchased-part inspection, material/process trials, load review and physical verification. |

## Evidence classes

| ID | Class | What the package can claim |
|---|---|---|
| EC-01 | Vendor source | A directly inspected manufacturer page/drawing states a value for a named part/revision. It does not certify the assembled Poseidon system. |
| EC-02 | Calculated geometry | CadQuery/OCP recomputed a solid, export and stated numerical checks for a specified parameter set. A valid solid is not a strength or pressure result. |
| EC-03 | Engineering calculation | A reproducible equation and cited/assumed inputs yield a result. No measured consumption, lifetime or operating margin is implied. |
| EC-04 | Proposed physical test | Procedure, sample configuration, owner, instrument and acceptance-rule freeze are specified. An unperformed test stays `not_performed`, with no pass result. |
| EC-05 | Physical evidence | Requires specimen identity, calibration records, actual raw measurements, method, uncertainty, deviations and reviewer approval. None is supplied by this wave. |

## Change control

Retain vendor source filenames, hashes and retrieval dates with derived values. If text extraction mixes a PDF table's columns, the drawing/table itself governs; record the correction, not the incorrect summary. A changed vendor part or mounting datum triggers fit and cable-route checks; a changed power part triggers voltage-range, protection, backfeed, thermal and EMC review. A CAD geometry change alone cannot close a physical gate.

The reference BOM can name an exact COTS candidate while its installation envelope remains unresolved. Such an item is not fabrication-ready. Missing exact components, quotes, seals, penetrators and cable data remain explicit release blockers, not zero-cost items or assumed ratings.
