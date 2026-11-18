import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { evaluateDependencyAudit } from "../scripts/dependencyAuditPolicy.mjs";

const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url)));
const allowlist = JSON.parse(readFileSync(new URL("../dependency-audit-allowlist.json", import.meta.url)));
const date = "2026-11-18";
const advisory = {
  name: "picomatch", severity: "high",
  url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf",
};

function report() {
  return {
    auditReportVersion: 2,
    vulnerabilities: {
      picomatch: { severity: "high", via: [advisory] },
      fdir: { severity: "high", via: ["picomatch"] },
      tinyglobby: { severity: "high", via: ["fdir", "picomatch"] },
      vite: { severity: "high", via: ["tinyglobby", "picomatch"] },
      "@vitejs/plugin-react": { severity: "high", via: ["vite"] },
    },
    metadata: { vulnerabilities: { high: 5, total: 5 } },
  };
}

function evaluate(customReport = report(), customAllowlist = allowlist, customLock = lock, today = date) {
  return evaluateDependencyAudit(customReport, customAllowlist, customLock, today);
}

test("kun picomatch GHSA samt dokumenterede dev-only meta-advisories accepteres", () => {
  const result = evaluate();
  assert.deepEqual(result.unexpected, []);
  assert.deepEqual(result.exceptionsUsed, ["picomatch"]);
  assert.deepEqual(result.accepted, ["@vitejs/plugin-react", "fdir", "picomatch", "tinyglobby", "vite"]);
});

test("ny direkte advisory i vite må aldrig arve picomatch-undtagelsen", () => {
  const custom = report();
  custom.vulnerabilities.vite.via.push({
    name: "vite", url: "https://github.com/advisories/GHSA-2345-6789-cfgh",
  });
  assert.deepEqual(evaluate(custom).unexpected.map((item) => item.packageName), ["vite", "@vitejs/plugin-react"]);
});

test("ny direkte advisory i picomatch afvises, også hvis den gamle stadig er til stede", () => {
  const custom = report();
  custom.vulnerabilities.picomatch.via.push({
    url: "https://github.com/advisories/GHSA-2345-6789-cfgh",
  });
  assert.equal(evaluate(custom).unexpected.length, 5);
});

test("uidentificeret direkte advisory er ikke en metafinding og afvises", () => {
  const custom = report();
  custom.vulnerabilities.vite.via.push({ name: "vite", title: "ukendt security issue" });
  assert.deepEqual(evaluate(custom).unexpected.map((item) => item.packageName), ["vite", "@vitejs/plugin-react"]);
});

test("nye eller ikke-auditerede meta-afhængigheder afvises", () => {
  const custom = report();
  custom.vulnerabilities.vite.via.push("ukendt-pakke");
  assert.deepEqual(evaluate(custom).unexpected.map((item) => item.packageName), ["vite", "@vitejs/plugin-react"]);
});

test("meta-advisories kræver ægte dependency- eller peerDependency-kæder i lock", () => {
  const custom = report();
  custom.vulnerabilities.vite.via = ["fdir"]; // Vite afhænger ikke direkte af fdir.
  assert.deepEqual(evaluate(custom).unexpected.map((item) => item.packageName), ["vite", "@vitejs/plugin-react"]);
});

test("produktionsafhængighed kan ikke undtages", () => {
  const changedLock = structuredClone(lock);
  changedLock.packages["node_modules/picomatch"].dev = false;
  assert.equal(evaluate(report(), allowlist, changedLock).unexpected.length, 5);
});

test("devOptional-tilfælde kan ikke smugles ind i en dev-only-undtagelse", () => {
  const changedLock = structuredClone(lock);
  changedLock.packages["node_modules/picomatch"].devOptional = true;
  assert.equal(evaluate(report(), allowlist, changedLock).unexpected.length, 5);
});

test("ændret låst version kræver en ny sikkerhedsvurdering", () => {
  const changedLock = structuredClone(lock);
  changedLock.packages["node_modules/picomatch"].version = "4.0.6";
  assert.equal(evaluate(report(), allowlist, changedLock).unexpected.length, 5);
});

test("udløbet undtagelse afviser hele kæden", () => {
  assert.throws(() => evaluate(report(), allowlist, lock, "2026-11-26"), /udløbet/);
});

test("overflødig undtagelse efter rettelse skal aktivt fjernes", () => {
  const clean = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  assert.deepEqual(evaluate(clean).unexpected.map((item) => item.packageName), ["picomatch"]);
});

test("rapport med positiv tæller uden advisory-details fejler lukket", () => {
  const broken = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 1 } } };
  const result = evaluate(broken);
  assert.deepEqual(result.unexpected.map((item) => item.packageName), ["picomatch", "npm audit"]);
});

test("legacy npm advisories-format accepterer kun den præcise GHSA", () => {
  const legacy = { advisories: { 100: { module_name: "picomatch", severity: "high", github_advisory_id: "GHSA-fc5q-39xc-vjpf" } }, metadata: { vulnerabilities: { total: 1 } } };
  assert.deepEqual(evaluate(legacy).unexpected, []);
  legacy.advisories[101] = { module_name: "picomatch", severity: "high", github_advisory_id: "GHSA-2345-6789-cfgh" };
  assert.equal(evaluate(legacy).unexpected.length, 1);
});

test("bred eller mangelfuld undtagelse afvises straks", () => {
  const changed = structuredClone(allowlist);
  delete changed.exceptions[0].lockedVersion;
  assert.throws(() => evaluate(report(), changed), /Ugyldig/);
  changed.exceptions[0].lockedVersion = "4.0.5";
  changed.exceptions[0].scope = "all";
  assert.throws(() => evaluate(report(), changed), /Ugyldig/);
});
