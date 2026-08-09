#!/bin/bash
set -e
echo "=== containers ==="
docker ps --format '{{.Names}} {{.Status}}' | grep -i mail || true
echo "=== subscriptions (via app certs) ==="
docker exec -i mail-manager python - <<'PY'
import os
from pathlib import Path
from urllib.parse import urlparse
from pymongo import MongoClient

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

client = MongoClient(uri, serverSelectionTimeoutMS=20000, **kwargs)
db = client[db_name]
n = db.push_subscriptions.count_documents({})
print("db", db_name, "subs", n, flush=True)
for s in db.push_subscriptions.find().limit(50):
    ep = s.get("endpoint") or ""
    host = urlparse(ep).netloc
    keys = s.get("keys") or {}
    print(
        s.get("user_email"),
        "|",
        host,
        "|",
        "ok-keys" if keys.get("p256dh") and keys.get("auth") else "BAD-keys",
        "|",
        (ep[:100] + ("…" if len(ep) > 100 else "")),
        flush=True,
    )
print("done", flush=True)
PY

echo "=== recent push-ish logs ==="
docker logs --tail 80 mail-manager 2>&1 | grep -iE 'push|vapid|Web push|Background sync|\+.*messaggi' | tail -40 || true
