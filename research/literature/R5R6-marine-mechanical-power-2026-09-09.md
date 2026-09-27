# R5/R6 — Electrical, power, communications, mechanical and marine feasibility

Package: `R5` + `R6`. Desk review date: **2026-09-09**. Reviewer: research worker (not a marine, mechanical or electrical engineer).
Status: **desk research only**.

This is desk research; no measurement, purchase, supplier contact or suitability claim is made.

Companion machine-readable source register: [`R5R6-marine-mechanical-power-2026-09-09.sources.json`](R5R6-marine-mechanical-power-2026-09-09.sources.json).

Site assumed by the task brief: Limski kanal / Limski zaljev, Istria, Croatia — a sheltered marine inlet, shellfish farm longlines and rafts, target depth a few metres to about 30 m, seasonal fouling, Adriatic salinity and temperature range. Arrangement already decided in the repository: above-water hub, radio, solar and battery; wired underwater receive/camera head; separately gated projector ([`docs/hardware/reference-decisions.md`](../../docs/hardware/reference-decisions.md), RD-01, RD-04, RD-07). The current CAD carries only a placeholder wet envelope, explicitly recorded as provisional in [`hardware/interfaces/reference-v1.json`](../../hardware/interfaces/reference-v1.json).

## Questions

R5 (audit plan section 3) asks for load/peak budgets, conversion loss, tether drop, battery autonomy and worst-season solar, heat paths, 4G survey, LoRa link budget and data cost. R6 asks for rated depth/time, storm and current loads, buoyancy, corrosion couples, seal and penetrator specification, cable strain relief, optical window, service interval, mooring/retrieval and lost-equipment prevention, plus a review of off-the-shelf housings. Section 5 rows C3 (underwater receive/vision head) and C4 (lens-wiper and projector modules) are the CAD packages that these answers are supposed to unlock.

The desk-answerable sub-questions taken from the task brief:

- **Q-a** Rated off-the-shelf underwater enclosures for a small camera and hydrophone head: tube sizes, end caps, windows, penetrators, depth ratings, materials, published prices, lead-time notes.
- **Q-b** Hydrophone candidates for 1–100 kHz passive recording: sensitivity, self-noise, depth rating, cable and connector, published price.
- **Q-c** Marine cable, strain relief, wet-mate connectors, glands.
- **Q-d** Materials and corrosion pairs for aluminium, 316 stainless, POM/acetal, PEEK and fibreglass in seawater; galvanic guidance; window anti-fouling options.
- **Q-e** Mooring and attachment practice on shellfish longlines and rafts, lost-equipment prevention and retrieval.
- **Q-f** Hub electronics: Raspberry Pi 5 / CM5 power and thermal data; USB audio DAQ or multichannel hydrophone interfaces; LTE and LoRaWAN options for Croatia; availability check of the solar/battery parts already named in the BOM.
- **Q-g** Published Adriatic / Lim bay environmental parameters.

Out of scope: selecting any part, freezing any depth, duration, band or channel count, or claiming that any listed product is suitable for this deployment. A vendor "IP68" or depth figure describes a tested configuration, not this system.

## Sources reviewed

40 sources are recorded in the JSON register with URL, publisher, retrieved date, access level and a verbatim quote.

| Access | Count | Meaning |
|---|---|---|
| `full` | 33 | Page or PDF text was retrieved and read in this run. |
| `abstract` | 3 | Only an abstract, product summary or search-index summary was readable. |
| `inaccessible` | 4 | HTTP 403, connection refused, or a page that did not resolve. |

Not readable in this run, and therefore not used for any number:

- `R5R6-S14` Aquarian Audio AS-1 vendor page — connection refused (`ECONNREFUSED`) on repeated attempts. AS-1 figures below come from the NAUTA distributor page (`R5R6-S13`) instead, which is a distributor restatement, not the manufacturer page.
- `R5R6-S38` Nickel Institute *Stainless Steel in Waters: Galvanic Corrosion and its Prevention* — HTTP 403.
- `R5R6-S39` Hammond Manufacturing 1554-series enclosure pages — HTTP 403 on the manufacturer site and a distributor timeout. The BOM alternate `ENC-ALT-001` therefore has **no availability result** in this pass.
- `R5R6-S40` FAO OpenKnowledge repository record `cd8213en` (shellfish farming manual) — HTTP 403. Mooring evidence below uses the NOAA aquaculture-gear guide (`R5R6-S35`) instead.

## Site parameters

Every row is a published figure for the named location. None of it was measured by this project, and none of it is an operating limit.

| Parameter | Published value | Location and period | Source |
|---|---|---|---|
| Maximum depth of the inlet | 32 m; maximum width about 650 m | Limski kanal, E–W axis | `R5R6-S15` |
| Water temperature | 17.9 ± 0.9 to 23.5 ± 0.4 °C (June measurements); older literature 9–12 / 20–25 °C | Limski kanal | `R5R6-S15` |
| Practical salinity | 35.2 ± 0.3 to 36.9 ± 0.1 ‰, increasing with depth; older literature 35–39 ‰ | Limski kanal | `R5R6-S15` |
| Current velocity | 2.2 ± 0.9 cm/s at 5 m; 0.8 ± 0.9 cm/s at 15 m; older literature range 0.1–11.8 cm/s | Limski kanal | `R5R6-S15` |
| Secchi visibility | 12.6 ± 0.8 m; earlier reports 6 m and 10 m | Limski kanal | `R5R6-S15` |
| Dissolved oxygen | 6.6 ± 0.2 to 8.8 ± 0.7 mg/L | Limski kanal | `R5R6-S15` |
| pH | 8.06 ± 0.1 to 8.20 ± 0.01 | Limski kanal | `R5R6-S15` |
| Light | PAR 17.9 to 1,925.1 µmol·m⁻²·s⁻¹; about 35 % of surface PAR remains at 5 m, 11 % deeper | Limski kanal | `R5R6-S15` |
| Adriatic sea-surface temperature | Basin mean 18.6 ± 4.7 °C, 5th–95th percentile 12.5–26.1 °C, historical trend 0.04 °C/yr | Adriatic basin, 1992–2011 model/reanalysis | `R5R6-S17` |
| Farming method in Lim bay | Off-bottom culture only: longlines carrying bags, trays, lanterns or *pergolari*; nets used against predation | Croatian farms including Lim channel | `R5R6-S16` |
| Fouling pressure | *Pergolari* in Lim Bay overgrown by an undetermined green alga blocking water flow, causing mussel deaths | Lim Bay, recent | `R5R6-S16` |
| Licensed operators | 108 registered shellfish farmers nationally in 2022, 20 in Istria including the Lim channel | Croatia, 2022 | `R5R6-S16` |

Gaps in the site record, relevant to R6: no published wave height, no storm current, no measured turbidity in NTU/FNU, no seabed holding characteristics at any candidate anchor point, no winter temperature series at depth, and no fouling rate by month. `R5R6-S15` reports June sampling; it is not an annual series.

## Findings

### R5 — electrical, thermal, power, communications

**R5-F1.** Raspberry Pi 5 requires 5 V/5 A over USB-C with Power Delivery, and its product brief states an operating temperature of 0 °C to 70 °C. [`R5R6-S18`] This is 20 K above the 50 °C figure the repository thermal screen currently uses for Pi 4 (`docs/hardware/power-refinement.md`, cases T1–T4). Any move from Pi 4 to Pi 5 would change the numerator of that screen, but the Pi 5's higher power draw and the unresolved heat path (blocker B1 in the same document) are not closed by a different ambient rating.

**R5-F2.** Raspberry Pi Compute Module 5 publishes a current-consumption table: shutdown 1.3 mA (PMIC_ENABLE < 0.4 V) or 3 mA (PMIC_ENABLE > 2 V), idle 400 mA typical, operation 900 mA typical, RTC 1.7 µA at Vin = 5 V and 6 µA at Vin = 0 V. Its overall operating range is −20 °C to +85 °C non-condensing, with best wireless RF performance −20 °C to +75 °C. [`R5R6-S19`] The datasheet also states CM5 has less passive heat sinking than Raspberry Pi 5 and that any thermal solution must keep the ambient of surrounding silicon inside its safe range. [`R5R6-S19`]

**R5-F3.** Raspberry Pi 4 Model B remains listed for sale at "From $35" with no per-variant prices and **no production-lifetime statement on the product page**. [`R5R6-S20`] By contrast Raspberry Pi 5 carries a stated production commitment to at least January 2036 and CM5 publishes an MTBF section. [`R5R6-S18`, `R5R6-S19`] The BOM's `HUB-CPU-001` choice of Pi 4 therefore has weaker published longevity evidence than the two newer parts.

**R5-F4.** A class-compliant USB audio interface is the cheapest route to a calibrated-chain-ready capture front end with published noise numbers. MOTU publishes for the M2: sample rates 44.1–192 kHz, "Measured 120 dB dynamic range on outputs", "Measured -129 dBu EIN on mic inputs", per-input 48 V phantom power, and USB-C bus power. [`R5R6-S21`] MOTU does not publish a price on that page. [`R5R6-S21`] Neither Linux/ARM64 driver behaviour nor stable long-run capture is established by any of this; both are bench items.

**R5-F5.** Two-channel general-purpose interfaces top out at 192 kHz, which bounds usable bandwidth near 96 kHz. Purpose-built recorders reach further: the SoundTrap ST600 HF offers sample rates 384/192/128/96/64/32 kHz and a flat 20 Hz – 150 kHz (±3 dB) band, while the STD offers 192/96/64/48/32/16 kHz and 20 Hz – 60 kHz. [`R5R6-S11`] If the 1–100 kHz brief in the task is taken literally, an M2-class interface cannot cover it and an ST600 HF-class instrument or an equivalent high-rate DAQ is required. No band is frozen by this package; that remains `HD-02` in the interface record.

**R5-F6.** LoRaWAN infrastructure in Croatia cannot be assumed. The Things Network's Croatia page reports **"0 gateways"** connected countrywide, with community listings summing to 16 (Zagreb 11, Djakovo 2, Opatija 1, Osijek 1, Šibenik 1). [`R5R6-S24`] No community is listed for Rovinj, Vrsar or the Lim area. A private gateway is therefore the realistic path, matching BOM item `HUB-GATEWAY-001`.

**R5-F7.** A rated outdoor EU868 gateway is available at a published price. RAKwireless lists the WisGate Edge Pro RAK7289V2/CV2 at $382.00–$525.00 depending on channel count and LTE option, with an "IP67/NEMA-6 industrial-grade enclosure with cable glands", PoE per IEEE 802.3af (37–57 VDC) or a 12 VDC / 1 A port, EU868 among supported bands, 8- or 16-channel SX1303 options, and LoRa antennas **not included**. [`R5R6-S22`] The same page warns that connecting solar chargers directly is forbidden due to overvoltage risk and voids the warranty — directly relevant because the Poseidon REEF concept is solar-fed. [`R5R6-S22`]

**R5-F8.** The RAK3272S breakout already in the BOM (`REEF-RF-001`) is confirmed current: 2.0–3.6 V supply, typical VCC 3.3 V, UART2/LPUART1 on J4 pins 7/8 which "Supports AT commands and firmware updates", and EU868 among the supported regions. No end-of-life notice appears for the board; firmware V1.0.4 is marked deprecated in favour of RUI3. [`R5R6-S23`]

**R5-F9.** Croatian mobile coverage must be checked per site from the regulator's map, not assumed. HAKOM publishes quarterly coverage maps for A1 Hrvatska, Hrvatski Telekom and Telemach Hrvatska, with separate indoor/outdoor and voice/data layers and 2G/3G/4G/5G filters, and states that "The coverage data, i.e. the coverage maps, are produced by the operators, who are responsible for the accuracy of the submitted maps". [`R5R6-S25`] That is a self-declared dataset; it is a screening tool, not a link budget. A physical signal survey at the raft remains required.

**R5-F10.** Industrial LTE router vendors do not always publish the numbers a power budget needs. Teltonika's RUT241 product page carries placeholder specification entries and an "INQUIRE NOW" call to action rather than a published electrical or environmental table. [`R5R6-S26`] No RUT241 power, temperature or IP figure is transcribed into this package.

**R5-F11.** The BOM's MEAN WELL SD-50A-5 candidate (`HUB-DC5-001`) is confirmed by the manufacturer specification: 5 V output, 10 A rated current, 50 W, input range A: 9.2–18 VDC, output adjust 4.5–5.5 VDC, efficiency typ. 70 %, working temperature "-10 ~ +60℃", dimensions 159 × 97 × 38 mm, 1500 VAC I/O isolation. [`R5R6-S27`] The 70 % typical efficiency is a load-budget input the current repository calculations should be checked against; a 50 W-class converter at 70 % dissipates meaningful heat inside the HUB, which is the same enclosure whose heat path is already blocked (B1).

**R5-F12.** The Victron 40 W panel in the BOM is not discontinued at datasheet level. The BlueSolar monocrystalline datasheet lists `SPM040401200` as "40W-12V Mono 425 x 668 x 25mm series 4a", Pmpp 40 W, Vmpp 18.3 V, Impp 2.19 A, Voc 22.45 V, Isc 2.40 A, Voc temperature coefficient −0.35 %/°C, mass 3.1 kg, and the row carries **no** discontinued marker, whereas the 20 W, 30 W, 55 W, 90 W, 115 W, 130 W, 140 W, 175 W, 185 W, 215 W, 305 W and 360 W rows all carry the "(2)" footnote "2) Discontinued, see current models datasheet". [`R5R6-S28`] This confirms the retraction already recorded in `hardware/interfaces/reference-v1.json` revision notes. It says nothing about distributor stock.

**R5-F13.** The Victron 12.8 V / 50 Ah Smart battery (`REEF-BAT-001`) is still listed with dimensions 199 × 188 × 147 mm (h × w × d) and 7 kg, and every model in the table lists a BMS interface, "Male + female cable with M8 circular 3 pole connector, length 50cm". No discontinuation statement appears. [`R5R6-S29`] The technical-data page itself does not carry an explicit "external BMS required" sentence; that requirement is stated in the surrounding manual, which was not read in this run. The manual-versus-drawing width discrepancy recorded in the repository is unchanged by this check.

**R5-F14.** The Victron SmartSolar MPPT 75/10 (`REEF-MPPT-001`) product page is live and lists an EU RED Declaration of Conformity for the 75/10 specifically. The page does **not** publish the ordering code `SCC075010060R`, the maximum PV power at 12 V, or the maximum PV open-circuit voltage; those sit in the linked datasheet PDF, which was not read in this run. [`R5R6-S30`]

**R5-F15.** ESP32-DevKitC-32E (`REEF-CPU-001`) supply is constrained rather than discontinued: distributor listings indicate backorder with restocks scheduled and a long factory lead time, while sibling variants ESP32-DEVKITC-32U and ESP32-DEVKITC-32D-F are marked obsolete or discontinued at one distributor. [`R5R6-S31`] This is search-index evidence only (`accessed: abstract`); the distributor page was not fetched, so no stock quantity or price is transcribed.

### R6 — mechanical and marine

**R6-F1.** A rated, configurable off-the-shelf pressure boundary exists in the size class the CAD placeholder assumes. Blue Robotics publishes per-length depth ratings for its watertight-enclosure line: for the 100 mm (4") series, aluminium 6061-T6 tubes are 1000 m (200/300 mm lengths) and 900 m (400 mm), while cast-acrylic tubes of the same series are 140 m (200 mm), 100 m (300 mm) and 60 m (400 mm). End caps for the 4" series are rated 300 m in acrylic and 1000 m in aluminium; the 4" polycarbonate dome is 500 m with a plastic ring and 1000 m with an aluminium ring. The configurator base price is "From: $ 61.00", a pressure-relief valve is $32.00 and a vacuum pump $98.00. [`R5R6-S01`]

**R6-F2.** The acrylic option carries an explicit duration limit that matters more than its depth number for a seasonal deployment: the acrylic ratings apply "only for short-term submersions lasting less than two weeks". [`R5R6-S01`] A monitoring unit intended to sit on a longline for a season is outside that published condition, which pushes the tube and end-cap choice toward aluminium and makes the optical window, not the tube, the transparent element.

**R6-F3.** Compression-gland penetrators are cheap and rated, with an explicit validity condition. The Blue Robotics WetLink Penetrator is $13.00–$17.00 each (volume $9.10–$11.90 at 200–1000 units), rated to "1000 meter (3,280 feet) water depth when used with tested cables", with a design lifetime of 3 years or 500 pressure cycles, bulkhead and plug in aluminium 7075-T6 with type III anodising, FKM seal (−25 °C to 200 °C) and Buna-N 70A O-rings, in M06/M10/M14 bulkhead sizes covering roughly 3.7–9.8 mm cable jackets. The vendor states specifications apply only to tested and validated cables and that suitability determination remains the customer's responsibility. [`R5R6-S02`] The "3 years or 500 cycles" figure is a direct input to the R6 service-interval question.

**R6-F4.** A wet-mate connector family is available and rated far beyond this site. MacArtney SubConn Micro Circular (2, 3 and 4 contacts) is qualified pressure tested to "1,400 bar, 20,300 psi (mated), 800 bar, 11,600 psi (open face)", with a PEEK bulkhead depth rating of 300 bar (4,350 psi), more than 500 wet matings, 300 V DC/AC rms, 10 A per contact and 20 A per connector, water temperature −4 to 60 °C, chloroprene rubber body, gold-plated brass contacts, and bulkhead bodies in brass, stainless steel, titanium, anodised aluminium or PEEK. [`R5R6-S06`] No price is published.

**R6-F5.** A cheaper dry-mate alternative exists that shares the same bulkhead hole as the penetrator family. Blue Trail Engineering's Cobalt series uses 316 stainless shells with PEEK inserts and states "they withstand long-term use in seawater at depths up to 600 meters", with a 600 m depth rating, 0 °C to +50 °C operating temperature, M10 × 1.5 bulkhead thread, and ratings from 400 VDC/12 A (3-pin) to 150 VDC/3 A (8-pin). [`R5R6-S07`] Dry-mate means every service action must be done dry — a maintenance constraint for a fouled unit recovered from a longline, not a defect.

**R6-F6.** A neutrally buoyant tether with published mechanical numbers exists for the wet-head-to-hub run. The Blue Robotics Fathom ROV tether sells at $5.00–$8.00 per metre, in a 4-pair 7.6 mm variant and a 1-pair 4.0 mm variant, with "350 lb breaking strength" in the description and 155 kgf (342 lb) breaking / 35 kgf (77 lb) working in the spec table, 26 AWG unshielded twisted pairs arranged like Cat5, Kevlar strength members with water-blocking compound, and a 300 VDC rating. No depth rating is published for the cable itself; communication limits of 300 m (standard) and 200 m (slim) are given instead. [`R5R6-S03`] The absence of a cable depth rating, combined with R6-F3's "tested cables" condition, is a real gap for `WET-HARNESS-001`.

**R6-F7.** Two camera routes exist with published numbers. A board-level camera intended to sit inside a housing behind a window or dome: Sony Exmor IMX322/IMX323, 1/2.9", 0.01 lux minimum illumination, 1920 × 1080, 80° H / 64° V field of view, USB 2.0, 5 V at 220 mA max, 32 × 32 mm PCB, $120.00. [`R5R6-S04`] Or a self-contained rated camera that removes the window problem entirely: the DeepWater Exploration exploreHD, 400 m depth rating, anodised aluminium 6061 housing (wetted materials also 7075-T6, glass, polyurethane, Buna-N), 1/2.9" Sony Exmor CMOS rolling shutter, 1920 × 1080 at 30 fps, fisheye f/1.9 with about 82° horizontal underwater, 1 m external cable with a preinstalled WetLink Penetrator, UVC plug-and-play, about 180 mA / 0.9 W in MJPEG or 250 mA / 1.2 W in H.264, $325.00. [`R5R6-S05`]

**R6-F8.** Seawater is the aggravating factor for the aluminium/stainless couple, not an incidental one: "As a highly conductive environment, seawater tends to encourage galvanic corrosion." [`R5R6-S32`] The same guidance identifies the three prerequisites (differing corrosion potentials, a conductive connection, a conductive electrolyte film), notes that galvanic coupling can cause crevice or pitting corrosion in materials such as aluminium that would otherwise be resistant, identifies the cathode/anode area ratio and anode–cathode distance as controlling variables, and lists practical measures: electrical insulation with insulators, plastic bushes or polyamide washers; positioning the joint away from humidity; and coating the cathode or both surfaces. It notes that in salty liquid films several millimetres thick the effective cathode area extends beyond 10 cm. [`R5R6-S32`]

**R6-F9.** Hard anodising measurably improves 6061-T6 in natural seawater but does not address stress-corrosion cracking. A study forming a uniform oxide layer of roughly 25 µm found the untreated base metal had a corrosion current density about 13 times greater than the anodised sample, while "the anodizing film showed no significant effect on SCC in the slow strain rate test". [`R5R6-S33`] Both commercial candidates above rely on anodised 6061/7075. [`R5R6-S01`, `R5R6-S02`, `R5R6-S05`]

**R6-F10.** PEEK — used as the insert material in both connector families — degrades in seawater in a pressure-dependent way: "seawater absorption of PEEK and its composites were greatly accelerated by increased hydrostatic pressure in the deep sea". Testing from normal pressure to 40 MPa in artificial seawater (ASTM D1141-98, pH 8.2, about 25 °C) found tensile strength, elongation at break, flexural strength, compressive strength and impact strength all declining roughly linearly with pressure, with neat PEEK crystallinity falling from 45.3 % to 40.9 % after saturation at 40 MPa. [`R5R6-S34`] At the Lim bay pressure scale (about 0.3 MPa at 30 m, per `docs/hardware/mechanical-calculations.md` MC-05 arithmetic at 10 m) the pressure-acceleration effect is small, but the underlying absorption and plasticisation are not pressure-gated and apply at any depth over a long immersion.

**R6-F11.** Optical-window fouling has a field-tested passive answer combined with an active one. A four-month field test of a stereo-optical camera system used copper rings plus ClearSignal anti-fouling coating on the optical ports together with mechanical wipers, and reported that barnacles colonised almost every surface of the camera system **except** the optical ports carrying the mitigation measures. [`R5R6-S37`] This is abstract-level evidence from one deployment at a tidal-turbine site, not Lim bay, and it does not separate the contribution of the copper, the coating and the wiper. It is nonetheless the most directly relevant published evidence found for CAD row C4 (lens-wiper module).

**R6-F12.** Mooring practice at shellfish farms is anchor-type-driven, and the anchor choice is a seabed question this project has not asked. The NOAA aquaculture-gear guide records that shellfish systems use drag, deadweight and direct-embedment anchors; that direct-embedment toggle anchors (e.g. Platipus) and auger/helical anchors are common in shellfish systems, with "Auger anchors are widely used for floating systems as they are low cost and readily available"; that toggle anchors can be installed by hand or from a vessel and tensioned after installation; and that chain size depends on depth, gear size and required holding capacity. [`R5R6-S35`] It also records the trade-offs: drag-embedment anchors are incapable of sustaining vertical loading and need large line scopes; direct-embedment anchors are typically not recoverable; deadweight anchors have low horizontal load resistance, reduce usable water depth and need large load-handling equipment for placement. [`R5R6-S35`]

**R6-F13.** The same guide records that horizontal longlines (backbones) are typically a polyester/polyethylene blend rope whose diameter is dictated by design loading and availability, that buoys for shellfish systems are sized for nearshore low-wave-energy environments and are used both as farm markers and to hold gear at a set depth, and that farm markers may be posts, buoys or both, with size, topmark, daymark and light requirements set by the permitting authority. [`R5R6-S35`] For Poseidon this means the instrument must be attached to a structure whose own line sizing is set by the farmer's design load, and that adding a marked instrument may touch the farm's marking permit.

**R6-F14.** Lost-equipment prevention has an established international framework to borrow from, even though it is written for capture-fishery gear. The FAO Voluntary Guidelines on the Marking of Fishing Gear were endorsed by COFI 33 in July 2018 and take a systems approach that includes "mechanisms to ensure legality, enforcement, lost gear reporting and recovery, and the safe and environmentally sound disposal of ALDFG". [`R5R6-S36`] Applying its logic to a research instrument means: durable owner marking on the unit and on its attachment, a recorded position, a loss-reporting route to the farm operator and the reserve authority, and a retrieval plan agreed before deployment.

**R6-F15.** Lim bay's own fouling record raises the service interval question directly. `R5R6-S16` records *pergolari* in Lim Bay overgrown by an undetermined green alga that blocks water flow and causes mussel deaths, and nets used against predation. A camera window and a hydrophone in the same water column, at the same depths, face the same growth. No fouling rate, and therefore no service interval, can be set from published data; this needs a measured local trial.

## Candidate tables

Every price is the figure published on the vendor page on the retrieval date, before VAT, shipping and duty unless stated. No quote was requested from anyone.

### Enclosures, windows and pressure-boundary parts

| Vendor | Model / item | Key published numbers | Published price | Retrieved | Source |
|---|---|---|---|---|---|
| Blue Robotics | Watertight Enclosure, 100 mm (4") series, aluminium 6061-T6 tube | 1000 m (200 and 300 mm lengths); 900 m (400 mm length) | From $61.00 (configurator base) | 2026-09-09 | `R5R6-S01` |
| Blue Robotics | Watertight Enclosure, 100 mm (4") series, cast acrylic tube | 140 m (200 mm), 100 m (300 mm), 60 m (400 mm); rating valid "only for short-term submersions lasting less than two weeks" | From $61.00 (configurator base) | 2026-09-09 | `R5R6-S01` |
| Blue Robotics | 4" series end caps | Acrylic blank 300 m; aluminium blank and M10/M14 hole patterns 1000 m | not published separately on the configurator page | 2026-09-09 | `R5R6-S01` |
| Blue Robotics | 4" polycarbonate dome | 500 m with plastic ring; 1000 m with aluminium ring | not published separately on the configurator page | 2026-09-09 | `R5R6-S01` |
| Blue Robotics | 75 mm (3") series | Aluminium 1000 m (150–400 mm); acrylic 275 m (150 mm) to 120 m (400 mm); acrylic end cap 400 m | From $61.00 (configurator base) | 2026-09-09 | `R5R6-S01` |
| Blue Robotics | Pressure relief valve (PRV) | "strongly recommended" with the locking cord | $32.00 | 2026-09-09 | `R5R6-S01` |
| Blue Robotics | Vacuum pump | leak-check tool | $98.00 | 2026-09-09 | `R5R6-S01` |
| DeepWater Exploration (sold via Blue Robotics) | exploreHD USB camera | 400 m; anodised aluminium 6061 housing; 1080p30; ~180–250 mA at 5 V | $325.00 | 2026-09-09 | `R5R6-S05` |

Nothing in this table is an EU-sourced item. No EU or Croatian vendor of small rated instrument housings was located with published prices in this pass; Blue Robotics operates an authorised-distributor network including German resellers, which is the plausible EU purchase route, but no distributor price or lead time was verified in this pass.

### Hydrophones

| Vendor | Model | Sensitivity | Band | Self-noise | Depth | Cable / connector | Published price | Retrieved | Source |
|---|---|---|---|---|---|---|---|---|---|
| Teledyne RESON | TC4013 | −211 dB ±3 dB re 1V/µPa | 1 Hz – 170 kHz usable | not published | 700 m operating, 1000 m survival | 6 m standard cable, other lengths on request; NBR encapsulation; 3.4 nF | not published | 2026-09-09 | `R5R6-S08` |
| High Tech Inc | HTI-96-MIN | −201 dB re 1V/µPa without preamp; −165 dB max with preamp | 2 Hz – 30 kHz | 78 dB re 1 µPa RMS (1–1000 Hz); 42 dB re 1 µPa/√Hz at 100 Hz and 1 kHz | 500 m "with no signal degradation"; implodes at 1000 m | not published | not published | 2026-09-09 | `R5R6-S09` |
| Aquarian Scientific (via NAUTA distributor) | AS-1 | −208 dBV re 1 µPa (40 µV/Pa) | 1 Hz – 100 kHz ±2 dB | not published | 200 m operating, 350 m survival | 9 m polyurethane, BNC; PA4/PA6 48 V phantom preamps | not published | 2026-09-09 | `R5R6-S13` |
| Ambient Recording | ASF-2 MKII | not published | 70 Hz – 20 kHz linear | not published | 10 m max depth (equal to cable length) | 10 m polyurethane cast into housing, XLR, 48 V phantom, 5 mA | €460.00 excl. VAT | 2026-09-09 | `R5R6-S10` |
| Ocean Instruments | SoundTrap ST600 STD (integrated recorder) | not published as dB re 1V/µPa; factory single-point calibration at 250 Hz | 20 Hz – 60 kHz ±3 dB | < 36 dB re 1 µPa above 2 kHz; better than sea state 0 (100 Hz – 2 kHz) | 200 m titanium housing, 500 m with optional PRV | self-contained; 530 × 60 mm, 2.6 kg air / 1.2 kg water with 12 cells | $4,700.00 (STD); $5,500.00 (HF) | 2026-09-09 | `R5R6-S11`, `R5R6-S12` |
| Ocean Instruments | SoundTrap ST600 HF | as above | 20 Hz – 150 kHz ±3 dB | < 37 dB re 1 µPa above 2 kHz | as above | as above | $5,500.00 | 2026-09-09 | `R5R6-S11` |

Lead-time note, published: SoundTrap "has up to 10 weeks production lead time" and ships without batteries because of shipping restrictions. [`R5R6-S12`] No lead time is published by Teledyne, High Tech Inc or Ambient on the pages read.

Band coverage against the task's 1–100 kHz brief: TC4013 and AS-1 cover it; HTI-96-MIN and ASF-2 MKII do not; ST600 STD does not, ST600 HF does. Only the ST600 publishes a self-noise figure in a directly comparable form; the ASF-2 MKII publishes neither sensitivity nor self-noise, which makes it unusable for any calibrated work regardless of price.

### Connectors, cables, penetrators and strain relief

| Vendor | Item | Key published numbers | Published price | Retrieved | Source |
|---|---|---|---|---|---|
| Blue Robotics | WetLink Penetrator | 1000 m with tested cables; 3 years or 500 pressure cycles design life; 7075-T6 type III anodised; FKM seal; M06/M10/M14; 3.7–9.8 mm cables | $13.00–$17.00 each; $9.10–$11.90 at 200–1000 units | 2026-09-09 | `R5R6-S02` |
| Blue Robotics | Fathom ROV tether (by the metre) | 7.6 mm 4-pair / 4.0 mm 1-pair; 155 kgf breaking, 35 kgf working; 26 AWG UTP; 300 VDC; neutrally buoyant; **no depth rating published** | $5.00–$8.00 per metre | 2026-09-09 | `R5R6-S03` |
| MacArtney | SubConn Micro Circular, 2/3/4 contacts (wet-mate) | 1400 bar mated / 800 bar open face qualified; PEEK bulkhead 300 bar; >500 wet matings; 300 V; 10 A/contact, 20 A/connector; water −4 to 60 °C | not published | 2026-09-09 | `R5R6-S06` |
| Blue Trail Engineering | Cobalt series (dry-mate) | 600 m; 316 stainless shell, PEEK insert; M10 × 1.5 thread, same 10 mm hole as BR penetrators; 0 to +50 °C; 400 VDC/12 A (3-pin) to 150 VDC/3 A (8-pin) | not published on the datasheet | 2026-09-09 | `R5R6-S07` |

Strain relief: no dedicated strain-relief product with published ratings was located in this pass. Both penetrator families transfer cable load into the end cap through a compression gland or a threaded shell; neither vendor publishes an allowable cable pull. This is an open item, not a solved one.

### Acquisition / DAQ

| Vendor | Model | Key published numbers | Published price | Retrieved | Source |
|---|---|---|---|---|---|
| MOTU | M2 (2-in USB-C interface) | 44.1–192 kHz; 120 dB dynamic range on outputs; −129 dBu EIN on mic inputs; 48 V phantom per input; USB-C bus powered | not published on the vendor page | 2026-09-09 | `R5R6-S21` |
| Ocean Instruments | SoundTrap ST600 STD / HF | 16-bit SAR ADC; 192 kHz (STD) or 384 kHz (HF) max; up to 2 TB microSD; 12 × 18650 cells; up to 160 days continuous | $4,700 / $5,500 | 2026-09-09 | `R5R6-S11`, `R5R6-S12` |

No multichannel synchronised-clock hydrophone interface with a published input-noise figure and a published price was located in this pass. That is a gap, and it matters only if R2 shows localisation is justified (`ARRAY-DAQ-OPT-001` stays omitted until then).

### Communications

| Vendor | Model | Key published numbers | Published price | Retrieved | Source |
|---|---|---|---|---|---|
| RAKwireless | WisGate Edge Pro RAK7289V2 / RAK7289CV2 | IP67/NEMA-6 with cable glands; PoE 802.3af 37–57 VDC or 12 VDC/1 A; EU868 among bands; 8 or 16 channel SX1303; LoRa antennas not included; direct solar-charger connection forbidden | $382.00–$525.00 | 2026-09-09 | `R5R6-S22` |
| RAKwireless | RAK3272S breakout (RAK3172 core) | 2.0–3.6 V supply, 3.3 V typical; UART2/LPUART1 on J4.7/J4.8; EU868 supported; no EOL notice | not published on the datasheet | 2026-09-09 | `R5R6-S23` |
| The Things Network | Croatia community network | "0 gateways" reported countrywide; community listings sum to 16, none in the Lim area | free community network | 2026-09-09 | `R5R6-S24` |
| HAKOM | Mobile coverage maps (A1, HT, Telemach) | quarterly publication; 2G/3G/4G/5G, indoor/outdoor, voice and data layers; operator-supplied data | public | 2026-09-09 | `R5R6-S25` |
| Teltonika | RUT241 industrial LTE router | product page publishes no electrical or environmental specification table | not published ("INQUIRE NOW") | 2026-09-09 | `R5R6-S26` |

### Power (BOM parts re-verified)

| Vendor | Model | Key published numbers | Published price | Retrieved | Source |
|---|---|---|---|---|---|
| MEAN WELL | SD-50A-5 | 5 V / 10 A / 50 W; input 9.2–18 VDC; adjust 4.5–5.5 V; efficiency typ. 70 %; −10 to +60 °C; 159 × 97 × 38 mm; 1500 VAC isolation | not published on the manufacturer spec | 2026-09-09 | `R5R6-S27` |
| Victron Energy | SPM040401200 BlueSolar 40 W 12 V mono | 425 × 668 × 25 mm; Pmpp 40 W; Vmpp 18.3 V; Impp 2.19 A; Voc 22.45 V; Isc 2.40 A; Voc coefficient −0.35 %/°C; 3.1 kg; **no discontinued marker** | not published on the datasheet | 2026-09-09 | `R5R6-S28` |
| Victron Energy | 12.8 V / 50 Ah Smart lithium (BAT512050610) | 199 × 188 × 147 mm; 7 kg; BMS interface M8 3-pole, 50 cm; no discontinuation notice | not published on the technical-data page | 2026-09-09 | `R5R6-S29` |
| Victron Energy | SmartSolar MPPT 75/10 | product page live, EU RED DoC listed for 75/10; ordering code, max PV power and max PV Voc not on that page | not published | 2026-09-09 | `R5R6-S30` |
| Raspberry Pi | Raspberry Pi 5 | 5 V/5 A USB-C PD; operating temperature 0–70 °C; production to at least January 2036 | $305 shown for 16 GB only | 2026-09-09 | `R5R6-S18` |
| Raspberry Pi | Compute Module 5 | shutdown 1.3/3 mA; idle 400 mA; operation 900 mA; RTC 1.7 µA at 5 V; −20 to +85 °C non-condensing | not published on the datasheet | 2026-09-09 | `R5R6-S19` |
| Raspberry Pi | Raspberry Pi 4 Model B | listed for sale; no production-lifetime statement on the page | "From $35" | 2026-09-09 | `R5R6-S20` |

### BOM availability check

Every part id in [`hardware/bom/reference-v1.json`](../../hardware/bom/reference-v1.json), with the result of this pass. "Vendor page live" means a manufacturer or manufacturer-store page for the exact named part was read on 2026-09-09. No distributor stock level or price was verified for any part; none of these results is a procurement release.

| BOM id | Named part | Availability result | Source |
|---|---|---|---|
| `HUB-CPU-001` | Raspberry Pi 4 Model B 4 GB (SC0194) | Vendor page live, product still offered; no production-lifetime statement; ordering code SC0194 not shown on the page | `R5R6-S20` |
| `HUB-DC5-001` | MEAN WELL SD-50A-5 | Manufacturer specification live and current; SD-50A-5 present in the model table | `R5R6-S27` |
| `HUB-PSU-ALT-001` | Raspberry Pi 15 W USB-C PSU | Not checked in this pass — superseded in relevance by the Pi 5 27 W supply; no vendor page read | — |
| `HUB-USBC-001` | COTS 5.1 V / 3 A USB-C source | No part named in the BOM; nothing to check | — |
| `HUB-STORE-001` | Industrial storage / SSD | No part named in the BOM; nothing to check | — |
| `HUB-DAQ-001` | Above-water DAQ and analog conditioner | No part named in the BOM. Candidates now identified: MOTU M2, SoundTrap ST600 | `R5R6-S21`, `R5R6-S11` |
| `HUB-ENC-001` | Above-water weather enclosure | No part named in the BOM; nothing to check | — |
| `ENC-ALT-001` | Hammond 1554V2GY | **Not verified** — manufacturer pages returned HTTP 403 and a distributor page timed out | `R5R6-S39` |
| `HUB-PROTECT-001` | DC protection assembly | No part named in the BOM; nothing to check | — |
| `WET-HYD-001` | Analog receive hydrophone | No part named in the BOM. Candidates now identified: TC4013, HTI-96-MIN, AS-1, ASF-2 MKII, ST600 | `R5R6-S08`, `R5R6-S09`, `R5R6-S13`, `R5R6-S10`, `R5R6-S11` |
| `WET-CAM-001` | Camera, lens, wet interface | No part named in the BOM. Candidates now identified: BR low-light USB camera, DWE exploreHD | `R5R6-S04`, `R5R6-S05` |
| `WET-PRESSURE-001` | Blue Robotics pressure enclosure family | Vendor configurator live with per-length depth ratings and a base price | `R5R6-S01` |
| `WET-HARNESS-001` | Wet cables, penetrators, strain relief | No part named in the BOM. Candidates now identified: WetLink Penetrator, Fathom tether, SubConn Micro Circular, Cobalt series | `R5R6-S02`, `R5R6-S03`, `R5R6-S06`, `R5R6-S07` |
| `REEF-CPU-001` | Espressif ESP32-DevKitC-32E | Active product, supply constrained: distributor backorder with scheduled restocks; sibling variants -32U and -32D-F marked obsolete/discontinued. Search-index evidence only | `R5R6-S31` |
| `REEF-RF-001` | RAKwireless RAK3272S | Vendor datasheet live and current; EU868 supported; no EOL notice; firmware V1.0.4 deprecated | `R5R6-S23` |
| `REEF-DC-001` | COTS 12→5 V and 3.3 V regulators | No part named in the BOM; nothing to check | — |
| `REEF-BAT-001` | Victron BAT512050610 | Vendor technical data live; 12.8 V / 50 Ah listed with dimensions; no discontinuation notice | `R5R6-S29` |
| `REEF-BMS-001` | Victron external Smart BMS | No exact model named in the BOM. Vendor lists a BMS interface connector on every battery model | `R5R6-S29` |
| `REEF-MPPT-001` | Victron SCC075010060R (MPPT 75/10) | Product page live with an EU RED DoC for the 75/10; the ordering code is not shown on that page | `R5R6-S30` |
| `REEF-PV-001` | Victron SPM040401200 (40 W) | Datasheet live; the 40 W row carries **no** discontinued marker while twelve other rows do | `R5R6-S28` |
| `REEF-ENC-001` | REEF enclosure | No part named in the BOM; nothing to check | — |
| `REEF-PROBE-001` | Wet environmental probes | No part named in the BOM; nothing to check | — |
| `REEF-ANT-001` | EU868 antenna and surge strategy | No part named in the BOM; nothing to check. Note: RAK7289 gateway antennas are sold separately | `R5R6-S22` |
| `HUB-GATEWAY-001` | EU868 LoRaWAN gateway | No part named in the BOM. Candidate now identified: RAK7289V2/CV2, $382–$525, IP67. TTN reports 0 gateways in Croatia | `R5R6-S22`, `R5R6-S24` |
| `ARRAY-DAQ-OPT-001` | Additional hydrophones / shared clock | Omitted option; no part named. No multichannel synchronised interface with published noise and price located | — |
| `WIPER-DRIVE-OPT-001` | Wiper motor and driver | Omitted option; no part named. Field evidence for the wiper concept exists but not for any specific drive | `R5R6-S37` |
| `PROJECTOR-AMP-OPT-001` | Optional amplifier | Omitted option; no part named; out of scope for R5/R6 (owned by R4) | — |
| `PROJECTOR-XDCR-OPT-001` | Optional projector | Omitted option; no part named; out of scope for R5/R6 (owned by R4) | — |
| `PROJECTOR-STOP-OPT-001` | Independent safety controller | Omitted option; no part named; architecture concept only | — |
| `FARM-HARNESS-001` | Surface DC/data harness | No part named in the BOM; nothing to check | — |
| `JIG-ELEC-001` | Electrical test jigs | No part named in the BOM; nothing to check | — |

Summary: 31 BOM ids checked. 7 have a named part with a live vendor page confirming the part still exists (`HUB-CPU-001`, `HUB-DC5-001`, `WET-PRESSURE-001`, `REEF-RF-001`, `REEF-BAT-001`, `REEF-MPPT-001`, `REEF-PV-001`). 1 has a named part with search-index-only evidence and constrained supply (`REEF-CPU-001`). 1 named part could not be verified at all (`ENC-ALT-001`, HTTP 403). 1 named part was not checked (`HUB-PSU-ALT-001`). The remaining 21 ids name no manufacturer part, so availability is not a meaningful question for them yet. **No discontinuation was found for any named BOM part in this pass.**

## Materials and corrosion

| Material | Published behaviour relevant to this build | Where it appears in candidate hardware | Source |
|---|---|---|---|
| Aluminium 6061-T6, hard anodised | Anodising to about 25 µm reduced corrosion current density by roughly 13× versus base metal in natural seawater; no significant effect on stress-corrosion cracking | Blue Robotics tubes and end caps; exploreHD housing | `R5R6-S33`, `R5R6-S01`, `R5R6-S05` |
| Aluminium 7075-T6, type III anodised | Used as penetrator bulkhead and plug material; vendor design life 3 years or 500 pressure cycles | WetLink Penetrator; exploreHD wetted parts | `R5R6-S02`, `R5R6-S05` |
| 316 stainless steel | Cathodic relative to aluminium; used as connector shell material for long-term seawater service | Cobalt connector shells; SubConn bulkhead option | `R5R6-S07`, `R5R6-S06`, `R5R6-S32` |
| Aluminium ↔ 316 stainless couple | Seawater is highly conductive and "tends to encourage galvanic corrosion"; the aluminium is the anode; cathode/anode area ratio and separation distance control the rate; insulation with plastic bushes or polyamide washers, coating the cathode, and avoiding wetted joints are the named remedies; in salty films several mm thick the effective cathode area exceeds 10 cm | Cobalt 316 bulkhead threaded into an anodised aluminium end cap is exactly this couple | `R5R6-S32` |
| PEEK | Absorbs seawater; absorption accelerates strongly with hydrostatic pressure; tensile, flexural, compressive and impact strength and elongation all fall after saturation; crystallinity of neat PEEK fell 45.3 % → 40.9 % at 40 MPa saturation | Connector inserts in both Cobalt and SubConn PEEK-bulkhead variants | `R5R6-S34` |
| POM / acetal | **No published seawater-immersion data source was read in this pass.** Do not carry any acetal claim into design | not present in any candidate above | — |
| Fibreglass / GRP | **No published seawater-immersion data source was read in this pass.** | not present in any candidate above | — |
| Chloroprene rubber, nitrile O-rings, gold-plated brass contacts | SubConn published wetted-material set; water service −4 to 60 °C | SubConn Micro Circular | `R5R6-S06` |
| FKM seal, Buna-N 70A O-ring | Penetrator seal set; FKM −25 to 200 °C | WetLink Penetrator | `R5R6-S02` |
| Titanium | Housing material of a 200 m-rated commercial recorder | SoundTrap ST600 | `R5R6-S11` |
| Copper ring + ClearSignal coating on optical ports | In a four-month field test, barnacles colonised almost every surface except the optical ports carrying copper rings, ClearSignal coating and wipers | Candidate approach for the C4 window/wiper package | `R5R6-S37` |

Two rows are deliberately empty. The task asked about POM/acetal and fibreglass; no source with published seawater-immersion data for those materials was read in this run, so nothing is asserted about them.

## Mooring options

All rows are published practice from the NOAA technical guide to marine aquaculture gear; none is a design for this site, and none accounts for the instrument's own drag, mass or recovery loads.

| Option | Published characteristics | Consequence for a wired instrument on a Lim bay longline | Source |
|---|---|---|---|
| Attach to the farmer's existing backbone / longline | Horizontal longlines are typically polyester/polyethylene blend rope, diameter set by design loading and availability; buoys hold gear at a chosen depth | Cheapest and least invasive; the instrument becomes an added load on someone else's engineered line, so the farmer's designer must accept it. Attachment depth is chosen by buoyancy, not by a new mooring | `R5R6-S35` |
| Auger / helical direct-embedment anchor | Widely used for floating systems, low cost, readily available; accurate placement possible; does not protrude above the seafloor; higher holding-capacity-to-weight ratio than other types; **typically not recoverable** | Good for a season-long dedicated mooring in suitable sediment. Not recoverable conflicts with a research deployment that must leave no trace in a special marine reserve | `R5R6-S35` |
| Toggle anchor (e.g. Platipus type) | Direct-embedment; installable by hand or from a vessel; tensioned after installation; consists of anchor, wire tension rod and top accessory | Deployable without heavy plant, which matters for a solo builder with a small boat | `R5R6-S35` |
| Deadweight anchor | Large vertical reaction component permitting shorter mooring-line scope; no setting distance; reliable holding from mass; simple onsite construction; but low horizontal load resistance, reduced usable water depth, and needs large load-handling equipment to place | Simple and fully recoverable, but the placement equipment requirement is the blocker for a small operation | `R5R6-S35` |
| Drag-embedment anchor | Capacity exceeds 100,000 lbs; standard off-the-shelf equipment; recoverable; but incapable of sustaining vertical loading and requires large line scopes; does not function in hard seafloors | Large footprint for a small instrument; scope requirement conflicts with a 32 m-deep, 650 m-wide inlet with other users | `R5R6-S35` |
| Surface marking | Farm markers may be posts, buoys or both; buoy size requirements relate to topmark dimensions, shape, daymarks and light signals; requirements are set by the permitting authority | An added instrument buoy may fall inside the farm's marking permit and the reserve's navigation rules. Confirm with the farm operator and the reserve authority before adding any surface marker | `R5R6-S35` |
| Loss prevention and retrieval | FAO's systems approach covers legality, enforcement, lost-gear reporting and recovery, and environmentally sound disposal | Adopt: durable owner marking on unit and attachment, recorded position, an agreed loss-report route to the farm operator and Natura Histrica, and a pre-agreed retrieval plan | `R5R6-S36` |

## Gaps that need measurement or a marine engineer

| Id | Gap | Why desk research cannot close it | Owner |
|---|---|---|---|
| G-01 | Rated depth and continuous immersion duration for the wet head | Vendor depth ratings are per configuration; the acrylic caveat is a duration limit, and the penetrator life is "3 years or 500 cycles" — the project has no declared depth or season length to compare against | Root/user with farm partner (`HD-01`) |
| G-02 | Site loads: waves, storm current, gear motion | `R5R6-S15` gives fair-weather June currents of 0.8–2.2 cm/s; no storm case, no wave height, no line-motion data exists for the inlet | Marine/mechanical engineer with farm survey |
| G-03 | Seabed holding characteristics at candidate anchor points | Anchor type selection in `R5R6-S35` is explicitly substrate-dependent; the seabed is described only as muddy with grain size increasing toward the mouth (`R5R6-S15`) | Marine engineer + farm operator |
| G-04 | As-built mass, centre of gravity and displaced volume of the wet head | `docs/hardware/mechanical-calculations.md` MC-03/MC-04 use an assumed 3 kg and an envelope cylinder; no candidate part masses have been summed into a real figure | Mechanical reviewer |
| G-05 | Allowable cable pull at the penetrator and at the connector | Neither penetrator nor connector vendor publishes a cable-load limit; the tether publishes 35 kgf working strength but that is the rope, not the termination | Mechanical reviewer + vendor technical enquiry (not made) |
| G-06 | Fouling rate on window, hydrophone face and housing at this site | `R5R6-S37` is a four-month test at a different site with three mitigations combined; `R5R6-S16` records severe local algal growth. No rate exists for Lim bay | Local trial |
| G-07 | Service interval | Follows directly from G-01 and G-06; cannot be set from published data | Hardware + validation reviewer (`HD-08`) |
| G-08 | Galvanic detail design at every aluminium/stainless interface | `R5R6-S32` gives the mechanism and remedies but the area ratios, isolation parts and coatings for this specific assembly are a design task | Mechanical/corrosion reviewer |
| G-09 | POM/acetal and fibreglass seawater behaviour | Not researched to a citable source in this pass; no claim may be made about them | Research follow-up |
| G-10 | HUB heat path with real parts | `R5R6-S27` adds a 70 %-efficiency converter to the enclosed heat; blocker B1 in `docs/hardware/power-refinement.md` remains open, and the Pi 5's 0–70 °C rating (`R5R6-S18`) changes the screen only if the CPU changes | Electrical/thermal reviewer |
| G-11 | Measured 4G signal at the raft | HAKOM maps are operator-supplied and illustrative (`R5R6-S25`); a physical survey with the intended antenna is required | Field survey |
| G-12 | LoRaWAN network path | TTN reports 0 gateways in Croatia (`R5R6-S24`); a private gateway (`R5R6-S22`) plus a network server and backhaul must be designed and costed | Firmware/hardware reviewer (`HD-05`) |
| G-13 | Multichannel synchronised acquisition | No candidate with a published input-noise figure and price was located; only relevant if R2 justifies localisation | Acquisition specialist (`HD-02`) |
| G-14 | Linux/ARM64 driver and long-run capture stability for any chosen DAQ | Class-compliance claims are vendor statements about Mac/Windows; nothing here is a Linux test | Bench test |
| G-15 | Distributor stock, EU pricing, VAT, duty and lead time for every item above | All prices are US vendor list prices; no distributor page, quote or lead time (except SoundTrap's published 10 weeks) was obtained | Procurement, when authorised |

## Quote-ready line list

Parts a human could request quotes for, once someone with authority decides to. **No quote was requested and no supplier was contacted in this work.** Quantities are one unit unless a range is stated, and each line names what the quote must include beyond unit price.

1. Watertight enclosure assembly, 100 mm (4") series, aluminium 6061-T6 tube 300 mm, aluminium end cap with M10/M14 penetrator pattern one end, polycarbonate dome with aluminium ring the other end, O-ring flanges, pressure relief valve, O-ring pick — ask for EU-delivered price, VAT, duty, lead time and the vendor's stated depth rating for the exact assembled configuration. [`R5R6-S01`]
2. Same, alternative: 75 mm (3") series aluminium equivalent for a smaller hydrophone-only head. [`R5R6-S01`]
3. WetLink Penetrators, M10 bulkhead, seal sizes to be set by the chosen cable diameter, quantity 6–10 including spares, plus blanks — ask which of the vendor's *validated* cables the quote's seal size is tested against. [`R5R6-S02`]
4. Fathom ROV tether, 4-pair 7.6 mm, length to be fixed by the site survey (order of 20–50 m), by the metre — ask explicitly for any depth rating the vendor will state in writing, since the product page publishes none. [`R5R6-S03`]
5. Cobalt series bulkhead connectors and matching cables, 4-pin or 6-pin, quantity 2–4 — ask for price, EU availability and the vendor's guidance on the 316-stainless-into-anodised-aluminium interface. [`R5R6-S07`]
6. SubConn Micro Circular 4-contact wet-mate pair, bulkhead plus inline, PEEK or 316 bulkhead body — ask for price, minimum order and lead time; MacArtney publishes none. [`R5R6-S06`]
7. Reference hydrophone Teledyne RESON TC4013 with a cable length to suit the head, individually calibrated — ask for calibration certificate scope, EU price and lead time. [`R5R6-S08`]
8. Alternative hydrophone High Tech Inc HTI-96-MIN with a stated preamp mode and cable termination — ask for price, connector options and depth-rated cable termination. [`R5R6-S09`]
9. Alternative hydrophone Aquarian Scientific AS-1 with PA4 preamp, cable length stated — ask NAUTA (EU stock) for price and lead time. [`R5R6-S13`]
10. Integrated recorder Ocean Instruments SoundTrap ST600 STD ($4,700 published) or HF ($5,500 published), with the optional pressure relief valve for the 500 m rating, plus batteries sourced separately and a charger — published lead time up to 10 weeks. [`R5R6-S11`, `R5R6-S12`]
11. USB audio interface MOTU M2 — ask a distributor for price; MOTU publishes none. [`R5R6-S21`]
12. Camera, either DeepWater Exploration exploreHD ($325 published, self-contained 400 m) or the board-level Blue Robotics low-light USB camera ($120 published) plus dome and internal mount. [`R5R6-S05`, `R5R6-S04`]
13. LoRaWAN gateway RAKwireless RAK7289V2, 8-channel, EU868, plus the LoRa antenna that is not included, plus PoE injector or 12 V supply — published $382. [`R5R6-S22`]
14. LoRa modem RAK3272S, EU868 ordering variant to be resolved before ordering, plus antenna and pigtail. [`R5R6-S23`]
15. Solar and storage, re-confirming the existing BOM: Victron SPM040401200 40 W panel (×1 or ×2 per the two-series comparison in `docs/hardware/power-refinement.md`), BAT512050610 12.8 V/50 Ah battery, SmartSolar MPPT 75/10, and the compatible external BMS with load and charge disconnect devices — ask for the exact BMS model the supplier will pair with the battery. [`R5R6-S28`, `R5R6-S29`, `R5R6-S30`]
16. DC/DC converter MEAN WELL SD-50A-5 — ask for EU distributor price and stock. [`R5R6-S27`]
17. Compute: Raspberry Pi 5 with the 27 W USB-C supply, or CM5 with a carrier — ask for the industrial/extended-temperature variant availability where it exists. [`R5R6-S18`, `R5R6-S19`]
18. Anti-fouling consumables for the window: copper ring stock and an optically clear fouling-release coating of the ClearSignal type — ask for optical transmission data and cure/handling requirements. [`R5R6-S37`]
19. Mooring hardware, only if a dedicated mooring is chosen over attaching to the farmer's backbone: toggle or auger anchor set with tension rod and top accessory, chain, shackles and thimbles sized by a marine engineer. [`R5R6-S35`]
20. Enclosure for the hub and REEF electronics — no vendor could be verified this pass (`ENC-ALT-001` unreachable); re-run this line once the Hammond or an alternative page is readable. [`R5R6-S39`]

## Recommendation

**REVISE.** Do not proceed to detailed underwater-head CAD (row C3) yet, and do not proceed to the wiper/projector package (row C4) at all in this wave.

What passes:

- A rated, purchasable pressure boundary exists in the right size class, with published per-configuration depth ratings that comfortably exceed 30 m, and a published base price. [`R5R6-S01`]
- Penetrators, tether and both wet-mate and dry-mate connector families exist with published ratings and, in three of four cases, published prices. [`R5R6-S02`, `R5R6-S03`, `R5R6-S06`, `R5R6-S07`]
- Hydrophones covering 1–100 kHz exist with published sensitivity and depth ratings, and one integrated recorder publishes self-noise, band, depth, endurance, price and lead time. [`R5R6-S08`, `R5R6-S13`, `R5R6-S11`, `R5R6-S12`]
- A camera route exists that removes the window design problem entirely at $325. [`R5R6-S05`]
- The site's published temperature, salinity, current and visibility ranges are benign relative to every candidate's published envelope. [`R5R6-S15`]
- No named BOM part was found discontinued. [`R5R6-S27`, `R5R6-S28`, `R5R6-S29`, `R5R6-S30`, `R5R6-S23`, `R5R6-S20`]

What blocks detailed CAD:

- **G-01.** There is still no declared depth or immersion duration. Vendor ratings are per configuration and, for acrylic, expire at two weeks. A head cannot be dimensioned against an undeclared envelope. [`R5R6-S01`]
- **G-13/`HD-02`.** The receive chain is unchosen, and the choice changes the head's internal volume, penetrator count and cable diameter by a large factor: an analog hydrophone plus above-water DAQ is a different head from an integrated 530 × 60 mm titanium recorder. [`R5R6-S11`, `R5R6-S21`]
- **G-05.** No vendor publishes an allowable cable pull at the penetrator or connector, and the head hangs on a moving longline. That is a load path with no number in it.
- **G-08.** Every candidate assembly puts 316 stainless into anodised aluminium in a highly conductive electrolyte, which is the couple the corrosion guidance singles out. The isolation detail must be designed before geometry is frozen. [`R5R6-S32`]
- **G-06/G-07.** Local fouling is documented as severe enough to kill mussels, and no fouling rate or service interval exists. Window, wiper and mount geometry all depend on it. [`R5R6-S16`, `R5R6-S37`]

Minimum set that would turn this into a PASS for C3: a declared depth and immersion duration; a chosen receive chain (analog + DAQ, or integrated recorder); a stated attachment point and load case from the farm survey; and a corrosion-isolation scheme reviewed by a competent person. Three of those four are decisions the project can take without new measurement; only the load case needs the site visit.

For C4 the answer is **stop for now**: the only field evidence found for window anti-fouling combines copper, coating and a wiper in one four-month test at another site and does not separate their contributions, so a wiper cannot be justified as a required mechanism yet. [`R5R6-S37`]

## Method and integrity notes

1. Repository inputs read first: the audit plan (section 3 rows R5 and R6, section 5 rows C3 and C4), [`HARDWARE.md`](../../HARDWARE.md), [`hardware/interfaces/reference-v1.json`](../../hardware/interfaces/reference-v1.json), [`hardware/bom/reference-v1.json`](../../hardware/bom/reference-v1.json), [`docs/hardware/reference-decisions.md`](../../docs/hardware/reference-decisions.md), [`docs/hardware/power-refinement.md`](../../docs/hardware/power-refinement.md), [`hardware/candidates/passive-v2/README.md`](../../hardware/candidates/passive-v2/README.md) and [`docs/hardware/mechanical-calculations.md`](../../docs/hardware/mechanical-calculations.md).
2. Web search and page fetch only. No account was created, no form submitted, no message sent, no purchase made, no binary executable downloaded. Several vendor PDFs were cached by the fetch tool and their text was read locally with a PDF text extractor; those are marked `full` in the register.
3. Every quantitative statement carries a source id. Where a vendor does not publish a value the tables say **not published**. No price was converted between currencies, no rating was interpolated, and no figure was averaged.
4. A vendor depth rating, an IP code or a materials list describes a tested vendor configuration. None of it establishes suitability for this site, this duration, this attachment or this assembly.
5. This package changes no other repository file. It does not modify the BOM, the interface record, the CAD or any calculation, and it does not close `HD-01` through `HD-08`.

This is desk research; no measurement, purchase, supplier contact or suitability claim is made.
