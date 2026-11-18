import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
const sourceUrl = new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url);

test("RD native geometry is preserved even with lower HTTPS JPEG quality", async () => {
  const source = await readFile(sourceUrl, "utf8");
  assert.match(source, /native: true/);
  assert.match(source, /RD_HTTPS_JPEG_QUALITY = 65/);
  assert.match(source, /wsRef\.current\?\.transport === "https_long_poll"/);
  assert.match(source, /\{ \.\.\.streamStartPayloadRef\.current, fps, quality \}/);
  assert.doesNotMatch(source, /width:\s*RD_HTTPS/);
});

test("scroll is attached non-passively to remote image without duplicate React wheel handler", async () => {
  const source = await readFile(sourceUrl, "utf8");
  assert.match(source, /image\.addEventListener\("wheel", handleWheel, \{ passive: false \}\)/);
  assert.match(source, /image\.removeEventListener\("wheel", handleWheel\)/);
  assert.doesNotMatch(source, /onWheel=\{handleWheel\}/);
});
