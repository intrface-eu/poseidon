# Poseidon: Funding & Stakeholder Brief (v0.1, historical)

> **Historical and superseded:** This 2025-11-07 draft does not describe current readiness and is not approved for external use. It is not evidence of implementation, efficacy, safety, permission, conformity, funding need, licensing, patent rights, or commercial authorization. Current work is governed by the [production roadmap](docs/production-roadmap.md), [requirements register](docs/requirements/production-requirements.md), and [passive-first ADR](docs/decisions/0001-passive-first-system-boundary.md).

Owner: CEII (Alex) · Maintainer: Interface / Intrface Engineering  
Date: 2025‑11‑07  
Superseded: 2026-09-07
Repository: poseidon

---

## 1) Historical Executive Summary
Poseidon was proposed as a modular marine monitoring and acoustic-intervention platform. The physical hub, vision, projector, LoRaWAN nodes, cloud, update path, safety controls, and field deployment described here were not implemented or verified when this brief was superseded. Deterrence and sea-flora effects were hypotheses, not supported outcomes. The current first slice is offline passive replay and later permission-bound passive collection; it contains no acoustic output path.

Historical impact goals, all unverified:
- Test whether measured evidence can support a non-lethal response to predation and stock loss.
- Review sea-flora hypotheses as a separate research track with no current product claim.
- Develop an auditable monitoring path only after its site, data, hardware, and operational requirements pass.

---

## 2) Problem Statement & Outcomes
Coastal aquaculture faces losses due to predators and environmental stressors. The project must measure the local problem and compare non-acoustic options before selecting an intervention. The current aims are to:
- test passive monitoring against observed local feeding events and hard negatives;
- define environmental telemetry only after site need, calibration, power, and communications evidence;
- build a lawful, reviewable evidence path without claiming a safe or effective protection system.

Historical proposed metrics, not measured results:
- Reliability: ≥ 7 days unattended operation was an engineering gate, not production qualification.
- Vision-to-audio latency targets are superseded because active output is outside the current slice.
- The ≥ 95% LoRa target lacked offered load, outage denominator, site scale, and gateway evidence.
- No bench SPL validation existed. Digital amplitude limiting does not establish calibrated underwater output or biological safety.
- One-command bootstrap and ≥ 90% OTA success were not implemented, and the update target did not define safe recovery.

---

## 3) Historical Solution Overview
Historically proposed capabilities, not current product features:
- vision-triggered deterrence and lens-wiper maintenance;
- acoustic playback and synthesis;
- ESP32 LoRaWAN sensor/actuator nodes with solar power;
- MQTT/cloud ingestion and dashboards;
- containerized services, updates, and hub connectivity management.

The diagram is conceptual. Its node-to-node LoRa arrows do not define an approved mesh or underwater RF path. Current architecture keeps the gateway and radios above water, wires submerged instruments to surface equipment, and keeps active output inhibited.

Historical system architecture:

```
                 ┌─────────────────────────────────────────────────────────────────────────┐
                 │                                 AEOLUS (Cloud)                          │
                 │  • EMQX/Mosquitto (MQTT)  • FastAPI (API)  • Timescale/Influx  • UI    │
                 │  • ChirpStack (LoRaWAN NS+AS)  • Vector/Promtail→Loki (logs)           │
                 └───────────────▲──────────────────────────────▲──────────────────────────┘
                                │ MQTT/TLS                    │ HTTPS/TLS
                                │                             │
    4G Network                   │                             │
┌────────────────────────────────┼─────────────────────────────┼────────────────────────────────┐
│        POSEIDON HUB (Raspberry Pi 4/5 + 4G HAT)                                                     │
│  ┌───────────────┐   ┌───────────────────────┐   ┌───────────────────┐   ┌──────────────────────┐ │
│  │  TRIDENT      │   │  NEREID (Vision)     │   │  SIREN (Audio)    │   │ AQUILON (LoRa/MQTT)  │ │
│  │  Orchestrator │   │  • EdgeTPU/TensorRT  │   │  • Player+Synth   │   │ • LoRaWAN GW client  │ │
│  │  • Supervisor │   │  • Lens Wiper Ctrl   │   │  • SPL Limiter     │   │ • MQTT Agent         │ │
│  └───────▲───────┘   └───────────▲───────────┘   └───────────▲───────┘   └───────────▲──────────┘ │
│          │                       │                           │                          │        │
│          │ gRPC/IPC              │ CSI/USB camera+PWM        │ I2S/USB DAC → Amp → SPK  │ LoRa   │
└──────────┼───────────────────────┼────────────────────────────┼──────────────────────────┼────────┘
           │                       │                            
           │                       │
     ┌─────▼─────┐          ┌──────▼──────┐
     │  REEF     │  LoRa    │  REEF       │  LoRa
     │ ESP Nodes │◄────────►│ ESP Nodes   │ … solar, sensors, relays
     └───────────┘          └─────────────┘
```

---

## 4) Historical Component Boundaries

The following responsibilities were proposed; they did not describe implemented or tested services.

- TRIDENT (Hub Orchestrator): service supervision; config sync; connectivity watchdog; site schedules; inter‑service RPC; safe shutdown; local cache; command routing. Proposed CLI: `poseidon hub status|provision|apply-config|tail|killswitch`.
- NEREID (Vision): camera capture; EdgeTPU/TensorRT/CPU detection; droplet/smudge classifier; PWM lens‑wiper control; publishes `vision/event`.
- SIREN (Audio): proposed playback/synthesis and digital limiter/duty logic; not an SPL safety control or approved scheduler.
- AQUILON (LoRa/MQTT): ChirpStack/TTS integration; CBOR uplink decode; MQTT republish and command downlink.
- REEF (ESP Firmware): OTAA join; deep sleep; sensor reads; CBOR payload packing; low‑battery behaviors.
- AEOLUS (Cloud): Broker (MQTT/TLS); API (FastAPI) for device registry & configs; Timescale/Influx; UI (Next.js); logs (Vector→Loki).

Monorepo Strategy and Layout:

```
poseidon/
├─ apps/
│  ├─ trident/      # Orchestrator (Python)
│  ├─ nereid/       # Vision (Python; TFLite/EdgeTPU, TensorRT)
│  ├─ siren/        # Audio (Python; ALSA/GStreamer)
│  ├─ aquilon/      # LoRaWAN + MQTT gateway client (Python)
│  ├─ aeolus-api/   # Cloud API (FastAPI)
│  ├─ aeolus-ui/    # Dashboard (Next.js/TypeScript)
│  └─ chirpstack/   # IaC/compose for LoRaWAN (optional)
├─ firmware/
│  └─ esp-sentinel/ # ESP32 + LoRa
├─ libs/
│  ├─ proto-py/     # Pydantic schemas, topic helpers
│  ├─ proto-ts/     # Shared TS types for UI
│  └─ dsp/          # Signal generation, filters, envelopes
├─ models/          # ONNX/TFLite zoo + converters
├─ ops/             # Dockerfiles, compose, k8s, OTA, ansible
├─ hardware/        # BOM, wiring, CAD, test jigs (stubs)
├─ scripts/         # bootstrap, flashing, helpers
├─ configs/         # sites, audio programs, vision, lorawan
├─ docs/            # runbooks, safety, IP strategy
└─ .github/         # CI workflows
```

---

## 5) Historical Safety, Environmental, and Governance Ideas

No control in this section was implemented, calibrated, permissioned, or validated when the brief was superseded.

- Digital RMS/peak and gain settings are not underwater SPL limits. Any later output chain needs specialist-set reference units, geometry, exposure basis, uncertainty, independent hardware inhibit, startup silence, and calibrated-water tests.
- Duty cycles, software guards, time windows, and remote stops are secondary controls; they do not replace ecological evidence, written authorization, a physical stop, abort rules, or explicit rearm.
- The current offline prototype has no hardware or acoustic output path. The initial [hazard register](docs/safety/initial-hazard-register.md) keeps field and emission hazards open.
- MQTT logs and retained configuration would not prove compliance or permission.
- Mutual TLS, per-device credentials, secret management, scoped roles, signed commands, and recoverable updates remain production requirements, not current capabilities.

---

## 6) Historical Data and Protocol Sketches

These topics and payloads were not adopted contracts. The audio command's normalized digital values are not SPL, source level, received level, or biological safety limits, and its named program is not approved.

MQTT Topic Taxonomy:
```
poseidon/{site}/{zone}/{device}/telemetry
poseidon/{site}/{zone}/{device}/event
poseidon/{site}/{zone}/{device}/state
poseidon/{site}/{zone}/{device}/cmd/{action}
poseidon/{site}/{zone}/{device}/ack/{action}
poseidon/{site}/{zone}/audio/cmd/{program}
poseidon/{site}/{zone}/vision/event
poseidon/{site}/{zone}/power/telemetry
poseidon/{site}/hub/state
```

Example Payloads:
```json
{
  "ts": 1730978400,
  "device": "reef-esp-07",
  "sensors": {"temp_c": 14.3, "turbidity_NTU": 4.1, "lux": 120},
  "power": {"vbat": 3.91, "soc": 0.72, "solar_mv": 4300},
  "rssi": -88
}
```
```json
{
  "ts": 1730978405,
  "source": "nereid",
  "event": "motion",
  "score": 0.87,
  "region": [120, 60, 220, 180]
}
```
```json
{
  "action": "play_program",
  "program": "dolphin-deterrent-A",
  "duration_s": 45,
  "gain_db": -6,
  "safety": {"max_rms": 0.6, "max_peak": 0.9}
}
```

LoRaWAN Uplink (compact CBOR → decoded at gateway):
- Fields: `dev`, `ts`, `bat`, `t`, `tb`, `lx`, `evt` (bitfield), `fw`.

---

## 7) Historical Deployment and Operations Sketch

The compose files, provisioning path, and OTA templates described here were not present or tested. These snippets are not current setup instructions.

Hub (Pi) Bootstrap (dev example):
```
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# enable camera/I2C/PWM manually or via raspi-config

# Fetch compose (replace with your repo remote, e.g., poseidon)
# git clone <your-repo-url>
# cd poseidon/ops/compose
# sudo docker compose -f hub.dev.yml up -d
```

Cloud (dev example):
```
# cd poseidon/ops/compose && docker compose -f cloud.dev.yml up -d
```

Historical OTA options:
- balena or Mender were candidates; no included template or selected production path existed.
- Ansible was a proposed lab option.

Observability:
- Logs: Vector/Promtail→Loki  
- Metrics: Prometheus/Telegraf (light Pi metrics)

---

## 8) Historical Roadmap (superseded 10–12 week MVP)

This sequence omitted site access, ecological evidence, calibrated acoustic safety, physical engineering, conformity, manufacturing, and support. It is not a production schedule.

M1 — Repo & Scaffolding (Week 1)
- Monorepo bootstrapped; CI lint/build green.  
- MQTT taxonomy + pydantic schemas.  
- Compose stack for hub (stubs), cloud broker in dev.

M2 — Vision & Lens Cleaning (Weeks 2–3)
- Camera capture + CPU motion detector.  
- Servo PWM driver + cleaning scheduler; droplet classifier stub.  
- EdgeTPU and TensorRT backends integrated (select via config).

M3 — Audio Engine (Weeks 3–4)
- WAV playback + parametric click/whistle synthesis.  
- Safety limiter + duty cycle; program DSL.  
- Reactive triggers from vision; basic playlists.

M4 — LoRaWAN Path (Weeks 4–5)
- ESP sentinel firmware: OTAA join, CBOR uplink, sleep/wake.  
- AQUILON gateway client + ChirpStack dev stack; MQTT bridge.  
- Telemetry graphs in UI (minimal).

M5 — Orchestration & Reliability (Weeks 6–7)
- TRIDENT supervising services; backoff/retries; config apply.  
- 4G watchdog + failover to Wi‑Fi; offline cache.  
- Bootstrapping script for fresh Pi.

M6 — Cloud API & Dashboard (Weeks 8–9)
- Device registry; config bundles; command endpoints.  
- Dashboard: map view, device list, program selector, kill‑switch.  
- Time‑series storage; retention; log ingestion.

M7 — Field Pilot Readiness (Weeks 10–12)
- SPL bench calibration doc + limiter validation.  
- HIL test pass; soak test 7 days.  
- Runbooks; deployment guide; IP strategy outline.

---

## 9) Historical Risk List (superseded)
1. Acoustic exposure requires physical inhibit, calibrated acoustic measures, ecological review, permission, and authorized tests; a software limiter is not enough.
2. Field design needs bounded offline behavior and cannot put safety in the 4G/cloud loop.
3. Lens cleaning effectiveness, scratch/jam risk, and service interval remain unverified.
4. LoRaWAN needs an above-water gateway and measured link/airtime budget; it is not an underwater peer mesh.
5. ESP load, battery behavior, and worst-season solar reserve remain TBD.
6. Use CPU first; select an accelerator only if measured requirements justify it.
7. An IP rating or coating does not prove the chosen pressure, immersion, corrosion, or service envelope.
8. Configurable bands and documentation do not grant underwater-sound permission.
9. Time windows and duty caps do not replace non-target evidence, monitoring, and abort rules.
10. Production updates need signing, target/version checks, rollback control, interruption testing, and known-good recovery.

---

## 10) Historical Hardware Candidate Summary

This was not a quoted, complete, compatible, or production-ready BOM. No listed model is selected by the current plan.
- Hub: Raspberry Pi 4/5; 4G HAT (Quectel EC25/EC20) + external antenna.  
- Acceleration: Google Coral USB/PCIe or Jetson Nano.  
- Camera: Pi Cam (global‑shutter preferred) + IR option; micro‑servo + wiper arm; PCA9685.  
- Audio: USB/I2S DAC → Marine amp → Underwater transducers (IP68); inline limiter (optional hardware).  
- Nodes: ESP32 LoRa boards; solar + MPPT/PMIC; sensors (temp, light, turbidity proxy); battery gauge.  
- LoRaWAN: Gateway (RAK/Multitech) if needed; otherwise TTS via public gateway.

---

## 11) Compliance, Permission, and Ethics Preparation

All items remain unverified. No authority, farm, or research partner has been contacted through this brief, and no permission, calibration record, legal review, or approved template exists.

- Passive recording: confirm farm access, protected-area research rules, installation/navigation requirements, work safety, privacy, retention, and publication terms before collection.
- Acoustic emissions: no output is authorized. Retained settings, digital caps, time windows, or a stop topic would not establish permission or acoustic safety.
- Data protection: planned camera/audio collection may capture people, vessels, identifiers, private operations, and sensitive coordinates; it cannot be described as telemetry-only or PII-free without review.
- Product obligations: establish the intended use and dated EU/EEA applicability matrix with a qualified adviser/lab before design freeze and release.
- Change control: signed, recoverable updates, audit records, and vulnerability response remain requirements.

Use the [site and permissions register](docs/research/site-permissions-evidence-register.md) for current evidence and blocked decisions.

---

## 12) Historical Pilot Sketch (not approved)

Do not run the active sequence below. The directly reviewed ARIEL Croatian report found that the tested 2019 Lim Bay DDD03L pingers did not provide persistent protection; severe predation was reported by mid-July, and the July repeat failed after about two weeks. The report lacks clearly described randomized sham controls, so it neither validates another acoustic treatment nor proves every acoustic approach ineffective.

Current order: confirm site and permission evidence, run an approved passive collection study, assess local detectability, obtain raw prior-trial methods/data, and design any later active study with specialist safety work, sham/no-output controls, replication, blinded outcomes, habituation follow-up, and non-target monitoring. No active pilot is authorized.

---

## 13) Historical IP and Licensing Ideas (not adopted)
- No BUSL/MIT split or `PATENTS.md` was adopted through this brief. No license, patent, ownership, freedom-to-operate, or commercial-use conclusion is made here.
- The listed project names were not shown to be registered or legally available.
- Mentioning a program DSL or lens-cleaning feedback does not establish novelty, inventorship, ownership, or patentability.

---

## 14) Historical Budget Framework (incomplete)
- Feasibility, access, adviser time, and passive measurement: TBD
- Hardware, spares, calibration, assembly, and test: TBD
- Data, connectivity, software operations, and storage: TBD
- Field operations, vessel time, installation, retrieval, and maintenance: TBD
- Compliance, ecological review, qualification, manufacture, support, warranty, and disposal: TBD
- Contingency: TBD

No current EUR quotes, quantities, selected SKUs, recurring costs, or approved spending cap exist. The historical USD component subtotals are recorded separately in [`hardware-components-cost-analysis.md`](hardware-components-cost-analysis.md); they are not a project budget.

---

## 15) Historical Appendices

The snippets below were never calibrated, authorized, or adopted. Frequency, gain, timing, and `spl_cap_db`/`max_rms`/`max_peak` values must not be used as acoustic design or safety limits.

A. Example Site Config (snippet):
```yaml
site: vrsar-reef
hub_id: hub-vrsar-01
zones:
  - id: north-line
    audio_device: usb_dac_1
    spl_cap_db: -3
    programs:
      periodic:
        - name: flora-sweep-A
          every: "0 */2 * * *"
          duration_s: 300
          gain_db: -12
      reactive:
        - name: dolphin-deterrent-A
          duration_s: 45
          gain_db: -8
vision:
  backend: edgetpu   # edgetpu|tensorrt|cpu
  motion_threshold: 0.6
  cooldown_s: 30
  lens_cleaning:
    every_min: 120
    sweep_ms: 1500
lorawan:
  ns: chirpstack
  dev_prefix: reef-esp
```

B. Example Audio Program:
```yaml
name: dolphin-deterrent-A
blocks:
  - type: click_burst
    rate_hz: 20
    burst_ms: 800
    gap_ms: 300
    jitter: 0.1
  - type: whistle
    f0_hz: 6000
    f1_hz: 18000
    glide_ms: 1200
safety:
  max_rms: 0.65
  max_peak: 0.9
```

C. Glossary
- EdgeTPU: Coral accelerator for TFLite models.  
- TensorRT: NVIDIA runtime for optimized inference.  
- CBOR: compact binary JSON.  
- ADR: Adaptive Data Rate (LoRaWAN).

D. References
- Full PRD: `poseidon_monorepo_taskmaster_prd_delivery_plan_v_0.md`
- Task Backlog: `.taskmaster/tasks/tasks.json` (generated)

---

This historical draft is retained for traceability only. It is superseded, not approved for external use, and makes no safety, compliance-readiness, funding, efficacy, or field-trial claim.
