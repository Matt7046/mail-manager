# Deploy Mail Manager → https://mail.colorsdev.tech

Stesso schema di **Password Manager**: DNS su **GoDaddy** → VPS → **nginx colorsdev-site** (conf in `/root/nginx-apps/`) + container API sulla rete Docker.

Niente Cloudflare Tunnel.

## Setup una tantum

1. GoDaddy: record **A** `mail` → IP VPS (`173.212.220.20`)
2. `SETUP-SERVER.BAT` — copia compose, `.env`, cert Mongo, `mail.colorsdev.tech.conf` in `/root/nginx-apps/`
3. Certbot SSL per `mail.colorsdev.tech`
4. Path web: `/root/mail-manager/web` (visibile all’edge come `/var/www/root/mail-manager/web`) + reload nginx
5. `DEPLOY-ALL.BAT`

## Comandi (PC)

```bat
cd backend\bat\deploy
SETUP-SERVER.BAT
DEPLOY-API.BAT
DEPLOY-WEB.BAT
rem oppure:
DEPLOY-ALL.BAT
```

| Script | Cosa fa |
|--------|---------|
| `SETUP-SERVER.BAT` | dirs + file sul VPS + conf nginx-apps |
| `DEPLOY-API.BAT` | Hub image + `up` container `mail-manager` |
| `DEPLOY-WEB.BAT` | Expo export → `/root/mail-manager/web` + reload nginx AM |
| `DEPLOY-ALL.BAT` | API + WEB |
