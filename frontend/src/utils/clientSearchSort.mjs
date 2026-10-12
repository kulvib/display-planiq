// Pure client-side views over the already authorized Control Room projection.
// Never expand a user's access scope or request the backend on keystrokes.
export function organizationNamesById(organizations = []) {
  return new Map(organizations.map((org) => [String(org.id), String(org.name || "")]));
}

function normalized(value) {
  return String(value ?? "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("da-DK").trim();
}

function organizationName(client, namesById) {
  return namesById.get(String(client?.organization_id ?? client?.organizationId ?? "")) || "";
}

export function clientMatchesSearch(client, search, namesById = new Map()) {
  const query = normalized(search);
  if (!query) return true;
  const fields = [
    client?.id,
    client?.name,
    client?.hostname,
    client?.locality,
    client?.location,
    organizationName(client, namesById),
    client?.active_network_ip,
    client?.wifi_ip_address,
    client?.lan_ip_address,
  ];
  return fields.some((value) => normalized(value).includes(query));
}

const COLLATOR = new Intl.Collator("da-DK", { numeric: true, sensitivity: "base" });

export function sortLivestreamClients(clients, order = "online", namesById = new Map()) {
  const sorted = [...clients];
  const byName = (a, b) => COLLATOR.compare(String(a.name || ""), String(b.name || "")) ||
    COLLATOR.compare(String(a.id ?? ""), String(b.id ?? ""));
  sorted.sort((a, b) => {
    if (order === "online") {
      const rank = Number(b?.presence?.is_online === true) - Number(a?.presence?.is_online === true);
      if (rank !== 0) return rank;
    }
    if (order === "location") {
      const rank = COLLATOR.compare(String(a.locality || a.location || ""), String(b.locality || b.location || ""));
      if (rank !== 0) return rank;
    }
    if (order === "organization") {
      const rank = COLLATOR.compare(organizationName(a, namesById), organizationName(b, namesById));
      if (rank !== 0) return rank;
    }
    if (order === "manual") {
      const aOrder = Number.isFinite(Number(a.sort_order)) && a.sort_order != null ? Number(a.sort_order) : Infinity;
      const bOrder = Number.isFinite(Number(b.sort_order)) && b.sort_order != null ? Number(b.sort_order) : Infinity;
      if (aOrder !== bOrder) return aOrder - bOrder;
    }
    return order === "name_desc" ? -byName(a, b) : byName(a, b);
  });
  return sorted;
}
