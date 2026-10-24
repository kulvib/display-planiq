import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const terminal = readFileSync(path.join(root, "frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx"), "utf8");
const wifi = readFileSync(path.join(root, "frontend/src/pages/clientdetailspage/terminal/wifiSupportCommands.mjs"), "utf8");

const expected = [
  "ClientFlow samlet status", "Display / kiosk browser", "Aktiv release / updater",
  "Livestream v2 status", "Terminal status", "Remote Desktop status",
  "Aktive ClientFlow units", "Ubuntu / APT health", "Disk, RAM og oppetid",
  "Netværk, DNS, tid og backend", "WiFi / NetworkManager diagnose",
  "Tilføj WiFi-profil (uden aktivering)", "Test gemt WiFi (auto-rollback)",
  "Rollbackrapportering / outbox", "Display/browser logs", "Status/System logs",
  "Livestream logs", "Terminal logs", "Remote Desktop logs",
];

test("all 19 diagnostic helpers are distinct and structurally present", () => {
  const labels = [...terminal.matchAll(/\{ label: "([^"]+)", command:/g)].map((x) => x[1]);
  assert.deepEqual(new Set(labels).size, labels.length, "Duplicate support commands");
  for (const label of expected) assert.ok(labels.includes(label), `Missing ${label}`);
  assert.equal(labels.length, expected.length, "Audit must cover every support item");
});

test("all built-in terminal Bash scripts parse as both wrapper and body", () => {
  const scripts = [...terminal.matchAll(/const (\w+_COMMAND) = `([\s\S]*?)`;/g),
    ...wifi.matchAll(/export const (\w+_COMMAND) = `([\s\S]*?)`;/g)];
  assert.ok(scripts.length >= 11, "Unexpected missing scripts");
  for (const [, name, script] of scripts) {
    assert.ok(script.startsWith("cat <<'CLIENTFLOW_"), `${name}: missing protected here-document`);
    for (const source of [script, script.split("\n").slice(1, -1).join("\n")]) {
      const parsed = spawnSync("bash", ["-n"], { input: source, encoding: "utf8" });
      assert.equal(parsed.status, 0, `${name}: ${parsed.stderr}`);
    }
  }
});

test("terminal referenced ClientFlow units exist in immutable client source", () => {
  const known = new Set([
    ...readdirSync(path.join(root, "client/systemd")),
    ...readdirSync(path.join(root, "client/stable-systemd")),
  ]);
  const units = new Set(terminal.match(/\b(?:clientflow|planiq)-[\w-]+\.(?:service|socket|target|timer)\b/g) || []);
  assert.ok(units.size >= 25);
  for (const name of units) assert.ok(known.has(name), `No canonical unit for ${name}`);
});

test("diagnostic helpers do not dump signed kiosk URL, tokens or WiFi credentials", () => {
  assert.match(terminal, /Sanitiseret Display runtime/);
  assert.match(terminal, /configuration\.json/);
  assert.match(terminal, /Rollbackrapportering \/ outbox/);
  assert.match(terminal, /\/var\/lib\/planiq-rollback-outbox/);
  assert.doesNotMatch(terminal, /cat "\$f" 2>\/dev\/null \| python3 -m json\.tool/);
  assert.doesNotMatch(terminal, /python3 -m json\.tool "\$f"/);
  assert.doesNotMatch(wifi, /--show-secrets|show-password/);
});
