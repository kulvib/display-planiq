import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { evaluateDependencyAudit } from "../scripts/dependencyAuditPolicy.mjs";

const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url)));
const activeAllowlist = JSON.parse(readFileSync(new URL("../dependency-audit-allowlist.json", import.meta.url)));
// Historical fixture: exercises strict exception handling without enabling a real waiver.
const allowlist = { exceptions: [{
  package: "picomatch", lockedVersion: "4.0.5",
  advisories: ["GHSA-fc5q-39xc-vjpf"], expires: "2026-11-25",
  scope: "dev-only", replacementPlan: "Historical regression fixture only",
}] };
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
  assert.deepEqual(result.dormantExceptions, []);
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

test("aktiv allowlist er tom efter officiel tilbagetrækning; ren audit består uden undtagelser", () => {
  const clean = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  assert.deepEqual(activeAllowlist.exceptions, []);
  const result = evaluate(clean, activeAllowlist, lock, "2026-11-26");
  assert.deepEqual(result.unexpected, []);
  assert.deepEqual(result.exceptionsUsed, []);
  assert.deepEqual(result.dormantExceptions, []);
  assert.equal(evaluate(report(), activeAllowlist, lock, "2026-11-26").unexpected.length, 5);
});

test("ikke-rapporteret advisory berettiger ikke en ubrugt undtagelse", () => {
  const clean = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  const result = evaluate(clean);
  assert.deepEqual(result.unexpected.map((item) => item.packageName), ["picomatch"]);
  assert.deepEqual(result.exceptionsUsed, []);
  assert.deepEqual(result.dormantExceptions, []);
});

test("manglende advisory fritager ikke en ændret version, runtime-afhængighed eller devOptional", () => {
  const clean = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  for (const change of [
    (entry) => { entry.version = "4.0.6"; },
    (entry) => { entry.dev = false; },
    (entry) => { entry.devOptional = true; },
  ]) {
    const modified = structuredClone(lock);
    change(modified.packages["node_modules/picomatch"]);
    assert.deepEqual(evaluate(clean, allowlist, modified).unexpected.map((item) => item.packageName), ["picomatch"]);
  }
  const missing = structuredClone(lock);
  delete missing.packages["node_modules/picomatch"];
  assert.deepEqual(evaluate(clean, allowlist, missing).unexpected.map((item) => item.packageName), ["picomatch"]);
});

test("manglende advisory afviser også ændrede undtagelser", () => {
  const clean = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  for (const mutate of [
    (entry) => { entry.advisories = ["GHSA-2345-6789-cfgh"]; },
    (entry) => { entry.expires = "2026-11-26"; },
    (entry) => { entry.package = "fdir"; entry.lockedVersion = lock.packages["node_modules/fdir"].version; },
  ]) {
    const modified = structuredClone(allowlist);
    mutate(modified.exceptions[0]);
    assert.deepEqual(evaluate(clean, modified).unexpected.map((item) => item.packageName), [modified.exceptions[0].package]);
  }
});

test("den ikke-rapporterede picomatch-undtagelse udløber fortsat", () => {
  const clean = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 0 } } };
  assert.throws(() => evaluate(clean, allowlist, lock, "2026-11-26"), /udløbet/);
});

test("rapport med positiv tæller uden advisory-details fejler lukket", () => {
  const broken = { vulnerabilities: {}, metadata: { vulnerabilities: { total: 1 } } };
  const result = evaluate(broken);
  assert.deepEqual(result.unexpected.map((item) => item.packageName), ["picomatch", "npm audit"]);
  assert.deepEqual(result.dormantExceptions, []);
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
