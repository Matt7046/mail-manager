# Mail Manager (v2)

Vault personale multi-casella: **Gmail, Outlook, IMAP e PEC** (lettura + invio), inbox unificata, ricevute certificate, PWA con web push.

URL: https://mail.colorsdev.tech

Stack: **Expo (React Native / Web PWA)** · **FastAPI** · **MongoDB** · sync IMAP in background.

Sibling di [Password Manager](https://github.com/Matt7046/password-manager) e [Activity Manager](https://github.com/Matt7046/activity-manager).

## Funzionalità

- Auth vault con **master password**
- **Biometria** (come Password Manager): Windows Hello / Face ID / impronta via WebAuthn o `expo-local-authentication`. Si abilita da Home → **Biometria**; al login successivo usa **Usa biometrica** (o prompt automatico)
- Sessione tab in PWA (con biometria attiva serve Hello/password dopo Esci)
- Account: **OAuth Google / Microsoft** (IMAP/SMTP XOAUTH2), IMAP password, **PEC** (preset Aruba, Legalmail, Intesi, …)
- Inbox unificata con cartelle **Ricevute / Inviate / Cestino**
- Filtri combinabili: account, non lette, PEC; ricerca
- Dettaglio messaggio (HTML + immagini CID), allegati, flag letto
- Compose da qualsiasi account (anche PEC) + tracking ricevute
- Sync IMAP periodico (INBOX + Sent, inclusa Posta inviata Gmail) e pull-to-refresh
- Web Push su nuova mail; PWA installabile
- Export messaggio (ZIP), regole semplici

Dettagli OAuth: [`backend/OAUTH.md`](backend/OAUTH.md).

## Struttura

```
mail-manager/
  backend/              FastAPI + Mongo + mail_provider (IMAP/SMTP)
  backend/bat/deploy/   Script deploy VPS
  frontend/             Expo Router PWA
  BRIEF.md              brief prodotto
```

## Avvio locale

### Backend

```bash
cd backend
cp .env.EMPTY .env
# Compila MONGO_URL, DB_NAME, SERVER_SECRET (e opz. Google/Microsoft OAuth)
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

Health: `GET http://localhost:8000/api/health`

### Frontend

```bash
cd frontend
cp .env.EMPTY .env
# EXPO_PUBLIC_BACKEND_URL=http://localhost:8000
yarn install
npx expo start --web
```

## Deploy → https://mail.colorsdev.tech

DNS **GoDaddy** → VPS → nginx Activity Manager (`/root/nginx-apps/mail.colorsdev.tech.conf`) + API Docker sulla rete `backend_app-network`. Niente Cloudflare Tunnel.

```bat
cd backend\bat\deploy
SETUP-SERVER.BAT          rem una tantum: conf nginx-apps + compose + cert
DEPLOY-ALL.BAT            rem API Hub + web static
```

| Script | Cosa fa |
|--------|---------|
| `SETUP-SERVER.BAT` | Setup VPS / nginx-apps |
| `DEPLOY-API.BAT` | Build/push image + recreate `mail-manager` |
| `DEPLOY-WEB.BAT` | Export Expo → `/root/mail-manager/web` + reload nginx |
| `DEPLOY-ALL.BAT` | API + WEB |

Guida: [`backend/bat/deploy/README.md`](backend/bat/deploy/README.md).

## Sicurezza

- Password IMAP e token OAuth cifrati (chiave da email vault + `SERVER_SECRET`)
- Body messaggi cifrati a riposo dove previsto
- Biometria: WebAuthn / hardware come gate locale; la master password resta la chiave API (salvata in storage sicuro solo dopo abilitazione)
- Non loggare master password / secret in chiaro
