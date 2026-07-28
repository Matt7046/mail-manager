# Mail Manager (v2)

Vault personale multi-casella: **Gmail, Outlook, IMAP e PEC** (lettura + **invio PEC**), inbox unificata, ricevute certificate, PWA.

URL target: `https://mail.colorsdev.tech`

Stack: **Expo (React Native / Web PWA)** · **FastAPI** · **MongoDB** · worker sync IMAP.

Sibling di [Password Manager](https://github.com/Matt7046/password-manager) e [Activity Manager](https://github.com/Matt7046/activity-manager).

## Scope v2 (questo scaffold)

- Auth vault (master password + biometria lato app)
- Account: Google / Microsoft OAuth (hook), IMAP, **PEC**
- Inbox unificata, filtri, cerca
- Dettaglio messaggio + allegati meta
- **Compose** anche da account PEC + tracking ricevute
- Regole semplici, export ZIP (stub), sync status
- PWA installabile

## Struttura

```
mail-manager/
  backend/          FastAPI + Mongo
  frontend/         Expo Router PWA
  BRIEF.md          prodotto v1→v2
```

## Avvio locale

### Backend

```bash
cd backend
cp .env.EMPTY .env
# MONGO_URL=...  DB_NAME=mail_manager  SERVER_SECRET=...
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.EMPTY .env
# EXPO_PUBLIC_BACKEND_URL=http://localhost:8000
yarn install
npx expo start --web
```

## Deploy (come Password Manager)

Tunnel Cloudflare → nginx dedicato → API `mail-manager:8000`, web static export sotto `/web`.  
Non toccare nginx di Activity Manager.

## Cosa non è ancora wired

- Sync IMAP reale / OAuth token exchange (hook + modelli pronti)
- IDLE push e notifiche web push
- Sanitizzazione HTML avanzata e antivirus allegati

I contratti API e le schermate ci sono: si implementano i provider sopra lo scheletro.
