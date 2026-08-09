# OAuth setup — Mail Manager

Redirect URI (devono coincidere con `.env` sul VPS **e** con Google/Azure Console):

- Google: `https://mail.colorsdev.tech/oauth/google/callback`
- Microsoft: `https://mail.colorsdev.tech/oauth/microsoft/callback`

## Google Cloud (fix `redirect_uri_mismatch`)

1. Apri [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials).
2. Apri **il client OAuth il cui Client ID è uguale a** `GOOGLE_CLIENT_ID` sul VPS  
   (oggi: `549622774155-atv0j0qj40r1vpl1heibaughtf0t2lon.apps.googleusercontent.com` — **Client web 1**).
3. Tipo client: deve essere **Web application** (non Desktop / iOS / Android).
4. In **Authorized redirect URIs** incolla **esattamente** (senza slash finale, senza spazi):

   ```
   https://mail.colorsdev.tech/oauth/google/callback
   ```

   Non basta `https://mail.colorsdev.tech` (dominio nudo): Google manda `code`/`state` su `/` e la pagina callback che aggiunge l’account non viene mai eseguita.
5. Salva e attendi 1–5 minuti, poi riprova da Mail Manager → Account → Google.
6. Consent screen: External (o Internal se Workspace); l’utente di test deve essere in Test users se l’app è in Testing.
7. Abilita **Gmail API**; scope usati: `openid email profile https://mail.google.com/`.

### Errori tipici

- URI aggiunto su **un altro** Client ID (deve essere quello in `GOOGLE_CLIENT_ID`, oggi `549622…` Client web 1).
- Client di tipo **Desktop** senza URI Web (serve **Web application**).
- Solo dominio nudo in Console / `.env` → redirect su `/` o `/login` senza aggiungere l’account.
- `http://` invece di `https://`, trailing slash, path sbagliato (`/api/...` o `/oauth2/callback`).
- Modifica Console non ancora propagata.

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
