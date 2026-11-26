import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { createNativeRdpAutologin } from "../src/pages/clientdetailspage/remotedesktop/nativeRdpAutologin.mjs";

const subtle = webcrypto.subtle;
const encoder = new TextEncoder();
const SESSION = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc";
const id = () => "73a81005-99cc-4efa-9f7c-9e82e82f2fa9";

function b64url(bytes) {
  return Buffer.from(bytes).toString("base64url");
}
function unb64url(text) {
  return Uint8Array.from(Buffer.from(text, "base64url"));
}
async function sealed(request, options = {}) {
  const pair = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const browserPublic = await subtle.importKey(
    "raw", unb64url(request.public_key), { name: "ECDH", namedCurve: "P-256" }, false, []
  );
  const shared = await subtle.deriveBits({ name: "ECDH", public: browserPublic }, pair.privateKey, 256);
  const source = await subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
  const salt = webcrypto.getRandomValues(new Uint8Array(16));
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const info = encoder.encode(`planiq-clientflow-rdp-v1|${SESSION}|${request.request_id}`);
  const aad = encoder.encode(`planiq-clientflow-rdp-v1|${options.clientId ?? 3}|${SESSION}|${request.request_id}`);
  const key = await subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt, info }, source,
    { name: "AES-GCM", length: 256 }, false, ["encrypt"]
  );
  const expires = Math.floor(Date.now() / 1000) + 40;
  const payload = {
    username: "cfpilotabcdef12",
    password: "a".repeat(42),
    fingerprint: "ab".repeat(32),
    expires_unix: expires,
  };
  const ciphertext = await subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: aad, tagLength: 128 },
    key, encoder.encode(JSON.stringify(payload))
  );
  return {
    schema: 1, session_id: SESSION, request_id: request.request_id,
    public_key: b64url(await subtle.exportKey("raw", pair.publicKey)),
    salt: b64url(salt), nonce: b64url(iv), ciphertext: b64url(ciphertext),
    expires_unix: options.expires_unix ?? expires,
  };
}

test("63D-49 ECDH one-time GNOME login decrypts in requesting browser only", async () => {
  const handle = await createNativeRdpAutologin(SESSION, 3, subtle, id);
  assert.deepEqual(Object.keys(handle.request).sort(), ["public_key", "request_id", "type"]);
  assert.equal(handle.request.type, "native_rdp_autologin_request");
  const envelope = await sealed(handle.request);
  const login = await handle.open(envelope);
  assert.deepEqual(login, {
    username: "cfpilotabcdef12",
    password: "a".repeat(42),
    fingerprint: Array.from({length:32}, () => "ab").join(":"),
  });
  await assert.rejects(handle.open(envelope), /kun bruges én gang/);
});

test("63D-49 fails closed on wrong session, challenge, expiry and tampering", async () => {
  for (const modify of [
    (x) => { x.request_id = "73a81005-99cc-4efa-9f7c-9e82e82f2fa8"; },
    (x) => { x.session_id = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bd"; },
    (x) => { x.expires_unix = Math.floor(Date.now()/1000) - 1; },
    (x) => { x.expires_unix = Math.floor(Date.now()/1000) + 120; },
    (x) => { x.ciphertext = x.ciphertext.slice(0, -3) + "AAA"; },
    (x) => { x.extra_plaintext_password = "x"; },
  ]) {
    const handle = await createNativeRdpAutologin(SESSION, 3, subtle, id);
    const envelope = await sealed(handle.request);
    modify(envelope);
    await assert.rejects(handle.open(envelope));
  }
});

test("63D-49 rejects malformed public parameters and never exports a private key", async () => {
  await assert.rejects(createNativeRdpAutologin("wrong", 3, subtle, id));
  const handle = await createNativeRdpAutologin(SESSION, 3, subtle, id);
  assert.equal(Object.keys(handle).includes("privateKey"), false);
  const envelope = await sealed(handle.request);
  envelope.public_key = "X";
  await assert.rejects(handle.open(envelope));
});

test("63D-49 has no storage, plaintext WSS, cookies or certificate-ignore fallback", async () => {
  const fs = await import("node:fs");
  const src = fs.readFileSync(
    new URL("../src/pages/clientdetailspage/remotedesktop/nativeRdpAutologin.mjs", import.meta.url),
    "utf8"
  );
  const ui = fs.readFileSync(
    new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url),
    "utf8"
  );
  assert.doesNotMatch(src, /(?:localStorage|sessionStorage|indexedDB|document\.cookie|console\.log)/);
  assert.match(src, /AES-GCM/);
  assert.match(src, /HKDF/);
  assert.doesNotMatch(ui, /VITE_NATIVE_RDP_AUTOLOGIN|Number\(clientId\) === 3/);
  assert.match(ui, /createNativeRdpAutologin\(sessionId, Number\(clientId\)\)/);
  assert.match(ui, /onClick=\{startAutomatic\}/);
  assert.doesNotMatch(ui, /TextField|onFallback|Bekræft fysisk billede/);
});


test("63D-52 invalidates asynchronous launch on disconnect, error and session replacement", async () => {
  const fs = await import("node:fs");
  const ui = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
  const parent = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");
  assert.match(ui, /const disconnect = \(\) => \{\s*operationRef\.current \+= 1/);
  assert.match(ui, /await createBrowserWsTicket[^\n]+\n\s*if \(operationRef\.current !== operation\) return/);
  assert.match(ui, /await createNativeRdpAutologin[^\n]+\n\s*if \(operationRef\.current !== operation\) return/);
  assert.match(parent, /key=\{\x60\$\{clientId\}:\$\{sessionId \|\| "pending"\}:\$\{agentConnected/);
});


test("managed pilot requests and cancels the exact one-time login", async () => {
  const fs = await import("node:fs");
  const ui = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
  assert.match(ui, /requestAutologin\(\{ \.\.\.handle\.request, managed: true \}\)/);
  assert.match(ui, /type: "native_rdp_autologin_cancel", request_id: requestId/);
  assert.match(ui, /const disconnect = \(\) => \{\s*operationRef\.current \+= 1;\s*cancelManaged\(\)/);
});


test("canonical login envelope is bound to the actual non-pilot client", async () => {
  for (const clientId of [37, 1001]) {
    const handle = await createNativeRdpAutologin(SESSION, clientId, subtle, id);
    assert.equal((await handle.open(await sealed(handle.request, {clientId}))).username, "cfpilotabcdef12");
    const wrong = await createNativeRdpAutologin(SESSION, clientId, subtle, id);
    await assert.rejects(wrong.open(await sealed(wrong.request, {clientId: 3})), /verificeres/);
  }
  for (const invalid of [null, 0, -1, "37", true, 1.5]) {
    await assert.rejects(createNativeRdpAutologin(SESSION, invalid, subtle, id));
  }
});
