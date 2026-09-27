# ADR-0001: Passive-first system boundary

- Status: Accepted
- Date: 2026-09-07
- Decision owners: product owner and safety owner
- Roadmap: [Poseidon Trident production roadmap](../production-roadmap.md)

## Context

The historical v0.1 PRD led with vision-triggered acoustic deterrence, sea-flora frequency programs, a field-deployable platform, and several hardware variants. Repository evidence did not support those capabilities, acoustic safety, biological efficacy, site permission, or a production schedule. It also mixed passive event detection with localization despite specifying one hydrophone, treated digital amplitude values as acoustic limits, and depicted LoRa as a submerged node mesh.

A later direct review of the official ARIEL Croatian regional report found directly relevant negative evidence: a 2019 trial at two Lim Bay mussel-farm concessions used six DDD03L pingers. Initial protection did not persist: severe predation was reported by mid-July, and the July repeat also failed after about two weeks. The authors called the tested devices non-functional against fish predation. The report does not clearly document randomized sham controls, so temperature, habituation, and other causes remain confounded. It rules out treating that device or its 5–500 kHz, roughly 140 kHz-peak output as an approved baseline; it does not prove all acoustic approaches ineffective or support another frequency or level.

The first tranche needs a useful software path that can run without field hardware, permission, purchases, cloud services, or acoustic output.

## Decision

1. The first vertical slice is passive monitoring and offline replay. It may ingest declared audio or synthetic fixtures, mark signal candidates, pair evidence when available, preserve provenance, and report processing health. A candidate detector is not species identification, feeding confirmation, localization, deterrence, or stock-loss prevention.
2. The offline prototype has no interface that can drive a projector, amplifier, actuator, sensor, camera, radio, or other field hardware. It performs no transmission or acoustic emission. Field capture enters only after the site, permission, safety, and data-governance gates in the requirements register pass.
3. Event detection and localization are separate requirements. One receive channel may support feasibility work. Array geometry, synchronized channels, and localization enter only if local evidence and a stated use case justify them.
4. The initial compute target is Python on a Linux CPU. An accelerator enters only after measured workloads fail a frozen latency, power, or throughput requirement.
5. The field architecture, if later approved, places the hub, LoRaWAN gateway, cellular radio, antennas, and primary power controls above water. Underwater hydrophones, cameras, probes, and any later projector use wired links to surface equipment. LoRaWAN is a gateway-based star-of-stars network, not a submerged peer mesh, and does not carry bulk audio or video.
6. Active acoustic intervention is a separate conditional branch. The failed Lim Bay DDD03L pilot must be treated as a negative gate against repeating that device or output profile. SIREN remains absent from the passive prototype and electrically inhibited in later hardware until raw prior-trial evidence review, specialist acoustic engineering, ecological review, written authorization, calibrated-water tests, and independent stop controls pass. No waveform, source level, duty cycle, or biological safety limit is approved here.
7. Any deterrence study must compare treatment with sham/no-output controls and assess sustained outcomes, habituation, uncertainty, and non-target effects. A failed or inconclusive gate can leave a monitoring-only product; it cannot be converted into a protection claim.
8. Sea-flora stimulation remains an independent research track. It cannot enter a product claim or output program without credible species-specific evidence, an approved study, permission, and replicated results.
9. Cloud services, LoRaWAN nodes, vision models, wipers, custom pressure vessels, custom PCBs, and product variants are later work packages. The passive replay boundary does not imply those choices are selected or implemented.

## Consequences

- Software can be tested with files and synthetic fixtures before any site activity.
- Data provenance, split integrity, hard negatives, missing evidence, dropped input, and clock uncertainty become core outputs.
- The product can continue as a monitoring system if active deterrence fails its evidence or permission gates.
- This boundary delays output hardware and active-control features by design. Coding them early would create safety and claims risk without resolving the biological question.
- The historical PRD remains as a labeled record, but this ADR and the [production requirements register](../requirements/production-requirements.md) control current implementation decisions.

## Not decided

- Farm, coordinates, cultured species, confirmed target predator, and loss baseline
- Hydrophone, camera, sample rate, bandwidth, channel count, array geometry, or calibration chain
- Physical depth, immersion, load, material, power, storage, or service limits
- Detection acceptance thresholds
- Any projector, amplifier, waveform, acoustic envelope, or trial design
- EU conformity route, permission conditions, manufacturing quantity, budget, or release date

This ADR authorizes no purchase, external contact, field recording, installation, deployment, physical test, or acoustic emission.
