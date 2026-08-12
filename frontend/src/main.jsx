import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom/client';
import App, { DrawBoundaryPage } from './App.jsx';
import Login from './Login.jsx';
import { auth } from './auth.js';

// No client-side router in this project (see DrawBoundaryPage's comment
// in App.jsx) -- the Telegram BOUNDARY hand-off link is the one route
// that isn't part of the normal dashboard shell, so it's picked here at
// mount time instead of inside a component (keeps this decision out of
// App()'s own hook order).
const drawToken = window.location.pathname === '/draw-boundary'
  ? new URLSearchParams(window.location.search).get('token')
  : null;

// Gates the dashboard behind staff login. The public draw-boundary page is
// NOT gated (it carries its own single-use token). A 401 from any API call
// clears the token (api.js -> auth.handleUnauthorized) and flips back to login.
function AuthGate() {
  const [authed, setAuthed] = useState(auth.hasToken());
  useEffect(() => {
    auth.onUnauthorized(() => setAuthed(false));
    return () => auth.onUnauthorized(null);
  }, []);
  if (!authed) return <Login onLoggedIn={() => setAuthed(true)} />;
  return <App onLogout={() => { auth.logout(); setAuthed(false); }} />;
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {drawToken ? <DrawBoundaryPage token={drawToken} /> : <AuthGate />}
  </React.StrictMode>
);
