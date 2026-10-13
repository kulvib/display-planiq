import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { receiveBrowserCountdown, formatBrowserCountdownStatus } from "../src/pages/clientdetailspage/browserCountdown.mjs";

function source(path) {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

test("Clientlist receives the existing authoritative browser deadline, then ticks locally", () => {
  const model = source("../backend/service1/models.py");
  const projection = source("../backend/service1/routers/clients.py");
  const list = source("src/pages/ClientInfoPage.jsx");
  assert.match(model, /browser_countdown: Optional\[dict\[str, Any\]\] = None/);
  assert.match(projection, /_set_runtime_read_attr\(client, "browser_countdown", projection\.get\("browser_countdown"\)\)/);
  assert.match(list, /receiveBrowserCountdown\(countdown, Date\.now\(\)\)/);
  assert.match(list, /window\.setInterval\([\s\S]*?250\)/);
  assert.match(list, /formatBrowserCountdownStatus\(snapshot, clockMs\)/);
  assert.match(list, /ca\.browser_countdown\?\.ends_at !== cb\.browser_countdown\?\.ends_at/);
  const cell = list.slice(list.indexOf("const ClientStatusCell"), list.indexOf("const ClientHealthCell"));
  assert.doesNotMatch(cell, /getControlRoomClients\(|getChromeStatus\(|fetch\(/);

  const received = receiveBrowserCountdown({
    remaining_seconds: 7, reason: "reset_browser", step: "countdown",
    ends_at: "2026-10-13T10:00:07.000Z", server_now: "2026-10-13T10:00:00.000Z",
  }, 100_000);
  assert.match(formatBrowserCountdownStatus(received, 102_000), /5 sekunder/);
  assert.match(formatBrowserCountdownStatus(received, 106_500), /1 sekund/);
  assert.equal(formatBrowserCountdownStatus(received, 107_001), "Afventer ny browserstatus fra klienten…");
});

test("mobile livestream panels are single column for touch portrait and landscape while desktop grid remains", () => {
  const detail = source("src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx");
  const wall = source("src/pages/adminpages/LivestreamOverview.jsx");
  assert.match(detail, /\? \{ xs: "minmax\(0, 1fr\) 320px", md: "minmax\(0, 1fr\) 320px", lg: "minmax\(0, 1fr\) 320px" \}/);
  assert.match(detail, /"@media \(hover: none\) and \(pointer: coarse\) and \(max-width: 1023\.95px\)"/);
  assert.match(detail, /"@media \(orientation: landscape\) and \(hover: none\) and \(pointer: coarse\) and \(max-width: 1023\.95px\)"/);
  assert.match(wall, /gridTemplateColumns: \{ xs: "1fr", sm: "repeat\(2, minmax\(0, 1fr\)\)", xl: "repeat\(3, minmax\(0, 1fr\)\)" \}/);
  assert.match(wall, /"@media \(hover: none\) and \(pointer: coarse\) and \(max-width: 1023\.95px\)"/);
  for (const view of [detail, wall]) {
    assert.match(view, /Afspil livestream/);
    assert.match(view, /webkitEnterFullscreen/);
    assert.match(view, /video\.play\(\)\.then\(\(\) => setNeedsTapToPlay\(false\)\)/);
    assert.doesNotMatch(view, /mediaCapability.*\$\{hlsParams/);
  }
});
