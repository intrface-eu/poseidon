"""Host-side K1 acknowledgement formatter for `config-apply`. No device I/O.

`poseidon.command-ack.v1` is the canonical acknowledgement format. This module
formats exactly that and nothing else: there is no second wire format, no
legacy-shaped variant, and no choice between formats at runtime.

What this module does:

* build an acknowledgement only from complete, caller-supplied trusted context;
* accept a configuration document only through
  ``poseidon_proto.config_migrations.migrate_config``;
* validate its own output with ``poseidon_proto.command.parse_command_ack``
  before returning it.

What this module does not do, by decision:

* It does not dispatch, publish, retry, deduplicate, or remember sequences.
  There is no replay window and no key store here.
* It does not authenticate anything. ``parse_command`` and ``parse_command_ack``
  check shape, not provenance; a document that parses is not a document that was
  signed by anyone in particular. Nothing in this module may be read as evidence
  of authentication.
* It does not bridge the legacy 21-byte REEF device-config downlink to K1. See
  :func:`bridge_legacy_configuration`.

This module is imported by full path from ``firmware/reef/host``; it adds no
package and changes no frozen input. It is a host formatter, not firmware.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from poseidon_proto.command import ID, OUTCOMES, UTC, UUID4, parse_command, parse_command_ack
from poseidon_proto.config_migrations import migrate_config

ACK_SCHEMA_VERSION = "poseidon.command-ack.v1"
COMMAND_KIND = "config-apply"

#: `emit` is representable in the shared state enum and is never a valid ack
#: state; ADR-0001 and the K2 brief keep it unreachable.
ACK_STATES = ("observe", "armed", "inhibited", "fault")
#: Outcomes that assert a configuration document was understood and applied.
CONFIG_REQUIRED_OUTCOMES = ("accepted", "executed")

_UUID4 = re.compile(UUID4["pattern"])
_ID = re.compile(ID["pattern"])
_UTC = re.compile(UTC["pattern"])
_UINT64_TEXT = re.compile(r"(0|[1-9][0-9]{0,19})\Z")
_UINT64_MAX = 2**64 - 1
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class AckRefused(ValueError):
    """Context or configuration that must not become an acknowledgement."""


def _text(value: object, name: str) -> str:
    if type(value) is not str:
        raise AckRefused(f"{name} must be text, and must come from trusted context")
    return value


@dataclass(frozen=True)
class AckContext:
    """The complete trusted context an acknowledgement needs.

    Every field is required. Nothing is defaulted, inferred, or filled in from a
    clock, a hostname or a counter held by this module: an acknowledgement that
    invents part of its own context is not an acknowledgement of anything.

    * ``command_id`` — UUID4 text, copied from the command being acknowledged.
    * ``device_id`` — the acknowledging device's registry identity.
    * ``received_at`` — when the command was received, UTC with a ``Z`` suffix.
    * ``outcome`` — one of ``poseidon_proto.command.OUTCOMES``.
    * ``reason`` — a non-empty single-line explanation, at most 256 characters.
    * ``state_after`` — hub state after handling, from :data:`ACK_STATES`.
    * ``sequence_seen`` — uint64 as canonical decimal text, never an integer.
    """

    command_id: str
    device_id: str
    received_at: str
    outcome: str
    reason: str
    state_after: str
    sequence_seen: str

    def __post_init__(self) -> None:
        if not _UUID4.fullmatch(_text(self.command_id, "command_id")):
            raise AckRefused("command_id must be UUID4 text copied from the command")
        if not _ID.fullmatch(_text(self.device_id, "device_id")):
            raise AckRefused("device_id must be a registry identity")
        if not _UTC.fullmatch(_text(self.received_at, "received_at")):
            raise AckRefused("received_at must be UTC text ending in Z")
        if _text(self.outcome, "outcome") not in OUTCOMES:
            raise AckRefused("outcome is not in the closed acknowledgement enum")
        reason = _text(self.reason, "reason")
        if not 1 <= len(reason) <= 256:
            raise AckRefused("reason must be non-empty and at most 256 characters")
        if _CONTROL.search(reason):
            raise AckRefused("reason must not contain control characters")
        if _text(self.state_after, "state_after") not in ACK_STATES:
            raise AckRefused("state_after must be observe, armed, inhibited or fault")
        sequence = _text(self.sequence_seen, "sequence_seen")
        if not _UINT64_TEXT.fullmatch(sequence):
            raise AckRefused("sequence_seen must be canonical uint64 decimal text")
        if int(sequence) > _UINT64_MAX:
            raise AckRefused("sequence_seen exceeds uint64")


def format_config_apply_ack(context: AckContext, *, config: dict | None,
                            retained: bool = False) -> dict:
    """Return the canonical `poseidon.command-ack.v1` document for a config-apply.

    ``config`` is the ``params.config`` document from the command. When the
    outcome asserts the configuration was applied, it is required and must
    survive ``migrate_config``; a configuration this host cannot migrate cannot
    be acknowledged as accepted or executed. When the outcome is a refusal, a
    configuration may be absent, and any configuration that is supplied is still
    migrated rather than trusted.

    ``retained`` is passed through to the parser, which rejects a retained
    acknowledgement. Acks are never retained.
    """
    if not isinstance(context, AckContext):
        raise AckRefused("complete AckContext required; partial context is refused")
    if type(retained) is not bool:
        raise AckRefused("retained must be a boolean from the transport, not a payload field")
    if context.outcome in CONFIG_REQUIRED_OUTCOMES:
        if config is None:
            raise AckRefused(f"outcome {context.outcome!r} requires the configuration it applied")
        migrate_config(config)
    elif config is not None:
        migrate_config(config)
    document = {"schema_version": ACK_SCHEMA_VERSION, **asdict(context)}
    # The parser is the gate on the way out, not a formality: an ack this module
    # cannot re-parse is never returned.
    return parse_command_ack(document, retained=retained)


def ack_for_config_apply_command(command: dict | bytes | str, *, device_id: str,
                                 received_at: str, outcome: str, reason: str,
                                 state_after: str, retained: bool = False) -> dict:
    """Format an ack for a parsed `config-apply` command.

    ``command_id`` and ``sequence_seen`` are copied from the command, so they
    cannot drift from it. Parsing proves the command's shape and that its
    configuration migrates; it proves nothing about who signed it. Authentication
    happens before this call or not at all.
    """
    document = parse_command(command)
    if document["kind"] != COMMAND_KIND:
        raise AckRefused(f"this formatter acknowledges {COMMAND_KIND} only")
    if document["device_id"] != device_id:
        raise AckRefused("acknowledging device is not the command's target device")
    context = AckContext(command_id=document["command_id"], device_id=device_id,
                         received_at=received_at, outcome=outcome, reason=reason,
                         state_after=state_after, sequence_seen=document["sequence"])
    return format_config_apply_ack(context, config=document["params"]["config"], retained=retained)


def bridge_legacy_configuration(*_args: object, **_kwargs: object) -> None:
    """Refuse to map the legacy 21-byte device-config downlink onto K1.

    ``reef_update.model.ConfigurationController`` applies a private 21-byte
    downlink whose ``interval_s`` is a physical sampling period bounded to
    60..86400 seconds. K1 ``config-apply`` carries a digital control document
    whose ``health_interval_s`` is bounded to 1..3600 seconds. The two fields
    mean different things, their ranges barely overlap, and mapping one onto the
    other would silently reinterpret a sampling policy as a health-reporting
    policy.

    A device that must serve both needs an authorized mapping decision with its
    own fixtures. It does not get one by default. See ADR-0002 section 10.
    """
    raise AckRefused(
        "the legacy 21-byte device-config sample interval (60..86400 s) is not the K1 "
        "health_interval_s (1..3600 s); no bridge is authorized (ADR-0002 section 10)")
