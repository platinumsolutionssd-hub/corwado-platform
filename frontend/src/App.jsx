import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Users, Sprout, TrendingUp, Radio, MessageSquare, Phone, Smartphone, Plus, X, CheckCircle2, Signal, Loader2, MapPin, Undo2, RotateCcw, ArrowLeft, Building2, Layers, Send, AlertTriangle, GraduationCap, FlaskConical, Image as ImageIcon } from 'lucide-react';
import { MapContainer, TileLayer, Polygon, CircleMarker, useMapEvents } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { api } from './api.js';

// Registration includes a farm-boundary drawing step, backed by the real
// POST /api/parcels endpoint (app/routers/parcels.py) — PostGIS wants a
// closed ring (first position repeated as the last), which the browser
// click-to-add-point flow below doesn't naturally produce.
function closeRing(points) {
  if (points.length < 3) return null;
  const ring = points.map(([lat, lng]) => [lng, lat]); // GeoJSON is [lon, lat]
  ring.push(ring[0]);
  return ring;
}

// Default view centers on Western Bahr el Ghazal (CORWADO's actual
// operating area) rather than wherever earlier test parcels happened to
// be drawn — field staff drawing a real boundary need the map to open
// near their farmers, not near an unrelated prior test coordinate.
const DEFAULT_MAP_CENTER = [7.7025, 28.0092]; // Wau, South Sudan
const DEFAULT_MAP_ZOOM = 13;

function ClickToAddPoint({ onAdd }) {
  useMapEvents({
    click(e) {
      onAdd([e.latlng.lat, e.latlng.lng]);
    },
  });
  return null;
}

function ParcelDrawStep({ steward, onSaved, onSkip }) {
  const [points, setPoints] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const canSave = points.length >= 3;

  async function handleSave() {
    const ring = closeRing(points);
    if (!ring) return;
    setSaving(true);
    setError(null);
    try {
      const parcel = await api.registerParcel(steward.id, { type: 'Polygon', coordinates: [ring] });
      onSaved(parcel);
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: COLORS.charcoal + 'aa', marginTop: 0 }}>
        Click the map to trace <strong>{steward.full_name}</strong>'s farm boundary, point by point.
        Add at least 3 points, then save. This posts a real GeoJSON polygon to <code>POST /api/parcels</code>.
      </p>

      <div style={{ borderRadius: 10, overflow: 'hidden', border: `1px solid ${COLORS.sage}66`, height: 360 }}>
        <MapContainer center={DEFAULT_MAP_CENTER} zoom={DEFAULT_MAP_ZOOM} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <ClickToAddPoint onAdd={(p) => setPoints(prev => [...prev, p])} />
          {points.length >= 2 && <Polygon positions={points} pathOptions={{ color: COLORS.ochre, fillColor: COLORS.forest, fillOpacity: 0.25 }} />}
          {points.map((p, i) => (
            <CircleMarker key={i} center={p} radius={5} pathOptions={{ color: COLORS.forest, fillColor: '#fff', fillOpacity: 1, weight: 2 }} />
          ))}
        </MapContainer>
      </div>

      {error && <ErrorBanner message={error} />}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: COLORS.charcoal + '88' }}>{points.length} point{points.length === 1 ? '' : 's'} placed</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" onClick={() => setPoints(prev => prev.slice(0, -1))} disabled={!points.length}
            style={{ background: 'none', border: `1px solid ${COLORS.sage}66`, borderRadius: 8, padding: '8px 12px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6, opacity: points.length ? 1 : 0.5 }}>
            <Undo2 size={14} aria-hidden="true" /> Undo point
          </button>
          <button type="button" onClick={() => setPoints([])} disabled={!points.length}
            style={{ background: 'none', border: `1px solid ${COLORS.sage}66`, borderRadius: 8, padding: '8px 12px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6, opacity: points.length ? 1 : 0.5 }}>
            <RotateCcw size={14} aria-hidden="true" /> Clear
          </button>
          <button type="button" onClick={onSkip}
            style={{ background: 'none', border: 'none', color: COLORS.charcoal + '88', fontSize: 13, padding: '8px 4px' }}>
            Skip for now
          </button>
          <button type="button" onClick={handleSave} disabled={!canSave || saving}
            style={{ background: COLORS.forest, color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6, opacity: (!canSave || saving) ? 0.6 : 1 }}>
            {saving ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <MapPin size={14} aria-hidden="true" />}
            {saving ? 'Saving boundary…' : 'Save boundary'}
          </button>
        </div>
      </div>
    </div>
  );
}

const BASELINE_CROP = 'maize'; // the only crop verified end-to-end against agri-venture-v2 so far

function ParcelBaselineStep({ parcel, onDone }) {
  const [status, setStatus] = useState('loading'); // loading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);

    api.getBaseline(parcel.id, BASELINE_CROP)
      .then(res => { setResult(res); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); })
      .finally(() => clearInterval(tick));

    return () => clearInterval(tick);
  }, [parcel.id]);

  const s = result?.baseline_suitability;

  return (
    <div>
      <p style={{ fontSize: 13, color: COLORS.charcoal + 'aa', marginTop: 0 }}>
        Boundary saved ({parcel.area_acres ? `${parcel.area_acres.toFixed(2)} acres` : 'area pending'}).
        Now checking real {BASELINE_CROP} suitability via <code>GET /api/advisory/parcel/{'{parcel_id}'}/baseline</code>.
      </p>

      {status === 'loading' && (
        <div role="status" aria-live="polite" style={{
          display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center', justifyContent: 'center',
          padding: '32px 16px', border: `1px dashed ${COLORS.sage}66`, borderRadius: 10,
        }}>
          <Loader2 size={22} className="spin" aria-hidden="true" color={COLORS.forest} />
          <span style={{ fontSize: 14, fontWeight: 600 }}>Running live biophysical analysis ({elapsed}s elapsed)…</span>
          <span style={{ fontSize: 12, color: COLORS.charcoal + '88', textAlign: 'center', maxWidth: 320 }}>
            This calls agri-venture-v2's live Google Earth Engine analysis. Normally ~8-12 seconds,
            but a GEE cold start can take up to 150 seconds — this isn't stuck, please keep this open.
          </span>
        </div>
      )}

      {status === 'error' && (
        <ErrorBanner message={`Live suitability check failed: ${error}`} />
      )}

      {status === 'done' && s && (
        <div style={{ border: `1px solid ${COLORS.sage}66`, borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: COLORS.charcoal + '88', marginBottom: 10 }}>
            {BASELINE_CROP} suitability {result.cached ? '(cached)' : '(freshly computed)'}
          </div>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Classification</div>
              <div style={{ fontFamily: 'Newsreader, serif', fontSize: 22, fontWeight: 600, color: COLORS.forest }}>{s.overall_classification ?? '—'}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Score</div>
              <div style={{ fontFamily: 'Newsreader, serif', fontSize: 22, fontWeight: 600 }}>{s.overall_score ?? '—'}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Binding domain</div>
              <div style={{ fontFamily: 'Newsreader, serif', fontSize: 22, fontWeight: 600 }}>{s.binding_domain ?? '—'}</div>
            </div>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
        <button type="button" onClick={onDone}
          style={{ background: COLORS.forest, color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontWeight: 600, fontSize: 13 }}>
          Done
        </button>
      </div>
    </div>
  );
}

const CHANNELS = [
  { key: 'sms', label: 'SMS', icon: MessageSquare },
  { key: 'ussd', label: 'USSD', icon: Phone },
  { key: 'whatsapp', label: 'WhatsApp', icon: Smartphone },
  { key: 'ivr', label: 'IVR (Voice)', icon: Radio },
  { key: 'radio', label: 'Radio', icon: Radio },
];

const COLORS = {
  forest: '#1f4d2c', forestDark: '#163a20', sand: '#f3ecdb',
  ochre: '#c17f2a', sage: '#8fae86', charcoal: '#2b2620', clay: '#a8562f',
};

// Accessibility commitment (docs/ACCESSIBILITY.md): visible keyboard
// focus on every interactive element. Injected once, globally.
const FOCUS_STYLE = `
  a:focus-visible, button:focus-visible, input:focus-visible,
  select:focus-visible, [tabindex]:focus-visible {
    outline: 3px solid #1a73e8;
    outline-offset: 2px;
  }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
  }
`;

function ErrorBanner({ message, onRetry }) {
  return (
    <div role="alert" style={{
      background: '#fdecea', border: '1px solid #a8562f55', color: COLORS.clay,
      padding: '12px 16px', borderRadius: 8, marginBottom: 16, display: 'flex',
      justifyContent: 'space-between', alignItems: 'center', gap: 12,
    }}>
      <span><strong>Couldn't load data.</strong> {message}</span>
      {onRetry && (
        <button onClick={onRetry} style={{ background: COLORS.clay, color: '#fff', border: 'none', borderRadius: 6, padding: '6px 12px', fontWeight: 600, fontSize: 13 }}>
          Retry
        </button>
      )}
    </div>
  );
}

function LoadingState({ label }) {
  return (
    <div role="status" aria-live="polite" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 24, color: COLORS.charcoal + '99' }}>
      <Loader2 size={18} className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

function ChannelBadge({ channelKey }) {
  const ch = CHANNELS.find(c => c.key === channelKey) || CHANNELS[0];
  const Icon = ch.icon;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: COLORS.forest + '14', color: COLORS.forest,
      padding: '3px 9px', borderRadius: 20, fontSize: 12, fontWeight: 600,
    }}>
      <Icon size={12} aria-hidden="true" /> {ch.label}
    </span>
  );
}

function StatCard({ icon: Icon, label, value, sub }) {
  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: '18px 20px', border: `1px solid ${COLORS.sage}33`, flex: 1, minWidth: 140 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: COLORS.forest, marginBottom: 8 }}>
        <Icon size={18} aria-hidden="true" />
        <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: COLORS.charcoal + '99' }}>{label}</span>
      </div>
      <div style={{ fontFamily: 'Newsreader, serif', fontSize: 28, fontWeight: 600, color: COLORS.charcoal }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: COLORS.charcoal + '80', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function FlagBadge({ icon: Icon, label, color }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      background: color + '18', color, border: `1px solid ${color}55`,
      padding: '4px 10px', borderRadius: 20, fontSize: 12, fontWeight: 700,
    }}>
      <Icon size={13} aria-hidden="true" /> {label}
    </span>
  );
}

function FarmerNameLink({ steward, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(steward.id)}
      style={{
        background: 'none', border: 'none', padding: 0, margin: 0,
        fontWeight: 600, fontSize: 14, color: COLORS.forest, textDecoration: 'underline',
        textDecorationColor: COLORS.forest + '55', cursor: 'pointer',
      }}
    >
      {steward.full_name}
    </button>
  );
}

// Each section of the farmer detail view fetches its own already-tested
// endpoint independently (GET /api/stewards/{id}, GET /api/parcels,
// GET /api/dispatch/log) -- same honest-partial-failure principle as
// loadDashboardData()'s per-endpoint .catch() above: a slow/broken
// dispatch log must never block the profile header or land holdings
// from rendering.
function FarmerProfileHeader({ stewardId }) {
  const [status, setStatus] = useState('loading'); // loading | done | error
  const [steward, setSteward] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setStatus('loading');
    setError(null);
    api.getSteward(stewardId)
      .then(s => { setSteward(s); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); });
  }, [stewardId]);

  useEffect(() => { load(); }, [load]);

  if (status === 'loading') return <LoadingState label="Loading farmer profile…" />;
  if (status === 'error') return <ErrorBanner message={error} onRetry={load} />;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 24, fontWeight: 600, margin: 0 }}>{steward.full_name}</h2>
        <span style={{ fontSize: 13, color: COLORS.charcoal + '88', textTransform: 'capitalize' }}>
          {steward.role?.replaceAll('_', ' ')}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        {steward.is_youth && <FlagBadge icon={GraduationCap} label="Youth" color={COLORS.ochre} />}
        {steward.has_disability && <FlagBadge icon={AlertTriangle} label="Accessibility flagged" color={COLORS.clay} />}
        {steward.preferred_channel && <ChannelBadge channelKey={steward.preferred_channel} />}
        {steward.cooperative_name && <FlagBadge icon={Building2} label={steward.cooperative_name} color={COLORS.forest} />}
      </div>

      <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px 20px', margin: 0, fontSize: 13 }}>
        <div>
          <dt style={{ color: COLORS.charcoal + '88', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.03em' }}>Gender</dt>
          <dd style={{ margin: '2px 0 0', textTransform: 'capitalize' }}>{steward.gender || '—'}</dd>
        </div>
        <div>
          <dt style={{ color: COLORS.charcoal + '88', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.03em' }}>Registered by</dt>
          <dd style={{ margin: '2px 0 0' }}>{steward.registered_by || '—'}</dd>
        </div>
        <div>
          <dt style={{ color: COLORS.charcoal + '88', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.03em' }}>Registered on</dt>
          <dd style={{ margin: '2px 0 0' }}>{steward.created_at ? new Date(steward.created_at).toLocaleDateString() : '—'}</dd>
        </div>
      </dl>
    </div>
  );
}

// Renders parcel_crop_baseline's suitability tree (DomainResult ->
// FactorScore/Evidence, per agri-venture-v2's Explainability Requirement
// -- see advisory.py docstring) behind a native <details> disclosure.
// Structured for the fields the task calls out (factor_scores, evidence,
// warnings); a raw JSON fallback underneath guarantees nothing in the
// response is actually hidden, just not force-rendered.
function SuitabilityExplainability({ raw }) {
  if (!raw) return null;
  const domains = Array.isArray(raw.domains) ? raw.domains : [];
  return (
    <details style={{ marginTop: 12 }}>
      <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: COLORS.forest }}>
        How this was computed
      </summary>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {Array.isArray(raw.warnings) && raw.warnings.length > 0 && (
          <div style={{ background: '#fdecea', border: '1px solid #a8562f33', borderRadius: 8, padding: 10, fontSize: 12 }}>
            {raw.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
          </div>
        )}
        {domains.map((d, i) => (
          <div key={i} style={{ border: `1px solid ${COLORS.sage}44`, borderRadius: 8, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
              <span style={{ textTransform: 'capitalize' }}>{d.domain}</span>
              <span>{d.score ?? '—'} <span style={{ fontWeight: 400, color: COLORS.charcoal + '88' }}>({d.confidence ?? 'n/a'} confidence)</span></span>
            </div>
            {Array.isArray(d.factor_scores) && d.factor_scores.length > 0 && (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, marginBottom: 8 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: COLORS.charcoal + '88' }}>
                    <th style={{ padding: '4px 6px' }}>Factor</th>
                    <th style={{ padding: '4px 6px' }}>Score</th>
                    <th style={{ padding: '4px 6px' }}>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {d.factor_scores.map((f, j) => (
                    <tr key={j} style={{ borderTop: `1px solid ${COLORS.sage}22` }}>
                      <td style={{ padding: '4px 6px', textTransform: 'capitalize' }}>{f.name}</td>
                      <td style={{ padding: '4px 6px', fontFamily: 'monospace' }}>{f.score}</td>
                      <td style={{ padding: '4px 6px', color: COLORS.charcoal + 'aa' }}>{f.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {Array.isArray(d.evidence) && d.evidence.length > 0 && (
              <div style={{ fontSize: 12, color: COLORS.charcoal + 'aa' }}>
                {d.evidence.map((e, j) => (
                  <div key={j} style={{ padding: '3px 0' }}>
                    <strong>{e.dataset}</strong>: {e.observation} {e.unit} ({e.period || 'n/a'}, {e.confidence} confidence)
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <details style={{ marginTop: 10 }}>
        <summary style={{ cursor: 'pointer', fontSize: 11, color: COLORS.charcoal + '88' }}>Full raw response (JSON)</summary>
        <pre style={{ background: COLORS.sand, padding: 10, borderRadius: 6, fontSize: 11, overflowX: 'auto', maxHeight: 300 }}>
          {JSON.stringify(raw, null, 2)}
        </pre>
      </details>
    </details>
  );
}

// Deliberately does NOT auto-fetch on mount. GET /baseline computes a
// fresh result live via agri-venture-v2 (up to ~150s, per advisory.py's
// AGRIVENTURE_TIMEOUT_S) whenever nothing is cached yet -- auto-firing
// that for every parcel just from opening a profile would turn "view a
// farmer" into a hot path capable of triggering several concurrent live
// GEE calls. A manual check keeps that cost opt-in, same as the
// registration flow's ParcelBaselineStep already does for one parcel.
function ParcelSuitabilityCard({ parcel }) {
  const [status, setStatus] = useState('idle'); // idle | loading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  function check() {
    setStatus('loading');
    setError(null);
    startRef.current = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);
    api.getBaseline(parcel.id, BASELINE_CROP)
      .then(res => { setResult(res); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); })
      .finally(() => clearInterval(tick));
  }

  const s = result?.baseline_suitability;

  return (
    <div style={{ border: `1px solid ${COLORS.sage}44`, borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>
          {parcel.area_acres ? `${parcel.area_acres.toFixed(2)} acres` : 'Area pending'}
        </span>
      </div>

      {/* Diagnose (crop-independent Stage 1 LandDiagnostic) before analyse
          (crop suitability, below) -- workflow reads top-to-bottom in that
          order. Genuinely separate data: this is agri-venture-v2's Stage 1
          report, cached in its own parcel_diagnostic table (one row per
          parcel, not per crop). */}
      <div style={{ marginTop: 10 }}>
        <FarmLabReport parcel={parcel} />
      </div>

      <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${COLORS.sage}33` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: COLORS.charcoal + '88' }}>
            Crop suitability
          </span>
          {status !== 'loading' && (
            <button type="button" onClick={check}
              style={{ background: 'none', border: `1px solid ${COLORS.forest}55`, color: COLORS.forest, borderRadius: 8, padding: '5px 10px', fontSize: 12, fontWeight: 600 }}>
              {status === 'idle' ? `Check ${BASELINE_CROP} suitability` : status === 'error' ? 'Retry' : `Recheck ${BASELINE_CROP} suitability`}
            </button>
          )}
        </div>

        {status === 'idle' && (
          <p style={{ fontSize: 12, color: COLORS.charcoal + '88', margin: '8px 0 0' }}>Not checked yet.</p>
        )}

        {status === 'loading' && (
          <div role="status" aria-live="polite" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 12, color: COLORS.charcoal + '99' }}>
            <Loader2 size={14} className="spin" aria-hidden="true" />
            <span>Running live biophysical analysis ({elapsed}s elapsed) — a GEE cold start can take up to 150s…</span>
          </div>
        )}

        {status === 'error' && <div style={{ marginTop: 10 }}><ErrorBanner message={error} onRetry={check} /></div>}

        {status === 'done' && s && (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: COLORS.charcoal + '88', marginBottom: 8 }}>
              {BASELINE_CROP} suitability {result.cached ? '(cached)' : '(freshly computed)'}
            </div>
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Classification</div>
                <div style={{ fontFamily: 'Newsreader, serif', fontSize: 20, fontWeight: 600, color: COLORS.forest }}>{s.overall_classification ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Score</div>
                <div style={{ fontFamily: 'Newsreader, serif', fontSize: 20, fontWeight: 600 }}>{s.overall_score ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Binding domain</div>
                <div style={{ fontFamily: 'Newsreader, serif', fontSize: 20, fontWeight: 600 }}>{s.binding_domain ?? '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>Computed</div>
                <div style={{ fontSize: 13, marginTop: 3 }}>{result.baseline_computed_at ? new Date(result.baseline_computed_at).toLocaleDateString() : '—'}</div>
              </div>
            </div>
            <SuitabilityExplainability raw={result.baseline_suitability_raw} />
          </div>
        )}
      </div>
    </div>
  );
}

const NATURE_STYLE = {
  measured: { label: 'MEASURED', color: '#1f4d2c' },
  derived: { label: 'DERIVED', color: '#2171b5' },
  modelled: { label: 'MODELLED', color: '#c17f2a' },
};

function NatureBadge({ nature }) {
  const n = NATURE_STYLE[nature] || { label: (nature || '?').toUpperCase(), color: COLORS.charcoal };
  return (
    <span title="How solid this number is — measured (real observation), derived (arithmetic on observations), or modelled (rests on assumptions)"
      style={{
        display: 'inline-block', fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
        color: n.color, border: `1px solid ${n.color}66`, background: n.color + '14',
        padding: '2px 6px', borderRadius: 4, whiteSpace: 'nowrap',
      }}>
      {n.label}
    </span>
  );
}

// One DiagnosticFact: value/unit/status/nature front-and-center (the
// nature tag is the whole honesty point of this schema, per
// PROJECT_STATE.md -- never buried), plain-language description always
// visible, provenance (dataset/resolution/confidence/notes/series)
// behind a per-fact disclosure, same pattern as SuitabilityExplainability
// above.
function DiagnosticFactRow({ fact }) {
  return (
    <div style={{ padding: '10px 0', borderTop: `1px solid ${COLORS.sage}22` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{fact.title}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'monospace', fontSize: 13 }}>
            {fact.value ?? '—'}{fact.unit ? ` ${fact.unit}` : ''}
          </span>
          {fact.status && (
            <span style={{ fontSize: 11, fontWeight: 700, color: COLORS.forest, textTransform: 'uppercase' }}>
              {fact.status}
            </span>
          )}
          <NatureBadge nature={fact.nature} />
        </div>
      </div>
      <p style={{ fontSize: 12, color: COLORS.charcoal + 'aa', margin: '4px 0 0' }}>{fact.description}</p>
      <details style={{ marginTop: 4 }}>
        <summary style={{ cursor: 'pointer', fontSize: 11, color: COLORS.charcoal + '88' }}>Provenance</summary>
        <div style={{ fontSize: 11, color: COLORS.charcoal + '99', marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span>Dataset: {fact.dataset}{fact.resolution ? ` (${fact.resolution})` : ''}</span>
          {fact.period && <span>Period: {fact.period}</span>}
          <span>Confidence: {fact.confidence}</span>
          {fact.status_basis && <span>Basis: {fact.status_basis}</span>}
          {fact.notes && <span>Notes: {fact.notes}</span>}
          {Array.isArray(fact.series) && (
            <span>
              Series{fact.series_labels ? ` (${fact.series_labels.join(', ')})` : ''}: {fact.series.map(v => v ?? '—').join(', ')}
            </span>
          )}
        </div>
      </details>
    </div>
  );
}

function DiagnosticCategory({ title, facts }) {
  if (!facts || facts.length === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: COLORS.charcoal + '88' }}>
        {title}
      </div>
      {facts.map((f, i) => <DiagnosticFactRow key={f.code || i} fact={f} />)}
    </div>
  );
}

// Land-use's own thumbnail is rendered separately, up front alongside its
// DiagnosticCategory + pie chart (see FarmLabReport) -- not in this list.
const LAND_USE_THUMBNAIL = { kind: 'landuse', label: 'Land-use map' };
const THUMBNAIL_KINDS = [
  { kind: 'ndvi', label: 'NDVI (vegetation) map' },
  { kind: 'rainfall', label: 'Rainfall context map' },
];

// Deliberately separate, opt-in per thumbnail -- never fetched
// automatically alongside the diagnostic. Each click spends real EECU on
// agri-venture-v2's side (its own thumbnails.py docstring), and nothing
// here is cached/persisted server-side: every load is a fresh signed URL.
// Legend/scale/citation render straight from what agri-venture-v2's
// /thumbnail/* endpoints actually return (providers/thumbnails.py) --
// never a hardcoded guess of its palette, which could drift out of sync
// with the real rendering code. Per the Explainability Requirement, a
// colored map with no key is meaningless to a non-technical field
// officer, so these render whenever the source provides them.
function MapLegend({ legend }) {
  if (!Array.isArray(legend) || legend.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px 14px', marginTop: 8 }}>
      {legend.map(l => (
        <div key={l.code} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
          <span style={{ width: 12, height: 12, borderRadius: 3, background: l.color, display: 'inline-block', border: '1px solid #00000022', flexShrink: 0 }} aria-hidden="true" />
          <span>{l.label}</span>
        </div>
      ))}
    </div>
  );
}

function formatBandRange(b) {
  if (b.min == null) return `< ${b.max}`;
  if (b.max == null) return `≥ ${b.min}`;
  return `${b.min}–${b.max}`;
}

function MapScale({ scale }) {
  if (!scale) return null;
  const gradient = `linear-gradient(to right, ${scale.palette.join(', ')})`;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ height: 12, borderRadius: 6, background: gradient, border: '1px solid #00000022' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: COLORS.charcoal + '88', marginTop: 2 }}>
        <span>{scale.min}{scale.unit ? ` ${scale.unit}` : ''}</span>
        <span>{scale.max}{scale.unit ? ` ${scale.unit}` : ''}</span>
      </div>
      {Array.isArray(scale.bands) && scale.bands.length > 0 && (
        <div style={{ display: 'flex', gap: 14, marginTop: 4, fontSize: 11, flexWrap: 'wrap' }}>
          {scale.bands.map((b, i) => (
            <span key={i}><strong>{b.label}</strong>: {formatBandRange(b)}</span>
          ))}
        </div>
      )}
    </div>
  );
}

// Citation styled as a clear, always-visible line (not fine print) --
// the task's own complaint was that a legend/citation buried or missing
// tells a field officer nothing.
function MapCitation({ dataset, resolution, period }) {
  if (!dataset) return null;
  return (
    <div style={{ fontSize: 11, color: COLORS.charcoal + 'aa', marginTop: 8, borderTop: `1px solid ${COLORS.sage}22`, paddingTop: 6 }}>
      <strong>Source:</strong> {dataset}{resolution ? ` · ${resolution}` : ''}{period ? ` · ${period}` : ''}
    </div>
  );
}

function ThumbnailLoader({ parcelId, kind, label }) {
  const [status, setStatus] = useState('idle'); // idle | loading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  function load() {
    setStatus('loading');
    setError(null);
    api.getThumbnail(parcelId, kind)
      .then(res => { setResult(res); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); });
  }

  return (
    <div style={{ border: `1px solid ${COLORS.sage}33`, borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>{label}</span>
        {status !== 'loading' && (
          <button type="button" onClick={load}
            style={{ background: 'none', border: `1px solid ${COLORS.forest}55`, color: COLORS.forest, borderRadius: 6, padding: '4px 8px', fontSize: 11, fontWeight: 600 }}>
            {status === 'idle' ? 'Load map' : status === 'error' ? 'Retry' : 'Reload'}
          </button>
        )}
      </div>
      {status === 'loading' && (
        <div role="status" aria-live="polite" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 11, color: COLORS.charcoal + '99' }}>
          <Loader2 size={12} className="spin" aria-hidden="true" />
          <span>Generating from live satellite data — spends real compute, please wait…</span>
        </div>
      )}
      {status === 'error' && <div style={{ marginTop: 8 }}><ErrorBanner message={error} onRetry={load} /></div>}
      {status === 'done' && result && (
        <div style={{ marginTop: 8 }}>
          <img src={result.url} alt={label} style={{ maxWidth: '100%', borderRadius: 6, display: 'block' }} />
          <MapLegend legend={result.legend} />
          <MapScale scale={result.scale} />
          <MapCitation
            dataset={result.dataset}
            resolution={result.resolution}
            period={result.period || result.generated_period}
          />
          {result.buffer_km && (
            <div style={{ fontSize: 10, color: COLORS.charcoal + '88', marginTop: 4 }}>
              Zoomed out to a {result.buffer_km}km regional buffer (parcel too small for CHIRPS's own pixel size) — farm boundary outlined in white.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// The colors the land-use MAP IMAGE actually renders -- NOT the naive
// WorldCover per-class palette (WORLDCOVER_VIS in agri-venture-v2's
// thumbnails.py). Those two differ for every class except Tree cover:
// getThumbURL()'s {min:10, max:100, palette} treats the 11 class codes as
// a CONTINUOUS linear ramp across [10,100], not a discrete per-class
// lookup, so most classes render as a color BLEND between two palette
// stops. Confirmed by pixel-sampling two real rendered thumbnails and
// reverse-computing the ramp math (see agri-venture-v2's
// _interpolated_worldcover_color(), which /thumbnail/landuse's own
// "legend" field now uses and which produced these exact values) --
// e.g. Built-up is really rgb(219,80,80), not the "pure" fa0000 red the
// raw palette list implies.
//
// Hardcoded here (not fetched) because this chart renders from the
// already-loaded /diagnostic response alone (free) and must not force a
// caller to spend the separate, opt-in GEE thumbnail call just to learn
// the colors. FRAGILE: if agri-venture-v2 ever changes WORLDCOVER_VIS's
// min/max/palette, these values silently go stale again -- there is no
// way to keep them in sync automatically without either (a) always
// paying for the thumbnail call first, or (b) agri-venture-v2 exposing
// this palette on a lighter endpoint. Re-derive from
// _interpolated_worldcover_color() in thumbnails.py if that ever happens.
const WORLDCOVER_COLORS = {
  'Tree cover': '#006400', 'Shrubland': '#ffc327', 'Grassland': '#fce874',
  'Cropland': '#f364aa', 'Built-up': '#db5050', 'Bare / sparse vegetation': '#d5d5d5',
  'Snow and ice': '#5093d5', 'Permanent water': '#008ba9', 'Herbaceous wetland': '#00c97a',
  'Mangroves': '#6fd988', 'Moss and lichen': '#fae6a0',
};

function polarToXY(cx, cy, r, angleDeg) {
  const rad = (angleDeg - 90) * (Math.PI / 180);
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

// Donut chart straight from the land_cover DiagnosticFact's own series/
// series_labels (already the real, area-weighted percentages computed by
// agri-venture-v2's GEE reduceRegion -- see get_diagnostic() investigation).
// Deliberately uses the REAL WorldCover colors (not the dataviz skill's
// validated CVD-safe categorical palette) so a slice's color always matches
// the same category's color on the land-use map/legend directly above it --
// a documented trade-off: the validator flags Tree cover vs Built-up (this
// parcel's two largest categories) as CVD-indistinguishable (protanopia
// ΔE 2.1, far below the ≥12 target). Mitigated by never relying on color
// alone anywhere here: every slice's identity also comes from the legend's
// text label and from the center callout, never from color-matching alone.
function LandUsePieChart({ fact }) {
  if (!fact || !Array.isArray(fact.series) || fact.series.length === 0) return null;

  const total = fact.series.reduce((a, b) => a + b, 0) || 100;
  const R = 70, CX = 90, CY = 90, STROKE_GAP = 2;
  let cursor = 0;
  const slices = fact.series.map((pct, i) => {
    const label = fact.series_labels?.[i] ?? `Class ${i}`;
    const startAngle = (cursor / total) * 360;
    cursor += pct;
    const endAngle = (cursor / total) * 360;
    const color = WORLDCOVER_COLORS[label] || COLORS.charcoal + '55';
    return { label, pct, color, startAngle, endAngle };
  });

  return (
    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center', margin: '4px 0 16px' }}>
      <div style={{ position: 'relative', width: 180, height: 180, flexShrink: 0 }}>
        <svg viewBox="0 0 180 180" width={180} height={180} role="img" aria-label={`Land cover breakdown: dominant class ${slices[0].label} at ${slices[0].pct}%`}>
          {slices.map((s, i) => {
            // Full-circle case (single class = 100%) can't be drawn as an arc path.
            if (s.endAngle - s.startAngle >= 359.99) {
              return <circle key={i} cx={CX} cy={CY} r={R} fill={s.color} stroke={COLORS.sand} strokeWidth={STROKE_GAP} />;
            }
            const [x1, y1] = polarToXY(CX, CY, R, s.startAngle);
            const [x2, y2] = polarToXY(CX, CY, R, s.endAngle);
            const largeArc = s.endAngle - s.startAngle > 180 ? 1 : 0;
            const d = `M ${CX} ${CY} L ${x1} ${y1} A ${R} ${R} 0 ${largeArc} 1 ${x2} ${y2} Z`;
            return <path key={i} d={d} fill={s.color} stroke={COLORS.sand} strokeWidth={STROKE_GAP} />;
          })}
          {/* Donut hole, doubling as the direct-labeled callout for the one
              category that's actually the story here: the dominant class. */}
          <circle cx={CX} cy={CY} r={38} fill={COLORS.sand} />
        </svg>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', textAlign: 'center', pointerEvents: 'none',
        }}>
          <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'Newsreader, serif', color: COLORS.charcoal }}>{slices[0].pct}%</div>
          <div style={{ fontSize: 10, color: COLORS.charcoal + '99', maxWidth: 70, lineHeight: 1.2 }}>{slices[0].label}</div>
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 180 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {slices.map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12 }}>
              <span style={{ width: 11, height: 11, borderRadius: 3, background: s.color, border: '1px solid #00000022', flexShrink: 0 }} aria-hidden="true" />
              <span style={{ flex: 1 }}>{s.label}</span>
              <span style={{ fontFamily: 'monospace', color: COLORS.charcoal + 'aa' }}>{s.pct}%</span>
            </div>
          ))}
        </div>
        <MapCitation dataset={fact.dataset} resolution={fact.resolution} period={fact.period} />
      </div>
    </div>
  );
}

// 'land_use' deliberately excluded -- rendered as its own combined block
// (facts + map + legend + pie chart) ahead of Climate; see FarmLabReport.
const DIAGNOSTIC_CATEGORIES = [
  ['climate', 'Climate'], ['soil', 'Soil'], ['water', 'Water'],
  ['vegetation', 'Vegetation'], ['topography', 'Topography'],
  ['carbon', 'Carbon'],
];

function FarmLabReport({ parcel }) {
  const [status, setStatus] = useState('idle'); // idle | loading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  function load() {
    setStatus('loading');
    setError(null);
    startRef.current = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);
    api.getDiagnostic(parcel.id, 'quick')
      .then(res => { setResult(res); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); })
      .finally(() => clearInterval(tick));
  }

  const diag = result?.diagnostic;

  return (
    <details>
      <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: COLORS.forest, display: 'flex', alignItems: 'center', gap: 6 }}>
        <FlaskConical size={14} aria-hidden="true" /> Farm Lab Report
      </summary>

      <div style={{ marginTop: 10 }}>
        {status === 'idle' && (
          <button type="button" onClick={load}
            style={{ background: 'none', border: `1px solid ${COLORS.forest}55`, color: COLORS.forest, borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600 }}>
            Load Farm Lab Report
          </button>
        )}

        {status === 'loading' && (
          <div role="status" aria-live="polite" style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: COLORS.charcoal + '99' }}>
            <Loader2 size={14} className="spin" aria-hidden="true" />
            <span>Building land diagnostic ({elapsed}s elapsed) — quick depth, usually ~30s…</span>
          </div>
        )}

        {status === 'error' && <ErrorBanner message={error} onRetry={load} />}

        {status === 'done' && diag && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: COLORS.charcoal + '88' }}>
                {result.cached ? 'Cached' : 'Freshly computed'} · depth={result.depth}
              </span>
              <span style={{ fontSize: 11, color: COLORS.charcoal + '88' }}>
                {result.computed_at ? new Date(result.computed_at).toLocaleDateString() : '—'}
              </span>
            </div>

            {Array.isArray(diag.warnings) && diag.warnings.length > 0 && (
              <div style={{ background: '#fdecea', border: '1px solid #a8562f33', borderRadius: 8, padding: 10, fontSize: 12, marginBottom: 12 }}>
                {diag.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}

            {/* Land use surfaced first, ahead of Climate, per explicit
                ordering request -- facts, map, legend, and pie chart kept
                together as one block. Every other category below keeps its
                prior relative order unchanged. */}
            <DiagnosticCategory title="Land use" facts={diag.land_use} />
            {/* Collapsible as a display-only toggle -- <details> hides its
                content with CSS, it doesn't unmount it, so the already-loaded
                map/legend/pie-chart state survives a collapse/re-expand with
                no re-fetch. Defaults open so first load looks unchanged. */}
            <details open style={{ marginBottom: 12 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: COLORS.forest, marginBottom: 8 }}>
                Land-use map &amp; breakdown
              </summary>
              <div style={{ marginTop: 8 }}>
                <ThumbnailLoader parcelId={parcel.id} kind={LAND_USE_THUMBNAIL.kind} label={LAND_USE_THUMBNAIL.label} />
                <LandUsePieChart fact={diag.land_use?.[0]} />
              </div>
            </details>

            {DIAGNOSTIC_CATEGORIES.map(([key, label]) => (
              <DiagnosticCategory key={key} title={label} facts={diag[key]} />
            ))}

            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: COLORS.charcoal + '88', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                <ImageIcon size={13} aria-hidden="true" /> Map thumbnails
              </div>
              <p style={{ fontSize: 11, color: COLORS.charcoal + '88', marginTop: 0, marginBottom: 8 }}>
                Not loaded automatically — each spends real satellite compute on demand.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {THUMBNAIL_KINDS.map(({ kind, label }) => (
                  <ThumbnailLoader key={kind} parcelId={parcel.id} kind={kind} label={label} />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </details>
  );
}

function FarmerParcelsSection({ stewardId }) {
  const [status, setStatus] = useState('loading');
  const [parcels, setParcels] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setStatus('loading');
    setError(null);
    api.listParcels(stewardId)
      .then(p => { setParcels(p); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); });
  }, [stewardId]);

  useEffect(() => { load(); }, [load]);

  if (status === 'loading') return <LoadingState label="Loading land holdings…" />;
  if (status === 'error') return <ErrorBanner message={error} onRetry={load} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {parcels.length === 0 && (
        <p style={{ fontSize: 13, color: COLORS.charcoal + '88' }}>No parcels registered for this farmer yet.</p>
      )}
      {parcels.map(p => <ParcelSuitabilityCard key={p.id} parcel={p} />)}
    </div>
  );
}

function dispatchStatusColor(status) {
  if (status === 'delivered' || status === 'sent') return COLORS.forest;
  if (status === 'failed') return COLORS.clay;
  return COLORS.ochre; // queued/pending
}

function FarmerDispatchSection({ stewardId }) {
  const [status, setStatus] = useState('loading');
  const [log, setLog] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setStatus('loading');
    setError(null);
    api.dispatchLog({ steward_id: stewardId })
      .then(l => { setLog(l); setStatus('done'); })
      .catch(e => { setError(e.message); setStatus('error'); });
  }, [stewardId]);

  useEffect(() => { load(); }, [load]);

  if (status === 'loading') return <LoadingState label="Loading communication history…" />;
  if (status === 'error') return <ErrorBanner message={error} onRetry={load} />;

  if (log.length === 0) {
    return (
      <p style={{ fontSize: 13, color: COLORS.charcoal + '88' }}>
        Nothing sent to this farmer yet.
      </p>
    );
  }

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {log.map((d, i) => (
        <li key={d.id} style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', flexWrap: 'wrap',
          borderTop: i > 0 ? `1px solid ${COLORS.sage}22` : 'none',
        }}>
          <ChannelBadge channelKey={d.channel} />
          <span style={{ fontSize: 13, textTransform: 'capitalize' }}>{d.content_type?.replaceAll('_', ' ')}</span>
          <span style={{
            fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em',
            color: dispatchStatusColor(d.delivery_status),
          }}>
            {d.delivery_status}
          </span>
          <span style={{ fontSize: 12, color: COLORS.charcoal + '88', marginLeft: 'auto' }}>
            {d.sent_at ? new Date(d.sent_at).toLocaleString() : 'time unknown'}
          </span>
        </li>
      ))}
    </ul>
  );
}

function FarmerDetailView({ stewardId, onBack }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <button type="button" onClick={onBack}
        style={{
          alignSelf: 'flex-start', background: 'none', border: 'none', color: COLORS.forest,
          fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0',
        }}>
        <ArrowLeft size={15} aria-hidden="true" /> Back to list
      </button>

      <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
        <FarmerProfileHeader stewardId={stewardId} />
      </div>

      <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
        <h3 style={{ fontFamily: 'Newsreader, serif', fontSize: 16, fontWeight: 600, marginTop: 0, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Layers size={16} aria-hidden="true" color={COLORS.forest} /> Land holdings
        </h3>
        <FarmerParcelsSection stewardId={stewardId} />
      </div>

      <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
        <h3 style={{ fontFamily: 'Newsreader, serif', fontSize: 16, fontWeight: 600, marginTop: 0, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Send size={16} aria-hidden="true" color={COLORS.forest} /> Communication history
        </h3>
        <FarmerDispatchSection stewardId={stewardId} />
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState('dashboard');
  const [stewards, setStewards] = useState(null);
  const [prices, setPrices] = useState(null);
  const [postings, setPostings] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [registerStep, setRegisterStep] = useState('form'); // form | draw | baseline
  const [newSteward, setNewSteward] = useState(null);
  const [newParcel, setNewParcel] = useState(null);
  const [form, setForm] = useState({ full_name: '', preferred_channel: 'sms', gender: 'female', role: 'smallholder_farmer', is_youth: false, has_disability: false });
  const [toast, setToast] = useState(null);
  // null = list view; set = the "bank account" style full profile for
  // that farmer, replacing the current tab's content until Back is hit.
  const [selectedStewardId, setSelectedStewardId] = useState(null);

  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, p, po] = await Promise.all([
        api.listStewards(),
        api.listPrices().catch(() => []), // don't let one failed endpoint block the whole page
        api.listPostings().catch(() => []),
      ]);
      setStewards(s);
      setPrices(p);
      setPostings(po);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDashboardData(); }, [loadDashboardData]);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 2800);
      return () => clearTimeout(t);
    }
  }, [toast]);

  async function submitRegistration(e) {
    e.preventDefault();
    if (!form.full_name.trim()) return;
    try {
      const steward = await api.registerSteward(form);
      setNewSteward(steward);
      setRegisterStep('draw');
      setToast('Farmer registered — now trace their farm boundary');
      loadDashboardData();
    } catch (e) {
      setToast(`Registration failed: ${e.message}`);
    }
  }

  function closeRegisterDialog() {
    setShowRegister(false);
    setRegisterStep('form');
    setNewSteward(null);
    setNewParcel(null);
    setForm({ full_name: '', preferred_channel: 'sms', gender: 'female', role: 'smallholder_farmer', is_youth: false, has_disability: false });
  }

  const navItems = [
    { key: 'dashboard', label: 'Dashboard' },
    { key: 'registration', label: 'Farmer Registration' },
    { key: 'market', label: 'Market Linkage' },
  ];

  const femaleCount = stewards?.filter(s => s.gender === 'female').length ?? 0;
  const youthCount = stewards?.filter(s => s.is_youth).length ?? 0;
  const disabilityCount = stewards?.filter(s => s.has_disability).length ?? 0;

  return (
    <div style={{ fontFamily: 'Inter, sans-serif', background: COLORS.sand, minHeight: '100vh', color: COLORS.charcoal }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;0,600;0,700;1,500&family=Inter:wght@400;500;600;700&display=swap');
        * { box-sizing: border-box; }
        button { cursor: pointer; font-family: inherit; }
        input, select { font-family: inherit; }
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        ${FOCUS_STYLE}
      `}</style>

      <a href="#main-content" style={{
        position: 'absolute', left: -9999, top: 'auto',
      }} onFocus={(e) => { e.target.style.left = '10px'; e.target.style.top = '10px'; e.target.style.zIndex = 100; e.target.style.background = '#fff'; e.target.style.padding = '8px 12px'; }}>
        Skip to main content
      </a>

      <header style={{ background: COLORS.forestDark, color: '#fff', padding: '20px 28px' }}>
        <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontFamily: 'Newsreader, serif', fontSize: 22, fontWeight: 600 }}>CORWADO Digital Extension &amp; Market Linkage</div>
            <div style={{ fontSize: 13, color: '#ffffffaa', marginTop: 2 }}>LAST Project · Western Bahr el Ghazal · connected to live API</div>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12, color: '#ffffffcc', background: '#ffffff14', padding: '6px 12px', borderRadius: 20 }}>
            <Signal size={14} aria-hidden="true" /> {loading ? 'Connecting…' : error ? 'Connection issue' : 'Connected'}
          </div>
        </div>
      </header>

      <nav aria-label="Main navigation" style={{ background: '#fff', borderBottom: `1px solid ${COLORS.sage}44`, padding: '0 28px' }}>
        <div style={{ maxWidth: 1080, margin: '0 auto', display: 'flex', gap: 4 }}>
          {navItems.map(item => (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              aria-current={tab === item.key ? 'page' : undefined}
              style={{
                padding: '14px 16px', border: 'none', background: 'none',
                borderBottom: tab === item.key ? `2px solid ${COLORS.ochre}` : '2px solid transparent',
                color: tab === item.key ? COLORS.forest : COLORS.charcoal + '88',
                fontWeight: 600, fontSize: 14,
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      </nav>

      <main id="main-content" style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 28px 60px' }}>
        {error && <ErrorBanner message={`Is the backend running at the URL set in VITE_API_URL? (${error})`} onRetry={loadDashboardData} />}
        {loading && <LoadingState label="Loading platform data…" />}

        {!loading && !error && selectedStewardId && (
          <FarmerDetailView stewardId={selectedStewardId} onBack={() => setSelectedStewardId(null)} />
        )}

        {!loading && !error && !selectedStewardId && tab === 'dashboard' && (
          <>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 22 }}>
              <StatCard icon={Users} label="Registered Farmers" value={stewards?.length ?? 0} sub={`${femaleCount} women · ${youthCount} youth`} />
              <StatCard icon={CheckCircle2} label="Accessibility Flagged" value={disabilityCount} sub="Routed to IVR / in-person by default" />
              <StatCard icon={Sprout} label="Open Buyer Postings" value={postings?.length ?? 0} sub="Live market demand" />
              <StatCard icon={TrendingUp} label="Price Board Entries" value={prices?.length ?? 0} sub="Most recent market prices" />
            </div>
            <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
              <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 17, fontWeight: 600, marginTop: 0, marginBottom: 14 }}>Registered farmers</h2>
              {(!stewards || stewards.length === 0) && (
                <p style={{ color: COLORS.charcoal + '88', fontSize: 14 }}>
                  No farmers registered yet. Use "Farmer Registration" to add the first one, or run
                  <code style={{ background: COLORS.sand, padding: '2px 6px', borderRadius: 4, marginLeft: 4 }}>python -m app.seed</code> against the backend.
                </p>
              )}
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {stewards?.map((s, i) => (
                  <li key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: i > 0 ? `1px solid ${COLORS.sage}22` : 'none' }}>
                    <FarmerNameLink steward={s} onSelect={setSelectedStewardId} />
                    <ChannelBadge channelKey={s.preferred_channel} />
                    {s.is_youth && <span style={{ fontSize: 11, color: COLORS.ochre, fontWeight: 600 }}>Youth</span>}
                    {s.has_disability && <span style={{ fontSize: 11, color: COLORS.clay, fontWeight: 600 }}>Accessibility flagged</span>}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}

        {!loading && !error && !selectedStewardId && tab === 'registration' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ background: '#fff', borderRadius: 12, border: `1px solid ${COLORS.sage}33`, padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 17, fontWeight: 600, margin: 0 }}>Register a farmer</h2>
                <button onClick={() => { setRegisterStep('form'); setShowRegister(true); }} style={{ background: COLORS.forest, color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Plus size={15} aria-hidden="true" /> Register farmer
                </button>
              </div>
              <p style={{ fontSize: 13, color: COLORS.charcoal + '88' }}>
                This posts directly to <code>POST /api/stewards</code> — check the backend logs or database to confirm a new row was created.
              </p>
            </div>

            <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
              <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 17, fontWeight: 600, marginTop: 0, marginBottom: 14 }}>Registered farmers</h2>
              {(!stewards || stewards.length === 0) && (
                <p style={{ color: COLORS.charcoal + '88', fontSize: 14 }}>No farmers registered yet.</p>
              )}
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {stewards?.map((s, i) => (
                  <li key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: i > 0 ? `1px solid ${COLORS.sage}22` : 'none' }}>
                    <FarmerNameLink steward={s} onSelect={setSelectedStewardId} />
                    <ChannelBadge channelKey={s.preferred_channel} />
                    {s.is_youth && <span style={{ fontSize: 11, color: COLORS.ochre, fontWeight: 600 }}>Youth</span>}
                    {s.has_disability && <span style={{ fontSize: 11, color: COLORS.clay, fontWeight: 600 }}>Accessibility flagged</span>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {!loading && !error && !selectedStewardId && tab === 'market' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
              <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 17, fontWeight: 600, marginTop: 0 }}>Price board</h2>
              {(!prices || prices.length === 0) && <p style={{ color: COLORS.charcoal + '88', fontSize: 14 }}>No prices recorded yet.</p>}
              {prices?.map((p, i) => (
                <div key={p.id || i} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderTop: i > 0 ? `1px solid ${COLORS.sage}22` : 'none', fontSize: 14 }}>
                  <span>{p.market_location}</span>
                  <span style={{ fontFamily: 'monospace', color: COLORS.forest, fontWeight: 700 }}>SSP {p.price_ssp}/{p.unit}</span>
                </div>
              ))}
            </div>
            <div style={{ background: '#fff', borderRadius: 12, padding: 20, border: `1px solid ${COLORS.sage}33` }}>
              <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 17, fontWeight: 600, marginTop: 0 }}>Open buyer postings</h2>
              {(!postings || postings.length === 0) && <p style={{ color: COLORS.charcoal + '88', fontSize: 14 }}>No open postings yet.</p>}
              {postings?.map((p, i) => (
                <div key={p.id || i} style={{ padding: '12px 0', borderTop: i > 0 ? `1px solid ${COLORS.sage}22` : 'none' }}>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{p.quantity_kg} kg requested</div>
                  <div style={{ fontSize: 13, color: COLORS.charcoal + 'aa' }}>SSP {p.offer_price_ssp}/kg, needed by {p.needed_by || 'unspecified'}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {showRegister && (
        <div role="dialog" aria-modal="true" aria-labelledby="register-title" style={{ position: 'fixed', inset: 0, background: '#00000055', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 50 }}>
          <div style={{ background: '#fff', borderRadius: 14, padding: 24, width: registerStep === 'form' ? 420 : 520, maxWidth: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 id="register-title" style={{ fontFamily: 'Newsreader, serif', fontSize: 18, fontWeight: 600, margin: 0 }}>
                {registerStep === 'form' && 'Register farmer'}
                {registerStep === 'draw' && 'Trace farm boundary'}
                {registerStep === 'baseline' && 'Farm suitability'}
              </h2>
              <button type="button" onClick={closeRegisterDialog} aria-label="Close dialog" style={{ background: 'none', border: 'none' }}><X size={20} aria-hidden="true" /></button>
            </div>

            {registerStep === 'form' && (
              <form onSubmit={submitRegistration}>
                <label htmlFor="full_name" style={{ fontSize: 12, fontWeight: 600, color: COLORS.charcoal + 'aa' }}>Full name</label>
                <input id="full_name" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} required
                  style={{ width: '100%', padding: 10, border: `1px solid ${COLORS.sage}66`, borderRadius: 8, margin: '4px 0 12px', fontSize: 14 }} />

                <label htmlFor="preferred_channel" style={{ fontSize: 12, fontWeight: 600, color: COLORS.charcoal + 'aa' }}>Preferred channel</label>
                <select id="preferred_channel" value={form.preferred_channel} onChange={e => setForm({ ...form, preferred_channel: e.target.value })}
                  style={{ width: '100%', padding: 10, border: `1px solid ${COLORS.sage}66`, borderRadius: 8, margin: '4px 0 12px', fontSize: 14 }}>
                  {CHANNELS.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>

                <div style={{ display: 'flex', gap: 16, margin: '4px 0 16px' }}>
                  <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input type="checkbox" checked={form.is_youth} onChange={e => setForm({ ...form, is_youth: e.target.checked })} /> Youth
                  </label>
                  <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input type="checkbox" checked={form.has_disability} onChange={e => setForm({ ...form, has_disability: e.target.checked })} /> Accessibility needs
                  </label>
                </div>

                <button type="submit" style={{ width: '100%', background: COLORS.forest, color: '#fff', border: 'none', borderRadius: 8, padding: 12, fontWeight: 700, fontSize: 14 }}>
                  Register
                </button>
              </form>
            )}

            {registerStep === 'draw' && newSteward && (
              <ParcelDrawStep
                steward={newSteward}
                onSaved={(parcel) => { setNewParcel(parcel); setRegisterStep('baseline'); }}
                onSkip={closeRegisterDialog}
              />
            )}

            {registerStep === 'baseline' && newParcel && (
              <ParcelBaselineStep parcel={newParcel} onDone={closeRegisterDialog} />
            )}
          </div>
        </div>
      )}

      {toast && (
        <div role="status" aria-live="polite" style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          background: COLORS.forestDark, color: '#fff', padding: '12px 20px', borderRadius: 10,
          fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8, zIndex: 60,
        }}>
          <CheckCircle2 size={16} aria-hidden="true" /> {toast}
        </div>
      )}
    </div>
  );
}
