/**
 * If Google redirected to bare `/` or `/login` (wrong GOOGLE_REDIRECT_URI),
 * forward code+state to the real callback route.
 */
export function oauthBareRedirectTarget(): string | null {
  if (typeof window === 'undefined') return null;
  const sp = new URLSearchParams(window.location.search);
  const code = sp.get('code');
  const state = sp.get('state');
  if (!code || !state) return null;
  const path = window.location.pathname || '/';
  if (path.includes('/oauth/')) return null;
  const qs = window.location.search || `?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`;
  return `/oauth/google/callback${qs}`;
}
