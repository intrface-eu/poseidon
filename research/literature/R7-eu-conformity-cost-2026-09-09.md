# R7 — EU product, conformity and business feasibility, with a quote-ready procurement package

Record `R7-DESK-1`, desk date **2026-09-09**. Method: web search and web fetch only. No supplier, lab, authority or funding body was contacted; no form was submitted, no account created, no purchase made, no binary downloaded for use. Every date, fee and price below carries a source id resolved in `R7-eu-conformity-cost-2026-09-09.sources.json`.

Binding inputs: [regulatory applicability `REG-DESK-1`](../../docs/compliance/regulatory-applicability-2026-09-08.md), [technical-file index `TF-DESK-1`](../../docs/compliance/technical-file-index.md), [cost and quotation request `MFG-04` rev 0.2](../../docs/manufacturing/cost-and-quotation-request.md), [BOM `HW-REF-1.1`](../../hardware/bom/reference-v1.json). The historical USD component estimate in `hardware-components-cost-analysis.md` is treated as a non-budget artefact and is not carried into any line here.

Product assumed for the screen: above-water hub with LTE and LoRaWAN radio, solar and battery; wired underwater camera and hydrophone head; separately gated underwater sound projector. First intended market EU/EEA, first site Croatia. Solo builder, no legal manufacturer appointed, no budget set.

This is desk research; it is not legal advice, a quote, a budget or a conformity assessment.

## Questions

- **Q1** Which EU acts apply to the passive variant, and which change if the projector or a consumer sale is added?
- **Q2** Which harmonised standards currently sit in the OJEU for the RED articles this product touches, and what changes between today and 11 December 2027?
- **Q3** Do CE-marked bought-in modules (Raspberry Pi, LTE modem, LoRa module) reduce the final-system obligations?
- **Q4** Which notified bodies and test labs in Croatia, Slovenia, Italy and Austria publish RED/EMC/environmental scopes, and where are their contact pages?
- **Q5** Which Croatian and EU funding programmes are plausibly applicable, with dates and links?
- **Q6** Which BOM parts and services have a **published** price that can serve as a planning reference, and which do not?
- **Q7** What would a supplier have to be told before any of CQ-01 to CQ-04 could be priced at all?

## Sources reviewed

37 sources recorded in the sibling JSON. 30 were read in full; 7 could not be read and are recorded as inaccessible with the reason:

| Source id | Why inaccessible |
|---|---|
| S09 | ECHA Candidate List table, HTTP 403 |
| S33 | EUR-Lex PDF of Implementing Decision (EU) 2025/138, empty body returned |
| S34 | Victron EUR price list PDF, text held in compressed streams, not read |
| S35 | REDCA TGN 01 PDF, HTTP 425 |
| S36 | TME product page for Hammond 1554V2GY, HTTP 403 |
| S37 | SGS note on the REACH Candidate List reaching 253 entries, HTTP 403 |
| — | EUR-Lex `eli/...` and `legal-content/.../HTML` routes returned empty bodies throughout; no primary legal text was read directly in this pass |

**Consequence to carry forward:** every legal date below rests on a Commission, national-authority or accredited-body page, not on retained primary OJEU text. `TF-05` still requires the retained full legal text.

## Applicability matrix

| Act | Applies | Why | Date checked | Source id |
|---|---|---|---|---|
| RED 2014/53/EU | **Yes** | Any variant with LTE, LoRaWAN, Wi-Fi or Bluetooth is radio equipment. RED applicable since 13 June 2016; essential requirements are safety and health, EMC, and efficient spectrum use. | 2026-09-09 | S02 |
| RED Art. 3(3)(d)(e)(f) via Del. Reg. (EU) 2022/30 | **Yes, until 10 Dec 2027** | Cybersecurity, personal-data and fraud requirements activated from August 2025 for connected radio equipment. | 2026-09-09 | S02, S04 |
| Del. Reg. (EU) 2026/339 | **Yes, from 11 Dec 2027** | Repeals 2022/30 with effect from the CRA's full application date. | 2026-09-09 | S02, S05 |
| CRA (EU) 2024/2847 | **Depends** on whether there is commercial supply | Reporting obligations apply from 11 September 2026; main obligations from 11 December 2027. | 2026-09-09 | S03 |
| EMC Directive 2014/30/EU | **No** for the radio product; **depends** for separately supplied non-radio apparatus | EMC is an RED essential requirement for radio equipment. | 2026-09-09 | S02 |
| LVD 2014/35/EU | **No** as a separate act for the radio product; **depends** for a separately supplied mains adapter or non-radio apparatus | RED carries the safety objectives without a voltage limit. | 2026-09-09 | S02 |
| GPSR (EU) 2023/988 | **Depends** on consumer or foreseeable-consumer supply | Applicable since 13 December 2024; acts as the residual net for consumer products and for risks not covered by sectoral law. | 2026-09-09 | S10 |
| RoHS 2011/65/EU | **Yes** | All products with an electrical or electronic component must comply unless specifically excluded; ten restricted substances. | 2026-09-09 | S06 |
| REACH (EC) 1907/2006 | **Yes**, at article level | Candidate-List communication, Art. 7 notification and SCIP are separate duties. Current entry count **not verified** — ECHA table inaccessible. | 2026-09-09 | S09 (inaccessible), S37 (inaccessible) |
| WEEE 2012/19/EU | **Yes / depends** on producer role per destination country | Separate collection, treatment, national registration and reporting duties attach to producers. | 2026-09-09 | S07 |
| Batteries Reg. (EU) 2023/1542 | **Yes**, category and role to be fixed | In force 17 August 2023. Passport and due-diligence dates **not verified from primary text** in this pass. | 2026-09-09 | S08 |
| GDPR (EU) 2016/679 | **Depends** on identifiability in camera and audio streams | EDPB Guidelines 3/2019 govern video-device processing. | 2026-09-09 | S11 |
| Croatian spectrum authorisation (HAKOM) | **Yes**, separate from RED | Use of bands available under general authorisation is open to any legal or natural person under the Table of Allocations and the RF spectrum ordinance. | 2026-09-09 | S13 |
| Machinery Reg. (EU) 2023/1230 (powered wiper variant) | **Depends** | Not researched in this pass; no source retrieved. Keep on the boundary list in `REG-E` rather than treating as screened. | 2026-09-09 | none |
| Marine equipment, EMFAF-funded activity, maritime-domain and nature permissions | Out of R7 scope | Held in the Croatian permission track `REG-H1`–`REG-H7`. | 2026-09-09 | none |

## Findings

**R7-F1 — RED is the anchor act and it swallows EMC and safety for this product.** RED entered into force 11 June 2014 and became applicable 13 June 2016; its Article 3 essential requirements are safety and health protection, electromagnetic compatibility, and efficient use of the radio spectrum. Declaring standalone EMC or LVD alongside RED for the same radio product is not the route. [S02]

**R7-F2 — The OJEU list for RED is a moving target and it moved four days ago.** Harmonised standards references are published by Commission implementing decisions amending Implementing Decision (EU) 2022/2191 of 8 November 2022. The Commission's own page lists amendments of 3 October 2023, 27 November 2023 (2023/2669), 28 January 2025 (2025/138), 14 May 2025 (2025/893), 13 August 2025 (2025/1741), 9 December 2025 (2025/2499) and **4 September 2026 (Implementing Decision (EU) 2026/2003)** — five days before this desk date. The Commission also states that its consolidated summary list "does not as such generate legal effects". [S01]

**R7-F3 — The specific standard numbers for this product's radios were not verified in this pass.** The EUR-Lex routes to the annexes of 2022/2191 and its amendments returned empty bodies (S33 and the `eli`/HTML routes). The candidate families a lab would work from — EN 300 220 series for 863–870 MHz short-range devices, EN 301 908 and EN 301 511 for cellular, the EN 301 489 series for radio EMC, EN 62368-1 for safety, EN IEC 62311 for RF exposure — appear in the accredited scopes of the labs reviewed (SIQ names EN 300 220-2, EN 300 330, EN 300 328, EN 301 893, EN 300 440 and EN IEC 62311). Treat these as **lab-scope evidence, not as verified OJ citations**. [S15, S33]

**R7-F4 — The cybersecurity requirements apply now and are replaced, not relaxed, on 11 December 2027.** Article 3(3)(d), (e) and (f) were activated by Delegated Regulation (EU) 2022/30 and applied from August 2025; Delegated Regulation (EU) 2026/339 of 16 February 2026 repeals 2022/30 with effect from 11 December 2027, the date the CRA applies in full. There is no gap and no window without a cybersecurity obligation. [S02, S05]

**R7-F5 — EN 18031 gives a self-declaration route only if the restrictions do not bite.** Implementing Decision (EU) 2025/138 of 28 January 2025 listed EN 18031-1:2024, EN 18031-2:2024 and EN 18031-3:2024 as Annex I entries 164–166 with restrictions. The restrictions: the "rationale" and "guidance" sections "do not confer a presumption of conformity"; presumption is lost where, applying clauses 6.2.5.1 and 6.2.5.2, "the user is allowed not to set and use any password"; EN 18031-2 loses presumption for Art. 3(3)(e) where "parental or guardian access control is not ensured" in the toy and childcare clauses; and EN 18031-3 clause 6.3.2.4 does not confer presumption for Art. 3(3)(f). For Poseidon this means: **the hub must not ship with an optional-password path**, or the self-assessment route closes and a notified body is needed. [S04]

**R7-F6 — The CRA reporting clock starts in two days and is not deferred by the 2027 transition.** CRA main obligations apply from 11 December 2027, but reporting obligations apply from **11 September 2026** and reach products already on the market. This is a duty on a manufacturer that has actually supplied something commercially; on the current record Poseidon has supplied nothing, so the correct action is to keep it that way deliberately, or to stand up the reporting route before any supply. [S03]

**R7-F7 — Bought-in CE-marked modules do not transfer conformity to the final system.** No accessible primary source was read on this point in this pass — REDCA TGN 01 returned HTTP 425 (S35) and the Commission RED Guide page does not discuss modules (S02). What is on the record: RED places conformity responsibility on the manufacturer of the product placed on the market, and the essential requirements attach to the finished radio equipment, not to a component (S02). The practical consequence a lab will state — that integration changes EMC and radiated performance and that module test data may only be reused with a documented technical analysis — is **asserted in secondary industry sources only and is not sourced here**. Treat `REG-E1`/`REG-E3` as unchanged and closed only by a lab. [S02, S35]

**R7-F8 — Croatian spectrum authorisation is a separate, licence-free-but-conditional track.** HAKOM issues general authorisations for bands where interference risk is negligible or the band is harmonised; every legal and natural person has the right to use a band falling under one, under the conditions of the Table of Allocations and the Ordinance on conditions of allocation and use of the RF spectrum ("NN" 40/23). HAKOM also publishes a register of general authorisations and a list of withdrawn ones (OD-53, OD-76, OD-112, OD-141, OD-204 are shown as withdrawn), so **the authorisation number must be read from the live register at the time of use, not quoted from memory**. [S13]

**R7-F9 — Croatia has exactly one RED notified body and it is in Zagreb.** HAKOM lists NB 2494, KONČAR-Institute for Electrical Engineering Ltd., for 2014/53/EU, and points to the NANDO database for the full EU list. [S12, S14]

**R7-F10 — The nearest RED notified body with a published cybersecurity scope is SIQ in Ljubljana.** SIQ is notified body 1304 for 2014/30/EU and 2014/53/EU, accredited under Slovenian Accreditation LP-009, with published radio, EMC and EMF/MPE scopes and an ISED company number. [S15]

**R7-F11 — Italy offers two published RED routes.** IMQ is "accredited and authorized by the Ministry of Enterprises and Made in Italy to operate as Notified Body" for Annex III Module B, covering Articles 3.1(a), 3.1(b), 3.2 and 3.3(d)(e)(f). Nemko publishes NB 1622 for RED with accredited EMC, radio, exposure and safety testing and an explicit policy on accepting third-party 17025 reports. [S16, S17]

**R7-F12 — The Austrian option is not confirmed from an accessed page.** The TÜV AUSTRIA EMC pages read here give contact and accreditation-index links but **do not state notified-body designation for RED or EMC**. The claim appears only in search summaries. Do not record Austria as a designated route without reading NANDO or the TÜV AUSTRIA accreditation index. [S18]

**R7-F13 — Croatia's EMFAF programme is the largest plausible non-dilutive envelope, and it is farm-shaped, not product-shaped.** The Croatian 2021–2027 programme is €348 million total with €243.6 million EU contribution, split 46.4% sustainable fisheries, 39.6% sustainable aquaculture/processing/marketing, 13.6% sustainable blue economy, 0.4% international ocean governance; adopted 29 November 2022. [S20, S21]

**R7-F14 — The EMFAF innovation measures require a scientific body as applicant or partner.** In the published Croatian call plan, measure I.1 *Inovacije u ribolovu* carries "Ukupan iznos bespovratnih sredstava: 666.667,00 EUR" with eligible applicants being scientific bodies and licensed fishers in cooperation with a confirmed scientific body; measure II.1 *Inovacije u akvakulturi* carries €2,000,000 with scientific bodies and aquaculture farmers in cooperation with a scientific body. Aid intensity runs 50% to 100% depending on beneficiary type. **A solo builder without an institutional partner is not an eligible applicant for these two.** The figures read are from the 2025 plan; the 2026 plan was not located. [S22]

**R7-F15 — The one instrument a solo Croatian SME can reach today is small.** *Inovacijski vaučeri za MSP-ove* (PK.1.1.06) has a total allocation of €4,874,214, a minimum of €2,000.00 and a maximum of €10,000.00 per project, maximum aid intensity 50% rising to 85%, eligible applicants being micro, small and medium enterprises, submissions until funds are exhausted and at the latest **31 December 2026 at 16:00**. The voucher pays a scientific research organisation to test — which maps directly onto CQ-03 pre-compliance work. [S23]

**R7-F16 — EIC Accelerator is open but out of reach at this maturity.** The grant is a "Lump sum contribution below € 2.5 million, for innovation activities (TRL 6-8), to be completed within 24 months", with equity €1–10 million; 2026 full-proposal cut-offs are 7 January, 4 March, 6 May, 8 July, 2 September and 4 November. Poseidon has no released design or field site; TRL 6-8 is not the current state. INTRFACE j.d.o.o. is registered (MBS 130172611). [S19]

**R7-F17 — Almost nothing in the qualification chain has a published price.** Sonardyne's hydrostatic chamber (0.76 m internal diameter, 2 m internal height, 630 bar, 6,300 m equivalent) is "Fixed priced per day" with a half-day minimum but publishes **no figure**. EMC Hire's facility-hire pricing page publishes availability ("Monday to Friday 8:00 - 16:00 for both half-day and full-day bookings") and **no figure**. None of KONČAR, SIQ, IMQ or Nemko publishes a fee schedule. Record every conformity and pressure line as `unpriced`. [S29, S30, S12, S15, S16, S17]

**R7-F18 — Board fabrication and assembly is priced only through interactive calculators.** Eurocircuits states no minimum order charge and no tooling charges, 1–5 board quantities, 3 working days bare / 6 working days assembled, and that price "cannot be automatically calculated for a PCB containing more than 200 BOM lines or 1000 component placements". No static figure is published. JLCPCB publishes exactly one fixed figure in its assembly capabilities: "The fixture cost is $23.57 per fixture, and the required quantity depends on your production volume." [S31, S32]

**R7-F19 — Four BOM parts have a published list price; the rest do not.** Published: Raspberry Pi 4 Model B "From $35" with **no per-variant 4 GB price** (S27); RAK3272S at "8XX MHz for EU868/RU864/IN865 - $15.00 USD" (S25); Blue Robotics configurable watertight enclosure "From: $ 61.00" with published accessory prices — pressure relief valve $32.00, coupler flanges $40.00–$60.00, clamps $34.00–$166.00, penetrator blanks $5.00–$8.00 (S26). Espressif publishes **no price** for ESP32-DevKitC-32E (S28). Hammond 1554V2GY distributor price was inaccessible (S36).

**R7-F20 — Victron publishes an official EUR price list but its figures were not read.** Victron publishes a single end-user list, EUR only, and states "All prices mentioned are per unit and EUR ex VAT", describing the figures as recommended and non-binding. The Q3 2026 PDF could not be parsed (S34), so **no Victron line item is priced here** — the battery, MPPT and panel stay `unpriced` with a known, readable public source to close them. [S24, S34]

**R7-F21 — No sourced EUR conversion rate was retrieved.** The three published prices found are quoted natively in USD by their publishers — Raspberry Pi, RAKwireless, Blue Robotics and the JLCPCB fixture fee. No line converts a USD list price to EUR anywhere in this package; doing so requires a dated rate source that this pass does not have. [S25, S26, S27, S32]

**R7-F22 — Nothing found changes the `REG-DESK-1` outcome.** No source contradicts the existing hold on field activity, emission, fabrication and market release. Two dates tighten: CRA reporting begins 11 September 2026 (S03) and the RED cyber delegated act runs to 10 December 2027 before the CRA replaces it (S02, S05).

## Labs and bodies

Contact pages only. **None of these was contacted.** No fee schedule is published by any of them.

| Body | Country | Published status | Published scope relevant here | Contact page |
|---|---|---|---|---|
| KONČAR – Institute for Electrical Engineering | HR (Zagreb) | NB **2494** for 2014/53/EU, per HAKOM's own list [S12] | Testing, calibration and certification for compliance with standards and directives; HAA accreditation numbers not shown on the page read [S14] | https://koncar-institut.hr/en/laboratory-center |
| SIQ Ljubljana | SI | NB **1304** for 2014/30/EU and 2014/53/EU; Slovenian Accreditation **LP-009**; IECEE CBTL; ISED company 21434 [S15] | EMC emission and immunity, harmonics and flicker; radio spectrum EN 300 220-2, EN 300 330, EN 300 328, EN 301 893, EN 300 440; EMF/MPE 0 Hz–18 GHz incl. EN IEC 62311; on-site testing [S15] | https://www.siq.si/en/our-services/testing-and-certification-of-products/contacts/ |
| IMQ | IT | Notified body authorised by the Ministry of Enterprises and Made in Italy; Annex III Module B [S16] | Articles 3.1(a), 3.1(b), 3.2 and 3.3(d)(e)(f); EU type-examination plus accredited testing [S16] | https://www.imq.it/en/eu-directives/radio-equipment-directive-red-2014-53-eu |
| Nemko | IT / NO | NB **1622** listed on NANDO [S17] | RED conformity assessment and EU type examination; accredited EMC, radio/RF, exposure and safety; will review third-party 17025 reports [S17] | https://www.nemko.com/contact |
| TÜV AUSTRIA (TVFA) | AT | **Unverified.** The EMC pages read do not state RED or EMC notified-body designation [S18] | Not established from an accessed page | https://en.tuv.at/contact/ and accreditation index https://en.tuv.at/accreditations-and-authorizations/ |
| NANDO database | EU | Authoritative list, pointed to by HAKOM [S12] | Filter by 2014/53/EU and country before treating any body above as designated | http://ec.europa.eu/growth/tools-databases/nando/index.cfm?fuseaction=country.main |
| Sonardyne hydrostatic facility | UK | Commercial facility, not a notified body [S29] | 0.76 m ID × 2 m, 630 bar, 6,300 m equivalent, 6 breakout ports, up to 168 h dwell; "Fixed priced per day", half-day minimum, no figure published [S29] | https://www.sonardyne.com/product/hydrostatic-pressure-testing-facility/ |

**Action rule:** before any of these is approached, `TF-01` (signed intended-use and supply boundary) and `TF-02` (configuration baseline) must exist, or the body cannot scope the work and any figure it gives is meaningless.

## Funding

| Programme | Instrument | Amount published | Dates published | Eligibility fit for Poseidon today | Source id |
|---|---|---|---|---|---|
| Croatian EMFAF programme 2021–2027 | Shared management, Uprava ribarstva | €348 m total, €243.6 m EU; 39.6% to aquaculture/processing/marketing, 13.6% blue economy | Programme adopted 29 Nov 2022 | Envelope only; access is through its measures | S20 |
| EMFAF measure I.1 *Inovacije u ribolovu* | Grant | €666,667.00 total; intensity 50%–100% by beneficiary type | 2025 indicative plan, March 2025 publication; **2026 plan not located** | **Not eligible alone** — scientific body must be applicant or confirmed partner | S22 |
| EMFAF measure II.1 *Inovacije u akvakulturi* | Grant | €2,000,000 total; intensity 50%–100% | 2025 indicative plan, March 2025 publication; **2026 plan not located** | **Not eligible alone** — same partner requirement; closest thematic fit to a farm-sited monitor | S22 |
| EMFAF direct management | CINEA calls, BlueInvest, EU Aquaculture Assistance Mechanism | Not read | Not read | Worth a targeted pass; no call read here | S21 |
| *Inovacijski vaučeri za MSP-ove* (PK.1.1.06) | Voucher, ERDF, Ministarstvo gospodarstva | Total €4,874,214; **min €2,000.00, max €10,000.00** per project; intensity 50% up to 85% | Open until funds exhausted, at the latest **31 Dec 2026, 16:00** | **Reachable for registered INTRFACE j.d.o.o. (MBS 130172611)** subject to current call eligibility and remaining funds; pays a scientific research organisation to test | S23 |
| EIC Accelerator | Lump-sum grant plus equity | Grant below **€2.5 m**; equity €1 m–€10 m | 2026 cut-offs 7 Jan, 4 Mar, 6 May, 8 Jul, **2 Sep**, **4 Nov** | Not a fit — TRL 6-8 required; Poseidon has no released design or field site | S19 |
| Horizon Europe Cluster 6 | Collaborative RIA/IA/CSA | Not read from an authoritative page | Not read from an authoritative page | Consortium instrument; a solo builder would need a coordinator | none |
| HAMAG-BICRO PoC | Grant | No 2026 call figure obtained from an accessible page | No 2026 call located | Monitor; nothing to record | none |
| EIT | — | Not researched | Not researched | Not screened in this pass | none |

**Blocker recorded:** the two instruments with real money attached (EMFAF I.1 and II.1) require a scientific body, and the one instrument a solo builder can reach (PK.1.1.06) requires a registered company and expires 31 December 2026. Both routes need a decision Poseidon has not made — institutional partner, or legal entity — before any funding line is real.

## Quote packages

Mirrors `MFG-04` rev 0.2 §1. Its CQ-05 Lifetime and CQ-06 Conditional active research are outside the four packages requested here and are unchanged. **No quote is requested and no supplier is contacted.** Each row states what a supplier would have to be handed before it could price anything.

### CQ-01 — Feasibility and passive evidence

| Field | Content |
|---|---|
| BOM part ids / service lines | `WET-HYD-001`, `WET-CAM-001`, `HUB-DAQ-001`, `HUB-STORE-001`, `JIG-ELEC-001`; services: hydrophone calibration and facility time, ecology/statistics/acoustics adviser hours, data handling and storage |
| Missing inputs a supplier would ask for | Receive band, sample rate, channel count, input impedance, bias and gain; hydrophone sensitivity and pressure/duration rating; camera transport and tether length; deployment duration and duty cycle; retention volume and workload; calibration traceability and uncertainty expectation; delivery site |
| Document revision needed | `TF-01` signed intended-use and supply boundary; `TF-11` preregistered scientific endpoints from acquisition; `HW-REF-1.1` §WET with the unresolved gates in `WET-HYD-001` and `WET-CAM-001` closed |
| Blocking gate | None of the three WET part rows has a selected part; `reference_qty` is 1 but `populated_default_qty` is 0. Nothing here is quoteable today |

### CQ-02 — Engineering units / EVT

| Field | Content |
|---|---|
| BOM part ids / service lines | `HUB-CPU-001`, `HUB-DC5-001`, `HUB-USBC-001`, `HUB-STORE-001`, `HUB-ENC-001`, `HUB-PROTECT-001`, `REEF-CPU-001`, `REEF-RF-001`, `REEF-DC-001`, `REEF-BAT-001`, `REEF-BMS-001`, `REEF-MPPT-001`, `REEF-PV-001`, `REEF-ENC-001`, `REEF-PROBE-001`, `REEF-ANT-001`, `WET-PRESSURE-001`, `WET-HARNESS-001`, `FARM-HARNESS-001`, `HUB-GATEWAY-001`; services: harness build, PCB fabrication and assembly, machining/printing, fixtures, assembly labour, rework allowance |
| Missing inputs a supplier would ask for | Order quantity and price-break points; exact regional SKUs and board revisions; antenna model, gain, connector and feedline; harness lengths, conductor sizes, pinouts and connector families; enclosure vendor envelope and gland schedule; battery/BMS pairing and disconnect ratings; drawings at a controlled revision; incoming inspection expectation; Incoterms, VAT and duty treatment |
| Document revision needed | `TF-02` configuration baseline with BOM, drawing, schematic, harness, firmware and SBOM revisions and permitted combinations; `TF-03` part-level supplier evidence and revisioned drawings; `HW-REF-1.1` with `purchase_authorized` still `false` — it must be lifted by the product owner first |
| Blocking gate | 8 of 20 rows have `manufacturer: null` and `mpn: null`. `HUB-GATEWAY-001` and `REEF-PROBE-001` have `reference_qty: null`. A quantity-based BOM does not exist |

### CQ-03 — DVT / conformity

| Field | Content |
|---|---|
| BOM part ids / service lines | Test specimens built from the CQ-02 configuration, plus `JIG-ELEC-001`; services: RED Art. 3(1)(a) safety and RF exposure, 3(1)(b) EMC, 3(2) spectrum, 3(3)(d)(e)(f) cybersecurity against EN 18031 with its restrictions; pre-compliance scans; pressure and leak qualification of the WET assembly; corrosion, thermal and load testing; manual, label and technical-file review |
| Missing inputs a supplier would ask for | Every enabled radio, band, mode, modulation and maximum configured RF power, plus simultaneous-transmit combinations; antenna and cable used in test; firmware version and lock; enclosure and mounting as tested; number of specimens; whether the password path is mandatory (determines whether EN 18031 presumption survives — see R7-F5); target depth, dwell time and cycle profile for pressure; whether notified-body involvement is required; retest and travel policy |
| Document revision needed | `TF-06` test plan; `TF-07` cybersecurity risk assessment, SBOM and update design; `TF-12` physical qualification procedure with limits; accepted EVT from CQ-02; a frozen variant and envelope |
| Blocking gate | No frozen radio configuration exists (`REG-E5` open). No depth or environmental envelope exists (`TF-12`). A lab cannot scope this |

### CQ-04 — PVT / production

| Field | Content |
|---|---|
| BOM part ids / service lines | Full CQ-02 BOM at pilot quantity plus spares; services: independent assembler setup and training, incoming inspection, end-of-line and provisioning stations, fixture and reference calibration, traceability system, packaging validation, yield/rework/scrap accounting, service reproduction |
| Missing inputs a supplier would ask for | Pilot quantity and acceptance plan; controlled documentation package; serial and traceability scheme; end-of-line test definition and throughput target; provisioning secrets handling; packaging and transport requirements including battery transport classification; who the legal manufacturer is |
| Document revision needed | `TF-14` labels, instructions, languages and signed DoC; `TF-15` support period and vulnerability handling; `TF-16` traveler, EOL and calibration records; DVT acceptance |
| Blocking gate | No legal manufacturer is appointed (`TF-01`, `REG-E13`). A pilot cannot be ordered by an unnamed entity |

## Cost model skeleton (EUR)

Rules applied: a cell holds either a **published planning reference with its source id** or the literal `unpriced`. **No total is computed.** Unpriced lines are not zero. No USD figure is converted to EUR — no dated rate source was retrieved (R7-F21), so USD references are shown in USD with the conversion explicitly withheld.

| Roadmap line | Cost element | Planning reference | Source id | Currency conversion note |
|---|---|---|---|---|
| **B1** Feasibility and measurement | Farm access, vessel and logistics | `unpriced` | — | — |
| B1 | Adviser time (ecology, statistics, acoustics) | `unpriced` | — | — |
| B1 | Hydrophone, DAQ, camera, calibration rental and facility time | `unpriced` — no part selected, no vendor published rate found | — | — |
| B1 | Storage and data handling | `unpriced` | — | — |
| B1 | Offsetting instrument: innovation voucher, min €2,000.00 / max €10,000.00, intensity to 85%, deadline 31 Dec 2026 16:00 | Published grant ceiling, **not a cost** | S23 | Native EUR |
| **B2** Active-output research | Projector, amplifier, protection, calibration facility, permits, ecology and statistics support | `unpriced` — gated behind the R3/R4 go decision; no part selected in `PROJECTOR-*` rows | — | — |
| **B3** Engineering units | `HUB-CPU-001` Raspberry Pi 4 Model B | Published starting price **"From $35"**; the 4 GB variant price is **not published** | S27 | USD list; **no EUR conversion** — no rate source |
| B3 | `REEF-RF-001` RAK3272S EU868 | Published **$15.00 USD** for the 8XX MHz EU868/RU864/IN865 variant | S25 | USD list; **no EUR conversion** — no rate source |
| B3 | `REEF-CPU-001` ESP32-DevKitC-32E | `unpriced` — Espressif publishes no price | S28 | — |
| B3 | `WET-PRESSURE-001` pressure enclosure family | Published **"From: $ 61.00"** base configuration; accessories published: relief valve $32.00, coupler flanges $40.00–$60.00, clamps $34.00–$166.00, penetrator blanks $5.00–$8.00 | S26 | USD list; **no EUR conversion** — no rate source. Final price is configuration-dependent |
| B3 | `REEF-BAT-001`, `REEF-MPPT-001`, `REEF-PV-001` Victron | `unpriced` — Victron publishes an official EUR ex-VAT end-user list but the Q3 2026 PDF could not be parsed; the line is closeable from a public source | S24, S34 | Would be native EUR ex VAT when read |
| B3 | `ENC-ALT-001` Hammond 1554V2GY | `unpriced` — distributor page inaccessible (HTTP 403) | S36 | — |
| B3 | All 8 BOM rows with null manufacturer and null MPN, plus null-quantity rows | `unpriced` — no part exists to price | — | — |
| B3 | PCB fabrication and assembly, prototype quantity | No static price published: Eurocircuits quotes only via calculator, states **no minimum order charge and no tooling charges**, 1–5 boards, 3 working days bare / 6 assembled | S31 | Native EUR when quoted |
| B3 | PCB assembly fixture (flex only) | Published fixed fee **$23.57 per fixture** | S32 | USD list; **no EUR conversion** — no rate source |
| B3 | Machining, printing, harness labour, fixtures, redesign allowance | `unpriced` | — | — |
| B3 | Shipping, VAT, duties | `unpriced` — requires an adviser and a named importing entity | — | — |
| **B4** Qualification and pilot | RED EMC, radio, spectrum and RF exposure testing | `unpriced` — no reviewed lab publishes a fee schedule or day rate | S12, S15, S16, S17 | — |
| B4 | Notified-body EU type examination (needed if EN 18031 restrictions bite, or if OJ standards are not fully applied) | `unpriced` — IMQ and Nemko publish scope, not fees | S16, S17 | — |
| B4 | Independent EMC chamber hire, self-test route | `unpriced` — EMC Hire publishes availability and options, **no figure** | S30 | — |
| B4 | Hydrostatic pressure qualification | `unpriced` — Sonardyne states "Fixed priced per day" with half-day minimum, **no figure**; no reviewed EU facility publishes a rate | S29 | — |
| B4 | Cybersecurity assessment against EN 18031-1/-2/-3 with restrictions | `unpriced` — scope exists (SIQ accredited for the series), fee does not | S15, S04 | — |
| B4 | Environmental, corrosion, thermal, field trials; pilot quantity, yield, rework; packaging; manuals; EOL equipment | `unpriced` | — | — |
| **B5** Product lifetime | Connectivity, EU hosting, storage and backup | `unpriced` — not researched in this pass | — | — |
| B5 | Installation and vessel service visits | `unpriced` | — | — |
| B5 | Battery, probe, seal and wiper replacement | `unpriced` | — | — |
| B5 | Security response, signed updates and update hosting for the CRA support period | `unpriced` — the **obligation** is dated (reporting from 11 Sep 2026; main regime from 11 Dec 2027) but no cost reference was found | S03 | — |
| B5 | Support labour, returns, warranty, insurance | `unpriced` | — | — |
| B5 | WEEE producer registration, reporting and take-back financing per destination country | `unpriced` — obligation established, national fee schedules not read | S07 | — |
| B5 | Battery EPR and end-of-life obligations | `unpriced` — obligation established, fees not read | S08 | — |

**Totals: none.** 4 of roughly 30 lines carry a published reference, all four in USD, none convertible without a rate source. Summing this table in any form would produce a fabricated number.

## Open items that need a qualified adviser

1. **Primary legal text.** No OJEU or EUR-Lex text was read directly; every date here rests on a Commission or authority page. A compliance adviser must retain the dated full text of RED, 2022/30, 2026/339, CRA, RoHS, REACH, WEEE and 2023/1542, and the current 2022/2191 annex as amended through Implementing Decision (EU) 2026/2003 of 4 September 2026. [S01, S33]
2. **Exact OJ standard references for this product's radios.** R7-F3 gives lab-scope families, not verified OJ citations. A lab must produce the clause-level requirement/test matrix with restrictions and withdrawal dates. [S15]
3. **Whether a notified body is required at all.** Turns on whether harmonised standards are fully applied for Art. 3(2) and whether the EN 18031 restrictions bite — specifically whether the product can ever ship without a mandatory password. [S04]
4. **Module reuse.** Whether and how much module-level evidence from the Pi, LTE modem and LoRa module can be carried into the final-system file. Not answerable from any source read here. [S02, S35]
5. **REACH current state.** Candidate List entry count and content unverified; the article-level hierarchy for cables, connectors, PCBs and coatings needs a materials adviser. [S09]
6. **Battery category, passport and due-diligence dates.** Only the entry-into-force date was verified. Category, passport trigger and due-diligence timing must come from the retained regulation text. [S08]
7. **Legal entity and economic role.** WEEE producer status, CRA manufacturer status, DoC signature and GPSR obligations all attach to a named entity that does not exist. This is the single item blocking the most downstream work. [S03, S07, S10]
8. **Croatian spectrum authorisation identity.** The applicable general authorisation must be read from HAKOM's live register at the time of use; several SRD authorisations are shown as withdrawn. [S13]
9. **Austrian route.** Verify TÜV AUSTRIA's designation in NANDO or drop Austria from the lab shortlist. [S18]
10. **Funding route decision.** Institutional partner (unlocks EMFAF I.1/II.1) or registered SME (unlocks PK.1.1.06 before 31 Dec 2026). Both are decisions, not research. [S22, S23]

## Recommendation

**Revise.**

Not *pass*: nothing found supports a funded product specification. Three of the four cost-model bands are entirely unpriced, no lab or notified body publishes a fee, no legal manufacturer exists, 8 of 20 engineering-unit BOM rows have no part at all, and both meaningful funding routes are closed to the current actor configuration. There is no number in this package that a budget could be built on.

Not *stop*: the regulatory picture is coherent and navigable rather than prohibitive. The anchor act is RED with EMC and safety absorbed into it, there is exactly one Croatian notified body and a stronger one 140 km away in Ljubljana, and the cybersecurity route is self-declarable through EN 18031 provided one specific design choice is made correctly. The obligations are heavy but ordinary.

Revise the plan on three points, in this order:

1. **Confirm the funding applicant and partner.** INTRFACE j.d.o.o. is registered (MBS 130172611); verify current SME eligibility and identify a scientific research organisation for voucher-funded tests or EMFAF partnership. The voucher route expires 31 December 2026 (S23), subject to available funds.
2. **Freeze the radio configuration and the password design.** `REG-E5` is the gate that decides whether CQ-03 is a self-declaration with a lab report or a notified-body type examination. The EN 18031 default-password restriction (R7-F5) is a design constraint, not a paperwork item, and it is cheap to honour now and expensive to retrofit.
3. **Close CQ-02 before touching CQ-03 or CQ-04.** No lab can scope a specimen that does not exist. Selecting the 8 null-manufacturer BOM rows and reading the Victron EUR price list — a public document that this pass simply failed to parse — would convert a meaningful share of B3 from `unpriced` to a real planning figure without contacting anyone.

Also record, as a live item and not a finding: CRA reporting obligations begin **11 September 2026**, two days after this desk date (S03). They attach only to a manufacturer that has commercially supplied a product with digital elements. Poseidon has supplied nothing. That should remain a deliberate position, not an accident.

This is desk research; it is not legal advice, a quote, a budget or a conformity assessment.
