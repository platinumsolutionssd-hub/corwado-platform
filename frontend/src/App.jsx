import React, { useState, useEffect, useCallback } from 'react';
import { Users, Sprout, TrendingUp, Radio, MessageSquare, Phone, Smartphone, Plus, X, CheckCircle2, Signal, Loader2 } from 'lucide-react';
import { api } from './api.js';

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

export default function App() {
  const [tab, setTab] = useState('dashboard');
  const [stewards, setStewards] = useState(null);
  const [prices, setPrices] = useState(null);
  const [postings, setPostings] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [form, setForm] = useState({ full_name: '', preferred_channel: 'sms', gender: 'female', role: 'smallholder_farmer', is_youth: false, has_disability: false });
  const [toast, setToast] = useState(null);

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
      await api.registerSteward(form);
      setShowRegister(false);
      setForm({ full_name: '', preferred_channel: 'sms', gender: 'female', role: 'smallholder_farmer', is_youth: false, has_disability: false });
      setToast('Farmer registered — saved to the database');
      loadDashboardData();
    } catch (e) {
      setToast(`Registration failed: ${e.message}`);
    }
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

        {!loading && !error && tab === 'dashboard' && (
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
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{s.full_name}</span>
                    <ChannelBadge channelKey={s.preferred_channel} />
                    {s.is_youth && <span style={{ fontSize: 11, color: COLORS.ochre, fontWeight: 600 }}>Youth</span>}
                    {s.has_disability && <span style={{ fontSize: 11, color: COLORS.clay, fontWeight: 600 }}>Accessibility flagged</span>}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}

        {!loading && !error && tab === 'registration' && (
          <div style={{ background: '#fff', borderRadius: 12, border: `1px solid ${COLORS.sage}33`, padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ fontFamily: 'Newsreader, serif', fontSize: 17, fontWeight: 600, margin: 0 }}>Register a farmer</h2>
              <button onClick={() => setShowRegister(true)} style={{ background: COLORS.forest, color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Plus size={15} aria-hidden="true" /> Register farmer
              </button>
            </div>
            <p style={{ fontSize: 13, color: COLORS.charcoal + '88' }}>
              This posts directly to <code>POST /api/stewards</code> — check the backend logs or database to confirm a new row was created.
            </p>
          </div>
        )}

        {!loading && !error && tab === 'market' && (
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
          <form onSubmit={submitRegistration} style={{ background: '#fff', borderRadius: 14, padding: 24, width: 420, maxWidth: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 id="register-title" style={{ fontFamily: 'Newsreader, serif', fontSize: 18, fontWeight: 600, margin: 0 }}>Register farmer</h2>
              <button type="button" onClick={() => setShowRegister(false)} aria-label="Close dialog" style={{ background: 'none', border: 'none' }}><X size={20} aria-hidden="true" /></button>
            </div>

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
