import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const admin = readFileSync(path.join(root, "frontend/src/pages/adminpages/AdminPage.jsx"), "utf8");
const page = readFileSync(path.join(root, "frontend/src/pages/adminpages/OperationalIncidents.jsx"), "utf8");
const backend = readFileSync(path.join(root, "backend/service1/routers/operational_incidents.py"), "utf8");

test("incident view is gated by the superadmin-only admin section", () => {
  assert.match(admin, /key: "incidents"[\s\S]*?superadminOnly: true/);
  assert.match(admin, /activeSection === "incidents" &&[\s\S]*?isSuperadmin \?/);
  assert.match(backend, /Depends\(get_current_superadmin_user\)/);
});

test("incident view distinguishes active, stale and recovery states", () => {
  assert.match(page, /"active"/);
  assert.match(page, /"resolved"/);
  assert.match(page, /verification === "stale"/);
  assert.match(page, /En genstart løser aldrig automatisk en fejl/);
  assert.match(page, /genstarten var årsagen/);
  assert.match(page, /\.get\(`\/api\/superadmin\/operational-incidents/);
  assert.doesNotMatch(page, /localStorage|sessionStorage/);
});

test("fleet report coverage is gated, does not claim scanner execution, and distinguishes missing reports", () => {
  assert.match(backend, /@router\.get\("\/report-coverage"\)[\s\S]*?Depends\(get_current_superadmin_user\)/);
  assert.match(page, /Dækning af klientrapporter/);
  assert.match(page, /rapportdækningen kunne ikke hentes/i);
  assert.match(page, /fejldetektorens baggrundsscanner kører/);
  assert.match(page, /domain\.missing/);
  assert.match(page, /domain\.stale/);
  assert.match(page, /operational-incidents\/report-coverage/);
});
