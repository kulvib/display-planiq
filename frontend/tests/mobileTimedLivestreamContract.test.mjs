import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  MOBILE_LIVESTREAM_DURATIONS,
  MOBILE_LIVESTREAM_DEFAULT_SECONDS,
  mobileLivestreamDeadline,
  remainingMobileLivestreamSeconds,
} from "../src/utils/mobileLivestreamTiming.mjs";

function read(path) {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

const hook = read("src/utils/useMobileLivestreamSession.js");
const wall = read("src/pages/adminpages/LivestreamOverview.jsx");
const detail = read("src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx");

test("mobile-only durations are bounded and time is based on absolute wall clock", () => {
  assert.deepEqual([...MOBILE_LIVESTREAM_DURATIONS], [15, 30, 60, 120]);
  assert.equal(MOBILE_LIVESTREAM_DEFAULT_SECONDS, 30);
  assert.equal(mobileLivestreamDeadline(1000, 30), 31_000);
  assert.equal(remainingMobileLivestreamSeconds(31_000, 1000), 30);
  assert.equal(remainingMobileLivestreamSeconds(31_000, 30_001), 1);
  assert.equal(remainingMobileLivestreamSeconds(31_000, 31_000), 0);
  assert.equal(remainingMobileLivestreamSeconds(31_000, 99_000), 0);
  assert.equal(remainingMobileLivestreamSeconds(null, 12_000), 0);
  assert.throws(() => mobileLivestreamDeadline(1000, 13), RangeError);
});

test("mobile session only starts on explicit user action, stops at deadline and on background", () => {
  assert.match(hook, /const \[endsAtMs, setEndsAtMs\] = useState\(null\)/);
  assert.match(hook, /if \(!isTouchHandset \|\| document\.visibilityState === "hidden"\) return/);
  assert.match(hook, /setEndsAtMs\(mobileLivestreamDeadline\(now, durationSeconds\)\)/);
  assert.match(hook, /remainingMobileLivestreamSeconds\(endsAtMs, now\) === 0\) stop\(true\)/);
  assert.match(hook, /window\.setInterval\(tick, 250\)/);
  assert.match(hook, /window\.clearInterval\(interval\)/);
  assert.match(hook, /document\.addEventListener\("visibilitychange", onHide\)/);
  assert.match(hook, /window\.addEventListener\("pagehide", onPageHide\)/);
  assert.match(hook, /setEndsAtMs\(null\)/);
  assert.match(hook, /!isTouchHandset && endsAtMs != null\) stop\(false\)/);
});

test("portrait and landscape phone livestream start stop use only viewer leases", () => {
  for (const view of [wall, detail]) {
    assert.match(view, /useMobileLivestreamSession\(isTouchHandset\)/);
    assert.match(view, /!isTouchHandset \|\| mobileSession\.isActive/);
    assert.match(view, /\(hover: none\) and \(pointer: coarse\) and \(max-width: 1023\.95px\)/);
    assert.match(view, /mobileSession\.isActive \? \(\) => mobileSession\.stop\(\) : mobileSession\.start/);
    assert.match(view, /MOBILE_LIVESTREAM_DURATIONS\.map/);
    assert.match(view, /Stopper om \$\{mobileSession\.remainingSeconds\} sek\./);
    assert.match(view, /viewer-leave/);
    assert.doesNotMatch(view, /sendLivestreamCommand\(clientId, "livestream_stop"/);
  }
  assert.match(wall, /pageMediaActive && intersecting && clientOnline && mobileViewerActive/);
  assert.match(wall, /if \(cancelled\) \{[\s\S]*?livestream_wall_late_heartbeat/);
  assert.match(detail, /!clientId \|\| inactivityStopped \|\| !mobileViewerActive/);
  assert.match(detail, /!clientId \|\| inactivityStopped \|\| !pageVisible \|\| !mediaCapability \|\| !mobileViewerActive/);
  assert.match(detail, /!clientId \|\| !serverReady \|\| inactivityStopped \|\| !pageVisible \|\| !mediaCapability \|\| !mobileViewerActive/);
  assert.match(detail, /client_details_livestream_late_heartbeat/);
  // Desktop still has the same auto-start lease and HLS handling.
  assert.match(detail, /const mobileViewerActive = !isTouchHandset \|\| mobileSession\.isActive/);
  assert.match(wall, /const mobileViewerActive = !isTouchHandset \|\| mobileSession\.isActive/);
  assert.match(detail, /VIEWER_HEARTBEAT_MS = 25_000/);
  assert.match(wall, /const VIEWER_HEARTBEAT_MS = 25_000/);
});
