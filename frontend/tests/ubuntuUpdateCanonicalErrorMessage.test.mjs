import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(
  path.resolve(here, "../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx"), "utf8"
);
const start = source.indexOf("function getUbuntuHumanMessage(");
const end = source.indexOf("function getUbuntuSearchText(", start);
assert.ok(start >= 0 && end > start);
// Exercise the actual pure rendering helper, not a duplicate of its logic.
const message = new Function("client", "localStatus", `${source.slice(start, end)}; return getUbuntuHumanMessage(client, localStatus);`);

test("canonical in-doubt failure replaces stale agent-waiting message", () => {
  const actual = message({
    ubuntu_update_status: "error",
    ubuntu_update_error: "system_command_in_doubt",
    ubuntu_update_message: "Ubuntu-opdatering fejlede",
    os_update_message: "Ubuntu-opdatering afventer System-agent",
  }, { phase: "requested", message: "Ubuntu-opdatering afventer System-agent" });
  assert.match(actual, /resultatet skal kontrolleres lokalt/i);
  assert.doesNotMatch(actual, /afventer System-agent/);
});

test("canonical success replaces previous transient error", () => {
  assert.equal(message({
    ubuntu_update_status: "success",
    ubuntu_update_message: "Ubuntu-opdatering gennemført",
  }, { error: "Ubuntu-opdatering afventer System-agent" }), "Ubuntu-opdatering gennemført");
});

test("non-terminal projected status keeps local pending feedback", () => {
  assert.equal(message({
    ubuntu_update_status: "requested",
    ubuntu_update_message: "Ubuntu-opdatering afventer System-agent",
  }, { message: "Ubuntu-opdatering er bestilt" }), "Ubuntu-opdatering er bestilt");
});
