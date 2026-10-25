import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const srcRoot = fileURLToPath(new URL("../src/", import.meta.url));

function jsxFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return jsxFiles(fullPath);
    return entry.isFile() && /\.(jsx|tsx)$/.test(entry.name) ? [fullPath] : [];
  });
}

// JS transforms can turn an unresolved JSX name into a runtime ReferenceError.
// Source-contract tests catch those references even when browser tests cannot run locally.
function unboundComponentNames(source) {
  const used = new Set([...source.matchAll(/<([A-Z][A-Za-z0-9_]*)\b/g)].map((match) => match[1]));
  const declared = new Set([...source.matchAll(/\b(?:const|let|class|function)\s+([A-Z][A-Za-z0-9_]*)\b/g)].map((match) => match[1]));

  for (const match of source.matchAll(/\bimport\s+([\s\S]*?)\s+from\s+["'][^"']+["']\s*;?/g)) {
    for (const identifier of match[1].matchAll(/\b([A-Z][A-Za-z0-9_]*)\b/g)) declared.add(identifier[1]);
  }

  return [...used].filter((identifier) => !declared.has(identifier)).sort();
}

test("All frontend JSX capitalized components are locally declared or imported", () => {
  const missing = jsxFiles(srcRoot).flatMap((file) =>
    unboundComponentNames(readFileSync(file, "utf8")).map((name) =>
      `${path.relative(srcRoot, file)}: <${name}>`,
    ),
  );
  assert.deepEqual(missing, [], `Unresolved JSX components can crash their pages at runtime:\n${missing.join("\n")}`);
});

test("Adgang regression guard detects a missing Stack import", () => {
  const file = path.join(srcRoot, "pages/adminpages/UserAdministration.jsx");
  const source = readFileSync(file, "utf8");
  assert.match(source, /<Stack\b/);
  assert.deepEqual(unboundComponentNames(source), []);
  assert.match(source, /\bStack\s*,\s*Table\b/);
  const withoutImport = source.replace(/\n\s*Stack,\s*\n/, "\n");
  assert.notEqual(withoutImport, source, "Stack must be a named import");
  assert.ok(unboundComponentNames(withoutImport).includes("Stack"), "Removed Stack import must fail this guard");
});
