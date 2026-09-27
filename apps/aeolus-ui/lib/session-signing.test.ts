import { describe, expect, test } from "bun:test";
import { createSessionSigner } from "./session-signing";

describe("browser-memory Ed25519 session custody", () => {
  test("exports only the public key and signs the supplied shared bytes", async () => {
    const signer = await createSessionSigner("synthetic-operator", "synthetic-key");
    try {
      expect(signer.publicKeyHex).toMatch(/^[a-f0-9]{64}$/);
      expect(Object.keys(signer).sort()).toEqual(["destroy", "keyId", "principalId", "publicKeyHex", "sign"]);
      const bytes = new TextEncoder().encode("Synthetic custody test bytes; protocol bytes come from the shared library.");
      const signature = Uint8Array.from(atob(await signer.sign(bytes)), (character) => character.charCodeAt(0));
      const publicKey = await crypto.subtle.importKey("raw", Uint8Array.from(signer.publicKeyHex.match(/../g)!, (byte) => parseInt(byte, 16)), "Ed25519", false, ["verify"]);
      expect(await crypto.subtle.verify("Ed25519", publicKey, signature, bytes)).toBe(true);
      expect(await crypto.subtle.verify("Ed25519", publicKey, signature, new Uint8Array([1]))).toBe(false);
      expect(JSON.stringify(signer)).not.toContain("private");
    } finally { signer.destroy(); }
  });
  test("clear drops signing authority and does not create a fallback", async () => {
    const signer = await createSessionSigner("synthetic-operator", "synthetic-clear-key");
    signer.destroy(); signer.destroy();
    await expect(signer.sign(new Uint8Array([0]))).rejects.toThrow("session signing key was cleared");
  });
  test("separate sessions generate distinct public keys", async () => {
    const first = await createSessionSigner("synthetic-operator", "synthetic-first");
    const second = await createSessionSigner("synthetic-operator", "synthetic-second");
    try { expect(first.publicKeyHex).not.toBe(second.publicKeyHex); }
    finally { first.destroy(); second.destroy(); }
  });
});
