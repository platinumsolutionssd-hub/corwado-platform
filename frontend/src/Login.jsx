import React, { useState } from 'react';
import { auth } from './auth.js';

// Minimal staff login screen. Gates the dashboard; no signup / reset here.
export default function Login({ onLoggedIn }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const data = await auth.login(email.trim().toLowerCase(), password);
      if (data.organization_status && data.organization_status !== 'active') {
        auth.clear();
        setError(`Your organization is "${data.organization_status}" — an administrator must approve it before you can sign in.`);
        return;
      }
      onLoggedIn();
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={styles.page}>
      <form onSubmit={submit} style={styles.card}>
        <h1 style={styles.title}>CORWADO</h1>
        <p style={styles.subtitle}>Staff sign in</p>

        <label style={styles.label}>Email</label>
        <input type="email" autoComplete="username" value={email} required
               onChange={(e) => setEmail(e.target.value)} style={styles.input} />

        <label style={styles.label}>Password</label>
        <input type="password" autoComplete="current-password" value={password} required
               onChange={(e) => setPassword(e.target.value)} style={styles.input} />

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" disabled={busy || !email || !password} style={styles.button}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}

const FOREST = '#1f3d2b';
const styles = {
  page: { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: '#f4f2ec', fontFamily: 'system-ui, sans-serif', padding: 16 },
  card: { width: '100%', maxWidth: 360, background: '#fff', borderRadius: 12,
          padding: '32px 28px', boxShadow: '0 8px 30px rgba(0,0,0,0.08)', display: 'flex', flexDirection: 'column' },
  title: { fontFamily: 'Newsreader, serif', fontSize: 26, fontWeight: 700, color: FOREST, margin: '0 0 4px', textAlign: 'center' },
  subtitle: { fontSize: 14, color: '#6b6b6b', margin: '0 0 24px', textAlign: 'center' },
  label: { fontSize: 12, fontWeight: 600, color: '#444', margin: '10px 0 4px' },
  input: { padding: '10px 12px', fontSize: 15, border: '1px solid #d5d2c8', borderRadius: 8, outline: 'none' },
  error: { marginTop: 14, padding: '10px 12px', fontSize: 13, color: '#8a1c1c', background: '#fbeaea', borderRadius: 8 },
  button: { marginTop: 22, padding: '11px 12px', fontSize: 15, fontWeight: 600, color: '#fff',
            background: FOREST, border: 'none', borderRadius: 8, cursor: 'pointer' },
};
