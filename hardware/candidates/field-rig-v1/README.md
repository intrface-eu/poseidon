# field-rig-v1: stage-1 recording rig

Copyright (C) 2026 INTRFACE j.d.o.o. Licensed under CERN-OHL-S-2.0.

A cheap rig for the first field recordings. It answers one question: can we hear seabream feeding on a mussel line over farm noise, at a useful range? It is separate from `reference-v1` and the passive-v3 and surface-v3 candidates, and it does not replace them. Those aim at 30 m and 90 days unattended; this rig sits a few metres down for a week at a time and is serviced by boat.

## Where it works

- Lim bay shellfish farms. The bay is 32 m deep at most; the rig hangs from a longline, a float or an anchor rope at 2 to 10 m.
- Design depth 10 m. The housing must hold 2 bar on the gauge (20 m of water) for 24 hours before it goes in the sea.
- Sea water, about 12 to 26 °C, fouling within weeks, boats passing, ropes and floats moving.

## What it must do

| Need | Target |
|---|---|
| Hydrophone | Omnidirectional, usable from 50 Hz to at least 30 kHz, known sensitivity (around -165 to -180 dB re 1 V/µPa) |
| Recording | One channel, 96 kHz preferred (48 kHz fallback), 16-bit minimum, continuous |
| Storage | 7 days at 96 kHz 16-bit mono is about 116 GB; 256 GB per rig |
| Run time | 7 days per battery swap, 3 days at least |
| Clock | Real-time clock set at deployment, drift logged at recovery |
| Camera | On one rig only, optional, daytime, in its own housing or behind a flat window |
| Power | Battery pack swapped by boat; no solar |
| Data link | None; recordings stay on the card |
| Mounting | Tether with shackle and a backup line, contact label, nothing a farmer's gear can snag |

## Two layouts to compare

- **O1 All underwater.** A self-contained recorder (HydroMoth class, or a small board with an audio codec) and its batteries inside one sealed pipe housing, hydrophone element in or on the housing.
- **O2 Cable to the surface.** A cabled hydrophone hangs below; the recorder and battery sit in a dry box on the farm float or raft.

## Budget

At most €5,000 for materials: two rigs, spares, and the tools to build and test them, delivered to Vrsar, Croatia, with VAT, customs and shipping. Target at most €1,500 per rig.

## Out of scope

90-day autonomy, 30 m rating, telemetry, solar, on-device detection, and any sound output.

## Files

- `acquisition.csv`: the buying table, one row per candidate part and supplier.
- `research.md`: prior builds, the pick for each part, and the risks.
