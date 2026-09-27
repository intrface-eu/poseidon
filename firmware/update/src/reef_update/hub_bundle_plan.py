"""Hub A/B bundle plan types. Host-only, plan-only, no bundle verifier.

ADR-0002 selects signed RAUC full-rootfs A/B bundles for the hub, as a paper
candidate pending the roadmap V7 interruption spike on real hardware. This
module describes the plan a hub update would follow and validates the parts a
host can validate: target compatibility, declared version identity, the
anti-rollback floor and slot selection.

It deliberately does NOT verify a RAUC bundle. RAUC bundle trust and the
existing ``poseidon.signed-manifest.v1`` Ed25519 control envelope are separate
validation gates over different artifacts; passing one proves nothing about the
other. There is no substitute verifier here, because a stand-in that returned
"verified" would be worse than an explicit refusal. ``verify_bundle`` and every
physical method refuse before producing any effect.

Nothing in this module downloads, writes, mounts, activates or reboots
anything.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Callable, Mapping, Sequence

from .model import Rejected, _integer

PLAN_SCHEMA = "poseidon.hub-update-plan.v1-candidate"
MECHANISM = "rauc-ab-full-rootfs"
DESCRIPTOR_SCHEMA = "poseidon.hub-bundle-descriptor.v1-candidate"
SLOTS = ("rootfs.0", "rootfs.1")
MAX_BUNDLE_BYTES = 4 * 1024 * 1024 * 1024

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

#: Everything that must be true before a hub bundle install may be attempted.
#: None of these is satisfied by this repository today.
PRECONDITIONS = (
    "a RAUC installation on the hub with its own trust store provisioned",
    "a hub signing key with a decided custody owner (ADR-0002 open item)",
    "a partition layout with two rootfs slots and a separate persistent data partition",
    "a bootloader that owns slot selection and the trial-boot counter",
    "an update source the hub is authorized to reach (ADR-0002 open item)",
    "the roadmap V7 interruption spike run on real hardware",
)


class PhysicalActionRefused(Rejected):
    """A method that would touch a real device, storage slot or power state."""


class MissingPrecondition(Rejected):
    """A capability ADR-0002 lists as undecided or absent."""


@dataclass(frozen=True)
class HubBundlePlan:
    """What a hub update would do. A description, never an instruction issued."""

    schema: str
    mechanism: str
    compatible: str
    version: str
    security_version: int
    bundle_sha256: str
    bundle_size: int
    active_slot: str
    target_slot: str
    security_floor_after_confirmation: int
    trial_boot_limit: int
    persistent_data_preserved: bool
    executable: bool
    refusal_reason: str

    def as_dict(self) -> dict:
        return asdict(self)


class HubBundlePlanner:
    """Builds a :class:`HubBundlePlan` and refuses to carry it out.

    ``fault`` receives a stage name at each interruption boundary named in
    ADR-0002 section 8 so a test can cut the sequence there. It is a test hook,
    not a power-loss measurement.
    """

    mechanism = MECHANISM
    preconditions = PRECONDITIONS

    def __init__(self, compatible: str, active_slot: str, *, security_floor: int,
                 trial_boot_limit: int = 3, max_bundle_bytes: int = MAX_BUNDLE_BYTES,
                 fault: Callable[[str], None] | None = None):
        if type(compatible) is not str or not _ID.fullmatch(compatible):
            raise Rejected("invalid hub compatible string")
        if active_slot not in SLOTS:
            raise Rejected("unknown active hub slot")
        self.compatible = compatible
        self.active_slot = active_slot
        self.security_floor = _integer(security_floor, 0, 0xFFFFFFFF, "hub security floor")
        self.trial_boot_limit = _integer(trial_boot_limit, 1, 16, "trial boot limit")
        self.max_bundle_bytes = _integer(max_bundle_bytes, 1, MAX_BUNDLE_BYTES, "hub bundle limit")
        self.fault = fault or (lambda _: None)

    def inactive_slot(self) -> str:
        return SLOTS[1] if self.active_slot == SLOTS[0] else SLOTS[0]

    def _descriptor(self, descriptor: Mapping[str, object]) -> dict:
        expected = {"schema", "target_kind", "compatible", "version", "security_version",
                    "bundle_sha256", "bundle_size"}
        if type(descriptor) is not dict or set(descriptor) != expected:
            raise Rejected("hub bundle descriptor fields")
        if descriptor["schema"] != DESCRIPTOR_SCHEMA:
            raise Rejected("wrong hub descriptor profile")
        if descriptor["target_kind"] != "hub":
            raise Rejected("descriptor does not target the hub")
        for name in ("compatible", "version"):
            value = descriptor[name]
            if type(value) is not str or not _ID.fullmatch(value):
                raise Rejected(f"invalid hub {name}")
        digest = descriptor["bundle_sha256"]
        if type(digest) is not str or not _SHA256.fullmatch(digest):
            raise Rejected("invalid hub bundle digest")
        _integer(descriptor["security_version"], 0, 0xFFFFFFFF, "hub security version")
        _integer(descriptor["bundle_size"], 1, self.max_bundle_bytes, "hub bundle size")
        return dict(descriptor)

    def plan(self, descriptor: Mapping[str, object]) -> HubBundlePlan:
        """Validate target, version identity and floor; return a refusing plan."""
        self.fault("before_verify")
        descriptor = self._descriptor(descriptor)
        # Target before anything else: a wrong-target bundle is refused even
        # when whatever signed it is otherwise trusted.
        if descriptor["compatible"] != self.compatible:
            raise Rejected("hub compatible mismatch")
        if descriptor["security_version"] < self.security_floor:
            raise Rejected("hub security downgrade")
        self.fault("after_verify")
        self.fault("before_slot_selection")
        target_slot = self.inactive_slot()
        self.fault("before_plan_emit")
        return HubBundlePlan(
            schema=PLAN_SCHEMA, mechanism=self.mechanism, compatible=self.compatible,
            version=str(descriptor["version"]), security_version=int(descriptor["security_version"]),
            bundle_sha256=str(descriptor["bundle_sha256"]), bundle_size=int(descriptor["bundle_size"]),
            active_slot=self.active_slot, target_slot=target_slot,
            # The floor advances at confirmation of a healthy boot, never at
            # download or staging, and never above a recoverable image.
            security_floor_after_confirmation=max(self.security_floor, int(descriptor["security_version"])),
            trial_boot_limit=self.trial_boot_limit, persistent_data_preserved=True,
            executable=False, refusal_reason=self.refusal_reason())

    @staticmethod
    def refusal_reason() -> str:
        return ("hub bundle installation is not implemented: RAUC native bundle verification, "
                "slot writing, bootloader slot selection and reboot are device capabilities "
                "this repository does not have (ADR-0002)")

    def verify_bundle(self, *_args: object, **_kwargs: object) -> None:
        """Refuse. RAUC bundle trust is a separate gate with no host stand-in."""
        raise MissingPrecondition(
            "RAUC bundle signature verification requires a provisioned RAUC trust store on "
            "the hub; the Ed25519 control envelope is a different gate over a different "
            "artifact and must not be used as a substitute")

    def download(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("no update source is hosted or authorized; nothing is fetched")

    def write_slot(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("writing a rootfs slot is refused; no slot device exists here")

    def activate_slot(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("bootloader slot selection is refused; the bootloader owns it")

    def reboot(self, *_args: object, **_kwargs: object) -> None:
        raise PhysicalActionRefused("reboot is refused; this is a host planning model")

    def unmet_preconditions(self) -> Sequence[str]:
        """Every precondition is unmet today; the list is the honest answer."""
        return self.preconditions
