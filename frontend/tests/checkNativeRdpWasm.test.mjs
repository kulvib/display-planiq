import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { inspectNativeRdpAssets, FREERDP_SOURCE_SHA } from "../scripts/checkNativeRdpWasm.mjs";

test("WASM gate fails closed if enabled without a source-pinned artifact", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "planiq-rdp-"));
  try {
    assert.equal(inspectNativeRdpAssets({ frontendDir: dir, enabled: false }).installed, false);
    assert.throws(() => inspectNativeRdpAssets({ frontendDir: dir, enabled: true }), /uden et verificeret/);
    mkdirSync(path.join(dir, "public", "native-rdp"), { recursive: true });
    writeFileSync(path.join(dir, "public", "native-rdp", "sdl-freerdp.js"), "// altered artifact\n");
    assert.throws(() => inspectNativeRdpAssets({ frontendDir: dir, enabled: false }), /ufuldstændig/);
    writeFileSync(path.join(dir, "public", "native-rdp", "sdl-freerdp.wasm"), "not wasm");
    writeFileSync(path.join(dir, "public", "native-rdp", "provenance.json"), JSON.stringify({
      freerdp_source_commit: FREERDP_SOURCE_SHA, freerdp_version: "3.33.1", emsdk: "6.0.12",
      files: { "sdl-freerdp.js": { sha256: "0", bytes: 19 }, "sdl-freerdp.wasm": { sha256: "0", bytes: 8 } },
    }));
    assert.throws(() => inspectNativeRdpAssets({ frontendDir: dir, enabled: false }), /størrelse/);
  } finally {
    rmSync(dir, { force: true, recursive: true });
  }
});
