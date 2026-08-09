/**
 * Web platform authenticator (Windows Hello / Touch ID) via WebAuthn.
 * Usato quando expo-local-authentication non ha hardware su web/PC.
 */

const CRED_ID_KEY = 'mm_webauthn_cred_id';

function bufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = '';
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
}

function base64ToBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

export async function isWebPlatformAuthAvailable(): Promise<boolean> {
  if (typeof window === 'undefined' || !window.PublicKeyCredential) return false;
  try {
    return await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

export async function registerWebPlatformAuth(email: string): Promise<void> {
  if (!(await isWebPlatformAuthAvailable())) {
    throw new Error('Windows Hello / autenticazione piattaforma non disponibile su questo PC');
  }

  const challenge = crypto.getRandomValues(new Uint8Array(32));
  const userId = new TextEncoder().encode(email);

  const credential = (await navigator.credentials.create({
    publicKey: {
      challenge,
      rp: {
        name: 'Mail Manager',
        id: window.location.hostname,
      },
      user: {
        id: userId,
        name: email,
        displayName: email,
      },
      pubKeyCredParams: [
        { alg: -7, type: 'public-key' },
        { alg: -257, type: 'public-key' },
      ],
      authenticatorSelection: {
        authenticatorAttachment: 'platform',
        userVerification: 'required',
        residentKey: 'preferred',
      },
      timeout: 60000,
    },
  })) as PublicKeyCredential | null;

  if (!credential) {
    throw new Error('Registrazione biometrica annullata');
  }

  localStorage.setItem(CRED_ID_KEY, bufferToBase64(credential.rawId));
}

export async function authenticateWebPlatformAuth(): Promise<boolean> {
  if (!(await isWebPlatformAuthAvailable())) return false;

  const stored = localStorage.getItem(CRED_ID_KEY);
  if (!stored) {
    throw new Error('Nessuna biometrica registrata. Abilitala dopo il login.');
  }

  const challenge = crypto.getRandomValues(new Uint8Array(32));
  const assertion = await navigator.credentials.get({
    publicKey: {
      challenge,
      allowCredentials: [
        {
          id: base64ToBuffer(stored),
          type: 'public-key',
          transports: ['internal'],
        },
      ],
      userVerification: 'required',
      timeout: 60000,
    },
  });

  return !!assertion;
}

export function clearWebPlatformAuth(): void {
  try {
    localStorage.removeItem(CRED_ID_KEY);
  } catch {
    /* ignore */
  }
}
