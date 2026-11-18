import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { evaluateDependencyAudit } from "./dependencyAuditPolicy.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");
const allowlist = JSON.parse(fs.readFileSync(path.join(frontendRoot, "dependency-audit-allowlist.json"), "utf8"));
const lock = JSON.parse(fs.readFileSync(path.join(frontendRoot, "package-lock.json"), "utf8"));

const result = spawnSync("npm", ["audit", "--json"], {
  cwd: frontendRoot,
  encoding: "utf8",
  shell: process.platform === "win32",
});

if (!result.stdout?.trim()) {
  console.error(result.stderr || "npm audit returnerede intet JSON-svar.");
  process.exit(2);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch (error) {
  console.error("npm audit-svaret kunne ikke parses som JSON.", error);
  process.exit(2);
}
if (result.error || (result.status !== 0 && result.status !== 1) || !report?.metadata) {
  console.error("npm audit returnerede ikke en gyldig komplet auditrapport.", result.stderr || result.error);
  process.exit(2);
}

const today = new Date().toISOString().slice(0, 10);
let evaluation;
try {
  evaluation = evaluateDependencyAudit(report, allowlist, lock, today);
} catch (error) {
  console.error("Dependency-audit-politikken fejlede lukket:", error.message);
  process.exit(2);
}
if (evaluation.accepted.length) {
  console.warn("Midlertidig dev-only picomatch-undtagelse og arvede meta-advisories:");
  for (const name of evaluation.accepted) console.warn(`- ${name}`);
  for (const name of evaluation.exceptionsUsed) {
    const entry = allowlist.exceptions.find((item) => item.package === name);
    console.warn(`  Kun ${name}@${entry.lockedVersion} / ${entry.advisories.join(", ")} (udløber ${entry.expires})`);
  }
}
if (evaluation.unexpected.length) {
  console.error("Uventede eller udløbne frontend-advisories:");
  for (const item of evaluation.unexpected) {
    console.error(`- ${item.packageName} (${item.severity}): ${item.advisoryIds.join(", ") || item.inheritedFrom.join(" -> ") || item.reason || "ukendt advisory"}`);
  }
  process.exit(1);
}
console.log(`Frontend dependency-audit bestået (${evaluation.total} rapporterede, ${evaluation.exceptionsUsed.length} tidsbegrænset dev-only-undtagelse).`);
