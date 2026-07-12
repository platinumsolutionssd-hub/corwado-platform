/**
 * API client — talks to the real FastAPI backend built Days 1-11.
 * No mock data lives here; every function is a real HTTP call.
 *
 * Set VITE_API_URL in a .env file (see .env.example) once the backend
 * is deployed. Defaults to localhost for local development against
 * `uvicorn app.main:app --reload`.
 */
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API error ${res.status} on ${path}: ${body}`);
  }
  // 204 No Content etc.
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export const api = {
  health: () => request('/api/health'),

  // --- Stewards (farmers / cooperative members) -----------------------
  listStewards: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/api/stewards${qs ? `?${qs}` : ''}`);
  },
  getSteward: (id) => request(`/api/stewards/${id}`),
  registerSteward: (data) =>
    request('/api/stewards', { method: 'POST', body: JSON.stringify(data) }),
  syncOfflineStewards: (batch) =>
    request('/api/stewards/sync', { method: 'POST', body: JSON.stringify(batch) }),

  // --- Parcels ----------------------------------------------------------
  listParcels: (stewardId) =>
    request(`/api/parcels${stewardId ? `?steward_id=${stewardId}` : ''}`),
  registerParcel: (stewardId, geojson) =>
    request('/api/parcels', {
      method: 'POST',
      body: JSON.stringify({ steward_id: stewardId, geojson }),
    }),

  // --- Advisory -----------------------------------------------------------
  getBaseline: (parcelId, crop, forceRefresh = false) =>
    request(`/api/advisory/parcel/${parcelId}/baseline?crop=${encodeURIComponent(crop)}${forceRefresh ? '&force_refresh=true' : ''}`),
  getLiveAdvisory: (parcelId, source = 'satyukt_sat2farm') =>
    request(`/api/advisory/parcel/${parcelId}/live?source=${source}`),
  getAdvisoryHistory: (parcelId) =>
    request(`/api/advisory/parcel/${parcelId}/history`),
  getDiagnostic: (parcelId, depth = 'quick', forceRefresh = false) =>
    request(`/api/advisory/parcel/${parcelId}/diagnostic?depth=${depth}${forceRefresh ? '&force_refresh=true' : ''}`),
  getThumbnail: (parcelId, kind) =>
    request(`/api/advisory/parcel/${parcelId}/thumbnail/${kind}`),

  // --- Market linkage ---------------------------------------------------
  listPrices: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/api/market/prices${qs ? `?${qs}` : ''}`);
  },
  recordPrice: (data) =>
    request('/api/market/prices', { method: 'POST', body: JSON.stringify(data) }),
  listPostings: (status = 'open') => request(`/api/market/postings?status=${status}`),
  findMatches: (postingId) => request(`/api/market/postings/${postingId}/matches`),
  confirmMatch: (postingId, aggregationEventId) =>
    request(`/api/market/postings/${postingId}/confirm-match?aggregation_event_id=${aggregationEventId}`, {
      method: 'POST',
    }),

  // --- Dispatch -----------------------------------------------------------
  dispatchAdvisory: (parcelId) =>
    request(`/api/dispatch/advisory/${parcelId}`, { method: 'POST' }),
  dispatchRadio: (payam, contentType, contentRefId) =>
    request(`/api/dispatch/radio/${payam}?content_type=${contentType}${contentRefId ? `&content_ref_id=${contentRefId}` : ''}`, {
      method: 'POST',
    }),
  dispatchLog: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/api/dispatch/log${qs ? `?${qs}` : ''}`);
  },
  dispatchStats: () => request('/api/dispatch/stats'),
};
