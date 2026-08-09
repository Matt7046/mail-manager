/**
 * Persistenza sessione vault (web).
 * Il master password era solo in memoria React: un click su notifica che
 * apre una nuova finestra / naviga via SW azzerava l'auth e mostrava
 * inbox vuota ("account non collegati").
 *
 * sessionStorage: stesso tab dopo reload
 * localStorage: nuova finestra PWA da notificationclick
 */

const SESSION_KEY = 'mm_vault_session';

export type VaultSession = {
  email: string;
  masterPassword: string;
};

function canUseStorage(): boolean {
  return typeof window !== 'undefined';
}

export function readVaultSession(): VaultSession | null {
  if (!canUseStorage()) return null;
  try {
    const raw =
      window.sessionStorage.getItem(SESSION_KEY) ||
      window.localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const email = typeof parsed?.email === 'string' ? parsed.email.trim().toLowerCase() : '';
    const masterPassword =
      typeof parsed?.masterPassword === 'string' ? parsed.masterPassword : '';
    if (!email || !masterPassword) return null;
    return { email, masterPassword };
  } catch {
    return null;
  }
}

export function writeVaultSession(email: string, masterPassword: string): void {
  if (!canUseStorage()) return;
  const payload = JSON.stringify({
    email: email.trim().toLowerCase(),
    masterPassword,
  });
  try {
    window.sessionStorage.setItem(SESSION_KEY, payload);
  } catch {
    /* quota / private mode */
  }
  try {
    window.localStorage.setItem(SESSION_KEY, payload);
  } catch {
    /* quota / private mode */
  }
}

export function clearVaultSession(): void {
  if (!canUseStorage()) return;
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}
