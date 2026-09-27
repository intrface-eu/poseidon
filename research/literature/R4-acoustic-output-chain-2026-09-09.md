# R4 — Acoustic safety and output chain

Package: `R4`. Desk review date: **2026-09-09**. Reviewer: research worker (not an underwater-acoustics specialist).
Status: **desk research only**. No measurement, calibration, permit application, purchase, contact with any vendor or authority, and no efficacy or safety conclusion.

Companion machine-readable source register: [`R4-acoustic-output-chain-2026-09-09.sources.json`](R4-acoustic-output-chain-2026-09-09.sources.json).

This is desk research; no measurement, permit, purchase or efficacy claim is made.

## Question

R4 in the production roadmap asks what an underwater-acoustics specialist would need in order to define an operating envelope, and what output hardware and calibration access exist. This package answers the desk-answerable part of five sub-questions:

- **Q-a** Which pressure and exposure measures, and which particle-motion considerations, apply when assessing a fish deterrent; what published hearing data exist for *Sparus aurata* or close sparids.
- **Q-b** Which underwater projectors and matching amplifiers are commercially available in roughly 0.5–20 kHz and could plausibly suit a small battery/solar unit, with impedance, TVR/source level, drive limits, depth rating, mass and price where published.
- **Q-c** Which calibration equipment and services (reference hydrophones, calibrators, laboratories in the EU or near Croatia) exist.
- **Q-d** Which regional noise frameworks and permit conditions plausibly apply to emitting sound inside a Croatian marine special reserve, and what a research permit application typically requires.
- **Q-e** What prior seabream and fish acoustic-deterrent trials report about effect size and habituation.

Out of scope here: selecting any component, any frequency, any level, any duty cycle, or any exposure limit. R4 does not close `REQ-SAF-001`, `REQ-SAF-002` or `TBD-SAF-001` in [`docs/requirements/production-requirements.md`](../../docs/requirements/production-requirements.md); those stay owned by a qualified specialist.

## Sources reviewed

27 sources are recorded in the JSON register with URL, publisher, retrieved date, access level and a verbatim quote. Access breakdown:

| Access | Count | Meaning |
|---|---|---|
| `full` | 16 | Page text was retrieved and read in this run. |
| `abstract` | 8 | Only an abstract, product summary or search-index summary was readable; publisher full text or datasheet PDF was not. |
| `inaccessible` | 3 | Login wall, HTTP 403, or a PDF whose text streams could not be read in this run. |

Sources fall into five families: exposure-metric and particle-motion guidance (R4-S01, R4-S02, R4-S03, R4-S05); species hearing and noise-response literature (R4-S09, R4-S10, R4-S11); vendor pages for projectors, amplifiers, reference hydrophones, calibrators and particle-motion sensors (R4-S15 to R4-S22, R4-S25, R4-S26); calibration laboratories (R4-S23, R4-S24); and regulatory or prior-trial material (R4-S04, R4-S06, R4-S07, R4-S08, R4-S12, R4-S13, R4-S14, R4-S27).

Four items that matter most were not fully readable: the ASA/ANSI fish exposure guidelines (R4-S01, login wall), the JRC TG Noise continuous-sound threshold report (R4-S05, PDF not readable in this run), the Reviews in Aquaculture predation review (R4-S12, HTTP 403; abstract read), and the ARIEL recommendations PDF (R4-S27, PDF not readable in this run; the repository audit records an earlier direct inspection of pages 3 and 19).

## Applicability to this site and species

The site is Limski zaljev in Istria, a marine special reserve managed by the public institution Natura Histrica (R4-S07). The intended predator is gilthead seabream, *Sparus aurata*, at a shellfish farm. Applicability limits that bound everything below:

- **No local data exist.** Nothing in this package is a measurement at, or a model of, Limski zaljev. Ambient level, depth, bathymetry, reverberation and propagation there are unknown, so no source level can be translated into an exposure at any distance.
- **Species-match is partial.** The strongest hearing measurements found are for European sea bass, a different family (R4-S10). Behavioural noise-response data exist for *S. aurata* itself, but only from tank studies at frequencies at or below 1 kHz (R4-S09).
- **Deterrent literature is mostly about mammals.** The most detailed efficacy and habituation evidence found concerns seals and porpoises at finfish farms (R4-S14), not sparids at shellfish farms.
- **Regulatory framework is descriptive, not permissive.** EU threshold values are area-exposure indicators for member-state assessment (R4-S04); they are not a permitted source level for one device, and Croatia has no threshold values set for D11 (R4-S06).
- **Prior negative evidence is local.** The repository requirements register records a failed 2019 Lim Bay DDD03L pinger pilot and forbids reusing that device or its band as a Poseidon default. Nothing found in this package contradicts that record.

## Method

1. Read the repository inputs: the audit plan (section 3 row R4, section 2 row D2), [`docs/requirements/production-requirements.md`](../../docs/requirements/production-requirements.md), [`hardware/interfaces/reference-v1.json`](../../hardware/interfaces/reference-v1.json), [`hardware/bom/reference-v1.json`](../../hardware/bom/reference-v1.json), [`docs/hardware/reference-decisions.md`](../../docs/hardware/reference-decisions.md), and [`docs/compliance/regulatory-applicability-2026-09-08.md`](../../docs/compliance/regulatory-applicability-2026-09-08.md). `apps/siren/README.md` does not exist; SIREN appears in the BOM only as omitted optional assemblies `PROJECTOR-AMP-OPT-001`, `PROJECTOR-XDCR-OPT-001` and `PROJECTOR-STOP-OPT-001`, all with `populated_default_qty: 0`.
2. Web search and page fetch only. No accounts, forms, messages, purchases or binary downloads were initiated. Two PDF fetches were auto-cached by the fetch tool as unreadable binary; their content was not used.
3. Every quantitative statement below is copied from a named source and carries its source id. Where a vendor or authority does not publish a value, the table says **not published**. No value is inferred, converted or averaged.
4. Paywalled or login-gated items are recorded as such, and only their abstract or landing metadata is used.

## Findings

### Q-a — Exposure measures, particle motion, and sparid hearing

**R4-F1.** The reference framework for fish sound-exposure criteria is the ANSI-accredited technical report *ASA S3/SC1.4 TR-2014, Sound Exposure Guidelines for Fishes and Sea Turtles* (R4-S01). Its full text sits behind a publisher login and was not read in this run, so **no numeric criterion from it is transcribed into this package**. A specialist must obtain the report and read the tables directly before any exposure figure enters a Poseidon document. [R4-S01]

**R4-F2.** Underwater sound levels in the applicable EU assessment framework are expressed in decibels referenced to 1 µPa, and continuous-noise assessment uses decidecade (third-octave) bands with a stated averaging rule; the HELCOM implementation uses monthly medians of modelled hourly values. [R4-S03]

**R4-F3.** That framework separates the raw level from the biological trigger through a *Level of Onset of Biologically adverse Effects* (LOBE), defined as "The noise level at which individual animals start to have adverse effects that could affect their fitness". LOBE is set per band, per receptor group and per effect (behavioural disturbance versus masking), not once for a whole device. [R4-S03]

**R4-F4.** In the HELCOM worked application the fish band is the 125 Hz decidecade band and the mammal band is 500 Hz; a 63 Hz band was modelled but not used in that evaluation. This shows that band selection is an assessment decision tied to the receptor, and it is not transferable to a 0.5–20 kHz deterrent without a specialist deciding the relevant bands. [R4-S03]

**R4-F5.** All fishes sense particle motion, and particle motion cannot be reliably predicted from sound pressure near the surface, near the bottom, or in shallow water — which is exactly the geometry of a shellfish longline farm. A published best-practice guide covers instrument choice, calibration, measurement and reporting for particle motion in biological work. [R4-S02]

**R4-F6.** Particle-motion instrumentation is a separate purchase and a separate calibration problem from a pressure hydrophone. The vendor category page for the GeoSpectrum particle motion sensor publishes **no** frequency range, sensitivity, depth rating, dimensions, weight or price; it is quote-only. [R4-S25]

**R4-F7.** No published audiogram for *Sparus aurata* was found in this review. The closest measured data found are for European sea bass (*Dicentrarchus labrax*), where auditory evoked potentials on 114 juveniles across 100, 200, 300, 400, 500 and 600 Hz gave a U-shaped audiogram with best sensitivity at 300 Hz (116.8 ± 3.3 dB re 1 µPa in the abstract; 117.2 dB at 300 Hz in the results, ranging to 126.4 dB at 600 Hz). That paper also states hearing sensitivity data are still lacking for many commercially important marine species. Sea bass is not a sparid; this is a proxy, not evidence about orada. [R4-S10]

**R4-F8.** For *S. aurata* itself the available data are behavioural, not audiometric. Juveniles were exposed for 7 h to white noise filtered in third-octave bands centred at 63, 125, 500 and 1000 Hz at 140–150 dB re 1 µPa; group dispersion fell immediately at 63 and 125 Hz and returned to control conditions after about 2 h, which the authors read as habituation, while at 1 kHz dispersion increased. This is a tank study, and tank levels are not free-field source levels. [R4-S09]

**R4-F9.** A 2025 aquaculture-noise review states that farm equipment noise sits particularly below 2000 Hz, "matching the hearing range of most cultured species". This supports treating *S. aurata* as a low-frequency-sensitive hearing generalist, and it also means a deterrent in the same band competes with, and adds to, existing farm noise. [R4-S11]

### Q-b — Projectors and amplifiers in roughly 0.5–20 kHz

**R4-F10.** Commercial full-band underwater loudspeakers in the target band exist but are shallow-rated. The Lubell LL916C/LL916H publishes 200 Hz–23 kHz (500 Hz–21,000 Hz ±10 dB), a maximum output of "180 dB/uPa/m @ 1 kHz", an operating depth of 1–18 m, and a cable limit of 20 Vrms / 3 A at 100% duty cycle. It publishes **no ohm rating**: the unit presents a capacitive load and is sold only with a Lubell AC-series transformer box, listed at 200 W / 40 Vrms (AC102C), 50 W / 20 Vrms (AC202C) and 78 W / 25 Vrms (AC203E splitter, AC205C). Price is not published. [R4-S15]

**R4-F11.** A higher-output Lubell variant, the LL9162, publishes 200 Hz–20 kHz, a nominal impedance of 16 ohms, "186dB/uPa/m @ 1 kHz and 190dB/uPa/m @ 10 kHz with 50 Vrms applied", a cable limit of 50 Vrms / 5 A, depth 1–18 m and 17 lbs in air. The vendor page requires a GFCI-protected amplifier with a transformer-isolated speaker output, an external series resistor and a fuse, and requires content below 200 Hz to be rolled off at 12 dB/octave. The page states government sales only and publishes no price. [R4-S16]

**R4-F12.** A deep-rated omnidirectional alternative is the Gavial ITC-1032: published operating band 0.01–50 kHz with 33 kHz resonance, TVR 149 dB/µPa/V @ 1 m, OCV −194 dB//1V/µPa, 250 m depth, 800 W power handling, spherical beam. Weight, dimensions and price are not published on that listing; the manufacturer's own product index publishes model names and downloadable datasheets only, with no specifications and no prices on the page. Its TVR is far lower than a loudspeaker-style projector, so a given source level costs far more drive voltage. [R4-S17][R4-S18]

**R4-F13.** Every projector found in the band is heavy and shallow relative to a small solar unit. The LL916H is 5.67 kg in air and the LL916C 8.0 kg including its standard 25-foot cable; both are 1–18 m rated. Neither survives an assumption of deeper deployment, and neither vendor publishes a duty-cycle-versus-thermal curve. [R4-S15]

**R4-F14.** Matching amplifiers for reactive underwater loads are laboratory-class, mains-powered rack equipment, not battery-friendly. Instruments Inc. publishes for the L2 model 260 VA continuous and 650 VA in a 1-second burst at 10% duty, with response quoted as "400 Hz to 100 kHz in the continuous mode, and 400 Hz to 40 kHz in the higher-power pulsed mode", in a 19-inch 3U chassis on single-phase mains. Output voltage, current, weight and price are not published; the site directs users to the factory. [R4-S20]

**R4-F15.** Board- and case-level amplifiers closer to a field unit exist. Benthowave publishes an RMS output power and a −3 dB bandwidth per model, including BII5160 at 208 W over 100 Hz–20 kHz (linear, with a portable-case package option) and BII5060 at 208–415 W over 0.1–70 kHz. Output voltage, load impedance, supply requirements, weight and price are **not published** on that page. [R4-S19]

**R4-F16.** Consequence for the reference design: none of `PROJECTOR-AMP-OPT-001`, `PROJECTOR-XDCR-OPT-001` or `PROJECTOR-STOP-OPT-001` in [`hardware/bom/reference-v1.json`](../../hardware/bom/reference-v1.json) can be populated from published data alone. Every candidate found is missing at least one of: impedance across the band, depth rating beyond 18 m, duty-cycle/thermal limits, mass with cable, or price. No vendor found publishes a price for any projector or amplifier in this band. [R4-S15][R4-S16][R4-S17][R4-S19][R4-S20]

### Q-c — Calibration equipment and services

**R4-F17.** An accredited free-field calibration route exists in the EU/UK. NPL operates a UKAS-accredited service (laboratory number 0478, ISO 17025) offering free-field reciprocity calibration of hydrophones 315 Hz–500 kHz, free-field comparison 1 kHz–1 MHz, pressure calibration by comparison 5 Hz–315 Hz, directional response 1 kHz–1 MHz over "360 degrees of rotation in both the horizontal and vertical plane", transducer electrical impedance/admittance 1 Hz–20 MHz, and pressure calibration of digital marine autonomous recorders 20 Hz–315 Hz. Prices are not published; the page is quote-only. [R4-S23]

**R4-F18.** The nearest comparable facility to Croatia is the CNR-INM Underwater Acoustics Laboratory in Rome: a 6 m × 4 m × 5.5 m deep tank with a motorised X-Y and rotation positioning system rated 100 kg, plus an outdoor basin at Lake Nemi. Published calibration ranges are 100 Hz–20 kHz outdoor and 3 kHz–500 kHz in the main tank, using "free-field international standard methods (comparison and reciprocity)" with uncertainties between 0.8 dB and 1.5 dB. The page records ISO/IEC 17025 accreditation as a hydrophone calibration centre held from 2007 to 2010; current accreditation status is not stated. Prices are not published. [R4-S24]

**R4-F19.** The outdoor 100 Hz–20 kHz range at CNR-INM is the only found calibration range that spans the whole 0.5–20 kHz band of interest in one facility; NPL's free-field reciprocity service starts at 315 Hz but its accredited comparison route starts at 1 kHz. Any calibration below those floors needs a separate pressure-chamber method. [R4-S23][R4-S24]

**R4-F20.** Reference receive equipment: the B&K Type 8104 is published as 0.1 Hz–120 kHz with a receiving sensitivity of −205 dB re 1V/µPa and is documented as usable as a projector for reciprocity, calibrated-projector and comparison calibrations. Price is not published. [R4-S21]

**R4-F21.** A field check device exists. The B&K Type 4229 hydrophone calibrator produces a tone of 251.2 Hz electronically controlled to ±0.1%, with coupler sound pressure levels typically 156.5, 166, 162 and 151.5 dB re 1 µPa for hydrophone types 8101, 8103, 8100/8104 and 8105 respectively, field calibration accuracy within ±0.6 dB and laboratory accuracy within ±0.3 dB. It is a single-frequency in-air coupler check, not a broadband calibration of a transmit chain. Price is not published. [R4-S22]

**R4-F22.** A low-cost measurement hydrophone exists but is not individually calibrated: the Aquarian AS-1 publishes a nominal free-field voltage sensitivity of "-207.6 (+2.1 / -2.0) dB re: 1V/µPa" over a nominal 5 Hz–100 kHz, and the manufacturer states units are not individually calibrated, with a ±3 dB tolerance on nominal sensitivity plus measurement error. That tolerance alone is larger than several of the assessment margins in R4-F3 and R4-F18. [R4-S26]

### Q-d — Regional noise frameworks and permit conditions

**R4-F23.** EU-level threshold values for underwater noise were agreed on 29 November 2022. They are exposure-area indicators: a maximum of 20% of a given marine area exposed to continuous noise over a year, and for impulsive noise "no more than 20% of a marine habitat can be exposed to impulsive noise over a given day, and no more than 10% over a year". They are stated as the first of their kind at global level and are recommendations that member states must factor into marine strategies, not a permitted source level for one emitter. [R4-S04][R4-S05]

**R4-F24.** Croatia has not set threshold values for Descriptor 11. Its 2020 MSFD Article 11 report, submitted by the Institute of Oceanography and Fisheries, describes programme MADHR-D11-03 for impulsive noise (10 Hz–10 kHz, register-based, D11C1) and MADHR-D11-04 for continuous noise (third-octave 20 Hz–10 kHz including 63 Hz and 125 Hz, 2-yearly, D11C2), and states plainly: "There is no law on the register of impulsive underwater noise and corresponding data." Absence of a national threshold is not permission; it means the assessment basis for a new emitter would have to be constructed for the case. [R4-S06]

**R4-F25.** The site's protection status is a marine special reserve, "POSEBNI REZERVAT U MORU LIMSKI ZALJEV", managed by the public institution Natura Histrica. The public page reachable in this run showed navigation and gallery content only; the designation year and the list of restricted activities were not on it, so both remain unverified here. [R4-S07]

**R4-F26.** The Croatian nature-protection route is a *dopuštenje* (permission) issued by the Ministry, and it covers scientific and expert research as well as interventions in strict reserves, national parks, special reserves and nature parks. The ministry page states the duty directly: "Pravna i fizička osoba koja namjerava provoditi zahvat na zaštićenom području". [R4-S08]

**R4-F27.** The published application content is specific and matches what R4 must produce anyway. For research the application requires: details of the researcher, the location, the purpose, the duration and timing, the methodology, and the equipment and tools used. For an intervention it requires a description or conceptual design, location, duration and timing, method of execution, and details of equipment, tools and machinery. An acoustic trial cannot be described in that application without a frozen waveform, level, duty and measurement method — which R4 cannot supply. [R4-S08]

**R4-F28.** The repository's own compliance record (REG-H6, `docs/compliance/regulatory-applicability-2026-09-08.md`) already found no single generic Croatian acoustic licence and no universal underwater SPL safe limit. Nothing in this review contradicts that; the sources found are consistent with it, and add that the applicable maritime-research and Natura 2000 routes are separate from the nature-protection permission (R4-S06, R4-S08).

### Q-e — Prior seabream and fish deterrent trials

**R4-F29.** The clearest prior sparid deterrent case is French, not Croatian. Ifremer adapted a cetacean pinger to deter seabream at shellfish farms and tested an experimental prototype in 2013 and 2014 for five months in the Rade de Brest and the Bay of Quiberon, reporting effectiveness on large shoals of bream within "a range of between 200 and 300 metres" and operation "on low power". The article publishes **no** frequency, no source level, no duty cycle and no quantitative predation-reduction figure. [R4-S13]

**R4-F30.** The follow-up outcome is habituation. The 2025 Reviews in Aquaculture review of fish predation in bivalve aquaculture reports that this French device initially appeared highly effective but that fish became habituated and effectiveness declined over time, attributed to a personal communication rather than a published trial; the review also notes there are no published studies of acoustic deterrents used against fish predation on bivalve farms. Full text returned HTTP 403; the abstract confirms losses "sometimes causing crop losses of up to 100%" and that mitigation splits into physical exclusion, deterrence, removal and husbandry change. [R4-S12]

**R4-F31.** The best-documented deterrent efficacy evidence found is for the wrong taxon and is unfavourable. The Scottish Government review of acoustic deterrent devices in aquaculture states "there is currently little scientific evidence to support their long-term use", reports habituation by seals to commonly used signal types, records a "dinner bell effect" in which animals associate the device with food, and reports device-dependent results (two devices cutting depredation by 70% and 50%, a third with apparently no effect). It also records disturbance risk to non-target cetaceans. [R4-S14]

**R4-F32.** The ARIEL Croatian pinger pilot could not be advanced in this run. The recommendations PDF was fetched but its text streams were not readable; the repository audit records an earlier direct inspection showing partner list (p. 3) and a seabream pinger pilot (p. 19) with no usable efficacy result. Obtaining the underlying report or data from the Institute of Oceanography and Fisheries remains an unfulfilled request, and it is a person-to-person task, not a desk task. [R4-S27]

**R4-F33.** Taken together (R4-F8, R4-F29, R4-F30, R4-F31), every deterrent line of evidence found reports habituation or reports no durable effect. R4-F8 shows habituation in *S. aurata* itself within about two hours of continuous low-frequency exposure. No source found reports a sustained, quantified reduction in bivalve stock loss attributable to an acoustic deterrent. [R4-S09][R4-S12][R4-S13][R4-S14]

## Uncertainty

| ID | Uncertainty | Effect on P3 |
|---|---|---|
| R4-U1 | The primary fish exposure guidelines (R4-S01) were not readable. No numeric injury, TTS or behavioural criterion is in this package. | A specialist must read the report before any exposure number exists. Blocks any envelope definition. |
| R4-U2 | No *S. aurata* audiogram was found. Sea bass values (R4-S10) are a different family; the *S. aurata* data (R4-S09) are tank behaviour, not thresholds. | Any assumed hearing curve for orada would be invented. Blocks frequency selection on hearing grounds. |
| R4-U3 | Tank sound levels in R4-S09 are not free-field source levels and the study's calibration chain was not inspected. | Its 140–150 dB re 1 µPa figures must not be reused as a Poseidon level. |
| R4-U4 | Vendor pages publish source level at one or two spot frequencies (R4-S15, R4-S16), not a full TVR curve or a duty-cycle/thermal limit. | Electrical and acoustic sizing cannot be closed from published data. |
| R4-U5 | No price is published by any projector, amplifier, calibration laboratory or reference-hydrophone vendor found. | B2 funding gate cannot be costed without quotes. |
| R4-U6 | The current accreditation status of CNR-INM (R4-S24, accredited 2007–2010) is unstated, and no Croatian underwater-acoustics calibration facility was identified. | Calibration logistics, cost and travel are unknown. |
| R4-U7 | Limski zaljev's restricted-activity list and designation instrument were not readable (R4-S07). | Site-specific prohibitions are unknown; do not assume any activity is allowed. |
| R4-U8 | Propagation, ambient level, bathymetry and reverberation at the site are unmeasured. | No source level maps to any received level or exposure radius. |
| R4-U9 | The ARIEL Croatian pilot's methods and outcome remain unread (R4-S27); the French prototype's frequency and level were never published (R4-S13). | Prior-art parameters cannot be reused or ruled out; both need person-to-person requests. |
| R4-U10 | Non-target effects at this site (protected species, cetaceans, shellfish, invertebrates) are entirely unassessed. R4-S14 shows non-target disturbance is a real regulatory issue elsewhere. | Blocks the ecological review that P3 and P4 depend on. |
| R4-U11 | Particle-motion measurement was not costed or scoped; the one vendor page found publishes no specification (R4-S25). | If the specialist requires particle-motion assessment, equipment and calibration are an unbudgeted addition. |

## Candidate shortlist

Screening candidates only. Nothing here is selected, approved, quoted or authorised for purchase, and no entry has been checked for marine suitability at this site. "Not published" means the vendor or authority does not state the value on the page reached; it is never a guess.

### Transducers / projectors

| Vendor | Model | Band | Impedance | Published output | Max drive | Depth | Mass | Price | Source | Retrieved |
|---|---|---|---|---|---|---|---|---|---|---|
| Lubell Labs | LL916C / LL916H | 200 Hz – 23 kHz (500 Hz – 21,000 Hz ±10 dB) | Not published; capacitive load, AC-series transformer box mandatory | 180 dB/uPa/m @ 1 kHz | Cable limit 20 Vrms / 3 A, 100% duty; recommended amp 78 W @ 8 ohms (25 Vrms) with AC205C | 1 m – 18 m | LL916H 5.67 kg; LL916C 8.0 kg with 25-ft cable | Not published | R4-S15 | 2026-09-09 |
| Lubell Labs | LL9162 | 200 Hz – 20 kHz | Nominal 16 ohms | 186 dB/uPa/m @ 1 kHz; 190 dB/uPa/m @ 10 kHz at 50 Vrms | 50 Vrms / 5 A, whichever first; amp up to 300 W into 8 ohms; series resistor + fuse; 12 dB/oct roll-off below 200 Hz | 1 m – 18 m | 17 lbs in air | Not published (government sales only) | R4-S16 | 2026-09-09 |
| Gavial ITC (ex International Transducer Corp.) | ITC-1032 | 0.01 – 50 kHz; resonance 33 kHz | Not published | TVR 149 dB/µPa/V @ 1 m; OCV −194 dB//1V/µPa | 800 W power handling | 250 m | Not published | Not published | R4-S17, R4-S18 | 2026-09-09 |
| Lubell Labs | LL9642T | Not retrieved | Not retrieved | Not retrieved | Not retrieved | Not retrieved | Not retrieved | Not published | R4-S15 (family page only) | 2026-09-09 |

### Amplifiers and drive electronics

| Vendor | Model | Band | Output | Load / impedance | Supply | Mass | Price | Source | Retrieved |
|---|---|---|---|---|---|---|---|---|---|
| Benthowave | BII5160 | 100 Hz – 20 kHz (−3 dB) | 208 W RMS | Not published | Not published | Not published | Not published | R4-S19 | 2026-09-09 |
| Benthowave | BII5060 | 0.1 – 70 kHz (−3 dB) | 208 – 415 W RMS | Not published | Not published | Not published | Not published | R4-S19 | 2026-09-09 |
| Instruments Inc. | L2 | 400 Hz – 100 kHz continuous; 400 Hz – 40 kHz pulsed | 260 VA continuous; 650 VA 1-second burst at 10% duty | Not published | Single-phase mains, 19-inch 3U rack | Not published | Not published | R4-S20 | 2026-09-09 |
| Instruments Inc. | L6 | 120 Hz – 70 kHz continuous; 120 Hz – 25 kHz pulsed | 800 VA continuous; 2,000 VA 1-second burst at 10% duty | Not published | Single-phase mains, 19-inch 8U rack | Not published | Not published | R4-S20 | 2026-09-09 |
| Lubell Labs | AC102C / AC202C / AC203E / AC205C transformer boxes | Not published | 200 W / 40 Vrms; 50 W / 20 Vrms; 78 W / 25 Vrms; 78 W / 25 Vrms | Tuned RLC, isolated winding, current limiting, electrical isolation | Not published | Not published | Not published | R4-S15 | 2026-09-09 |

### Calibration equipment and services

| Vendor / lab | Item | Key published numbers | Price | Source | Retrieved |
|---|---|---|---|---|---|
| NPL (UK) | Hydrophone and transducer calibration | UKAS accredited laboratory 0478, ISO 17025. Free-field reciprocity 315 Hz – 500 kHz; free-field comparison 1 kHz – 1 MHz; pressure comparison 5 Hz – 315 Hz; directional response 1 kHz – 1 MHz over 360°; impedance/admittance 1 Hz – 20 MHz; recorder pressure calibration 20 Hz – 315 Hz | Not published (quote) | R4-S23 | 2026-09-09 |
| CNR-INM (Rome, Italy) | Underwater Acoustics Laboratory | Tank 6 m × 4 m × 5.5 m deep, motorised X-Y and rotation, 100 kg capacity; calibration 100 Hz – 20 kHz outdoor (Lake Nemi), 3 kHz – 500 kHz main tank; uncertainty 0.8 – 1.5 dB; ISO/IEC 17025 accreditation held 2007–2010 | Not published | R4-S24 | 2026-09-09 |
| Brüel & Kjær / HBK | Type 8104 reference hydrophone | 0.1 Hz – 120 kHz; receiving sensitivity −205 dB re 1V/µPa; usable as a projector for reciprocity, calibrated-projector and comparison calibration | Not published | R4-S21 | 2026-09-09 |
| Brüel & Kjær / HBK | Type 4229 hydrophone calibrator | 251.2 Hz tone controlled to ±0.1%; coupler levels typically 156.5 / 166 / 162 / 151.5 dB re 1 µPa for types 8101 / 8103 / 8100-8104 / 8105; ±0.6 dB field, ±0.3 dB laboratory; NIST-traceable | Not published | R4-S22 | 2026-09-09 |
| Aquarian Audio / Aquarian Scientific | AS-1 measurement hydrophone | Nominal FFVS −207.6 (+2.1 / −2.0) dB re 1V/µPa; nominal 5 Hz – 100 kHz; not individually calibrated, ±3 dB tolerance on nominal sensitivity; 10 m cable standard | Not published | R4-S26 | 2026-09-09 |
| GeoSpectrum Technologies | Particle Motion Sensor (M20 family) | Frequency range, sensitivity, depth rating, dimensions, weight all **not published** on the vendor category page; enquiry-only | Not published | R4-S25 | 2026-09-09 |

## Open items that need a human

| ID | Item | Who | Why desk work cannot close it |
|---|---|---|---|
| R4-O1 | Obtain and read ASA S3/SC1.4 TR-2014 and define the applicable metrics, receptor group, effect categories and exposure basis for this species and site. | Underwater-acoustics specialist | Publisher login wall (R4-S01); and the choice of criterion is a professional judgement, not a lookup. |
| R4-O2 | Decide whether particle-motion assessment is required at a shallow longline site, and if so specify and cost the instrument and its calibration. | Underwater-acoustics specialist with marine ecologist | R4-S02 says pressure does not predict particle motion in this geometry; R4-S25 publishes no specification to plan against. |
| R4-O3 | Commission or locate an audiogram or behavioural response function for *Sparus aurata* usable for design. | Marine ecologist / bioacoustician | None exists in the sources found (R4-F7). |
| R4-O4 | Request quotes for projector, transformer box or matching network, amplifier, and cable assembly, including duty-cycle and thermal limits and full TVR and impedance curves. | Product owner with electrical engineer | No vendor found publishes a price or a full curve (R4-F10 to R4-F15). |
| R4-O5 | Request calibration quotes and lead times from NPL and CNR-INM, and confirm CNR-INM's current accreditation status. | Product owner | Both are quote-only; accreditation status is unstated (R4-S23, R4-S24). |
| R4-O6 | Identify any Croatian or Adriatic facility or partner (for example the Institute of Oceanography and Fisheries) able to host or witness calibrated water tests. | Product owner with farm/ecology partner | No such facility was identified from public pages. |
| R4-O7 | Obtain the Limski zaljev designation instrument and the reserve's restricted-activity list from Natura Histrica or the Official Gazette. | Product owner with legal adviser | The public page reached carried no activity list (R4-F25). |
| R4-O8 | Establish with the Ministry which acts and conditions cover an acoustic trial, and what the *dopuštenje* application must contain for this specific method. | Legal adviser and competent authority | R4-S08 states the duty and the application content, but only the authority can decide the case. |
| R4-O9 | Request the ARIEL Croatian seabream pinger pilot report, methods and data. | Product owner with the Institute of Oceanography and Fisheries | R4-S27 could not be read; the underlying data are not public. |
| R4-O10 | Request the Ifremer PREDADOR device parameters and any follow-up habituation data. | Product owner with Ifremer | Never published (R4-F29, R4-F30). |
| R4-O11 | Design the non-target-effects observation and abort protocol, including protected species present at the site. | Marine ecologist with safety owner | R4-S14 shows non-target disturbance is the main regulatory failure mode; site species list is unknown. |
| R4-O12 | Specify the independent hardware inhibit, dual disconnect, watchdog and manual rearm architecture for `PROJECTOR-STOP-OPT-001`. | Safety specialist | The BOM records this as concept architecture with all parts and ratings unresolved; no source in this package addresses it. |

## Recommendation

**Recommendation for proceeding to P3 controlled output engineering: STOP.**

P3 as written requires selecting a projector and amplifier and defining an operating envelope. This review found that none of the four inputs P3 needs is available:

1. **No exposure criterion.** The primary guidelines were unreadable and nothing else found supplies a defensible numeric limit for this species (R4-F1, R4-U1, R4-U2).
2. **No usable component data.** Every candidate in the band is either shallow-rated (1–18 m), missing an impedance or duty-cycle specification, or missing a price; several are missing all three (R4-F10 to R4-F16, R4-U4, R4-U5).
3. **No permission basis.** Croatia has no D11 threshold values and no generic acoustic licence; the nature-protection application requires a frozen method that does not exist (R4-F24, R4-F26, R4-F27).
4. **No supporting efficacy evidence.** Every deterrent line found reports habituation or no durable effect, including habituation in *S. aurata* itself within about two hours (R4-F33).

"Stop" here means: do not select, quote for, buy, build, bench-power or model any output chain, and do not schedule P3. It does not stop the passive monitoring track, which is unaffected, and it does not close the question permanently. The route to revisit is R4-O1 through R4-O12: a specialist reading of the exposure guidelines, an *S. aurata* response basis, the prior-trial data requests, and an authority conversation. If R3 and those items return a defensible envelope and a permission route, R4 can be re-run as a revise decision with real quotes.

This decision is a research worker's recommendation. It is not a specialist sign-off, and it does not change the status of `REQ-SAF-001` or `REQ-SAF-002`, which stay `Unverified`.

This is desk research; no measurement, permit, purchase or efficacy claim is made.

## Root review note (2026-09-09)

Root verified the package structure (27 sources, 33 findings, every finding cites a listed source, no quote over 25 words) and spot-checked R4-S09 through Crossref (DOI 10.1121/10.0001255) and the Europe PMC abstract. The abstract confirms habituation at 63 and 125 Hz after 2 h in juvenile *Sparus aurata* (140 to 150 dB re 1 µPa, 7 h exposure). It also reports that at 1 kHz group dispersion increased after 2 h without habituation over the 7 h. R4-F8 and R4-F33 should be read with that qualification: the study shows band-dependent habituation, not habituation at every frequency. This does not change the STOP recommendation, whose other three grounds stand.
