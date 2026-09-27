"""REEF pull-transport plan types. Host-only, plan-only, no transfer.

ADR-0002 selects an authenticated local-maintenance HTTPS pull from an approved
local hub or maintenance-service endpoint into the inactive ESP-IDF OTA slot, as
a paper candidate pending the roadmap V7 interruption spike on real hardware.

This module builds that plan. Image authenticity and target checks reuse the
existing :class:`~reef_update.platform_manifest.PlatformImageVerifier`, which
verifies the ``poseidon.signed-manifest.v1`` Ed25519 envelope and enforces
target kind, hardware revision, expiry, the security floor, the authorization
sequence and the image digest. No second verifier is introduced.

Bulk image delivery over LoRaWAN is not the transport and is not modelled here.
The endpoint is checked against an allowlist before anything else, and every
physical method — fetch, slot write, boot-partition selection, reboot — refuses
before producing any effect.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Sequence
from urllib.parse import urlsplit

from .model import Rejected, _integer
from .platform_manifest import PlatformCandidate, PlatformImageVerifier, REFERENCE_SLOT_BYTES

PLAN_SCHEMA = "poseidon.reef-pull-plan.v1-candidate"
TRANSPORT = "https-local-maintenance-pull"
# firmware/reference/partitions-reference.csv
SLOTS = ("ota_0", "ota_1")


class PhysicalActionRefused(Rejected):
    """A method that would move bytes, write flash, select a slot or reboot."""


PRECONDITIONS = (
    "a maintenance network a technician is authorized to attach the node to (ADR-0002 open item)",
    "an update endpoint that is hosted and authenticated in both directions (ADR-0002 open item)",
    "a REEF signing key with a decided custody owner (ADR-0002 open item)",
    "a decided secure-boot / flash-encryption / eFuse anti-rollback policy (ADR-0002 open item)",
    "an on-device update agent, which does not exist and is not added here",
    "the roadmap V7 interruption spike run on real hardware",
)


def approved_endpoint(url: str, allowlist: Sequence[str]) -> str:
    """Return ``url`` when it is HTTPS and inside an allowlisted prefix.

    A hostname is not an authenticated peer. This check narrows where a node may
    look; the mutual authentication ADR-0002 requires is a device capability
    that does not exist yet.
    """
    if type(url) is not str or not 1 <= len(url) <= 512:
        raise Rejected("invalid update endpoint")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise Rejected("update endpoint must be https")
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise Rejected("update endpoint must not carry credentials")
    if parts.query or parts.fragment:
        raise Rejected("update endpoint must not carry a query or fragment")
    if ".." in parts.path.split("/"):
        raise Rejected("update endpoint path traversal")
    for prefix in allowlist:
        if type(prefix) is not str or not prefix.startswith("https://") or not prefix.endswith("/"):
            raise Rejected("invalid endpoint allowlist entry")
        if url.startswith(prefix):
            return url
    raise Rejected("update endpoint is not on the approved local maintenance allowlist")


@dataclass(frozen=True)
class EspPullPlan:
    """What a REEF node would fetch and where it would put it. Never executed."""

    schema: str
    transport: str
    endpoint: str
    board: str
    version: str
    security_version: int
    image_size: int
    image_sha256: str
    key_id: str
    active_slot: str
    target_slot: str
    slot_capacity_bytes: int
    security_floor_after_confirmation: int
    rollback_on_failed_trial: bool
    executable: bool
    refusal_reason: str

    def as_dict(self) -> dict:
        return asdict(self)


class EspPullPlanner:
    """Builds an :class:`EspPullPlan` from an already-held signed image.

    The image bytes are supplied by the caller. This planner never fetches them;
    it validates what a node would have to validate before touching a slot.

    ``fault`` receives a stage name at each interruption boundary named in
    ADR-0002 section 8 so a test can cut the sequence there.
    """

    transport = TRANSPORT
    preconditions = PRECONDITIONS

    def __init__(self, verifier: PlatformImageVerifier, endpoint_allowlist: Sequence[str],
                 active_slot: str, *, slot_capacity_bytes: int = REFERENCE_SLOT_BYTES,
                 fault: Callable[[str], None] | None = None):
        if not isinstance(verifier, PlatformImageVerifier):
            raise Rejected("REEF authenticity requires the approved platform verifier")
        if active_slot not in SLOTS:
            raise Rejected("unknown active REEF slot")
        allowlist = tuple(endpoint_allowlist)
        if not 1 <= len(allowlist) <= 8:
            raise Rejected("endpoint allowlist size")
        for prefix in allowlist:
            if type(prefix) is not str or not prefix.startswith("https://") or not prefix.endswith("/"):
                raise Rejected("invalid endpoint allowlist entry")
        self.verifier = verifier
        self.allowlist = allowlist
        self.active_slot = active_slot
        self.slot_capacity_bytes = _integer(slot_capacity_bytes, 1, REFERENCE_SLOT_BYTES, "slot capacity")
        self.fault = fault or (lambda _: None)

    def inactive_slot(self) -> str:
        return SLOTS[1] if self.active_slot == SLOTS[0] else SLOTS[0]

    def plan(self, endpoint: str, envelope: bytes, image: bytes, *, now: int | None,
             security_floor: int, current_version: str, last_command_id: int,
             current_digest: str | None) -> EspPullPlan:
        endpoint = approved_endpoint(endpoint, self.allowlist)
        self.fault("before_verify")
        # Signature, target kind, hardware revision, expiry, floor, sequence and
        # image digest are all enforced by the existing verifier.
        candidate: PlatformCandidate = self.verifier.verify(
            envelope, b"", image, now=now, security_floor=security_floor,
            current_version=current_version, last_command_id=last_command_id,
            current_digest=current_digest)
        self.fault("after_verify")
        if candidate.image_size > self.slot_capacity_bytes:
            raise Rejected("image exceeds the inactive OTA slot")
        self.fault("before_slot_selection")
        target_slot = self.inactive_slot()
        self.fault("before_plan_emit")
        return EspPullPlan(
            schema=PLAN_SCHEMA, transport=self.transport, endpoint=endpoint,
            board=candidate.board, version=candidate.version,
            security_version=candidate.security_version, image_size=candidate.image_size,
            image_sha256=candidate.image_sha256, key_id=candidate.key_id,
            active_slot=self.active_slot, target_slot=target_slot,
            slot_capacity_bytes=self.slot_capacity_bytes,
            # Floor advancement follows a confirmed healthy boot, not a download.
            security_floor_after_confirmation=max(security_floor, candidate.security_version),
            rollback_on_failed_trial=True, executable=False,
            refusal_reason=self.refusal_reason())

    @staticmethod
    def refusal_reason() -> str:
        return ("REEF image transfer is not implemented: no update agent, no hosted endpoint, "
                "no maintenance network and no flash write path exist in this repository "
                "(ADR-0002)")

    def fetch(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("no endpoint is hosted or authorized; nothing is fetched")

    def write_slot(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("writing an OTA slot is refused; no flash device exists here")

    def set_boot_partition(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("boot-partition selection is refused; the bootloader owns it")

    def reboot(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("reboot is refused; this is a host planning model")

    def unmet_preconditions(self) -> Sequence[str]:
        return self.preconditions
