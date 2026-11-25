import test from "node:test";
import assert from "node:assert/strict";
import { createHlsGenerationObserver, generationFromHeartbeat, pilotGenerationFromHeartbeat, pilotMediaEndpoints } from "../src/pages/clientdetailspage/livestreamPilotTransport.mjs";

const id = "62b641a3-bdad-4454-a5fd-cfb8e6774582";

test("only an explicit server pilot and valid generation enable WSS", () => {
  assert.equal(pilotGenerationFromHeartbeat({ continuous_wss_pilot: true, generation: { id } }), id);
  for (const payload of [null, {}, { generation: { id } }, { continuous_wss_pilot: "true", generation: { id } },
    { continuous_wss_pilot: true, generation: { id: "../bad" } }]) {
    assert.equal(pilotGenerationFromHeartbeat(payload), null);
  }
});
test("generation-bound HTTPS ticket and WSS endpoints have no URL secrets", () => {
  const endpoints = pilotMediaEndpoints("https://api.example.test", 3, id);
  const path = "/api/livestream-wss/clients/3/generations/" + id;
  assert.deepEqual(endpoints, { ticket: "https://api.example.test" + path + "/ticket",
    subscribe: "wss://api.example.test" + path + "/subscribe" });
  for (const api of ["http://api.example.test", "https://user:secret@api.example.test",
    "https://api.example.test?token=secret", "https://api.example.test#secret"]) {
    assert.throws(() => pilotMediaEndpoints(api, 3, id));
  }
  assert.throws(() => pilotMediaEndpoints("https://api.example.test", "../3", id));
  assert.throws(() => pilotMediaEndpoints("https://api.example.test", 3, "../bad"));
});

test("ordinary HLS observes valid backend generations without enabling WSS", () => {
  assert.equal(generationFromHeartbeat({generation:{id}}),id);
  assert.equal(pilotGenerationFromHeartbeat({generation:{id}}),null);
  assert.equal(generationFromHeartbeat({generation:{id:"../bad"}}),null);
  assert.equal(generationFromHeartbeat(null),null);
});

test("manifest generation change is bound to successful media and rebuilds only once", () => {
  const seen = [], changes = [];
  const observe = createHlsGenerationObserver({onObserved: value => seen.push(value), onChange: value => changes.push(value)});
  const other = "11111111-1111-1111-1111-111111111111";
  const xhr = (value, status=200) => ({ status, getResponseHeader: key => key === "X-ClientFlow-HLS-Generation" ? value : null });
  observe(xhr(null)); observe(xhr("../bad")); observe(xhr(id)); observe(xhr(id));
  observe(xhr(other, 404)); assert.deepEqual(changes, []);
  observe(xhr(other)); observe(xhr(other)); observe(xhr(id));
  assert.deepEqual(changes, [other]);
  assert.deepEqual(seen, [id, id, other]);
});
