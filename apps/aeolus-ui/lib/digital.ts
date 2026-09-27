import type { Identity } from "./platform";
import type { CommandAck, CommandKind, HubStateRead } from "../../../libs/proto-ts/src/command-v1";
export * from "../../../libs/proto-ts/src/command-v1";

// Presentation gates only; the server checks current role, key, scope and state again.
export function canOperate(identity: Identity): boolean {
  return identity.role === "operator" && identity.auth_mode === "scoped_token";
}
export function commandUnavailable(identity: Identity, hub: HubStateRead | null, kind: CommandKind): string | null {
  if (!canOperate(identity)) return "An explicit scoped operator is required. Admin is not operator.";
  if (!hub) return "Refresh the local hub state before signing.";
  if (!hub.binding) return "No explicit registered hub binding. No default target is selected.";
  if (!identity.site_ids.includes(hub.binding.site_id)) return "Your operator scope does not cover the bound hub site.";
  if (kind === "inhibit" && !["observe", "armed"].includes(hub.state)) return "Inhibit requires observe or armed; it cannot clear a fault.";
  if (kind === "resume" && hub.state !== "inhibited") return "Resume requires inhibited and returns only to observe.";
  if (kind === "rearm") {
    if (hub.state !== "observe") return "Rearm requires observe.";
    if (hub.watchdogs.length === 0 || hub.watchdogs.some((watchdog) => !watchdog.healthy)) return "Every watchdog must be healthy before rearm.";
  }
  if (kind === "clear-fault" && hub.state !== "fault") return "Clear fault requires fault and a server-recorded fault-alarm acknowledgement.";
  return null;
}
export const ACK_MEANINGS: Record<CommandAck["outcome"], string> = {
  accepted: "Accepted by the digital consumer; execution is not confirmed.",
  rejected: "Rejected. This acknowledgement does not report execution.",
  expired: "Expired. The command was not executed.",
  duplicate: "Exact valid retry. No second execution or transition.",
  executed: "Executed in local digital simulation only. No hardware action.",
  failed: "Digital execution failed. Acceptance consumed the sequence; this is not success.",
};
