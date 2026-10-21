import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const listing = readFileSync(new URL("../src/pages/ClientInfoPage.jsx", import.meta.url), "utf8");

test("unknown fullscreen reports its purpose; status label is preserved", () => {
  assert.match(listing, /fullscreenLabel === "Ukendt" \? "Fuldskærm: Ukendt" : fullscreenLabel/);
  assert.match(listing, /label=\{fullscreenChipLabel\}/);
  assert.match(listing, /title=\{`Kiosk browser fuldskærm: \$\{fullscreenLabel\}`\}/);
});
