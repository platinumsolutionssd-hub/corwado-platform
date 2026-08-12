/**
 * Staff auth: token store + login/logout.
 *
 * The JWT is held in memory and mirrored to sessionStorage (per-tab, cleared
 * when the tab closes) — NOT localStorage, so a shared/kiosk machine doesn't
 * leave a persistent session behind. api.js attaches it as `Authorization:
 * Bearer` on every request and calls handleUnauthorized() on any 401.
 */
import { BASE_URL } from './config.js';

const KEY = 'ft_staff_token';
let _token = sessionStorage.getItem(KEY) || null;
let _onUnauthorized = () => {};

export const auth = {
  token: () => _token,
  hasToken: () => !!_token,

  setToken(t) {
    _token = t || null;
    if (t) sessionStorage.setItem(KEY, t);
    else sessionStorage.removeItem(KEY);
  },

  clear() {
    this.setToken(null);
  },

  // Registered by the auth gate; runs when a 401 clears the token so the UI
  // can drop back to the login screen.
  onUnauthorized(fn) {
    _onUnauthorized = typeof fn === 'function' ? fn : () => {};
  },

  handleUnauthorized() {
    this.clear();
    _onUnauthorized();
  },

  // POST /api/auth/login -> { access_token, token_type, organization_status }.
  // Uses its own fetch (not api.request) so this module never imports api.js.
  async login(email, password) {
    const res = await fetch(`${BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const body = await res.text();
      let detail = body;
      try {
        const parsed = JSON.parse(body);
        if (typeof parsed.detail === 'string') detail = parsed.detail;
      } catch { /* not JSON */ }
      throw new Error(detail || 'Login failed');
    }
    const data = await res.json();
    this.setToken(data.access_token);
    return data;
  },

  logout() {
    this.clear();
  },
};
