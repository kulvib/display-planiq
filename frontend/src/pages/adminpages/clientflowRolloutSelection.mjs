/** Version-independent, explicit organization and client selection. */
export function organizationKey(row) {
  const id = row?.organization_id;
  if (id == null) return "none";
  if (!Number.isSafeInteger(id) || id <= 0) throw new Error("Ugyldig organisation");
  return String(id);
}

export function organizationOptions(rows) {
  const groups = new Map();
  for (const row of rows) {
    const key = organizationKey(row);
    groups.set(key, row.organization_name || (key === "none" ? "Ingen organisation" : "Organisation #" + key));
  }
  return [...groups].sort((a,b) => a[1].localeCompare(b[1], "da") || a[0].localeCompare(b[0]));
}

export function organizationScope(key) {
  if (key === "all") return {kind:"all", organization_id:null};
  if (key === "none") return {kind:"unassigned", organization_id:null};
  const id = Number(key);
  if (!Number.isSafeInteger(id) || id <= 0 || String(id) !== key) throw new Error("Ugyldigt organisationsfilter");
  return {kind:"organization", organization_id:id};
}

export function filterRolloutClients(rows, key, query = "") {
  organizationScope(key);
  const needle = query.trim().toLocaleLowerCase("da");
  return rows.filter(row => (key === "all" || organizationKey(row) === key) &&
    [row.name, row.id, row.locality, row.organization_name].filter(Boolean).join(" ").toLocaleLowerCase("da").includes(needle));
}

export function visibleSelection(selected, visible, max) {
  if (!Number.isSafeInteger(max) || max < 1) throw new Error("Ugyldig bestillingsgrænse");
  const ids = new Set(visible.map(row=>row.id));
  const result = [...new Set(selected)].filter(id=>ids.has(id));
  if (result.length > max) throw new Error("For mange klienter valgt");
  return result;
}

export function bindOrganizationTargets(targets, visible, key) {
  const scope = organizationScope(key);
  const lookup = new Map(visible.map(row=>[row.id,row]));
  return targets.map(target=>{
    const row = lookup.get(target.client_id);
    if (!row || (key !== "all" && organizationKey(row) !== key)) throw new Error("Klientvalget eller organisationen er ændret");
    const id = organizationKey(row);
    return {...target, expected_organization_id:id === "none" ? null : Number(id)};
  });
}
