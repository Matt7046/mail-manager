/**
 * If Google/Microsoft redirected to `/` or `/login` with ?code=&state=
 * (wrong Authorized redirect URI), forward to the real callback route.
 */
export function oauthCallbackPathFromQuery(): string | null {
  if (typeof window === 'undefined') return null;
  const sp = new URLSearchParams(window.location.search);
  const code = sp.get('code');
  const state = sp.get('state');
  if (!code || !state) return null;

  let provider: 'google' | 'microsoft' = 'google';
  try {
    const raw =
      sessionStorage.getItem('mm_oauth_pending') || localStorage.getItem('mm_oauth_pending');
    if (raw) {
      const p = JSON.parse(raw)?.provider;
      if (p === 'microsoft' || p === 'google') provider = p;
    }
  } catch {
    /* default google */
  }

  return `/oauth/${provider}/callback${window.location.search}`;
}
