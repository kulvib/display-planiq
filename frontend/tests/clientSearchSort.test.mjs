import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  clientMatchesSearch,
  organizationNamesById,
  sortLivestreamClients,
} from "../src/utils/clientSearchSort.mjs";

const organizations = organizationNamesById([
  { id: 10, name: "Aarhus Kultur" },
  { id: 20, name: "Østervang" },
]);
const clients = [
  { id: 56, name: "Viborg2", hostname: "nuc-v2", locality: "Grønnegade", organization_id: 20,
    wifi_ip_address: "192.168.126.170", presence: { is_online: true }, sort_order: 3 },
  { id: 42, name: "Randers1", locality: "Torvet", organization_id: 10,
    presence: { is_online: false }, sort_order: 1 },
  { id: 48, name: "Randers2", locality: "Banegården", organization_id: 10,
    presence: { is_online: true }, sort_order: 2 },
];

test("client search matches organization, identity, locality and network without modifying source", () => {
  for (const text of ["østervang", "ØSTERVANG", "viborg", "56", "Grønnegade", "192.168.126"]) {
    assert.deepEqual(clients.filter((c) => clientMatchesSearch(c, text, organizations)).map((c) => c.id), [56]);
  }
  assert.deepEqual(clients.filter((c) => clientMatchesSearch(c, "AARHUS", organizations)).map((c) => c.id), [42, 48]);
  assert.deepEqual(clients.filter((c) => clientMatchesSearch(c, "", organizations)).map((c) => c.id), [56, 42, 48]);
  assert.deepEqual(clients.filter((c) => clientMatchesSearch(c, "bogus", organizations)), []);
  assert.equal(clients.length, 3);
});

test("unavailable organizations are not incorrectly exposed via search", () => {
  assert.equal(clientMatchesSearch(clients[0], "østervang", new Map()), false);
  assert.equal(clientMatchesSearch(clients[0], "20", new Map()), false);
  assert.equal(clientMatchesSearch(clients[0], "nuc-v2", organizations), false, "hostname is not in the authorized list API");
});

test("livestream sort is immutable, stable and reflects requested order", () => {
  const before = JSON.stringify(clients);
  assert.deepEqual(sortLivestreamClients(clients, "online").map((c) => c.id), [48, 56, 42]);
  assert.deepEqual(sortLivestreamClients(clients, "name").map((c) => c.id), [42, 48, 56]);
  assert.deepEqual(sortLivestreamClients(clients, "name_desc").map((c) => c.id), [56, 48, 42]);
  assert.deepEqual(sortLivestreamClients(clients, "manual").map((c) => c.id), [42, 48, 56]);
  assert.deepEqual(sortLivestreamClients(clients, "location").map((c) => c.id), [48, 56, 42]);
  assert.deepEqual(sortLivestreamClients(clients, "organization", organizations).map((c) => c.id), [56, 42, 48]);
  assert.equal(JSON.stringify(clients), before);
});

test("frontend filtering never writes manual drag-order to backend", () => {
  const list = readFileSync(new URL("../src/pages/ClientInfoPage.jsx", import.meta.url), "utf8");
  assert.match(list, /visibleApprovedClients\.map\(/);
  assert.match(list, /isDragDisabled=\{[\s\S]*?searchActive/);
  assert.match(list, /if \(!canManageClients \|\| searchActive\)/);
  assert.match(list, /clientMatchesSearch\(c, clientSearch, organizationNameMap\)/);
  const live = readFileSync(new URL("../src/pages/adminpages/LivestreamOverview.jsx", import.meta.url), "utf8");
  assert.match(live, /getOrganizations\(\)\.then/);
  assert.match(live, /sortLivestreamClients/);
  assert.match(live, /clientMatchesSearch/);
  assert.match(live, /<LivestreamTile key=\{client\.id\}/);
  assert.doesNotMatch(live, /getOrganizations\(\)[\s\S]{0,200}setInterval/);
});
