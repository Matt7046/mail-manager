#!/bin/bash
set -e
docker exec -i mail-manager python - <<'PY'
import os, json
from pathlib import Path
from pymongo import MongoClient
from pywebpush import webpush

uri = os.environ.get("MONGO_URL") or os.environ.get("MONGO_URI") or ""
db_name = os.environ.get("DB_NAME") or "mail_manager"
cert = os.environ.get("MONGO_CERT_PATH", "/app/certificate/client.pem")
key = os.environ.get("MONGO_KEY_PATH", "/app/certificate/client-key.pem")
kwargs = {}
if Path(cert).is_file() and Path(key).is_file():
    combined = Path("/tmp/mongo-client-combined-check.pem")
    combined.write_text(Path(cert).read_text(encoding="utf-8") + "\n" + Path(key).read_text(encoding="utf-8"), encoding="utf-8")
    kwargs["tls"] = True
    kwargs["tlsCertificateKeyFile"] = str(combined)

priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
mailto = os.environ.get("VAPID_MAILTO", "mailto:mail@colorsdev.tech")
db = MongoClient(uri, serverSelectionTimeoutMS=20000, **kwargs)[db_name]
subs = list(db.push_subscriptions.find({"user_email": "matteo.santangelo@colorsdev.tech"}))
print("subs", len(subs), flush=True)
payload = {
    "title": "Mail Manager",
    "body": "Test push VPS (TTL=86400) — se appare a telefono spento/chiuso, OK",
    "url": "/home",
    "tag": "push-test",
}
for s in subs:
    sub = {"endpoint": s["endpoint"], "keys": s.get("keys") or {}}
    host = s["endpoint"].split("/")[2]
    try:
        webpush(
            subscription_info=sub,
            data=json.dumps(payload),
            vapid_private_key=priv,
            vapid_claims={"sub": mailto},
            ttl=86400,
            headers={"Urgency": "high", "Topic": "push-test"},
        )
        print("OK", host, flush=True)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        print("FAIL", status, host, e, flush=True)
print("done", flush=True)
PY
