/** Web Push + Service Worker helpers (web/PWA only). */

const ENV_BASE =
  (typeof process !== 'undefined' && process.env.EXPO_PUBLIC_BACKEND_URL) ||
  'http://localhost:8000';

export type PushEnableResult = {
  ok: boolean;
  reason?: string;
  message: string;
};

function apiBase(): string {
  if (typeof window !== 'undefined') {
    const origin = window.location.origin;
    // Same-origin on production avoids wrong localhost BASE after export mishaps
    if (/mail\.colorsdev\.tech$/i.test(window.location.hostname)) {
      return origin;
    }
  }
  return ENV_BASE.replace(/\/$/, '');
}

function urlBase64ToUint8Array(base64String: string) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function isIosDevice(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const iOS = /iPad|iPhone|iPod/.test(ua);
  // iPadOS 13+ reports as Mac; detect touch
  const iPadOs =
    navigator.platform === 'MacIntel' && (navigator as any).maxTouchPoints > 1;
  return iOS || iPadOs;
}

/** iOS Web Push requires the app installed to Home Screen (standalone). */
export function isStandalonePwa(): boolean {
  if (typeof window === 'undefined') return false;
  const mq = window.matchMedia?.('(display-mode: standalone)')?.matches;
  const legacy = (navigator as any).standalone === true;
  const twa = window.matchMedia?.('(display-mode: minimal-ui)')?.matches;
  return !!(mq || legacy || twa);
}

function reasonMessage(reason: string): string {
  switch (reason) {
    case 'no-window':
      return 'Ambiente non web.';
    case 'unsupported':
      return isIosDevice()
        ? 'Su iPhone/iPad le notifiche push funzionano solo dalla PWA installata (Safari → Condividi → Aggiungi a Home), iOS 16.4+.'
        : 'Questo browser non supporta le notifiche push. Usa Chrome o Edge aggiornati.';
    case 'need-pwa':
      return 'Su iPhone/iPad: in Safari tocca Condividi → «Aggiungi a Home», apri Mail Manager dalla Home, poi riprova «Notifiche».';
    case 'denied':
      return 'Permesso notifiche negato. Abilitalo nelle impostazioni del browser o del sistema, poi riprova.';
    case 'default':
      return 'Permesso notifiche non concesso. Tocca Consenti quando compare la richiesta.';
    case 'no-sw':
      return 'Service Worker non attivo. Ricarica la pagina (o reinstalla la PWA) e riprova.';
    case 'no-vapid':
      return 'Server push non configurato. Riprova tra poco.';
    case 'subscribe-failed':
      return 'Impossibile creare la subscription push. Riprova dopo aver ricaricato l’app.';
    case 'no-session':
      return 'Sessione non valida. Effettua di nuovo l’accesso.';
    default:
      return reason || 'Attivazione notifiche fallita.';
  }
}

async function waitForActiveWorker(
  reg: ServiceWorkerRegistration,
  timeoutMs = 12_000,
): Promise<ServiceWorker | null> {
  if (reg.active) return reg.active;
  const worker = reg.installing || reg.waiting;
  if (!worker) {
    await navigator.serviceWorker.ready;
    return reg.active;
  }
  return new Promise((resolve) => {
    const done = () => resolve(reg.active);
    const t = setTimeout(done, timeoutMs);
    worker.addEventListener('statechange', () => {
      if (worker.state === 'activated' || worker.state === 'redundant') {
        clearTimeout(t);
        done();
      }
    });
  });
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return null;
  try {
    const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    // Prefer the newest worker immediately (important after deploy)
    if (reg.waiting) {
      reg.waiting.postMessage?.({ type: 'SKIP_WAITING' });
    }
    await waitForActiveWorker(reg);
    await navigator.serviceWorker.ready;
    return (await navigator.serviceWorker.getRegistration()) || reg;
  } catch (e) {
    console.warn('[sw] register failed', e);
    return null;
  }
}

export async function enablePushNotifications(
  email: string,
  masterPassword: string,
): Promise<PushEnableResult> {
  if (typeof window === 'undefined') {
    return { ok: false, reason: 'no-window', message: reasonMessage('no-window') };
  }

  const hasNotification = 'Notification' in window;
  const hasPushManager = 'PushManager' in window;
  const hasSW = 'serviceWorker' in navigator;

  // iOS: PushManager often missing until installed as Home Screen PWA
  if (isIosDevice() && (!hasPushManager || !isStandalonePwa())) {
    return { ok: false, reason: 'need-pwa', message: reasonMessage('need-pwa') };
  }

  if (!hasNotification || !hasPushManager || !hasSW) {
    return { ok: false, reason: 'unsupported', message: reasonMessage('unsupported') };
  }

  let permission = Notification.permission;
  if (permission === 'default') {
    permission = await Notification.requestPermission();
  }
  if (permission === 'denied') {
    return { ok: false, reason: 'denied', message: reasonMessage('denied') };
  }
  if (permission !== 'granted') {
    return { ok: false, reason: 'default', message: reasonMessage('default') };
  }

  const reg =
    (await registerServiceWorker()) || (await navigator.serviceWorker.getRegistration());
  if (!reg?.pushManager) {
    return { ok: false, reason: 'no-sw', message: reasonMessage('no-sw') };
  }

  const keyRes = await fetch(`${apiBase()}/api/push/vapid-public-key`);
  if (!keyRes.ok) {
    return { ok: false, reason: 'no-vapid', message: reasonMessage('no-vapid') };
  }
  const { publicKey } = await keyRes.json();
  if (!publicKey) {
    return { ok: false, reason: 'no-vapid', message: reasonMessage('no-vapid') };
  }

  const appServerKey = urlBase64ToUint8Array(publicKey);
  let sub: PushSubscription | null = null;
  try {
    sub = await reg.pushManager.getSubscription();
    if (sub) {
      // Re-subscribe if VAPID key changed (common after redeploy / key regen)
      const existingKey = sub.options?.applicationServerKey;
      let keyMatches = true;
      if (existingKey) {
        const a = new Uint8Array(existingKey);
        keyMatches =
          a.length === appServerKey.length && a.every((b, i) => b === appServerKey[i]);
      }
      if (!keyMatches) {
        await sub.unsubscribe().catch(() => undefined);
        sub = null;
      }
    }
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: appServerKey,
      });
    }
  } catch (e: any) {
    console.warn('[push] subscribe failed', e);
    return {
      ok: false,
      reason: 'subscribe-failed',
      message: e?.message || reasonMessage('subscribe-failed'),
    };
  }

  const json = sub.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    return { ok: false, reason: 'subscribe-failed', message: reasonMessage('subscribe-failed') };
  }

  const res = await fetch(`${apiBase()}/api/push/subscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      master_password: masterPassword,
      endpoint: json.endpoint,
      keys: json.keys,
      expiration_time: json.expirationTime ?? null,
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = (data as any).detail || res.statusText || 'subscribe error';
    return {
      ok: false,
      reason: typeof detail === 'string' ? detail : 'subscribe-failed',
      message: typeof detail === 'string' ? detail : reasonMessage('subscribe-failed'),
    };
  }

  // Prova immediata: conferma che FCM/APNs consegnano anche a PWA in background
  let testNote = '';
  const tested = await sendPushTest(email, masterPassword);
  if (tested) {
    markPushTestSent(email);
    testNote =
      ' Dovresti vedere subito una notifica di prova (chiudi l’app e attendi le nuove email).';
  } else {
    testNote =
      ' Subscription salvata, ma il test push non è andato a buon fine: ricarica e ritocca Notifiche.';
  }

  const tip = isIosDevice()
    ? 'Notifiche attivate. Su iPhone usa la PWA dalla Home; lascia Safari/Chrome non in Force Quit.'
    : 'Notifiche attivate su questo dispositivo (Web Push server-side).';
  return { ok: true, message: tip + testNote };
}

const PUSH_TEST_SESSION_KEY = 'mm_push_test_sent';

function markPushTestSent(email: string) {
  if (typeof sessionStorage === 'undefined') return;
  try {
    sessionStorage.setItem(PUSH_TEST_SESSION_KEY, email.toLowerCase());
  } catch (_) {
    /* ignore */
  }
}

function wasPushTestSent(email: string): boolean {
  if (typeof sessionStorage === 'undefined') return false;
  try {
    return sessionStorage.getItem(PUSH_TEST_SESSION_KEY) === email.toLowerCase();
  } catch (_) {
    return false;
  }
}

/** Invoca /api/push/test (richiede subscription già salvata). */
export async function sendPushTest(email: string, masterPassword: string): Promise<boolean> {
  try {
    const testRes = await fetch(`${apiBase()}/api/push/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, master_password: masterPassword }),
    });
    const testData = await testRes.json().catch(() => ({}));
    return !!(testRes.ok && (testData as any).ok);
  } catch (_) {
    return false;
  }
}

/**
 * Notifica di prova una sola volta per sessione browser (login / restore vault).
 * Non richiede gesto utente se la subscription esiste già.
 * `force: true` su login esplicito (reinvia anche se già inviata in questa tab).
 */
export async function sendPushTestOnce(
  email: string,
  masterPassword: string,
  opts?: { force?: boolean },
): Promise<boolean> {
  if (!opts?.force && wasPushTestSent(email)) return true;
  const ok = await sendPushTest(email, masterPassword);
  if (ok) markPushTestSent(email);
  return ok;
}
