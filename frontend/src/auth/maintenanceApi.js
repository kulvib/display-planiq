import client from "../api/client";
import { createApiError, normalizeApiError } from "../api/apiError";

async function readJson(res, fallback) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) throw createApiError({ response: res, body, fallback });
  return body;
}

export async function getMaintenanceStatus(signal) {
  try {
    const res = await fetch("/api/maintenance/status", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      // Same-origin avoids browser CORS masking Render edge 502 responses.
      // Public status is already no-store on the server. No extra
      // Cache-Control request-header: den udløser unødvendig CORS-preflight.
      signal,
    });
    return readJson(res, "Vedligeholdelsesstatus kunne ikke hentes");
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw normalizeApiError(error, "Vedligeholdelsesstatus kunne ikke hentes");
  }
}

export async function updateMaintenanceStatus(payload) {
  const { data } = await client.put("/api/maintenance", payload);
  return data;
}
