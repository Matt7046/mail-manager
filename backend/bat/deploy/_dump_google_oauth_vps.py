#!/usr/bin/env python3
"""Dump exact GOOGLE_* from VPS container + file (hex/repr). No full secret print."""
from __future__ import annotations

import json
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import urlopen

REMOTE = "root@173.212.220.20"


def ssh(cmd: str) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", REMOTE, cmd],
        check=True,
        text=True,
        capture_output=True,
    )
    return r.stdout


def main() -> int:
    script = r"""
import json, subprocess
ps = subprocess.check_output(['docker','ps','--filter','name=mail-manager','--format','{{.ID}} {{.Names}}'], text=True).strip()
print('CONTAINERS', repr(ps))
cid = ps.split()[0]
out = {}
for k in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI'):
    raw = subprocess.check_output(['docker','exec',cid,'printenv',k])
    content = raw.rstrip(b'\n')
    out[k] = {
        'len': len(content),
        'hex': content.hex(),
        'repr': content.decode('utf-8', 'replace'),
        'has_cr': content.endswith(b'\r'),
        'has_ws': content != content.strip(),
    }
print('JSON', json.dumps(out))
with open('/root/mail-manager/backend/.env','rb') as f:
    data = f.read()
for line in data.splitlines():
    if line.startswith(b'GOOGLE_CLIENT_ID=') or line.startswith(b'GOOGLE_REDIRECT_URI=') or line.startswith(b'GOOGLE_CLIENT_SECRET='):
        print('FILE', line.split(b'=',1)[0].decode(), 'hex', line.hex())
"""
    print(ssh(f"python3 - <<'PY'\n{script}\nPY"))

    status = urlopen("https://mail.colorsdev.tech/api/accounts/oauth/status", timeout=20).read().decode()
    print("STATUS", status)

    # Build authorize URL inside container (no vault auth needed)
    build = ssh(
        "docker exec mail-manager python - <<'PY'\n"
        "import os\n"
        "from urllib.parse import urlencode, parse_qs, urlparse, unquote\n"
        "cid = os.environ['GOOGLE_CLIENT_ID']\n"
        "redir = os.environ.get('GOOGLE_REDIRECT_URI','')\n"
        "q = urlencode({'client_id': cid, 'redirect_uri': redir, 'response_type': 'code', 'state': 'x'})\n"
        "url = 'https://accounts.google.com/o/oauth2/v2/auth?' + q\n"
        "qs = parse_qs(urlparse(url).query)\n"
        "print('CID', cid)\n"
        "print('REDIR_REPR', repr(redir))\n"
        "print('QS_REDIR', [unquote(x) for x in qs.get('redirect_uri', [])])\n"
        "print('URL_PARAM', url.split('redirect_uri=')[1].split('&')[0])\n"
        "PY"
    )
    print(build)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as e:
        print("SSH_FAIL", e.returncode, e.stdout, e.stderr, file=sys.stderr)
        raise SystemExit(1)
