"""Web Push (VAPID) per notifiche nuova email — PWA mobile + desktop."""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger("mail-manager.push")

_vapid_public: Optional[str] = None
_vapid_private: Optional[str] = None
_vapid_mailto: str = "mailto:mail@colorsdev.tech"


def vapid_configured() -> bool:
    return bool(_vapid_public and _vapid_private)


def get_vapid_public() -> Optional[str]:
    return _vapid_public


def set_vapid_keys(public_key: str, private_key: str) -> None:
    global _vapid_public, _vapid_private
    _vapid_public = (public_key or "").strip()
    _vapid_private = (private_key or "").strip()


def generate_vapid_keypair() -> Dict[str, str]:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_raw).decode("ascii").rstrip("=")
    return {"public_key": pub_b64, "private_key": priv_pem}


def init_vapid_from_env() -> Dict[str, str]:
    global _vapid_mailto
    _vapid_mailto = os.environ.get("VAPID_MAILTO", "mailto:mail@colorsdev.tech")
    pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if pub and priv:
        set_vapid_keys(pub, priv)
        return {"public_key": pub, "private_key": priv, "source": "env"}
    return {"public_key": "", "private_key": "", "source": "none"}


def send_push_to_subscription(subscription: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    if not vapid_configured():
        return False
    try:
        from pywebpush import webpush
    except Exception as exc:
        log.warning("pywebpush non disponibile: %s", exc)
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=_vapid_private,
            vapid_claims={"sub": _vapid_mailto},
        )
        return True
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning("Web push fallito status=%s: %s", status, exc)
        if status in (404, 410):
            raise
        return False


def notify_new_mail(
    subscriptions: List[Dict[str, Any]],
    *,
    title: str,
    body: str,
    url: str = "/home",
    tag: str = "new-mail",
) -> List[str]:
    """Invia push; ritorna endpoint da rimuovere (scaduti)."""
    dead: List[str] = []
    payload = {"title": title, "body": body, "url": url, "tag": tag}
    for sub in subscriptions:
        endpoint = (sub.get("endpoint") or "") if isinstance(sub, dict) else ""
        try:
            send_push_to_subscription(sub, payload)
        except Exception:
            if endpoint:
                dead.append(endpoint)
    return dead
