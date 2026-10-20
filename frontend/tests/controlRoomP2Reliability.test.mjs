import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { clientListNeedsFastPolling, clientListPollDelay } from "../src/utils/controlRoomPolling.mjs";

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const normal = { status: "approved", state: "normal", pending_chrome_action: "none" };

test("historical Chrome steps and permanently rejected enrollments don't trigger fast polling", () => {
  const stale = { ...normal, chrome_step: "system_rebooting", browser_countdown: { ends_at: "2026-10-18T19:00:00Z" } };
  assert.equal(clientListNeedsFastPolling([stale], Date.parse("2026-10-20T19:00:00Z")), false);
  assert.equal(clientListPollDelay([stale], Date.parse("2026-10-20T19:00:00Z")), 60_000);
  assert.equal(clientListNeedsFastPolling([{ ...normal, status: "rejected" }]), false);
  assert.equal(clientListNeedsFastPolling([{ ...normal, status: "disabled" }]), false);
});

test("real operations or future countdowns keep 10s fallback", () => {
  const now = Date.parse("2026-10-20T19:00:00Z");
  for (const active of [
    { ...normal, pending_chrome_action: "restart" },
    { ...normal, state: "rebooting" },
    { ...normal, status: "pending" },
    { ...normal, pending_reboot: true },
    { ...normal, pending_shutdown: true },
    { ...normal, pending_os_update: true },
    { ...normal, chrome_step: "countdown", browser_countdown: { ends_at: "2026-10-20T19:00:20Z" } },
  ]) {
    assert.equal(clientListPollDelay([active], now), 10_000);
  }
  assert.equal(clientListPollDelay([normal], now), 60_000);
});

test("sorting is one scoped API request with authoritative resync and no partial parallel writes", () => {
  const page = read("pages/ClientInfoPage.jsx");
  const api = read("api/api.js");
  const drag = page.slice(page.indexOf("const onDragEnd ="), page.indexOf("const handleRestoreClient ="));
  assert.match(drag, /await updateControlRoomOrder\(/);
  assert.doesNotMatch(drag, /Promise\.all|updateClient\(/);
  assert.match(drag, /const refreshed = await fetchClients\(true, false\)/);
  assert.match(drag, /setDragClients\(dragClients\)/);
  assert.match(drag, /Sortering gemt, men klientlisten kunne ikke genindlæses/);
  assert.match(api, /export async function updateControlRoomOrder\(expectedIds, orderedIds\)/);
  assert.match(api, /method: "POST"/);
  assert.match(api, /expected_ids: expectedIds, ordered_ids: orderedIds/);
});

test("manual refresh reports partial failure, and never falsely announces success", () => {
  const list = read("pages/ClientInfoPage.jsx");
  const details = read("pages/clientdetailspage/ClientDetailsPageWrapper.jsx");
  const action = list.slice(list.indexOf("const handleRefresh ="), list.indexOf("const openRemoveDialog ="));
  assert.match(action, /results\.every\(Boolean\)/);
  assert.match(action, /Siden blev kun delvist opdateret/);
  assert.match(action, /fetchClients\(true, true, false\)/);
  assert.match(details, /const results = await Promise\.all\(\[fetchClient\(true\), fetchMarkedDays\(\)\]\)/);
  assert.match(details, /Klientdata blev ikke fuldt opdateret/);
});

test("client list search promises only fields included in the authorized summary projection", () => {
  const list = read("pages/ClientInfoPage.jsx");
  const search = read("utils/clientSearchSort.mjs");
  assert.match(list, /WiFi- eller LAN-IP/);
  assert.doesNotMatch(search, /client\?\.hostname|client\?\.active_network_ip/);
});
