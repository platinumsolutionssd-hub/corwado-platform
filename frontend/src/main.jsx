import React from 'react';
import ReactDOM from 'react-dom/client';
import App, { DrawBoundaryPage } from './App.jsx';

// No client-side router in this project (see DrawBoundaryPage's comment
// in App.jsx) -- the Telegram BOUNDARY hand-off link is the one route
// that isn't part of the normal dashboard shell, so it's picked here at
// mount time instead of inside a component (keeps this decision out of
// App()'s own hook order).
const drawToken = window.location.pathname === '/draw-boundary'
  ? new URLSearchParams(window.location.search).get('token')
  : null;

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {drawToken ? <DrawBoundaryPage token={drawToken} /> : <App />}
  </React.StrictMode>
);
