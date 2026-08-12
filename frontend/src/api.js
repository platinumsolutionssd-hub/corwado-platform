/**
 * API client — talks to the real FastAPI backend built Days 1-11.
 * No mock data lives here; every function is a real HTTP call.
 *
 * Set VITE_API_URL in a .env file (see .env.example) once the backend
 * is deployed. Defaults to localhost for local development against
 * `uvicorn app.main:app --reload`.
 */
import { BASE_URL } from './config.js';
import { auth } from './auth.js';

async function request(path, options = {}) {
  const token = auth.token();
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  // Any 401 means the session is gone/invalid: clear the token and let the
  // auth gate drop back to the login screen (auth.handleUnauthorized).
  if (res.status === 401) {
    auth.handleUnauthorized();
    throw new Error('Your session has ended — please sign in again.');
  }
  if (!res.ok) {
    const body = await res.text();
    // FastAPI's error shape is {"detail": "..."} -- surface that message
    // directly (it's already written for a human, e.g. stewards.py's
    // delete-conflict message) instead of the raw JSON blob, wherever
    // an error banner in the UI just renders err.message.
    let detail = body;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed.detail === 'string') detail = parsed.detail;
    } catch {
      // not JSON -- fall back to the raw body as-is
    }
    throw new Error(detail);
  }
  // 204 No Content etc.
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export const api = {
  health: () => request('/api/health'),
  me: () => request('/api/auth/me'),

  // --- Stewards (farmers / cooperative members) -----------------------
  listStewards: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/api/stewards${qs ? `?${qs}` : ''}`);
  },
  getSteward: (id) => request(`/api/stewards/${id}`),
  registerSteward: (data) =>
    request('/api/stewards', { method: 'POST', body: JSON.stringify(data) }),
  updateSteward: (id, data) =>
    request(`/api/stewards/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSteward: (id) =>
    request(`/api/stewards/${id}`, { method: 'DELETE' }),
  syncOfflineStewards: (batch) =>
    request('/api/stewards/sync', { method: 'POST', body: JSON.stringify(batch) }),

  // --- Parcels ----------------------------------------------------------
  listParcels: (stewardId) =>
    request(`/api/parcels${stewardId ? `?steward_id=${stewardId}` : ''}`),
  // confirmLargeArea: re-submits after the caller already saw a
  // confirmation_required response (see ParcelDrawStep) and the user
  // chose "save anyway" -- see app/routers/parcels.py's
  // LARGE_PARCEL_THRESHOLD_HA guardrail.
  registerParcel: (stewardId, geojson, confirmLargeArea = false) =>
    request('/api/parcels', {
      method: 'POST',
      body: JSON.stringify({ steward_id: stewardId, geojson, confirm_large_area: confirmLargeArea }),
    }),
  // Telegram BOUNDARY hand-off: same endpoint, single-use token instead
  // of steward_id -- see app/routers/parcels.py, which resolves (and
  // atomically consumes) the steward from the token server-side.
  getDrawToken: (token) => request(`/api/parcels/draw-token/${encodeURIComponent(token)}`),
  registerParcelWithToken: (token, geojson) =>
    request('/api/parcels', {
      method: 'POST',
      body: JSON.stringify({ token, geojson }),
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

  // --- Seasons (season_planting) ------------------------------------------
  // parcelId omitted -> every season across every parcel (used by the
  // dashboard table to derive a "crops planted" column without an
  // N+1 fetch per farmer).
  listSeasons: (parcelId) => request(`/api/seasons${parcelId ? `?parcel_id=${parcelId}` : ''}`),
  startSeason: (parcelId, crop, sowingDate, seasonLabel) =>
    request('/api/seasons', {
      method: 'POST',
      body: JSON.stringify({ parcel_id: parcelId, crop, sowing_date: sowingDate, season_label: seasonLabel }),
    }),

  // --- Bill of Quantities + financing ledger -------------------------------
  listInputRequirements: (seasonPlantingId) =>
    request(`/api/inputs/requirements?season_planting_id=${seasonPlantingId}`),
  seedBoqBaseline: (seasonPlantingId) =>
    request(`/api/inputs/seed-baseline?season_planting_id=${seasonPlantingId}`, { method: 'POST' }),
  overrideInputRequirement: (requirementId, unitCostUsd, overrideReason, overrideBy) =>
    request(`/api/inputs/requirements/${requirementId}`, {
      method: 'PATCH',
      body: JSON.stringify({ unit_cost_usd: unitCostUsd, override_reason: overrideReason, override_by: overrideBy }),
    }),
  listFinancingByRequirement: (inputRequirementId) =>
    request(`/api/inputs/financing?input_requirement_id=${inputRequirementId}`),
  listFinancingBySeason: (seasonPlantingId) =>
    request(`/api/inputs/financing?season_planting_id=${seasonPlantingId}`),
  recordFinancing: (inputRequirementId, financierType, amountUsd, financedAt, financierName, notes) =>
    request('/api/inputs/financing', {
      method: 'POST',
      body: JSON.stringify({
        input_requirement_id: inputRequirementId, financier_type: financierType,
        amount_usd: amountUsd, financed_at: financedAt,
        financier_name: financierName || null, notes: notes || null,
      }),
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
