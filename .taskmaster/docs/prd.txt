# Poseidon Monorepo — Taskmaster PRD & Delivery Plan (v0.1, historical)

> **Historical and superseded:** This 2025-11-07 concept record was superseded on 2026-09-07 by `docs/production-roadmap.md`, `docs/requirements/production-requirements.md`, and `docs/decisions/0001-passive-first-system-boundary.md`. It is not evidence of implementation, field readiness, safety, biological efficacy, permission, product conformity, licensing, or ownership rights.
>
> **Canonical-copy policy:** This root file is the canonical historical source. `.taskmaster/docs/prd.txt` must remain a byte-identical mirror; edit this file first, then copy it to the mirror.
>
> **Codename**: **TRIDENT** (core hub) · **NEREID** (edge vision/audio) · **AQUILON** (LoRaWAN & MQTT) · **REEF** (ESP sensor/actuator fleet) · **SIREN** (audio engine) · **AEOLUS** (cloud & dashboards)
>
> **Historical goal:** The v0.1 concept proposed an end-to-end marine monitoring and acoustic-intervention platform. Shellfish protection, dolphin-like deterrence, sea-flora effects, field deployability, and accelerator needs were not verified. The current plan begins with passive monitoring and uses an above-water LoRaWAN gateway network, not a submerged peer mesh.

---

## 0) Historical Elevator Pitch
The v0.1 concept proposed a ruggedized, modular marine IoT platform: a Raspberry Pi hub, above-water 4G and LoRaWAN equipment, solar ESP32 nodes, a camera and lens wiper, and a separately gated underwater acoustic system. None of those physical capabilities was implemented or field-verified when this PRD was superseded. Dolphin imitation and sea-flora playback were hypotheses, not established effects or approved programs.

---

## 1) Historical Scope

The bullets below preserve the proposed v0.1 scope. They are not the current approved build order or proof that a listed component exists.

- **Historically proposed in-scope**
  - Raspberry Pi 4/5 hub with **4G HAT** (PPP/ModemManager), Wi‑Fi/Ethernet fallback.
  - **Edge compute backends**:
    - **Google Coral TPU** (TFLite/EdgeTPU) **or** **Jetson Nano** (TensorRT/ONNX) with CPU fallback.
  - **Vision**: motion/species triggers; droplet/smudging detection; servo **lens wiper** control.
  - **Audio**: proposed playback and synthesis for research-gated programs. Digital amplitude limiters were not implemented, calibrated to underwater SPL, or evidence of biological safety.
  - **LoRaWAN**: proposed ESP32 solar nodes using an above-water gateway; not an underwater or peer-to-peer mesh.
  - **Network orchestration**: proposed MQTT topic taxonomy, device provisioning, and remote configuration.
  - **Cloud**: proposed broker, API, database, dashboard, and update hooks; not implemented or production-ready.
  - **Ops**: proposed containerized services, CI/CD, observability, runbooks, and stop controls; not implemented or tested.
- **Historically proposed out-of-scope (v0)**
  - Full marine acoustic impact study (provide hooks, not the study itself).
  - Proprietary enclosure designs (placeholder CAD and BOM references only).
  - Legal certification filings (we prepare the checklist; execution external).

---

## 2) Historical Success Metrics (MVP → Field Pilot)

These were proposed targets, not measured results or current production acceptance criteria.

- **Reliability**: proposed ≥ 7 days continuous unattended operation with auto-recovery on connectivity loss; unverified.
- **Latency**: proposed camera-to-audio targets; superseded because active output is outside the passive-first slice.
- **Telemetry**: proposed ≥ 95% LoRa uplinks within 5 minutes; offered load, outage denominator, site scale, and gateway placement were undefined.
- **Safety**: no bench SPL validation existed. A digital limiter cannot establish underwater acoustic output or biological safety without a calibrated chain, reference units, geometry, exposure basis, and uncertainty.
- **Maintainability**: one-command bootstrap and ≥ 90% OTA success were unimplemented targets; the update target was not enough for production recovery evidence.

---

## 3) Historical System Architecture

The diagram records the original concept. Its node-to-node LoRa arrows must not be read as an approved mesh or underwater radio path. The current boundary uses an above-water LoRaWAN gateway and wired submerged instruments; active audio remains separately inhibited.

```
                 ┌─────────────────────────────────────────────────────────────────────────┐
                 │                                 AEOLUS (Cloud)                          │
                 │  • EMQX/Mosquitto (MQTT)  • FastAPI (API)  • Timescale/Influx  • UI    │
                 │  • ChirpStack (LoRaWAN NS+AS)  • Vector/Promtail→Loki (logs)           │
                 └───────────────▲──────────────────────────────▲──────────────────────────┘
                                 │ MQTT/TLS                    │ HTTPS/TLS
                                 │                             │
     4G Network                   │                             │
┌─────────────────────────────────┼─────────────────────────────┼────────────────────────────────┐
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

## 4) Monorepo Strategy
**Use a monorepo** for shared protocol libs, message schemas, tooling, and synchronized versioning.

```
poseidon/                      # Monorepo root
├─ apps/
│  ├─ trident/                 # Hub orchestrator (Python, asyncio)
│  ├─ nereid/                  # Vision service (Python; TFLite/EdgeTPU, TensorRT)
│  ├─ siren/                   # Audio engine (Python; ALSA/GStreamer)
│  ├─ aquilon/                 # LoRaWAN + MQTT gateway client (Python)
│  ├─ aeolus-api/              # Cloud API (FastAPI, Python)
│  ├─ aeolus-ui/               # Dashboard (Next.js/TypeScript)
│  └─ chirpstack/              # IaC/compose for LoRaWAN (optional self-host)
├─ firmware/
│  ├─ esp-sentinel/            # Sensor node (PlatformIO; ESP32 + LoRa)
│  ├─ esp-audio-node/          # Remote audio/relay node (optional)
│  └─ esp-power-telemetry/     # Solar/PMIC reporting
├─ libs/
│  ├─ proto-py/                # Shared Python schemas (pydantic), topic helpers
│  ├─ proto-ts/                # Shared TS types for UI
│  └─ dsp/                     # Signal generation, filters, envelopes
├─ models/                     # Model zoo (ONNX/TFLite) + converters
├─ ops/
│  ├─ docker/                  # Dockerfiles, multi-arch builds
│  ├─ compose/                 # docker-compose.* for Pi/x86/cloud
│  ├─ k8s/                     # Optional k8s manifs (cloud)
│  ├─ balena/ mender/          # proposed OTA options; no included-template claim
│  └─ ansible/                 # Bare-metal provisioning
├─ hardware/
│  ├─ bom/                     # BOM and part numbers (4G HAT, amp, speakers, servos)
│  ├─ wiring/                  # Pinouts, harness docs
│  ├─ cad/                     # Enclosure stubs
│  └─ test-jigs/               # HIL test rig notes
├─ scripts/                    # make-like helpers; flashing; tail logs
├─ configs/                    # YAML for sites, audio programs, detection rules
├─ docs/                       # Operations, runbooks, API, safety, IP strategy
├─ .github/                    # CI workflows (build, test, release)
├─ Makefile                    # top-level developer shortcuts
└─ LICENSE / PATENTS.md / SECURITY.md / CODEOWNERS / CONTRIBUTING.md
```

---

## 5) Technology Choices
- **Languages**: Python (orchestration, ML, audio, gateways); TypeScript (UI); C/C++ (ESP firmware).
- **ML**: TFLite + EdgeTPU (Coral), ONNX→TensorRT (Jetson), CPU fallback via OpenVINO or plain TFLite.
- **Audio**: ALSA/GStreamer backends; `numpy/scipy` + streaming for click/whistle synthesis.
- **Messaging**: MQTT over TLS (EMQX/Mosquitto). LoRaWAN via ChirpStack or The Things Stack (pluggable).
- **DB**: TimescaleDB or InfluxDB for time‑series; MinIO/S3 for media; SQLite on hub for offline cache.
- **OTA**: balenaOS or Mender (choose at deployment); Ansible for lab.
- **Observability**: Vector + Loki for logs; Prometheus + node‑exporter (cloud); light Pi metrics via Telegraf.

---

## 6) Protocols & Schemas (v0)
### 6.1 MQTT Topic Taxonomy
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

### 6.2 JSON Payload (examples)
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
The following historical command is unsafe as a current contract. Its normalized digital values are not SPL, source level, received level, or biological safety limits, and the named program is not approved.

```json
{
  "action": "play_program",
  "program": "dolphin-deterrent-A",
  "duration_s": 45,
  "gain_db": -6,
  "safety": {"max_rms": 0.6, "max_peak": 0.9}
}
```

### 6.3 LoRaWAN Uplink (compact CBOR → decoded at gateway)
Fields: `dev`, `ts`, `bat`, `t`, `tb`, `lx`, `evt` (bitfield), `fw`.

---

## 7) Components — Responsibilities & Interfaces
### 7.1 TRIDENT (Hub Orchestrator)
- **Responsibilities**: service supervision; config sync; connectivity watchdog; site schedules; inter‑service RPC; safe shutdown; local cache; command routing.
- **Interfaces**:
  - IPC/gRPC to NEREID, SIREN, AQUILON.
  - MQTT client (TLS) with reconnect/backoff.
  - Systemd service unit generation.
- **CLI**: `poseidon hub status|provision|apply-config|tail|killswitch`.

### 7.2 NEREID (Vision)
- **Pipeline**: camera capture → resize → (EdgeTPU/TensorRT/CPU) → trigger rules → publish `vision/event`.
- **Models**: EfficientDet‑Lite or YOLO‑Nano for motion/fish silhouettes; droplet/smudge classifier.
- **Servo Lens Wiper**: PWM control via PCA9685 or Pi PWM; sweep pattern; dry‑off delay.
- **Config**: ROI masks; min score; cool‑down windows; night IR modes.

### 7.3 SIREN (Audio Engine, historical proposal)
- **Modes**: dolphin-like and sea-flora programs were unverified research ideas, not approved treatments.
- **Safety**: digital limiting, duty cycles, and software guards were proposed only and could not establish calibrated acoustic safety.
- **Outputs**: any later DAC, amplifier, and projector chain requires an independent hardware inhibit and separate authorization.
- **Scheduler**: no reactive or periodic output is approved by this historical PRD.

### 7.4 AQUILON (LoRaWAN & MQTT Gateway Client)
- **Gateway**: proposed ChirpStack/TTS integration through a real above-water LoRaWAN gateway; decode CBOR and map telemetry to MQTT.
- **Downlinks**: config pushes, relay toggles, firmware OTA stub.
- **Health**: heartbeat, RSSI tracking; adaptive rate hints.

### 7.5 AEOLUS (Cloud)
- **Broker**: EMQX/Mosquitto + TLS mutual auth.
- **API**: FastAPI for device registry, configuration bundles, and program catalog.
- **DB**: time‑series metrics; event store; files (MinIO) for media.
- **UI**: Next.js dashboard (map of sites; live events; remote kill‑switch; playlist control; battery graphs).

### 7.6 REEF (ESP Firmware)
- **Boards**: ESP32 + LoRa (Heltec/TTGO); PMIC metering; I2C sensors (temp, light, turbidity proxy); relay/servo as needed.
- **Power**: deep sleep; wake on timer/threshold; brown‑out-safe logging.
- **Protocol**: LoRaWAN OTAA; compact CBOR payloads; basic CRC at app layer.
- **Bootloader hooks** for OTA (future).

---

## 8) Configuration Model
- `configs/sites/{site}.yml`: proposed site metadata, zones, hub IDs, and audio-device map. The historical `spl_cap_db` placeholder was not a calibrated acoustic limit.
- `configs/programs/`: JSON/YAML describing audio sequences (blocks, ADSR, wobble, burst cadence, duty limits).
- `configs/vision/`: ROIs, thresholds, detector choice, lens cleaning schedule.
- `configs/lorawan/`: JoinEUI/AppKey placeholders, RX windows, ADR policy.

---

## 9) Security & Secrets
- Mutual‑TLS for MQTT; client certs per hub.
- `.env` files only in dev; production secrets via Vault/SOPS/parameter store.
- Signed firmware (future milestone).
- Role‑based UI with device scoping.
- Remote **Kill‑Switch** topic: `poseidon/{site}/hub/cmd/killswitch` (requires signed command).

---

## 10) Deployability
- **Pi Hub**: Docker Compose stack with healthchecks; one‑command bootstrap script (Ansible or Bash) that:
  1) Enables camera, PWM, I2C; 2) Installs ModemManager/PPP for 4G; 3) Installs Docker; 4) Fetches compose; 5) Provisions certs; 6) Starts services.
- **Cloud**: Terraform/IaC for broker, API, DB; domain + TLS via Caddy/Traefik.
- **OTA**: balena or Mender was a proposed choice. The repository did not include either template when this PRD was superseded; production updates require a selected, signed, interruption-tested recovery path.

---

## 11) Historical Operational Safety Proposal (Audio)

No listed control was implemented or validated when this PRD was superseded.

- Digital RMS/peak settings are not absolute underwater acoustic ceilings and cannot replace calibration or an independent hardware inhibit.
- Duty-cycle and cool-down logic would be secondary controls inside a specialist-defined, permission-bound exposure envelope.
- No bench or in-water SPL calibration record, site curve, source geometry, exposure basis, or uncertainty record existed.
- A UI stop is not independent. Any later system requires a tested physical inhibit/stop, startup silence, fail-silent faults, and explicit rearm.

---

## 12) Testing Strategy
- **Unit tests**: DSP blocks, payload codecs, reconnection logic, rule engine.
- **HIL tests**: test jig triggers PWM, plays audio to dummy load, records camera frames.
- **Simulation**: replay recorded videos; synthetic telemetry generators.
- **Field pilot**: scripted soak tests; connectivity flaps; power brown‑out recovery.

---

## 13) CI/CD
- GitHub Actions:
  - Lint & type check (Black, Ruff, Mypy, ESLint, PIO check).
  - Build multi‑arch Docker images (linux/arm64, linux/amd64).
  - Firmware build matrix (boards variants).
  - Release tags → push images; attach firmware artifacts.

---

## 14) Developer Experience
- `Makefile` targets: `make dev`, `make up`, `make logs`, `make flash-esp`, `make model-sync`.
- Pre‑commit hooks; conventional commits; semantic release.
- VSCode devcontainers for x86 + remote‑SSH to Pi.

---

## 15) Historical Hardware Candidate List

This was not a quoted, complete, compatible, or production-ready BOM. No listed model is selected by the current plan.
- **Hub**: Raspberry Pi 4/5; 4G HAT (Quectel EC25/EC20‑based) with external antenna.
- **Acceleration**: Google Coral USB/PCIe **or** Jetson Nano.
- **Camera**: Pi Cam (global shutter preferred) + IR option; lens; micro‑servo + wiper arm; PCA9685.
- **Audio**: USB/I2S DAC → Marine amp → Underwater transducers (IP68); inline limiter (optional hardware).
- **Nodes**: ESP32 LoRa boards; solar panel + MPPT/PMIC; sensors (temp, light, turbidity proxy), battery gauge.
- **LoRaWAN**: Gateway (RAK/Multitech) if coverage absent; otherwise TTS via public gateway.

---

## 16) Historical Milestones & Sprints (superseded 10–12 week MVP)

This sequence omitted site access, ecological evidence, calibrated acoustic safety, physical engineering, conformity, manufacturing, and support. It is not a production schedule. Follow the staged production roadmap instead.
### M1 — Repo & Scaffolding (Week 1)
- [infra] Monorepo bootstrapped; CI lint/build green.
- [proto] MQTT taxonomy + pydantic schemas.
- [ops] Compose stack for hub (stubs), cloud broker in dev.

### M2 — Vision & Lens Cleaning (Weeks 2–3)
- [vision] Camera capture service + motion detector on CPU.
- [vision] Servo PWM driver + cleaning scheduler; droplet classifier stub.
- [vision] EdgeTPU and TensorRT backends integrated (select via config).

### M3 — Audio Engine (Weeks 3–4)
- [audio] WAV playback + parametric click/whistle synthesis.
- [audio] Safety limiter + duty cycle; program DSL.
- [audio] Reactive triggers from vision; basic playlists.

### M4 — LoRaWAN Path (Weeks 4–5)
- [lorawan] ESP sentinel firmware: OTAA join, CBOR uplink, sleep/wake.
- [lorawan] AQUILON gateway client + ChirpStack dev stack; MQTT bridge.
- [lorawan] Telemetry graphs in UI (minimal).

### M5 — Orchestration & Reliability (Weeks 6–7)
- [hub] TRIDENT supervising services; backoff/retries; config apply.
- [hub] 4G watchdog + failover to Wi‑Fi; offline cache.
- [ops] Bootstrapping script for fresh Pi.

### M6 — Cloud API & Dashboard (Weeks 8–9)
- [api] Device registry; config bundles; command endpoints.
- [ui] Map view, device list, program selector, killswitch.
- [db] Time‑series storage; retention policy; log ingestion.

### M7 — Field Pilot Readiness (Weeks 10–12)
- [safety] SPL bench calibration doc + limiter validation.
- [testing] HIL test pass; soak test 7 days.
- [docs] Runbooks; deployment guide; IP strategy outline.

---

## 17) Taskmaster Backlog (Epics → Stories)
> **Label taxonomy**: `[hub] [vision] [audio] [lorawan] [esp] [mqtt] [cloud] [ui] [ops] [safety] [docs] [legal]`

### EPIC A — Monorepo & Tooling
- A1 `[ops]` Init repo with `apps/ firmware/ libs/ ops/ configs/ docs/` and Makefile.
- A2 `[ops]` GitHub Actions: lint, test, multi‑arch builds.
- A3 `[proto]` Define MQTT topics & pydantic schemas; sample payloads.
- A4 `[ops]` Devcontainer & VSCode tasks; pre‑commit hooks.

### EPIC B — Hub Orchestrator (TRIDENT)
- B1 `[hub]` Process supervisor & healthchecks (asyncio tasks).
- B2 `[hub]` Connectivity watchdog (4G/PPP/ModemManager events).
- B3 `[hub]` Config loader (YAML) + live reload.
- B4 `[hub]` CLI for provision/apply/killswitch.

### EPIC C — Vision (NEREID)
- C1 `[vision]` CSI/USB camera capture module; ROI masking.
- C2 `[vision]` Motion detector baseline; publish `vision/event`.
- C3 `[vision]` EdgeTPU model integration; TensorRT alternative.
- C4 `[vision]` Droplet/smudging classifier; trigger lens wiper.
- C5 `[vision]` PWM driver (PCA9685) + cleaning patterns.

### EPIC D — Audio (SIREN)
- D1 `[audio]` ALSA/GStreamer output; WAV playlist loader.
- D2 `[audio]` Dolphin click/whistle synthesis (envelopes + bursts).
- D3 `[audio]` Seafloor programs (sweeps/FM/AM/noise) + DSL.
- D4 `[audio]` Hard limiter + duty cycle controller.
- D5 `[audio]` Reactive/periodic scheduler.

### EPIC E — LoRaWAN & MQTT (AQUILON)
- E1 `[lorawan]` ChirpStack dev compose; gateway bridge config.
- E2 `[lorawan]` Uplink decoder (CBOR) → MQTT publisher.
- E3 `[lorawan]` Downlink command path (set rate, relay toggle).
- E4 `[lorawan]` Health metrics + ADR hinting.

### EPIC F — ESP Firmware (REEF)
- F1 `[esp]` PlatformIO scaffold; board variants; PMIC drivers.
- F2 `[esp]` OTAA join; periodic telemetry; deep sleep.
- F3 `[esp]` Sensor drivers (temp/light/turbidity proxy); CBOR packer.
- F4 `[esp]` Low‑battery behaviors; brown‑out logging.

### EPIC G — Cloud (AEOLUS)
- G1 `[cloud]` EMQX/Mosquitto broker + TLS.
- G2 `[cloud]` FastAPI: device registry, config endpoints, signed commands.
- G3 `[cloud]` Timescale/Influx schema; retention; MinIO for media.
- G4 `[ui]` Next.js dashboard: sites map, device cards, killswitch, audio panel.
- G5 `[ops]` Log pipeline (Vector→Loki) + alert hooks.

### EPIC H — Safety, Compliance & Field Ops
- H1 `[safety]` SPL calibration doc + limiter verification test.
- H2 `[ops]` Field runbooks: install, bootstrapping, troubleshooting, recovery.
- H3 `[legal]` PATENTS.md template; IP capture doc; compliance checklist.

---

## 18) Definition of Done (per component)
- **Code**: linted, typed, unit‑tested (≥80% critical paths).
- **Docs**: README in each app; wiring & config examples.
- **Ops**: container image built; healthcheck passes; graceful shutdown.
- **Security**: no secrets in repo; TLS tested; kill‑switch tested.
- **Bench**: component demo script produces expected outputs on dev hardware.

---

## 19) Historical Example Configs (unsafe and superseded)

These snippets were never calibrated, authorized, or adopted. Frequency, gain, timing, and `spl_cap_db`/`max_rms`/`max_peak` values must not be used as acoustic design or safety limits.

**Site config** (`configs/sites/vrsar-reef.yml`):
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
          every: "0 */2 * * *"   # every 2 hours
          duration_s: 300
          gain_db: -12
      reactive:
        - name: dolphin-deterrent-A
          duration_s: 45
          gain_db: -8
vision:
  backend: edgetpu   # options: edgetpu|tensorrt|cpu
  motion_threshold: 0.6
  cooldown_s: 30
  lens_cleaning:
    every_min: 120
    sweep_ms: 1500
lorawan:
  ns: chirpstack
  dev_prefix: reef-esp
```

**Audio program** (`configs/programs/dolphin-deterrent-A.yml`):
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

---

## 20) Historical Bootstrap Sketch (not runnable as documented)

The referenced compose files and deployment templates did not exist when this PRD was superseded. Do not treat these commands as setup instructions.

```bash
# Hub (Pi) — first time
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# enable camera/I2C/PWM manually or via raspi-config

# Fetch compose
git clone git@github.com:intrface/poseidon.git
cd poseidon/ops/compose
sudo docker compose -f hub.dev.yml up -d

# Cloud (dev)
cd poseidon/ops/compose && docker compose -f cloud.dev.yml up -d
```

---

## 21) Historical Risk Register (superseded)
1. **Acoustic exposure**: a digital limiter does not prevent unsafe output. Current controls require physical inhibit, calibrated acoustic measures, permission, ecological review, and authorized tests.
2. **4G instability**: later field design needs bounded offline behavior and must not put safety in the cloud loop.
3. **Biofouling on lens**: cleaning effectiveness, scratch/jam risk, and service interval remain unverified.
4. **LoRaWAN coverage**: use an above-water gateway and measured link/airtime budget; no underwater or peer-mesh assumption.
5. **Power budget on ESP nodes**: loads, battery behavior, and worst-season solar reserve remain TBD.
6. **Model mismatch on hardware**: use CPU first and add an accelerator only after measurement.
7. **Moisture ingress**: an IP rating or coating alone does not prove the chosen pressure, immersion, corrosion, or service envelope.
8. **Underwater-sound regulation and permission**: configurable bands and documents are not authorization.
9. **Unintended fauna effects**: time windows and duty caps are not enough without evidence, non-target monitoring, and abort rules.
10. **Update failure**: production needs signed, wrong-target and rollback-protected updates with interruption and recovery tests.

---

## 22) Historical IP & Licensing Ideas (not adopted)
- **Repository**: no BUSL/MIT split or `PATENTS.md` was adopted by this PRD. No license, patent, ownership, freedom-to-operate, or commercial-use conclusion is made here.
- **Names**: the listed project codenames were not shown to be registered or legally available.
- **Invention ideas**: mentioning a program DSL or lens-cleaning feedback does not establish novelty, inventorship, ownership, or patentability.

---

## 23) Historical Build Order (superseded)

Do not follow the output-first sequence below. The current tranche is rebaseline plus offline passive replay; site/access evidence precedes field capture, and active audio remains gated.

1. Create monorepo scaffold + CI (EPIC A).
2. Implement **SIREN** minimal: play WAV from command + limiter (EPIC D1, D4).
3. Implement **NEREID** motion detector CPU baseline + event publish (EPIC C1–C2).
4. Wire **TRIDENT** to route vision→audio (reactive trigger) (EPIC B1–B3).
5. Stand up dev MQTT broker + basic UI page with live events (EPIC G1, G4 minimal).
6. Build **ESP sentinel** with battery + temp + light; CBOR uplink to ChirpStack dev (EPIC F1–F3).

---

## 24) Appendix — File/Service Stubs
- `apps/siren/main.py`: audio command worker, limiter, playlist.
- `apps/nereid/main.py`: camera loop, detector adapter (`edgetpu|tensorrt|cpu`).
- `apps/trident/main.py`: supervisor, config, router.
- `apps/aquilon/main.py`: LoRaWAN bridge (via MQTT from ChirpStack), topic mapper.
- `apps/aeolus-api/main.py`: FastAPI, /devices, /configs, /commands.
- `apps/aeolus-ui/`: Next.js with `/sites/:id` and live MQTT via websockets.
- `firmware/esp-sentinel/src/main.cpp`: OTAA join, read sensors, pack CBOR, uplink.

---

## 25) Glossary
- **EdgeTPU**: Coral accelerator for TFLite models.
- **TensorRT**: NVIDIA runtime for optimized inference.
- **CBOR**: compact binary JSON.
- **ADR**: Adaptive Data Rate (LoRaWAN).

---

**Repo name suggestion**: `poseidon-trident` (monorepo). Aliases inside the repo map to component codenames.

**Owner**: CEII (Alex) · **Maintainer**: Interface / Intrface Engineering.

