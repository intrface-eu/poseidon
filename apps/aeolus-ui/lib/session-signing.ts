// Session custody only. The private CryptoKey never leaves this closure.
export type SessionSigner = {
  principalId: string;
  keyId: string;
  publicKeyHex: string;
  sign: (sharedSigningBytes: Uint8Array) => Promise<string>;
  destroy: () => void;
};

export async function createSessionSigner(principalId: string, keyId: string): Promise<SessionSigner> {
  if (!globalThis.crypto?.subtle) throw new Error("This browser cannot create a local Ed25519 signing key. No unsigned fallback is available.");
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"]);
  let privateKey: CryptoKey | null = pair.privateKey;
  const publicBytes = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  const publicKeyHex = Array.from(publicBytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return {
    principalId, keyId, publicKeyHex,
    async sign(sharedSigningBytes) {
      if (!privateKey) throw new Error("The session signing key was cleared. Create and enroll a new key.");
      const signature = new Uint8Array(await crypto.subtle.sign("Ed25519", privateKey, Uint8Array.from(sharedSigningBytes)));
      // A signature is public; the non-extractable private key is never encoded.
      return btoa(String.fromCharCode(...signature));
    },
    destroy() { privateKey = null; },
  };
}
