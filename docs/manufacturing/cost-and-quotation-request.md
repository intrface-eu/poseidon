# Cost model and unsent quotation request

Document `MFG-04`, revision 0.2, 2026-09-08. **Desk structure only. No supplier contacted, quote received, budget approved, order placed or cost measured.** Addresses roadmap B1–B5 and REQ-MFG-001/REQ-LIFE-001/HAZ-017. All money, quantities, dates and lead times remain null unless supported by a later actual source. Unknown cost is not zero. The old USD component estimates are historical, not a EUR quotation or an approved budget.

## 1. Costed configuration and funding gates

Planning reference: `reference-v1 / HW-REF-1.1`, passive monitoring, intended EU/EEA region with first research interest in Lim Bay/Istria. Exact site, production quantity, selected wet/receive/power parts, assembly/test route, tax treatment and manufacturing country are not frozen. Physical build, field work and purchasing remain unauthorized. Cost active-output research as a separate conditional branch; do not quietly include a projector or promise deterrence. Flora remains separately research-gated.

Revision review, 2026-09-08: explicitly rebound to `HW-REF-1.1` for source-verified pin mappings, corrected battery/panel envelopes and the withdrawn panel-discontinuation interpretation; [MFG-01 records the changes](reference-build-and-eol.md). Quote attachments must use the revised geometry and unresolved power/harness scope. Current panel availability remains unverified; the corrected footnote does not establish supply, price or purchase approval. All requests remain unsent and physical work unperformed.

| Cost package | Required quote/actual lines | Dependency before spending | Budget authority |
|---|---|---|---|
| CQ-01 Feasibility and passive evidence | Farm access/logistics, ecology/statistics/acoustics time, receive/camera/probe selection, calibration equipment rental and facility time, data handling and storage | Authorized study method, permissions path, component compatibility and capped P1/P2 budget | User/product owner; currently none |
| CQ-02 Engineering units / EVT | Complete quantity-based BOM including hub, DAQ, wet housings/windows/seals/penetrators/cables/camera, REEF/radio/gateway/antennas, power/battery/solar/protection, mounts/harnesses, labor, fixtures, rework and inspection | Exact quoteable parts/drawings, controlled revisions, engineering review, approved quantity and work order | User/product owner; currently none |
| CQ-03 DVT / conformity | Lab method/standard review, pre-compliance and final EMC/RF/electrical/environmental/pressure/load/corrosion tests, security review, calibrated receive/timing, authorized endurance/field logistics, manuals/labels/technical-file review | Accepted EVT, frozen candidate variant/envelope and independent limits/test protocol | User/product owner; currently none |
| CQ-04 PVT / production | Independent assembler setup/training, pilot units, incoming/EOL fixtures and throughput, tool/reference calibration, provisioning station, traceability system, actual yield/rework/scrap, packaging validation and service reproduction | DVT acceptance, approved batch/sample/acceptance plan and manufacturer | User/product owner; currently none |
| CQ-05 Lifetime | Installation/retrieval/vessel service, connectivity, EU data hosting/storage/backup, security response/signed updates, support labor, spare inventories, recurring calibration/probes/seals/batteries, warranty/returns, insurance and waste handling | Service period/terms, supported variants, lawful obligations and funded capacity | User/product owner; currently none |
| CQ-06 Conditional active research | Separate compatible projector/amplifier/inhibit engineering, dummy-load facility, calibrated authorized water work, ecology/statistics/sham/repeat trials and adverse-event response | Explicit R3/R4 go decision and all safety/permissions/budget gates; no inferred frequency/level | User/product owner; currently none |

## 2. Line-item data and calculations

Use `COST-01` and `RFQ-01` in [unperformed-records.json](templates/unperformed-records.json). Each later actual line records cost package, NRE/recurring-unit/recurring-site/lifecycle classification, BOM part/service and revision, quantity/unit, currency, net amount, VAT/duty treatment, shipping/import/handling, minimum order and price breaks, tooling ownership, included/excluded scope, supplier and quote ID/date/expiry, lead time and capacity assumptions, payment/warranty terms, supporting document/hash, confidentiality, contingency basis and approval status.

Separate `unpriced`, `planning_estimate`, `supplier_quote`, `contracted` and `actual_invoice_or_timesheet` source classes. A received quote still does not authorize an order. Record exchange-rate source/date when conversion to EUR is needed, and show native amount; do not blend unsupported planning values with actuals. Tax and import assumptions require the responsible adviser. Lost time, unpurchased fixtures and customer-provided equipment are not free merely because an invoice is absent.

Future calculations, **not calculated results**:

- Material consumption cost = actual unit/lot consumption times applicable source-backed unit cost, plus attributable scrap; retain unused recoverable inventory separately.
- Direct labor cost = actual build, inspection, provisioning, calibration, test and rework hours times approved fully defined rate. Separate designer intervention, second-assembler hours and fixture setup.
- Pilot accepted-unit cost = reconciled pilot cost divided by accepted conforming units under the frozen batch definition. If accepted count is zero or unknown, the ratio is undefined, not zero. Show pilot NRE separately; do not imply pilot unit cost equals volume cost.
- Production scenario = quoted volume BOM/labor/test/packaging plus explicit yield/rework/overhead assumptions and NRE amortization basis. Assumptions require sensitivity scenarios approved for planning; no invented actual yield.
- Lifecycle cost = installation plus time-bounded recurring connectivity/storage/service/calibration/security/warranty/disposal obligations under documented utilization and support assumptions. Do not bury retrieval or mandatory support in an unexplained percentage.

A cost reconciliation retains ordered/received/consumed/returned/scrapped quantities, actual labor, external test invoices and outstanding liabilities. Missing taxes, parts, calibration, field access or support block an accepted business case even if a partial BOM total can be summed. Product and specialist owners must agree maximum cost/yield/rework criteria before PVT; these remain TBD.

## 3. Draft request body, not sent

**Subject:** Draft request for scope and quotation, Poseidon passive reference configuration (not a released design)

**Recipient/company/contact:** UNASSIGNED. **Sender/authorized requester:** UNASSIGNED. **Approval to send:** absent. **Requested quantity and response date:** TBD. This text has not been sent and contains no supplier offer.

> We are preparing a passive marine monitoring reference for a possible EU/EEA product. The exact site, operating envelope, budget and release design are not frozen. The current reference is `reference-v1 / HW-REF-1.1`; it excludes acoustic output hardware and a powered wiper. It is not a fabrication instruction or approval to start work.
>
> For the specific scope and controlled input package identified in the request attachment, please identify missing quote-critical inputs before pricing. Separate engineering/DFM review, setup/tooling, materials, assembly, traceability/provisioning, calibration/testing, packaging, documentation, rework and recurring support. State quantities/price breaks, currency, VAT/duties/shipping, validity, lead time, minimum order, exclusions, assumptions, subcontractors, tool ownership and payment/warranty terms. Mark any provisional estimate separately from a firm quoted scope.
>
> Please identify the exact parts/revisions and applicable supplier evidence, process limits, sample requirements and facility competence for the requested work. No part substitution, test limit or manufacturing method is approved by this request. Pressure, electrical, radio, battery, marine or acoustic work needs an independently approved protocol and separate authorization. If proposing a lab service, state the exact method/scope, report/raw-data deliverables, instrument calibration traceability, uncertainty/decision rules, accreditation scope where applicable, retest costs and whether travel/fixtures/specimens are included.
>
> For pilot assembly, include a build by someone other than the designer using the controlled documentation. Record every clarification, first-pass failure, retest, rework, consumed part and actual labor. State your proposed pilot/sampling basis for review; do not treat a sample count or yield target as already agreed. For service, state spare availability, repair restrictions, turnaround assumptions and support dependencies.
>
> This is a request for information/quotation only. It is not a purchase order, authority to manufacture, test or deploy, a product certification claim, or approval to contact the farm or authorities.

Before sending, the product owner approves recipient, scope/attachments, confidentiality, controlled drawing/BOM revisions, quantities and question list; specialists remove incompatible or unsafe assumptions. Attach only authorized non-secret documents, not exact sensitive site data, private keys or customer recordings. This tranche performs no outreach.

## 4. Comparison and award decision

Compare returned offers against a common revisioned scope and exclusions, not headline totals. Record source authenticity, exact variants, technical fit, lab competence and report scope, setup versus recurring costs, lead-time evidence, taxes/logistics, calibration/service capacity, retest/rework pricing, supplier substitution policy, and commercial/privacy terms. Unanswered quote-critical questions remain blocked. Engineering, quality/compliance and product owner separately record recommendations and decisions; no cheapest-offer rule waives a requirement.

Before award, reconcile the full configuration cost and lifetime obligations to an explicit capped budget and user authorization. Preserve the original offer and amendments with hashes and expiry dates. Later PVT replaces assumptions with actual consumed parts, labor and first-pass/final yield evidence from [EVT/DVT/PVT](../qualification/procedures/evt-dvt-pvt.md). No current line supports a funded production-readiness claim.
