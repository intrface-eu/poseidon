# ADR-0002: Hub and REEF update mechanisms

- Status: Accepted as a paper selection; both mechanisms are candidates until the hardware spike below runs
- Date: 2026-09-08
- Decision owners: unassigned (see "Open items"); proposed by the firmware lead, accepted by the campaign root for planning only
- Requirement: [REQ-SEC-001](../requirements/production-requirements.md)
- Gate: production roadmap gate **V7, OTA/security/recovery**
- Supersedes nothing. Extends [ADR-0001](0001-passive-first-system-boundary.md), which forbids field, radio and flash activity in this tranche.

## Context

The hub is a Linux ARM64 machine that runs the Python control stack, a journal on local storage and a web API. The REEF node is an ESP32 with a 4 MiB flash layout that already carries two equal OTA slots and `otadata`, and a compile-only reference that binds the ESP-IDF rollback API without calling it. `firmware/update` holds a host model of signed-image verification, A/B staging, trial boot, confirmation and rollback; it is a reference model on the laptop, not an agent on a device. Nothing in the repository downloads, writes or activates an image.

Two questions have to be answered before anyone writes an update agent: how a whole hub is replaced and rolled back, and how a REEF image reaches the inactive slot. Answering them late tends to force the answer that the first shipped script happens to imply, which is usually an in-place `git pull`.

No hardware, no network service and no key custody exists yet, so this ADR selects on paper only. Nothing here is a measurement, and nothing here authorizes flashing, hosting, purchasing or field work.

## Decision

### 1. Hub: signed RAUC bundles into a full-rootfs A/B pair

The hub update unit is a full root filesystem image delivered as a signed RAUC bundle. Two rootfs slots exist; the bundle is written to the inactive one. The bootloader selects the slot and owns the trial-boot counter. A newly written slot boots on trial; the hub confirms it only after the control stack reaches a healthy state, and an unconfirmed trial reverts to the previous slot on the next boot without an operator present.

Persistent application data — the journal, captured media, configuration, credentials and logs — lives on a separate data partition that no bundle overwrites. A bundle replaces code and system packages; it never replaces the data partition.

A bundle is installable only after signature verification against the hub trust store, and after the bundle's compatible string, version and security version pass the checks in section 3. Slot activation happens after those checks, never before.

### 2. REEF: authenticated local-maintenance HTTPS pull into the inactive OTA slot

A REEF node fetches its image over HTTPS from an approved local hub or maintenance-service endpoint, on a maintenance network reachable only during service. The node authenticates the endpoint and the endpoint authenticates the node; an unauthenticated or non-allowlisted endpoint is refused before any byte is fetched. The image is written to the inactive ESP-IDF OTA slot, verified there, marked bootable, and boots on trial with the ESP-IDF rollback flag set. The application marks itself valid only after its own health checks pass; otherwise the bootloader returns to the previous slot.

The node pulls. Nothing pushes an image to a node, and a node never opens an update session by itself outside a maintenance window.

### 3. Checks that must pass before any slot activation, on both sides

In this order, and all of them:

1. **Signature.** The image or bundle carries a signature that verifies against a trust store already on the device. A manifest that only parses is not authenticated; schema validation proves shape, not provenance.
2. **Target.** The declared target kind and hardware revision (REEF) or compatible string (hub) match the running device. A wrong-target image is refused even when its signature is valid.
3. **Version identity.** The declared version and the declared artifact digest match the bytes actually received; size and digest are checked against the received image, not against the manifest's own claim about itself.
4. **Anti-rollback.** The declared security version is at or above the device's stored security floor, and the authorization sequence is above the last accepted one.

Only then may the slot be written and marked bootable. A device that fails any check keeps running its current image and reports the refusal.

### 4. Rollback, the security floor and the known-good image

A failed trial boot falls back automatically to the last known-good image. Fallback is a bootloader property on both sides, not an operator procedure and not a script that has to survive the failure it is reacting to.

The security floor advances only when a recoverable image at or above the new floor still exists on the device. Raising the floor above every image the device can boot converts a rollback into a brick, so floor advancement is a consequence of a confirmed healthy boot, never of a download or a staged write. The host model in `firmware/update` already advances the floor at confirmation and not at staging; that ordering is the requirement, not an implementation detail.

### 5. RAUC bundle trust and the Ed25519 control envelope are separate gates

The repository already has `poseidon.signed-manifest.v1`, an Ed25519 envelope with a domain-separated signing input, used for control-plane authorization of an update. RAUC verifies its own bundle with its own native signature format and its own trust store. These are two independent gates over two different artifacts. Passing one says nothing about the other, and no code may treat a valid control envelope as evidence that a bundle is trustworthy, or the reverse. If both are used, both are checked, and the relation between the two key sets is an explicit custody decision that has not been made.

The interface stubs in `firmware/update/src/reef_update/hub_bundle_plan.py` therefore refuse to verify a RAUC bundle rather than approximating it with the Ed25519 verifier. There is no pretend hub verifier in this repository.

### 6. LoRaWAN does not carry images

Bulk image delivery over LoRaWAN is not the transport, on either side. LoRaWAN remains a small, slow, duty-cycle-limited telemetry and command link. It may carry a notification that an update is available or an acknowledgement that one was applied; it never carries the image.

### 7. Data and filesystem migration

Persisted documents carry `schema_version`, and migrations are pure functions in a registry keyed by (from, to). An update that changes a document format ships the migration that reads the old format. Rollback compatibility follows from that: after a rollback the previous code reads data that the newer code may have rewritten, so a migration that cannot be read by the immediately previous release is a breaking change and needs its own decision, its own fixture and its own recovery path. Until such a decision exists, updates must keep persisted documents readable by the previous release.

The data partition is never reformatted by an update. Media and journal deletion happens through the retention path with its own audit record, never as an update side effect.

### 8. Power-cut boundaries, stated as requirements

These are requirements with test hooks, not measured results. Nothing below has been observed on hardware.

- Interruption at any point of a download leaves the running image untouched. A partial download is discarded, not resumed into an activation.
- Interruption while writing the inactive slot leaves the active slot and its boot selection unchanged. A half-written inactive slot must never be selectable.
- Interruption between "slot written" and "slot marked bootable" resolves to the old slot.
- Interruption during the trial boot, before confirmation, resolves to the previous known-good image on the next boot.
- Interruption after confirmation resolves to the new image, with the security floor already advanced.
- The persistent data partition survives every one of these cases; a torn write in application data is a journal recovery problem, not an update problem, and is handled by the existing commit boundaries.

The host models expose fault-injection hooks at these boundaries (`before_state_write`, `before_commit`, `after_image_write` in the boot store; `before_verify`, `after_verify`, `before_slot_selection`, `before_plan_emit` in the new plan stubs) so a test can cut power at each point in the model. Passing those tests is not evidence about real flash, real bootloaders or real brownouts.

### 9. Code consequence for this tranche

Interface and plan types with tests only. `hub_bundle_plan.py` describes a bundle plan, validates target and floor, states its preconditions and refuses execution. `esp_transport_plan.py` describes a pull plan, validates the endpoint against an allowlist and reuses the existing `PlatformImageVerifier` for REEF image authenticity and target checks. On both, the physical methods — download, flash, slot switch, reboot — refuse before doing anything. No on-device update agent is added, and no C++ target source changes.

### 10. The legacy device-config path is not bridged to the K1 ack

`ConfigurationController` in `firmware/update/src/reef_update/model.py` applies a private 21-byte downlink whose `interval_s` is a physical sampling period bounded to 60..86400 seconds. K1's `config-apply` carries a digital control document whose `health_interval_s` is bounded to 1..3600 seconds. The two fields have different units of meaning, different ranges and different owners; mapping one onto the other would silently reinterpret a sampling policy as a health-reporting policy, and the ranges do not even overlap cleanly.

The K1 acknowledgement formatter added in `firmware/reef/host/reef_config_ack.py` therefore refuses that bridge explicitly, and the legacy controller is left exactly as it is. A device that must serve both will need an authorized mapping decision with its own fixtures; it does not get one by default.

## Rejected options

- **In-place `pip install -U`, `bun install` or `git pull` on the hub.** There is no single artifact to sign, no atomic boundary, and a failed run leaves a machine in a state that is neither the old nor the new release. Rollback would mean reconstructing an environment from a package index that may have moved. Rejected as the fleet mechanism; these remain fine for a developer laptop.
- **Containers alone as the whole-system rollback.** Containers version the application, not the kernel, bootloader, device tree, drivers or system packages, and a container runtime cannot roll back the machine it runs on. They may sit inside a rootfs image later; they do not answer this question.
- **Delta or differential image delivery.** A delta requires an exact known source image, adds a second failure mode when the source is not what the delta assumed, and buys bandwidth we do not need on a maintenance network. Rejected for now; a full image is verifiable against a single digest.
- **Image delivery over LoRaWAN.** Duty cycle, payload size and airtime make bulk delivery impractical, and it would put the update path on the least controllable link. Rejected outright, not deferred.
- **Serial-only flashing as the fleet mechanism.** It requires physical access to every node for every update and gives no unattended rollback. Rejected as the mechanism. Serial flashing stays available as a separately authorized recovery path for a node that cannot be recovered over the network, under its own authorization.

## Consequences

- Update code can be written against two named mechanisms instead of being invented per script.
- The hub needs a partition layout with two rootfs slots and a separate data partition before its first release image; changing that later means reflashing every hub.
- The REEF image budget is bounded by one OTA slot (`0x1F0000` in the current reference table), and image growth has to be tracked against that number from now on.
- Two signing key sets are implied, hub and REEF, with no custody decision behind either. That is the largest unfunded gap this ADR creates.
- The V7 gate now has concrete things to test: the interruption points in section 8, the refusal cases in section 3, and the floor rule in section 4.

## Confirmation condition

Both mechanisms are selected on paper. They are confirmed or replaced after the rollback and power-cut interruption spike on real hardware at gate V7: a hub with the real bootloader and RAUC, and a REEF node with the real ESP-IDF rollback path, interrupted at each boundary in section 8. If that spike shows either mechanism cannot recover a device without physical access, this ADR is replaced rather than amended.

## Open items

No owner is assigned to any of these, and none may be assumed.

- **Signing key custody.** Who holds the hub bundle key and the REEF image key, where they live, how they are rotated, and what happens after a compromise. Not decided.
- **Update server hosting.** Where a bundle or image is served from, who runs that service, and how it is reachable from a farm site. Not decided; nothing is hosted today.
- **Maintenance-network access.** How a service technician gets a node onto the maintenance network, and how that access is authenticated and revoked. Not decided.
- **Secure boot and eFuse policy.** Whether ESP32 secure boot, flash encryption and fuse-based anti-rollback are enabled. All three are disabled in the current compile reference. Burning fuses is irreversible per device and needs its own decision. Not decided.
- **Physical qualification.** Brownout behaviour, flash wear, real trial-boot timing, real bootloader behaviour, and the update matrix's statistical success measurement. Nothing in this ADR has been observed on hardware.

This ADR authorizes no flashing, no upload, no hosting, no key generation, no purchase and no field activity.
