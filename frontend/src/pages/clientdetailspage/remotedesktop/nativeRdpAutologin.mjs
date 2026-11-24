/*
 * 63D-49: zero manual GNOME RDP credentials. A per-request P-256 ECDH
 * private key stays only in this browser JS realm; Render relays a sealed
 * envelope and cannot see the GNOME password or the pinned TLS fingerprint.
 * Do not save credentials, private keys or envelopes to storage or logs.
 */
const DOMAIN = "planiq-clientflow-rdp-v1";
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const uuidRE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function base64url(bytes) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function unbase64url(s, max = 1024) {
  if (typeof s !== "string" || !/^[A-Za-z0-9_-]+$/.test(s) || s.length > max * 2) {
    throw new Error("Ugyldige krypterede RDP-data.");
  }
  const data = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4));
  if (data.length > max) throw new Error("For stor RDP-pakke.");
  const bytes = Uint8Array.from(data, c => c.charCodeAt(0));
  if (base64url(bytes) !== s) throw new Error("Ugyldigt RDP-datakodeformat.");
  return bytes;
}
function canonicalUuid(s) {
  return typeof s === "string" && uuidRE.test(s);
}
function validateEnvelope(envelope, sessionId, requestId) {
  if (!envelope || Object.getPrototypeOf(envelope) !== Object.prototype ||
      Object.keys(envelope).sort().join(",") !==
      "ciphertext,expires_unix,nonce,public_key,request_id,salt,schema,session_id" ||
      envelope.schema !== 1 || envelope.session_id !== sessionId ||
      envelope.request_id !== requestId || !Number.isSafeInteger(envelope.expires_unix)) {
    throw new Error("RDP-autologin tilhører ikke denne session.");
  }
  const secondsLeft = envelope.expires_unix - Math.floor(Date.now() / 1000);
  if (!(secondsLeft > 0 && secondsLeft <= 360)) throw new Error("RDP-autologin er udløbet.");
}
export async function createNativeRdpAutologin(sessionId, subtle = globalThis.crypto?.subtle,
  randomUUID = () => globalThis.crypto.randomUUID()) {
  if (!canonicalUuid(sessionId) || !subtle) throw new Error("Sikker RDP-autologin er ikke tilgængelig.");
  const requestId = randomUUID();
  if (!canonicalUuid(requestId)) throw new Error("Ugyldigt RDP-autologin request-id.");
  const pair = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
  const rawPublic = new Uint8Array(await subtle.exportKey("raw", pair.publicKey));
  if (rawPublic.length !== 65 || rawPublic[0] !== 4) throw new Error("Ugyldig ECDH-nøgle.");

  let consumed = false;
  return {
    request: {
      type: "native_rdp_autologin_request", request_id: requestId,
      public_key: base64url(rawPublic),
    },
    async open(envelope) {
      if (consumed) throw new Error("RDP-autologin må kun bruges én gang.");
      consumed = true;
      validateEnvelope(envelope, sessionId, requestId);
      const publicBytes = unbase64url(envelope.public_key, 65);
      if (publicBytes.length !== 65 || publicBytes[0] !== 4) throw new Error("Ugyldig RDP-servernøgle.");
      const salt = unbase64url(envelope.salt, 16);
      const iv = unbase64url(envelope.nonce, 12);
      const ciphertext = unbase64url(envelope.ciphertext, 1024);
      if (salt.length !== 16 || iv.length !== 12 || ciphertext.length < 32) {
        throw new Error("Ugyldig RDP-kryptering.");
      }
      const peerKey = await subtle.importKey("raw", publicBytes, { name: "ECDH", namedCurve: "P-256" }, false, []);
      const shared = await subtle.deriveBits({ name: "ECDH", public: peerKey }, pair.privateKey, 256);
      const hkdf = await subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
      const info = encoder.encode(`${DOMAIN}|${sessionId}|${requestId}`);
      const aad = encoder.encode(`${DOMAIN}|3|${sessionId}|${requestId}`);
      const key = await subtle.deriveKey(
        { name: "HKDF", hash: "SHA-256", salt, info }, hkdf,
        { name: "AES-GCM", length: 256 }, false, ["decrypt"]
      );
      let plaintext;
      try {
        plaintext = await subtle.decrypt(
          { name: "AES-GCM", iv, additionalData: aad, tagLength: 128 }, key, ciphertext
        );
      } catch {
        throw new Error("Krypteret RDP-autologin kunne ikke verificeres.");
      }
      let body;
      try {
        body = JSON.parse(decoder.decode(plaintext));
      } catch {
        throw new Error("Ugyldigt indhold i krypteret RDP-login.");
      }
      if (!body || Object.keys(body).sort().join(",") !==
          "expires_unix,fingerprint,password,username" ||
          body.expires_unix !== envelope.expires_unix ||
          typeof body.username !== "string" || !/^cfpilot[0-9a-f]{8}$/.test(body.username) ||
          typeof body.password !== "string" || !/^[A-Za-z0-9_-]{40,80}$/.test(body.password) ||
          typeof body.fingerprint !== "string" || !/^[0-9a-f]{64}$/.test(body.fingerprint)) {
        throw new Error("RDP-loginpakke er ugyldig.");
      }
      const fingerprint = body.fingerprint.match(/../g).join(":");
      return { username: body.username, password: body.password, fingerprint };
    },
  };
}
