#!/usr/bin/env python3
"""Inspect VPS push status: logs, subscription count, vapid presence."""
from __future__ import annotations

import subprocess
import sys

REMOTE = "root@173.212.220.20"


def ssh(cmd: str) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", REMOTE, cmd],
        capture_output=True,
        text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    print(f"=== CMD: {cmd[:120]} ===")
    print(out)
    print(f"exit={r.returncode}\n")
    return out


def main() -> int:
    ssh(
        "docker ps --format '{{.Names}} {{.Status}}' | grep -i mail || docker ps --format '{{.Names}} {{.Status}}'"
    )
    ssh(
        "docker logs --tail 200 mail-manager 2>&1 | grep -iE 'push|vapid|Web push|Background sync|pywebpush' || true"
    )
    ssh(
        "docker logs --tail 30 mail-manager 2>&1 || true"
    )
    # Count subscriptions + sample endpoints (no keys) inside container via python if mongo reachable
    ssh(
        r"""docker exec mail-manager python - <<'PY'
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path

async def main():
    url = os.environ.get('MONGO_URL') or os.environ.get('MONGODB_URI') or ''
    dbn = os.environ.get('DB_NAME', 'mail_manager')
    print('DB', dbn, 'mongo_set', bool(url))
    kwargs = {}
    cert = Path('/app/certificate/client.pem')
    key = Path('/app/certificate/client-key.pem')
    if cert.exists() and key.exists():
        combined = Path('/tmp/mongo-client.pem')
        combined.write_bytes(cert.read_bytes() + b'\n' + key.read_bytes())
        kwargs['tls'] = True
        kwargs['tlsCertificateKeyFile'] = str(combined)
    client = AsyncIOMotorClient(url, **kwargs)
    db = client[dbn]
    n = await db.push_subscriptions.count_documents({})
    print('push_subscriptions', n)
    async for s in db.push_subscriptions.find({}, {'user_email':1,'endpoint':1,'updated_at':1}).limit(20):
        ep = (s.get('endpoint') or '')[:80]
        print(s.get('user_email'), ep, 'fcm' if 'fcm.googleapis.com' in ep else 'other')
    vapid = await db.settings.find_one({'_id':'vapid'})
    print('vapid_in_mongo', bool(vapid and vapid.get('public_key') and vapid.get('private_key')))
    if vapid:
        print('vapid_pub_prefix', (vapid.get('public_key') or '')[:20])
    print('env_vapid', bool(os.environ.get('VAPID_PUBLIC_KEY')), bool(os.environ.get('VAPID_PRIVATE_KEY')))

asyncio.run(main())
PY"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
