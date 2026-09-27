"use client";

import { useEffect, useRef, useState } from "react";
import type { ApiPage } from "@/lib/api-types";
import { apiRequest, jsonRequest } from "@/lib/client-api";
import { PLATFORM_API, type Identity } from "@/lib/platform";
import { ACK_MEANINGS, canOperate, canonicalJson, commandUnavailable, parseCommand, parseCommandAck, signingBytes, uint64, type Command, type CommandAck, type CommandContext, type CommandKey, type CommandKind, type HubStateRead } from "@/lib/digital";
import { createSessionSigner, type SessionSigner } from "@/lib/session-signing";
import { Ledger, PageControls, RequestError } from "./PlatformCommon";
import { useDigitalResource as useResource } from "@/lib/use-digital-resource";

type StateCommand = Extract<CommandKind, "inhibit" | "resume" | "rearm" | "clear-fault">;
const ACTIONS: [StateCommand, string][] = [["inhibit", "Inhibit digital hub"], ["resume", "Resume to observe"], ["rearm", "Rearm digital hub"], ["clear-fault", "Clear acknowledged fault"]];

export function AckReceipt({ ack }: { ack: CommandAck }) {
  return <div className="inspection-block digital-ack" role="status" data-ack-outcome={ack.outcome}>
    <h3>Actual acknowledgement: {ack.outcome}</h3><p>{ACK_MEANINGS[ack.outcome]}</p>
    <Ledger rows={[["Command ID", ack.command_id], ["Device ID", ack.device_id], ["Reason", ack.reason], ["LOCAL DIGITAL state after", ack.state_after], ["Sequence seen (decimal text)", ack.sequence_seen], ["Received (UTC)", ack.received_at]]} />
  </div>;
}

export function DigitalCommands({ identity, hub, onChanged }: { identity: Identity; hub: HubStateRead | null; onChanged: () => void }) {
  const signer = useRef<SessionSigner | null>(null);
  const custodyEpoch = useRef(0);
  const [publicKey, setPublicKey] = useState<CommandKey | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmKind, setConfirmKind] = useState<StateCommand | null>(null);
  const [lastWire, setLastWire] = useState<string | null>(null);
  const [ack, setAck] = useState<CommandAck | null>(null);
  const target = hub?.binding;
  const operator = canOperate(identity);
  const inScope = Boolean(target && identity.site_ids.includes(target.site_id));

  function clearCustody() {
    custodyEpoch.current++;
    signer.current?.destroy(); signer.current = null;
    setPublicKey(null); setConfirmKind(null); setLastWire(null);
  }
  useEffect(() => {
    const clear = () => { clearCustody(); setMessage("Session signing key cleared. Public registry enrollment remains until revoked."); };
    window.addEventListener("pagehide", clear);
    return () => { window.removeEventListener("pagehide", clear); custodyEpoch.current++; signer.current?.destroy(); signer.current = null; };
  }, []);

  async function enroll() {
    if (!operator || !target || !inScope || pending) return;
    setPending(true); setError(null); setMessage(null);
    const epoch = custodyEpoch.current;
    let next: SessionSigner | null = null;
    try {
      const context = await apiRequest<CommandContext>(`${PLATFORM_API}/command-context/${encodeURIComponent(target.device_id)}`);
      if (context.device_id !== target.device_id) throw new Error("Command context does not match the explicit hub target.");
      next = await createSessionSigner(context.principal_id, `session-${crypto.randomUUID()}`);
      const registered = await apiRequest<CommandKey>(`${PLATFORM_API}/command-keys`, jsonRequest("POST", { key_id: next.keyId, principal_id: next.principalId, public_key_hex: next.publicKeyHex }));
      if (custodyEpoch.current !== epoch) { next.destroy(); return; }
      if (registered.key_id !== next.keyId || registered.principal_id !== next.principalId || registered.public_key_hex !== next.publicKeyHex || registered.revoked_at) throw new Error("Public-key enrollment did not match this session. No signing authority retained.");
      signer.current?.destroy(); signer.current = next; setPublicKey(registered);
      setMessage("Session key enrolled. Only its public key went to the API. Reloading, locking or leaving this section drops the private key.");
    } catch (caught) { next?.destroy(); setError(caught instanceof Error ? caught.message : "Key enrollment failed. No unsigned fallback is available."); }
    finally { setPending(false); }
  }
  async function revoke() {
    if (!publicKey || pending) return;
    setPending(true); setError(null);
    try {
      await apiRequest(`${PLATFORM_API}/command-keys/${encodeURIComponent(publicKey.key_id)}/revoke`, { method: "POST" });
      clearCustody(); setMessage("Public key revoked by the API and session private key dropped.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Key revocation failed; refresh the registry before relying on revocation."); }
    finally { setPending(false); }
  }
  async function postWire(wire: string) {
    const command = parseCommand(wire);
    const received = parseCommandAck(await apiRequest<unknown>(`${PLATFORM_API}/commands`, { method: "POST", headers: { "content-type": "application/json" }, body: wire }));
    if (received.command_id !== command.command_id || received.device_id !== command.device_id) throw new Error("Acknowledgement did not match the submitted command. Execution remains unknown.");
    setAck(received); onChanged();
  }
  async function send(kind: StateCommand) {
    const activeSigner = signer.current;
    if (!activeSigner || !target || pending) return;
    const unavailable = commandUnavailable(identity, hub, kind);
    if (unavailable) { setError(unavailable); return; }
    setPending(true); setError(null); setAck(null); setConfirmKind(null);
    try {
      const context = await apiRequest<CommandContext>(`${PLATFORM_API}/command-context/${encodeURIComponent(target.device_id)}`);
      if (context.principal_id !== activeSigner.principalId || context.device_id !== target.device_id || !context.allowed_kinds.includes(kind)) throw new Error("Current operator context does not permit this command and explicit target.");
      const sequence = uint64((BigInt(uint64(context.sequence_seen)) + 1n).toString());
      const now = Date.now();
      const payload: Omit<Command, "signature"> = { schema_version: "poseidon.command.v1", command_id: crypto.randomUUID(), site_id: target.site_id, zone_id: target.zone_id, device_id: target.device_id, principal_id: activeSigner.principalId, key_id: activeSigner.keyId, sequence, issued_at: new Date(now).toISOString(), expires_at: new Date(now + 120_000).toISOString(), kind, params: {} };
      const signature = { algorithm: "Ed25519" as const, canonicalization: "poseidon-json-v1" as const, value: await activeSigner.sign(signingBytes(payload, activeSigner.keyId)) };
      const wire = canonicalJson(parseCommand({ ...payload, signature }));
      setLastWire(wire); // Preserve exact bytes for transport-unknown/duplicate retry; no private key.
      await postWire(wire);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No acknowledgement received. Execution is unknown; retry the exact signed bytes, not a new command."); }
    finally { setPending(false); }
  }
  async function retryExact() {
    if (!lastWire || pending) return;
    setPending(true); setError(null); setAck(null);
    try { await postWire(lastWire); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "No matching acknowledgement received. Execution remains unknown."); }
    finally { setPending(false); }
  }
  return <section className="platform-panel" aria-labelledby="digital-commands-title"><header className="platform-heading"><div><h2 id="digital-commands-title">Signed local state commands</h2><p>Explicit scoped operator only. Admin never implicitly rearms. Inhibit cannot clear fault; resume never arms.</p></div></header>
    <div className="inspection-block"><h3>Browser-session signing custody</h3><p className="platform-note">Ed25519 private key: non-extractable browser memory only. No private-key input, export, server generation or persistence. This is not production key custody.</p>
      {!operator ? <p>An explicit scoped operator is required. Provision that role under Identity & access, then unlock with its token.</p> : !target ? <p>No registered hub binding is available. An admin must explicitly enroll a hub profile and bind that identity first.</p> : !inScope ? <p>Your operator scope does not include this hub site.</p> : null}
      {publicKey ? <><Ledger rows={[["Principal ID", publicKey.principal_id], ["Public key ID", publicKey.key_id], ["Ed25519 public key", publicKey.public_key_hex], ["Scope", publicKey.site_ids.join(", ")]]} /><div className="conflict-actions"><button className="button secondary" type="button" disabled={pending} onClick={() => { clearCustody(); setMessage("Private key dropped from this browser session. The enrolled public key remains active until revoked."); }}>Drop session signing key</button><button className="button secondary" type="button" disabled={pending} onClick={() => void revoke()}>Revoke session public key</button></div></> : <button type="button" className="button secondary" disabled={!operator || !target || !inScope || pending} onClick={() => void enroll()}>{pending ? "Enrolling session key…" : "Create and enroll session signing key"}</button>}
      {message ? <p role="status">{message}</p> : null}<RequestError message={error} />
    </div>
    <div className="inspection-block"><h3>Explicit command target</h3><Ledger rows={[["Registered hub", target?.device_id ?? "No target"], ["Bound site", target?.site_id ?? "No site"], ["Bound zone", target?.zone_id ?? "No zone"]]} />
      <div className="digital-command-actions">{ACTIONS.map(([kind, label]) => { const reason = commandUnavailable(identity, hub, kind); return <div key={kind}><button type="button" className="button secondary" disabled={Boolean(reason) || !publicKey || pending} aria-describedby={`command-${kind}-reason`} onClick={() => { setConfirmKind(kind); setError(null); }}>{label}</button><p className="platform-note" id={`command-${kind}-reason`}>{reason ?? (!publicKey ? "Enroll a session signing key first." : kind === "clear-fault" ? "Server requires all fault alarms acknowledged first." : "Signs a local digital transition only.")}</p></div>; })}</div>
      {confirmKind ? <section className="inline-message" aria-label="Confirm local digital command"><strong>Confirm {confirmKind} for {target?.device_id}</strong><span>This signs a two-minute K1 command for the exact site and zone above. The API can still reject or fail it. No hardware action or output is authorized.</span><div className="conflict-actions"><button type="button" className="button primary" disabled={pending} onClick={() => void send(confirmKind)}>Sign and submit {confirmKind}</button><button type="button" className="button secondary" onClick={() => setConfirmKind(null)}>Cancel command</button></div></section> : null}
      {pending ? <p role="status">Waiting for the actual API acknowledgement or key response…</p> : null}
      {lastWire ? <><p className="platform-note">A transport error does not prove non-execution. Retry preserves the command ID, signature and exact request bytes; current expiry, role and key checks still apply.</p><button type="button" className="button secondary" disabled={pending || !operator} onClick={() => void retryExact()}>Retry exact signed command</button></> : null}
    </div>{ack ? <AckReceipt ack={ack} /> : null}
  </section>;
}

export function CommandHistory({ version }: { version: number }) {
  const [offset, setOffset] = useState(0);
  const history = useResource<ApiPage<{ command: Command; ack: CommandAck }>>(`${PLATFORM_API}/commands?limit=10&offset=${offset}`, version);
  return <section className="platform-panel" aria-labelledby="command-history-title"><header className="platform-heading"><div><h2 id="command-history-title">Command acknowledgement records</h2><p>Stored command outcomes, not inferred completion. Sequence counters remain exact decimal text.</p></div></header><div className="inspection-block"><RequestError message={history.error} retry={history.reload} />{history.loading ? <p role="status">Refreshing command records…</p> : null}{history.data?.items.length === 0 ? <p className="list-empty">No command records in this scope.</p> : null}{history.data?.items.map(({ command, ack }) => <details key={command.command_id} className="data-table-disclosure"><summary>{command.kind} · {ack.outcome} · {command.device_id} · sequence {command.sequence}</summary><AckReceipt ack={ack} /></details>)}<PageControls page={history.data} onPage={setOffset} loading={history.loading} /></div></section>;
}
