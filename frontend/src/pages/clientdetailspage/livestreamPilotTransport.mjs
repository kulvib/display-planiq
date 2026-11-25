// Shared pilot adapter. Existing heartbeat/leave remains the sole viewer
// lifecycle authority; this module only owns the browser media transport.
import { createLivestreamTransportController } from "./livestreamTransportController.mjs";
import { createWssPlayer } from "./livestreamWssPlayer.mjs";

const GENERATION = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function generationFromHeartbeat(payload) {
  const id = payload?.generation?.id;
  return typeof id === "string" && GENERATION.test(id) ? id : null;
}
export function pilotGenerationFromHeartbeat(payload) {
  return payload?.continuous_wss_pilot === true ? generationFromHeartbeat(payload) : null;
}

export function pilotMediaEndpoints(apiUrl, clientId, generation, base = globalThis.location?.href) {
  if (!/^[1-9][0-9]*$/.test(String(clientId)) || !GENERATION.test(generation)) throw new Error("invalid pilot binding");
  const endpoint = new URL(apiUrl, base);
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash)
    throw new Error("invalid media origin");
  const path = endpoint.pathname.replace(/\/+$/, "") + "/api/livestream-wss/clients/" + clientId + "/generations/" + generation;
  endpoint.pathname = path + "/ticket";
  const ticket = endpoint.href;
  endpoint.protocol = "wss:";
  endpoint.pathname = path + "/subscribe";
  return { ticket, subscribe: endpoint.href };
}

export function createPilotTransport(video, {
  apiUrl, clientId, generation, viewerId, authenticatedFetch, authHeaders,
  getAuthSessionSignal, startHls, onTransport, onWssPlayable, onFailure,
}) {
  async function requestTicket({ signal }, probeOnly) {
    const endpoints = pilotMediaEndpoints(apiUrl, clientId, generation);
    const response = await authenticatedFetch(endpoints.ticket, {
      method: "POST", credentials: "include", cache: "no-store",
      headers: { ...authHeaders(), "Content-Type": "application/json", accept: "application/json" },
      body: JSON.stringify({ viewer_id: viewerId, probe_only: probeOnly }),
      signal: AbortSignal.any([signal, getAuthSessionSignal(), AbortSignal.timeout(4000)]),
    });
    if (!response.ok) throw new Error("media ticket unavailable");
    return response.json();
  }
  return createLivestreamTransportController({
    startHls, onTransport, onFailure,
    probeWss: async options => (await requestTicket(options, true))?.available === true,
    startWss: callbacks => {
      if (typeof MediaSource === "undefined" || typeof WebSocket === "undefined") {
        callbacks.onFailure("unsupported-codec");
        return { dispose() {} };
      }
      return createWssPlayer(video, {
        url: pilotMediaEndpoints(apiUrl, clientId, generation).subscribe,
        getTicket: options => requestTicket(options, false),
        onPlayable: () => { onWssPlayable(); callbacks.onPlayable(); },
        onFailure: callbacks.onFailure,
        // A buffered-edge distance alone is not end-to-end delay. Do not
        // display it as the existing comparable live-edge estimate.
      });
    },
  });
}
