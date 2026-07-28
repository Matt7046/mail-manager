# Mail Manager — brief prodotto

## v1 (base)
Inbox multi-account, PEC in lettura + ricevute, compose solo non-PEC.

## v2 (questo repo)
Tutto v1 **più**:
- Invio PEC + tracking ricevute
- Regole (es. PEC → priorità)
- Export legale ZIP (messaggio + ricevute)
- Notifiche “nuova PEC” (hook)
- Firma per account, template risposta (stub UI)
- Bridge futuro verso Activity Manager (“crea attività da mail”)

## Schermate
Lock → Inbox → Messaggio → Compose / Accounts / Settings / Search

## Sicurezza
Token e password IMAP cifrati (chiave da email + `SERVER_SECRET`).  
Niente body in chiaro nei log.
