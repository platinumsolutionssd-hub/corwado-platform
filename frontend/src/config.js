// Single source of the backend base URL. Vite bakes VITE_API_URL in at build
// time; falls back to localhost for `npm run dev`. Shared by api.js and auth.js
// so they don't import each other for it (avoids a circular import).
export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
