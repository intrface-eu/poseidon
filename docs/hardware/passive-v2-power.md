# HW-CAND-2.0 power-path candidate

Configuration `passive-v2`, status **`NON_ADOPTED_NOT_BUILD_AUTHORIZED`**. This is an additive COTS design candidate, not a replacement of HW-REF-1.1 or a viable-product claim. The field HUB DC-to-USB-C path, protective devices, selected ancillary consumption and physical qualification remain open. The hardware lead owns the separate thermal/enclosure analysis and CAD reconstruction.

All144 frozen wave1 files are checked against `hardware/candidates/passive-v2/baseline-lock.json`. The original failed evidence SHA256 remains `dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f`.

## Reproduce and review

From the repository root, standard-library Python only:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/power/calculate.py --output hardware/candidates/passive-v2/power/evidence.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -p 'test_candidate_v2_power.py' -v
```

Without `--output`, the CLI writes deterministic JSON to stdout. File output is restricted to this new candidate's `power/evidence.json`. It checks the frozen baseline before and after calculation and rejects attempts to overwrite baseline or sibling files. The parent runs the full hardware suite.

| ID | Editable artifact | Review content |
|---|---|---|
| P1 | `hardware/candidates/passive-v2/power/source-register.json` | Primary URLs/date, 13 SHA-256 records for privately fetched PDF/HTML files, extracted facts, dimension conflicts and bounded source-access failures |
| P2 | `hardware/candidates/passive-v2/power/part-envelopes.json` | Candidate power-part IDs, quantities, CAD dimensions and extra provisional service clearances |
| P3 | `hardware/candidates/passive-v2/power/bom.json` | Distinct22-line candidate power BOM; exact verified parts and explicit incomplete/unverified selections |
| P4 | `hardware/candidates/passive-v2/power/wiring.csv` and `schematic.txt` | Editable power/pin schedules, series PV wiring, Smart-BMS charge/load controls, retention and grounding/protection gates |
| P5 | `hardware/candidates/passive-v2/power/inputs.json`, `calculate.py`, `evidence.json` | Source-bound array/voltage calculations, selected ancillary overlay, unknown-loss sensitivity, source hashes and non-release status |

The evidence JSON retains hashes for 13 primary supplier files; captures are not included in the tree. Public stock/list-price claims are not quotes, approved availability or purchase decisions. No custom PCB is needed for this candidate.

## Source-backed COTS path

Sources were retrieved on **2026-09-08**. Manufacturer claims are not measurements or final-system qualification.

| ID / part | Candidate role and verified data | Remaining source/integration limits |
|---|---|---|
| D1: Victron `BMS400100000` | smallBMS with pre-alarm for **Lithium Battery Smart**, matching `BAT512050610`, not an NG-only BMS.8–70V;2.2mA own current remote-on excluding output loads; Load disconnect1A source limit; Charge disconnect10mA source limit. | Drawing107×46×12mm conflicts with datasheet106×42×23mm. CAD uses conservative107×46×23mm union, not one verified vendor envelope. Supply fuse and output loading remain open. |
| D2: Victron `BPR065022000` | Smart BatteryProtect12/24V65A.6–35V;65A continuous product rating;1.4mA operating with Bluetooth on; M6 studs,5Nm source torque. Battery IN to load OUT only. | Drawing106.3×55×46mm overall allocation differs from manual40×48×106mm. Larger drawing envelope retained. On-state loss, protection coordination and actual ModeC configuration/tests remain open. |
| D3: Victron `ASS030550320` | Manufacturer-supported non-inverting VE.Direct remote on/off cable. High enables; below1V or floating disables; approximate6V on threshold,70V maximum control input. | Exact cable/module dimensions and current consumption unknown. MPPT75/10 requires RX port configuration. VE.Direct is consumed by control and cannot simultaneously carry telemetry. |
| D4: Pololu `D36V28F5`, item3782 | Independent REEF5V source, not a USB-C source.5.3–50V input,5V±4%,17.8×20.3×8.8mm. Source names OVP, undervoltage, overcurrent, short-circuit and thermal protection. | Numerical protection thresholds/timing, low-load efficiency, selected load/ambient current rating and transients are unknown.2–3mA no-load current is typical, not guaranteed maximum. |
| D5: Pololu `D36V28F3`, item3781 | Independent RAK3.3V source, not assumed DevKit spare current.4.5–50V input,3.3V±4%, same board envelope,2–3mA typical idle current. | Normal voltage tolerance3.168–3.432V fits the RAK2.0–3.6V static range. PG upper status threshold3.96V is **not** an OVP cutoff and cannot establish RAK fault protection. |
| D6: Anderson `1327FP`, `1327G6FP`, `1331`, `110G21` | Both halves use fingerproof red/black housings, four1331 contacts total and one two-pole BlockLok. Contact accepts12–16AWG. Source lists24.6mm housing length,41.2mm mated length and600V AC/DC family rating. | Do not mix fingerproof and standard housings.55A is a10AWG family test, not this12AWG assembly's rating. Final key/polarity drawing, assembled lock envelope, wire derating, approved crimp process and retention remain open. Not a wet connector or service isolator. |
| D7: WAGO `221-415` and `221-412` | Enclosed lever-splice candidates, manufacturer450V/32A,0.2–4mm² conductors.221-415 is30×18.6×8.4mm localX/Y/Z;221-412 is13.1×18.6×8.3mm. | Ratings do not certify installation/DC fault clearing. Enclosing/retaining the parts, lever access, wire ampacity and PV insulation remain review gates. No weatherproof claim. |

The smallBMS [datasheet/manual](https://www.victronenergy.com/upload/documents/Datasheet-smallBMS-with-pre-alarm-EN-.pdf), [BatteryProtect manual](https://www.victronenergy.com/media/pg/Smart_BatteryProtect_12V_24V/en/installation-and-wiring-examples.html), [charge-control cable manual](https://www.victronenergy.com/upload/documents/Manual-VE.Direct-non-inverting-remote-on-off-cable-EN.pdf), [Pololu5V](https://www.pololu.com/product/3782), [Pololu3.3V](https://www.pololu.com/product/3781), [Anderson catalog](https://www.andersonpower.com/content/dam/app/ecommerce/product-pdfs/DS-PP1545.pdf) and [WAGO221-415](https://www.wago.com/global/installation-terminal-blocks-and-connectors/compact-splicing-connector/p/221-415) are captured or linked in the source register with exact locators and caveats.

### Charge and load control

The candidate uses the manufacturer-supported Smart-battery arrangement, not an assumed NG substitution:

- Matched battery M8 BTV leads connect to smallBMS. No generic M8 pin assignment or ESP GPIO connection is invented.
- smallBMS **Load disconnect** drives BatteryProtect **RemoteH**, with BatteryProtect configured for **ModeC** and the bypass jumper handled per the manufacturer diagram. BatteryProtect switches the regulator load branch only. Its1A smallBMS control output is not short-circuit protected.
- smallBMS **Charge disconnect** feeds `ASS030550320`; the cable drives the MPPT75/10 VE.Direct RX remote-on/off function. The75/10 setting must be made and verified; it is not assumed correct on receipt. At the frozen11.2–14.4V battery scenario, the healthy BMS charge signal is approximately10.6–13.8V, compatible with the cable's stated enable-voltage window. Cable current is still unknown.
- MPPT **BAT+/BAT−** has a separate fused battery connection. Charging must **not** run backwards through BatteryProtect OUT. PV must **not** run through a35V BatteryProtect; two-series-panel cold catalog Voc already reaches50.40025V before unknown tolerance.
- Charge disconnect floats on imminent cell overvoltage or high/low cell temperature. The cable disables on floating/low. No relay coil may be driven by the10mA charge-disconnect output. Remote off is not mechanical service isolation.

Actual ModeC/RX settings, low-temperature charging behavior, wiring faults, semiconductor failures, brownout and startup tests remain unperformed. The Boolean control fixture tests requirements only; it does not operate hardware. BatteryProtect has automatic reconnect behavior and is **not** a manual-rearm acoustic stop device.

### REEF logic and regulator interfaces

The5V regulator supplies ESP32-DevKitC-32E J2.19 and J2.14 return. Use only one ESP power method; remove service USB VBUS when header-powered. The independent3.3V regulator supplies RAK J5.9 and J5.7. RAK J4.9 remains unused because the pin changes across board revisions. ESP GPIO17/J3.11 TX crosses to RAK UART2_RX/J4.8; RAK UART2_TX/J4.7 crosses to ESP GPIO16/J3.12 RX. Power-off backfeed protection remains open.

Never connect12V,5V logic, an unconditioned battery divider or wet I2C directly to ESP GPIO. Pololu EN can be pulled toward VIN: do not connect it directly to ESP. PG is open-drain status; no new PG/EN GPIO allocation is made. All active amplifier/projector/wiper outputs and their harnesses remain physically absent.

## HUB source and fuse research stopped at precise blockers

**B1 — Field Pi power is unresolved.** Coolgear industrial USB-C source pages returned403. The candidate cannot verify an exact DC-source SKU, CC/source-role implementation, numerical OVP/current-limit behavior, dimensions or operation down to11.2V. Search indexing of a12V lower bound cannot prove11.2V operation. No bare buck or PD sink trigger substitutes for that missing source assembly.

The primary [Raspberry Pi15W PSU brief](https://datasheets.raspberrypi.com/power-supply/usb-c-power-supply-product-brief.pdf), April2024, does verify exact white EU **`SC0444` / `KSA-15E-051300HE`**, nominal5.1V/3A,1.5m captive18AWG USB-C lead, and short-circuit/overcurrent/overtemperature protection. It does not publish internal CC details or an OVP threshold. This is an **external mains drybench alternative only**, not a12V field solution or bench-test authorization. Do not parallel it with another source. Its external placement does not justify reducing the frozen21.857142857W thermal comparison.

**B2 — Fuses/holders are concrete source leads, not verified protective selections.** Littelfuse `0287005` ATOF base part and `01550320ZXU` ATO155 holder identify the bounded candidate family. The primary fuse PDF returned403; the holder landing page identifies the part but supplies no retrieved rating/dimensional evidence. Indexed5A/32V/1000A values are **not** promoted into verified data; the candidate BOM stores current, DC voltage, interrupt rating and dimensions as UNKNOWN/null. The fuse ordering suffix also remains unresolved.

The second family, Eaton ATC/HHF-JFCU, failed primary retrieval with HTTP2 errors and bounded HTTP1/WebFetch timeouts. Research stopped after these two families. Exact main battery, load, charge, BMS-supply, BatteryProtect-ground and PV protection remain unselected. smallBMS specifies a0.3–2.5A supply-fuse range;1A is only a target, not a released part. BatteryProtect documentation says300mA ground protection is sufficient; its exact fuse/holder remains open.

Battery prospective fault current, interrupt capacity, time-current/I²t, wire insulation/ampacity, cable lengths, crimps/lugs and service-isolator poles remain unknown. A catalog ampacity inequality would not close them. Do not use an unverified32V automotive fuse on a nominal50.4V cold PV array. No prices, supplier quotes, availability or purchase approval are fabricated.

## Two-panel energy with selected ancillary uncertainty

The electrical BOM and CAD mapping now both call for **two `SPM040401200` panels**, not a comparison attached to one-panel geometry. Power ID `V2-PV-001` maps to CAD ID **`REEF-PV-2S`**. Each panel is668×425×25mm. CentresY=±237.5mm give50mm gap and668×900mm panel footprint. Frame dimensions, mounting loads and actual STEP checks belong to the CAD package.

PanelA+ connects to panelB− in a sheltered retained series junction. PanelA− goes to MPPT PV−; panelB+ goes through the separately reviewed PV protection/isolation path to PV+. Exact weather/UV/insulation cable, glands and junction-box components remain open. No supplied MC4 lead is assumed for this model.

The calculation retains1PSH,0.65field derate,0.9charge and0.9discharge efficiency,27.5247475Wh/day original REEF load and294.912Wh usable load-side battery energy. It also retains35°C ambient,21.857142857W HUB heat and48W absorbed-sun comparison. It never lowers load or substitutes zero solar absorption.

| ID | Calculated result | Scope of result |
|---|---|---|
| N1 | 2S1P gives80W STC,44.9V STC Voc,50.40025V cold Voc,37.82825V hot Voc and3A design Isc | Catalog screens pass75V Voc,13A Isc,19.4V startup,10A controller charge and145W nominal PV limits. Tolerance, cables and loaded startup are not qualified. |
| N2 | 46.8Wh/day stored;42.12Wh/day load-side harvest | Both charge and discharge losses apply. Against the unchanged baseline alone, net is+14.5952525Wh/day; this is not the complete candidate demand. |
| N3 | Additional catalog-nominal currents: smallBMS2.2mA, BatteryProtect1.4mA, regulators3mA each at12.8V reference | Positive overlay0.12288W or2.94912Wh/day. Original0.1W generic BMS allowance and0.8 regulator efficiency assumptions are not subtracted or improved. |
| N4 | Nominal-overlay demand30.4738675Wh/day; only0.485255521W remains for unknown extra losses before net deficit | Cable/control-input draw, BMS output loads, BatteryProtect conduction, worst-case idle current, real low-load efficiency and wiring/protection losses remain unknown. |
| N5 | An additional0.5W unknown-loss scenario gives42.4738675Wh/day demand and−0.3538675Wh/day net | Small unresolved overhead can reverse the energy result. Actual total load and actual autonomy therefore remain UNKNOWN, not a reported positive duration. |

The overlay may double-count some conversion loss relative to the old model, but is not a worst-case bound: regulator idle figures are typical and control/output losses are unresolved. The CLI shows0/0.1/0.25/0.5/1W extra-loss sensitivities, all labeled assumptions and unqualified. No sunny-weather substitution or ignored selected part makes autonomy pass.

**Disposition:** `BLOCKED_ON_FIELD_DC_POWER_PROTECTION_AND_ANCILLARY_UNCERTAINTY`. The separate parent thermal model retains its own unknown/unmeasured heat-path gates. Candidate source facts and limited static screens advance the digital design; they do not authorize adoption, fabrication, purchases, energization, radio/acoustic output, field activity or a viable-product claim.
