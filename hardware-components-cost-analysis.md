# Poseidon: Historical Hardware Cost Estimate

> **Historical and superseded:** This rough 2025 estimate is not a procurement BOM, quote, component selection, compatibility review, budget approval, or production-readiness record. It excludes major system and lifecycle costs. Do not buy from it. Current requirements and spending gates are in the [production roadmap](docs/production-roadmap.md) and [requirements register](docs/requirements/production-requirements.md).

## Overview
This document preserves two early USD candidate lists and their original descriptions. Prices, availability, specifications, suitability, calibration, taxes, shipping, and completeness were not verified for current use. No current EUR quotes or selected SKUs exist.

---

## Historical Candidate Lists (not a procurement BOM)

### 1. Historical Budget-Conscious Demo List
**Listed-row subtotal: $895. Historical advertised range: $895–$1,425; the upper amount was not explained by the rows.**

| Component | Selection | Estimated Cost | Notes |
|-----------|-----------|----------------|-------|
| Processing Unit | Raspberry Pi 5 (8GB) | $80 | Basic computing, may struggle with parallel processing |
| Hydrophone | Aquarian Audio H2a | $175 | Entry-level with integrated pre-amp |
| DAQ | USB Audio Interface (e.g., Behringer UMC22) | $50 | Sufficient for basic signal acquisition |
| Camera | Blue Robotics Low-Light USB Camera | $150 | Reliable underwater option |
| Acoustic Projector | DIY (e.g., Dayton BST-1 + Potting) | $60 | Low cost, uncertain performance |
| Projector Amplifier | Mini Class-D Amp Board | $30 | Basic amplification |
| Enclosure | Blue Robotics 4" Enclosure Kit (2-port end cap) | $200 | Proven marine enclosure |
| Power System | Tethered Power (Tether, Penetrator, PSU) | $150 | Unlimited runtime for demos |

---

### 2. Historical Performance-Oriented Candidate List
**Listed-row subtotal: $3,549. Historical advertised range: $2,549–$3,599; the listed rows do not support the lower amount or explain the range.**

| Component | Selection | Estimated Cost | Notes |
|-----------|-----------|----------------|-------|
| Processing Unit | NVIDIA Jetson Orin Nano Dev Kit | $499 | GPU acceleration for real-time processing |
| Hydrophone | Benthowave BII-7001 | $750 | Professional grade, superior sensitivity |
| Hydrophone Pre-Amp | ETEC or similar single-channel preamp | $500 | Required high-quality signal conditioning |
| DAQ | USB Audio Interface (e.g., Focusrite Scarlett Solo) | $100 | Higher quality audio interface |
| Camera | Blue Robotics Low-Light USB Camera | $150 | Same reliable option |
| Acoustic Projector | Benthowave BII-8080 | $800 | Professional calibrated projector |
| Projector Amplifier | Small Form Factor Marine-ready Amp | $150 | Robust amplification system |
| Enclosure | Blue Robotics 4" Enclosure Kit (3-port end cap) | $250 | Expanded for additional components |
| Power System | Tethered Power (Fathom Tether, Penetrator, PSU) | $350 | Professional tether solution |

---

## Historical Price-Difference Rationale

The arithmetic differences below follow the listed estimates. Capability and necessity statements were assumptions, not benchmark, calibration, compatibility, or selection evidence.

1. **Processing Unit Upgrade** (+$419)
   - Jetson Orin Nano provides GPU acceleration crucial for:
     - Real-time acoustic signal processing
     - Simultaneous video handling
     - Future AI/ML capabilities
   
2. **Hydrophone System** (+$1,075)
   - Benthowave BII-7001 offers:
     - Superior sensitivity and signal-to-noise ratio
     - Wider frequency response
     - Calibration data for scientific measurements
   - Requires external pre-amp for optimal performance

3. **Acoustic Projector** (+$740)
   - Professional projector provides:
     - Calibrated output
     - Predictable performance
     - Broad frequency range
   - Essential for reliable deterrent effect

---

## Historical Cost-Saving Ideas (superseded)

Do not use these ideas as a purchase sequence. Current work starts with requirements, permission planning, offline replay, and a capped proposal for borrowed/rented passive receive gear.

1. **Historical budget-build idea**
   - Validate detection algorithms before upgrading components
   - Test system integration with lower-cost options
   - Reduce initial financial commitment

2. **Upgrade Priority Sequence**
   - **First**: Upgrade hydrophone if detection quality is insufficient
   - **Second**: Switch to professional projector if deterrent effectiveness is poor
   - **Third**: Upgrade to Jetson if processing becomes bottleneck

3. **Power System Strategy**
   - Use tethered power for demos (saves ~$650 vs battery)
   - Consider autonomous battery only after stationary demo is successful
   - Budget Blue Robotics battery for future autonomous phases

---

## Historical Build Sequence (superseded)

### Phase 1: Early demo list
- Listed-row subtotal: $895
- The old intent was a detection/deterrence demonstration, but it omitted permission, acoustic safety, ecological controls, compatibility, calibration, and many system costs.
- It is not an approved funding demonstration or field build.

### Phase 2: Performance candidate list, not production-ready
- Listed-row subtotal: $3,549
- The old `$3,200` phase figure did not match the listed rows.
- More expensive candidates do not establish reliability, scientific validity, product conformity, manufacturability, or field suitability.

---

## Current Limits of This Estimate

- All prices are historical estimates and exclude shipping, taxes, consumables, VAT/duties, spares, calibration, assembly, testing, recurring costs, and redesign.
- Brand or model appearance in the table is not a recommendation or verified selection.
- Receive and output chains need separate electrical/acoustic compatibility and calibration work. No projector purchase or output test is authorized.
- Tethered power is not proof of field autonomy or site suitability.
- DIY output hardware has unbounded performance and safety risk and is not approved.
- Missing items include at least above-water gateway/radios, node quantities, cabling/connectors, protection, mounts/moorings, storage, power conversion, safety controls, calibration equipment/services, field logistics, conformity, manufacturing, maintenance, and support.
- Current EUR budgets remain incomplete until site requirements, quantities, borrowed/rented options, and dated quotes are approved.

---

## References

- Complete research report: `.taskmaster/docs/research/2025-11-07_underwater-crack-detection-and-deterrent-systems-h.md`
- Task Master Task #6: Hardware Purchasing Plan and Component Selection