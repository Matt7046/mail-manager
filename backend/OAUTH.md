# OAuth setup — Mail Manager

Redirect URI (devono coincidere con `.env` sul VPS):

- Google: `https://mail.colorsdev.tech/oauth/google/callback`
- Microsoft: `https://mail.colorsdev.tech/oauth/microsoft/callback`

## Google Cloud

1. Crea progetto + OAuth consent screen (External).
2. Credentials → OAuth client ID → Application type **Web application**.
3. Authorized redirect URIs: quella sopra.
4. Copia Client ID / Secret in `/root/mail-manager/backend/.env`:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI=https://mail.colorsdev.tech/oauth/google/callback`
5. `docker compose up -d --force-recreate mail-manager`

## Microsoft Azure AD

1. App registrations → New → account types **Personal Microsoft accounts and organizational**.
2. Authentication → Web → redirect URI sopra.
3. Certificates & secrets → new secret.
4. API permissions (Delegated): `openid`, `email`, `profile`, `offline_access`,
   `IMAP.AccessAsUser.All`, `SMTP.Send` (Exchange / Outlook).
5. In `.env` VPS:
   - `MICROSOFT_CLIENT_ID`
   - `MICROSOFT_CLIENT_SECRET`
   - `MICROSOFT_REDIRECT_URI=https://mail.colorsdev.tech/oauth/microsoft/callback`
6. Recreate container.

In UI Account → pulsanti **Google** / **Microsoft**.
