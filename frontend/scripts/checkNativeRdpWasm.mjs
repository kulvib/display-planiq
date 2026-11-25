/**
 * Strict, source-pinned official FreeRDP 3.33.1 SDL3/Emscripten asset gate.
 * No network/CDN access, no new runtime dependencies, no credential handling.
 * Absence is allowed ONLY when the Viborg1 pilot is explicitly disabled.
 */
import { createHash } from "node:crypto";
import { readFileSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const EXPECTED = Object.freeze({
  "sdl-freerdp.js": { sha256: "c7d0a7e20a7b6473c5743892086b00dfb096807b8386adf992ab294867ad8112", bytes: 269234 },
  "sdl-freerdp.wasm": { sha256: "f5cfa907421b47c3ed6acdee329f5ebda7e9279c4a5972e02139dc8e2fe6f315", bytes: 11086426 },
});
export const FREERDP_SOURCE_SHA = "65bcca1913a28cbdd7eb913599f692bd2b707991";

export function inspectNativeRdpAssets({
  frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."),
  enabled = process.env.VITE_NATIVE_RDP_PILOT === "true",
} = {}) {
  const root = path.join(frontendDir, "public", "native-rdp");
  const filenames = ["sdl-freerdp.js", "sdl-freerdp.wasm", "provenance.json"];
  const present = filenames.map((name) => existsSync(path.join(root, name)));
  if (!present.some(Boolean)) {
    if (enabled) throw new Error("FreeRDP WASM-piloten er aktiveret uden et verificeret klientbuild");
    return { installed: false, verified: true };
  }
  if (!present.every(Boolean)) throw new Error("FreeRDP WASM-bygningen er ufuldstændig");

  const provenance = JSON.parse(readFileSync(path.join(root, "provenance.json"), "utf8"));
  if (provenance.freerdp_source_commit !== FREERDP_SOURCE_SHA ||
      provenance.freerdp_version !== "3.33.1" || provenance.emsdk !== "6.0.12") {
    throw new Error("FreeRDP WASM-kildeidentiteten matcher ikke den godkendte version");
  }
  if (Object.keys(provenance.files || {}).sort().join() !== Object.keys(EXPECTED).sort().join()) {
    throw new Error("FreeRDP WASM-manifestet indeholder uventede eller manglende filer");
  }

  for (const [name, expected] of Object.entries(EXPECTED)) {
    const filename = path.join(root, name);
    const info = statSync(filename);
    if (!info.isFile() || info.size !== expected.bytes ||
        provenance.files[name].bytes !== expected.bytes ||
        provenance.files[name].sha256 !== expected.sha256) {
      throw new Error("FreeRDP WASM-størrelse eller provenance er ændret: " + name);
    }
    const hash = createHash("sha256").update(readFileSync(filename)).digest("hex");
    if (hash !== expected.sha256) throw new Error("FreeRDP WASM SHA-256 matcher ikke: " + name);
  }
  const magic = readFileSync(path.join(root, "sdl-freerdp.wasm")).subarray(0, 4);
  if (!magic.equals(Buffer.from([0, 97, 115, 109]))) {
    throw new Error("FreeRDP WASM-header er ikke gyldig");
  }
  return { installed: true, verified: true, sourceCommit: FREERDP_SOURCE_SHA };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    const result = inspectNativeRdpAssets();
    console.log(result.installed ? "FreeRDP WASM SHA256/provenance: PASS" : "FreeRDP WASM: pilot deaktiveret; bundle ikke installeret");
  } catch (error) {
    console.error(error instanceof Error ? error.message : "Ugyldig FreeRDP WASM-bygning");
    process.exitCode = 1;
  }
}
