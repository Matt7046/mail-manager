#!/usr/bin/env python3
"""Sync GOOGLE_* keys from local backend/.env to VPS, then force-recreate container."""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

LOCAL_ENV = Path(r"C:\Progetti\mail-manager\backend\.env")
REMOTE_HOST = "root@173.212.220.20"
REMOTE_ENV = "/root/mail-manager/backend/.env"
KEYS = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")


def ssh(cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", REMOTE_HOST, cmd],
        check=check,
        text=True,
        capture_output=True,
    )


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def mask_report(vals: dict[str, str], label: str) -> None:
    print(f"=== {label} ===")
    cid = vals.get("GOOGLE_CLIENT_ID", "")
    sec = vals.get("GOOGLE_CLIENT_SECRET", "")
    redir = vals.get("GOOGLE_REDIRECT_URI", "")
    print(f"GOOGLE_CLIENT_ID set={bool(cid)} prefix={cid[:4] if cid else ''} len={len(cid)}")
    print(f"GOOGLE_CLIENT_SECRET set={bool(sec)} last4={sec[-4:] if sec else ''} len={len(sec)}")
    print(f"GOOGLE_REDIRECT_URI={redir}")


def upsert_keys(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        raw = line.rstrip("\r\n")
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            k = raw.partition("=")[0].strip()
            if k in updates:
                nl = "\n" if line.endswith("\n") else ""
                new_lines.append(f"{k}={updates[k]}{nl}")
                seen.add(k)
                continue
        new_lines.append(line)
    missing = [k for k in KEYS if k not in seen]
    if missing:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"
        for k in missing:
            new_lines.append(f"{k}={updates[k]}\n")
    return "".join(new_lines)


def main() -> int:
    local = parse_env(LOCAL_ENV.read_text(encoding="utf-8"))
    local_vals = {k: local.get(k, "") for k in KEYS}
    mask_report(local_vals, "LOCAL")

    if not local_vals["GOOGLE_CLIENT_ID"] or not local_vals["GOOGLE_CLIENT_SECRET"]:
        print("ERROR: local GOOGLE_CLIENT_ID/SECRET empty")
        return 1

    # Fetch remote env without printing secrets
    remote_text = ssh(f"cat {REMOTE_ENV}").stdout
    remote = parse_env(remote_text)
    remote_vals = {k: remote.get(k, "") for k in KEYS}
    mask_report(remote_vals, "VPS_BEFORE")

    need_sync = any(local_vals[k] != remote_vals[k] for k in KEYS)
    if need_sync:
        print("SYNC: local GOOGLE_* differ from VPS — updating VPS .env (preserving other keys)")
        updated = upsert_keys(remote_text, local_vals)
        # Write via stdin to avoid shell quoting of secrets
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=20",
                REMOTE_HOST,
                f"cat > {REMOTE_ENV}.tmp && mv {REMOTE_ENV}.tmp {REMOTE_ENV} && chmod 600 {REMOTE_ENV}",
            ],
            input=updated,
            text=True,
            capture_output=True,
            check=True,
        )
        after = parse_env(ssh(f"cat {REMOTE_ENV}").stdout)
        mask_report({k: after.get(k, "") for k in KEYS}, "VPS_AFTER")
        for k in KEYS:
            if after.get(k, "") != local_vals[k]:
                print(f"ERROR: sync failed for {k}")
                return 1
        print("SYNC: OK")
    else:
        print("SYNC: VPS already matches local GOOGLE_* — skip write")

    print("RECREATE: docker compose --force-recreate mail-manager")
    up = ssh(
        "cd /root/mail-manager && docker compose up -d --force-recreate mail-manager",
        check=False,
    )
    print(up.stdout)
    print(up.stderr)
    if up.returncode != 0:
        # try alternate service name / compose location
        print("RECREATE primary failed; probing compose services...")
        ls = ssh("cd /root/mail-manager && docker compose config --services", check=False)
        print(ls.stdout or ls.stderr)
        # fallback: recreate whatever container matches mail-manager
        fb = ssh(
            "cd /root/mail-manager && docker compose up -d --force-recreate",
            check=False,
        )
        print(fb.stdout)
        print(fb.stderr)
        if fb.returncode != 0:
            print("ERROR: force-recreate failed")
            return 1

    # wait briefly for health
    import time

    time.sleep(4)
    status = ssh("docker ps --filter name=mail-manager --format '{{.Names}} {{.Status}}'", check=False)
    print("CONTAINER:", status.stdout.strip() or status.stderr.strip())

    # health + oauth status via public URL
    for url in (
        "https://mail.colorsdev.tech/api/health",
        "https://mail.colorsdev.tech/api/accounts/oauth/status",
    ):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                print(f"HTTP {resp.status} {url}")
                print(body[:2000])
        except Exception as e:
            print(f"HTTP FAIL {url}: {e}")
            # try via localhost on VPS
            path = url.split("https://mail.colorsdev.tech", 1)[1]
            local_try = ssh(
                f"curl -sS -m 10 http://127.0.0.1:8091{path} || curl -sS -m 10 http://127.0.0.1:8000{path} || true",
                check=False,
            )
            print("VPS curl:", local_try.stdout[:2000], local_try.stderr[:500])

    return 0


if __name__ == "__main__":
    sys.exit(main())
