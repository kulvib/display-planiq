import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createLivestreamBrowserTiming, createHlsReserveController, contiguousVideoBuffer, latestManifestSegment, hlsHttpTransportLabel, livestreamLatencyStatus } from "../src/pages/clientdetailspage/livestreamBrowserTiming.mjs";

test("63D-33 HLS live-edge samples are bounded, local and independently labeled", () => {
  const timing = createLivestreamBrowserTiming(3);
  for (const seconds of [1, 3, 5, 7]) assert.equal(timing.observe(seconds), true);
  assert.deepEqual(timing.snapshot(), {
    samples: 3, ignored: 0, p50Seconds: 5, p95Seconds: 7,
  });
  timing.reset();
  assert.deepEqual(timing.snapshot(), {
    samples: 0, ignored: 0, p50Seconds: null, p95Seconds: null,
  });
});

test("63D-33 HLS invalid or extreme latency never contaminates the series", () => {
  const timing = createLivestreamBrowserTiming(3);
  for (const seconds of [NaN, Infinity, -1, 120.01, null]) {
    // null is not accepted as a measurement: callers must explicitly supply hls.latency.
    if (seconds !== null) assert.equal(timing.observe(seconds), false);
  }
  assert.equal(timing.snapshot().ignored, 4);
  assert.equal(timing.observe(0), true);
  assert.equal(timing.observe(8.13), true);
  assert.equal(timing.snapshot().p95Seconds, 8.1);
  for (const limit of [0, -1, 129, 1.5]) {
    assert.throws(() => createLivestreamBrowserTiming(limit), RangeError);
  }
});

test("63D-33 HLS UI separates live-edge player estimate from actual uploader age", () => {
  const source = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  assert.match(source, /label: "HLS livekant"/);
  assert.match(source, /hlsBrowserTiming\.observe\(measuredLatency\)/);
  assert.match(source, /hlsBrowserTiming\.reset\(\)/);
  assert.match(source, /Browser p50/);
  assert.doesNotMatch(source, /label: "Uploadalder", value: formatLagValue\(lastSegmentLag\)/);
  assert.match(source, /lowLatencyMode: false/); // no LL-HLS claim or transport switch
});

function fakeVideo() {
  const listeners = new Map();
  const video = {
    currentTime: 0, ranges: [], readyState: 2, paused: true, seeking: false, autoplay: true,
    plays: 0, pauses: 0, failPlay: false,
    get buffered() { return { length: this.ranges.length, start: (i) => this.ranges[i][0], end: (i) => this.ranges[i][1] }; },
    addEventListener(event, handler) { listeners.set(event, handler); },
    removeEventListener(event, handler) { if (listeners.get(event) === handler) listeners.delete(event); },
    emit(event) { listeners.get(event)?.(); },
    play() {
      this.plays++;
      if (this.failPlay) return Promise.reject(Object.assign(new Error("blocked"), { name: "NotAllowedError" }));
      this.paused = false;
      return Promise.resolve();
    },
    pause() { this.paused = true; this.pauses++; },
  };
  return video;
}

test("63D-73A requires two contiguous segment durations, not manifest entries or disjoint ranges", async () => {
  const video = fakeVideo();
  let ready = 0;
  const gate = createHlsReserveController(video, { onReady: () => ready++ });
  assert.equal(video.autoplay, false);
  video.ranges = [[0, 2], [3, 8]];
  assert.equal(contiguousVideoBuffer(video).ahead, 2);
  assert.equal(gate.pump(), false);
  assert.equal(video.plays, 0);
  video.ranges = [[0, 4]];
  assert.equal(gate.pump(), true);
  assert.equal(gate.pump(), false);
  await Promise.resolve();
  assert.equal(ready, 1);
  assert.equal(video.plays, 1);
  assert.equal(gate.snapshot().phase, "playing");
  gate.dispose();
});

test("63D-73A refills after real underrun, adapts and never seeks away the reserve", async () => {
  const video = fakeVideo();
  let clock = 0;
  const gate = createHlsReserveController(video, { now: () => clock });
  video.ranges = [[0, 6]];
  gate.pump();
  await Promise.resolve();
  video.currentTime = 5.8;
  video.emit("waiting");
  assert.equal(video.paused, true);
  assert.equal(gate.snapshot().requiredSeconds, 5);
  assert.equal(gate.snapshot().refills, 1);
  assert.equal(gate.pump(), false);
  video.ranges = [[0, 11]];
  video.emit("progress");
  await Promise.resolve();
  assert.equal(video.paused, false);
  assert.equal(gate.catchUp(20), false);
  video.ranges = [[0, 20]];
  assert.equal(gate.catchUp(17), true);
  assert.equal(video.currentTime, 15);
  clock = 31_000;
  video.emit("timeupdate");
  assert.equal(gate.snapshot().requiredSeconds, 4);
  gate.dispose();
  video.emit("waiting");
  assert.equal(gate.snapshot().refills, 1);
});

test("63D-73A preserves user activation and ignores late promises after disposal", async () => {
  const video = fakeVideo();
  const taps = [];
  const gate = createHlsReserveController(video, { onTapRequired: (v) => taps.push(v) });
  gate.setTargetDuration(1);
  video.ranges = [[0, 2]];
  video.failPlay = true;
  gate.pump();
  await Promise.resolve();
  assert.deepEqual(taps, [true]);
  assert.equal(gate.pump(), false);
  video.failPlay = false;
  assert.equal(gate.playFromGesture(), true);
  gate.dispose();
  await Promise.resolve();
  assert.deepEqual(taps, [true]);
});

test("63D-73A both HLS.js views use the reserve and keep native Safari fallback", () => {
  for (const path of ["../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", "../src/pages/adminpages/LivestreamOverview.jsx"]) {
    const source = readFileSync(new URL(path, import.meta.url), "utf8");
    assert.match(source, /createHlsReserveController\(video/);
    assert.match(source, /Hls\.Events\.BUFFER_APPENDED/);
    assert.match(source, /initialLiveManifestSize:/);
    assert.match(source, /maxLiveSyncPlaybackRate: 1,/);
    assert.match(source, /playFromGesture\(\)/);
    assert.match(source, /video\.canPlayType\("application\/vnd\.apple\.mpegurl"\)/);
    assert.doesNotMatch(source, /video\.currentTime = Math\.max\(0, livePos/);
  }
});

test("63D-73C manifest edge and transport are independent of playhead", () => {
  assert.equal(latestManifestSegment({ fragments: [{ sn: 57 }, { sn: 58 }, { sn: 59 }] }), 59);
  assert.equal(latestManifestSegment({ fragments: [] }), null);
  assert.equal(latestManifestSegment({ fragments: [{ sn: "59" }] }), null);
  assert.equal(hlsHttpTransportLabel("https://api.example.test/hls/3/index.m3u8"), "HTTPS");
  assert.equal(hlsHttpTransportLabel("/hls/3/index.m3u8", "http://localhost:8080"), "HTTP");
  assert.equal(hlsHttpTransportLabel("wss://api.example.test/video"), null);
  const source = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /setLastSegNum\(data\.frag\.sn\)/);
  assert.match(source, /setLastSegNum\(published\)/);
  assert.doesNotMatch(source, /segsBehind/);
  assert.match(source, /bufferStats\.aheadSeconds/);
  assert.match(source, /HLS · \$\{mediaTransport\}/);
});

test("63D-73C slows before depletion, counts one waiting episode and measures duration", async () => {
  const video = fakeVideo();
  let clock = 0;
  const observations = [];
  const gate = createHlsReserveController(video, { now: () => clock, onSnapshot: (s) => observations.push(s) });
  video.ranges = [[0, 6]];
  gate.pump();
  await Promise.resolve();
  assert.equal(video.playbackRate, 1);
  video.currentTime = 4;
  clock = 1000;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 0.95);
  assert.equal(gate.snapshot().stalls, 0);
  video.ranges = [[0, 9]];
  clock = 2000;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 1);
  video.currentTime = 6;
  clock = 3000;
  video.emit("waiting");
  video.emit("waiting");
  assert.equal(gate.snapshot().stalls, 1);
  clock = 3500;
  video.emit("playing");
  assert.equal(gate.snapshot().stalledSeconds, 0.5);
  video.currentTime = 8.5;
  clock = 4000;
  video.emit("waiting");
  assert.equal(gate.snapshot().stalls, 2);
  assert.equal(gate.snapshot().refills, 1);
  video.ranges = [[0, 14]];
  clock = 5000;
  video.emit("progress");
  await Promise.resolve();
  assert.equal(gate.snapshot().stalledSeconds, 1.5);
  assert.ok(observations.length > 0);
  gate.dispose();
  assert.equal(video.playbackRate, 1);
});

test("63D-73E warm tab keeps the player and health polling independent of bearer rotation", () => {
  const source = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  assert.match(source, /const hasMediaCapability = mediaCapabilityClientId !== null && mediaCapabilityClientId === clientId/);
  assert.match(source, /mediaCapabilityRef\.current = String\(payload\.media_capability\);\s*setMediaCapabilityClientId\(clientId\)/);
  assert.doesNotMatch(source, /setMediaCapability\(/);
  assert.equal([...source.matchAll(/pageVisible, hasMediaCapability, mobileViewerActive/g)].length, 2);
  assert.doesNotMatch(source, /pageVisible, mediaCapability, mobileViewerActive/);
  assert.match(source, /Authorization: `Bearer \$\{mediaCapabilityRef\.current\}`/);
  assert.match(source, /const token = mediaCapabilityRef\.current;\s*if \(token\) xhr\.setRequestHeader/);
  assert.match(source, /HIDDEN_MEDIA_WARM_GRACE_MS = 30_000/);
  assert.match(source, /setPageVisible\(false\);\s*\}, HIDDEN_MEDIA_WARM_GRACE_MS\)/);
  assert.match(source, /if \(stopped \|\| !manifestReady \|\| document\.visibilityState === "hidden"\) return;/);
  assert.match(source, /if \(document\.visibilityState === "hidden"\) return;\s*const video = videoRef\.current;\s*const hls = hlsRef\.current/);
  assert.match(source, /sendLeaveOnce\("client_details_livestream_unmount"\)/);
});

test("63D-73E diagnostics grow with content and transport stays at toolbar right", () => {
  const source = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  const panel = source.slice(source.indexOf('data-testid="livestream-diagnostics"'), source.indexOf('<Dialog open={settingsOpen}'));
  assert.match(panel, /gridAutoRows: "minmax\(min-content, 1fr\)"/);
  assert.match(panel, /height: "auto"/);
  assert.doesNotMatch(panel, /maxHeight:|gridTemplateRows:|WebkitLineClamp|overflow: "hidden"|whiteSpace: "nowrap"|textOverflow:/);
  assert.match(panel, /whiteSpace: "normal"/);
  assert.match(panel, /overflowWrap: "anywhere"/);
  assert.match(panel, /flexShrink: 0/);
  assert.match(source, /Skærmindstillinger\s*<\/Button>\s*\)\}\s*<\/Stack>\s*\{manifestReady && mediaTransport && \(/);
  assert.match(source, /data-testid="livestream-transport"[^\n]+justifyContent: "flex-end"[^\n]+ml: \{ md: "auto" \}/);
});

function fakeVisibility() {
  const events = new Map();
  const doc = { visibilityState: "visible",
    addEventListener(name, fn) { events.set(name, fn); },
    removeEventListener(name, fn) { if (events.get(name) === fn) events.delete(name); },
    show(value) { this.visibilityState = value; events.get("visibilitychange")?.(); },
  };
  const mediaEvents = new Map();
  const hls = { latency: 6, liveSyncPosition: 106, stops: 0, starts: [],
    on(name, fn) { mediaEvents.set(name, fn); },
    off(name, fn) { if (mediaEvents.get(name) === fn) mediaEvents.delete(name); },
    emit(details) { mediaEvents.get("level")?.("level", {details}); },
    stopLoad() { this.stops++; }, startLoad(position) { this.starts.push(position); },
  };
  return { doc, hls, events, mediaEvents };
}
test("63D-73F healthy short switch preserves instance and playback", async () => {
  const video = fakeVideo();
  let clock = 0;
  const {doc,hls} = fakeVisibility();
  const gate = createHlsReserveController(video,{now:()=>clock});
  video.ranges=[[0,12]];
  gate.pump(); await Promise.resolve();
  gate.bindLiveVisibility(hls,doc,"level");
  doc.show("hidden"); clock=5000; video.currentTime=5;
  doc.show("visible");
  assert.equal(hls.stops,0);
  assert.equal(video.paused,false);
  gate.dispose();
});
test("63D-73F stalled tab skips old media and waits for fresh contiguous reserve", async () => {
  const video=fakeVideo();
  let clock=0;
  const {doc,hls,events,mediaEvents}=fakeVisibility();
  const gate=createHlsReserveController(video,{now:()=>clock});
  video.ranges=[[0,8]];
  gate.pump(); await Promise.resolve();
  let timeout;
  gate.bindLiveVisibility(hls,doc,"level",{schedule:fn=>{timeout=fn;return 1;},cancel:()=>{timeout=null;}});
  doc.show("hidden"); clock=20000; video.emit("waiting");
  assert.equal(gate.snapshot().stalls,0);
  doc.show("visible");
  assert.equal(hls.stops,1);
  assert.deepEqual(hls.starts,[-1]);
  assert.equal(video.paused,true);
  assert.equal(gate.pump(),false);
  hls.emit({live:false,fragments:[{start:100,duration:2}]});
  assert.equal(video.currentTime,0);
  hls.emit({live:true,fragments:[{start:100,duration:2},{start:102,duration:2},{start:104,duration:2},{start:106,duration:2}]});
  assert.equal(video.currentTime,104);
  assert.equal(typeof timeout,"function");
  assert.equal(gate.pump(),false);
  video.ranges=[[0,8],[104,108]];
  video.emit("progress"); await Promise.resolve();
  assert.equal(video.paused,false);
  assert.equal(gate.snapshot().aheadSeconds,4);
  assert.equal(typeof timeout,"function");
  video.currentTime=104.25;
  video.emit("timeupdate");
  assert.equal(timeout,null);
  gate.dispose();
  assert.equal(events.size,0); assert.equal(mediaEvents.size,0);
});
test("63D-73F bounded local fallback and disposal", async () => {
  const video=fakeVideo();
  let clock=0, timeout, failures=0;
  const {doc,hls}=fakeVisibility();
  const gate=createHlsReserveController(video,{now:()=>clock});
  video.ranges=[[0,8]];
  gate.pump(); await Promise.resolve();
  gate.bindLiveVisibility(hls,doc,"level",{onFailure:()=>failures++,schedule:(fn,ms)=>{assert.equal(ms,8000);timeout=fn;return 1;},cancel:()=>{timeout=null;}});
  doc.show("hidden"); clock=20000; doc.show("visible");
  timeout();
  assert.equal(failures,1);
  doc.show("hidden"); clock=40000; doc.show("visible");
  gate.dispose();
  assert.equal(timeout,null);
  assert.equal(failures,1);
});
test("63D-73F both HLS.js views bind live recovery and dispose reserve", () => {
  for(const path of ["../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx","../src/pages/adminpages/LivestreamOverview.jsx"]) {
    const source=readFileSync(new URL(path,import.meta.url),"utf8");
    assert.match(source,/reserve\.bindLiveVisibility\(hls, document, Hls\.Events\.LEVEL_UPDATED/);
    assert.match(source,/(?:reserve|hlsReserveRef\.current)\??\.dispose\(\)/);
  }
});

test("63D-74 visual latency bands follow the displayed tenth and never coerce unknown", () => {
  for (const value of [null, undefined, NaN, Infinity, -1, "0", false]) {
    assert.equal(livestreamLatencyStatus(value).severity, "neutral");
  }
  for (const [value, severity] of [[0,"success"],[7,"success"],[7.04,"success"],[7.1,"warning"],[10,"warning"],[10.1,"elevated"],[15,"elevated"],[15.1,"error"]]) {
    assert.equal(livestreamLatencyStatus(value).severity, severity);
  }
  assert.equal(livestreamLatencyStatus(5.2).text, "5,2 sek. forsinkelse");
});
test("63D-74 both live views use numeric presentation, no false green on unknown", () => {
  const detail = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  const wall = readFileSync(new URL("../src/pages/adminpages/LivestreamOverview.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(detail, /title: "Stream live"/);
  assert.match(detail, /title: latencyStatus\.text/);
  assert.match(detail, /severity: latencyStatus\.severity/);
  assert.match(wall, /state === "live" \? latencyStatus\.text/);
  assert.doesNotMatch(wall, /Number\(hlsRef\.current\?\.latency\)/);
  assert.doesNotMatch(wall, /const value = Number\(seconds\)/);
});

test("63D-78 a playlist and a successful play promise cannot mask a frozen image", async () => {
  const video=fakeVideo(); let clock=0, timer=null, failures=0;
  const {doc,hls}=fakeVisibility();
  const gate=createHlsReserveController(video,{now:()=>clock});
  video.ranges=[[0,8]]; gate.pump(); await Promise.resolve();
  gate.bindLiveVisibility(hls,doc,"level",{
    onFailure:()=>failures++,
    schedule:(fn,ms)=>{timer={fn,ms};return 1;},cancel:()=>{timer=null;}
  });
  doc.show("hidden");clock=20_000;doc.show("visible");
  assert.equal(timer.ms,8000);
  hls.emit({live:true,fragments:[{start:100,duration:2},{start:102,duration:2},{start:104,duration:2},{start:106,duration:2}]});
  assert.equal(timer.ms,5000);
  video.ranges=[[104,108]];
  video.emit("progress");await Promise.resolve();
  assert.equal(video.paused,false);
  video.emit("timeupdate"); // seek target, no advancement
  assert.equal(timer.ms,5000);
  timer.fn();
  assert.equal(failures,1);
  assert.equal(video.paused,true);
  gate.dispose();
});
test("63D-78 verifies warm return without restarting healthy playback", async () => {
  const video=fakeVideo();let clock=0,timer=null;
  const {doc,hls}=fakeVisibility();const gate=createHlsReserveController(video,{now:()=>clock});
  video.ranges=[[0,20]];gate.pump();await Promise.resolve();
  gate.bindLiveVisibility(hls,doc,"level",{schedule:(fn,ms)=>{timer={fn,ms};return 1;},cancel:()=>{timer=null;}});
  doc.show("hidden");clock=5000;video.currentTime=5;doc.show("visible");
  assert.equal(hls.stops,0);assert.equal(timer.ms,3000);
  video.currentTime=5.25;video.emit("timeupdate");
  assert.equal(timer,null);assert.equal(hls.stops,0);
  doc.show("hidden");clock=10000;video.currentTime=10.25;doc.show("visible");
  assert.equal(timer.ms,3000);
  timer.fn();assert.equal(hls.stops,1);assert.equal(timer.ms,8000);
  gate.dispose();assert.equal(timer,null);
});
test("63D-78 a second hide cancels playback verification; visible return re-enters fresh recovery", async () => {
  const video=fakeVideo();let clock=0,timer=null,failures=0;
  const {doc,hls}=fakeVisibility();const gate=createHlsReserveController(video,{now:()=>clock});
  video.ranges=[[0,8]];gate.pump();await Promise.resolve();
  gate.bindLiveVisibility(hls,doc,"level",{onFailure:()=>failures++,schedule:(fn,ms)=>{timer={fn,ms};return 1;},cancel:()=>{timer=null;}});
  doc.show("hidden");clock=5000;doc.show("visible");
  hls.emit({live:true,fragments:[{start:100,duration:2},{start:102,duration:2},{start:104,duration:2},{start:106,duration:2}]});
  assert.equal(timer.ms,5000);
  doc.show("hidden");assert.equal(timer,null);
  clock=10000;doc.show("visible");assert.equal(hls.stops,2);assert.equal(timer.ms,8000);
  gate.dispose();assert.equal(timer,null);assert.equal(failures,0);
});
