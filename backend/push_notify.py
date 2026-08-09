"""Web Push (VAPID) per notifiche nuova email — PWA mobile + desktop."""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

log = logging.getLogger("mail-manager.push")

_vapid_public: Optional[str] = None
_vapid_private: Optional[str] = None
_vapid_mailto: str = "mailto:mail@colorsdev.tech"

# FCM/Android: TTL=0 = “solo se online ora, altrimenti scarta” → niente push a app chiusa.
# Urgency high aiuta a superare Doze sul canale FCM.
DEFAULT_TTL = int(os.environ.get("WEB_PUSH_TTL", "86400"))
DEFAULT_URGENCY = os.environ.get("WEB_PUSH_URGENCY", "high")


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


def _endpoint_host(endpoint: str) -> str:
    try:
        return urlparse(endpoint or "").netloc or "?"
    except Exception:
        return "?"


def send_push_to_subscription(subscription: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    if not vapid_configured():
        log.warning("Web push saltato: VAPID non configurato")
        return False
    try:
        from pywebpush import webpush
    except Exception as exc:
        log.warning("pywebpush non disponibile: %s", exc)
        return False

    endpoint = ""
    if isinstance(subscription, dict):
        endpoint = subscription.get("endpoint") or ""
    host = _endpoint_host(endpoint)

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=_vapid_private,
            vapid_claims={"sub": _vapid_mailto},
            ttl=DEFAULT_TTL,
            headers={
                "Urgency": DEFAULT_URGENCY,
                "Topic": str(payload.get("tag") or "new-mail")[:32],
            },
        )
        log.info(
            "Web push OK host=%s ttl=%s urgency=%s title=%s",
            host,
            DEFAULT_TTL,
            DEFAULT_URGENCY,
            (payload.get("title") or "")[:40],
        )
        return True
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning(
            "Web push fallito status=%s host=%s: %s",
            status,
            host,
            exc,
        )
        if status in (404, 410):
            raise
        return False


def notify_new_mail(
    subscriptions: List[Dict[str, Any]],
    *,
    title: str,
    body: str,
    url: str = "/",
    tag: str = "new-mail",
) -> Tuple[List[str], int, int]:
    """Invia push; ritorna (endpoint morti, ok_count, fail_count)."""
    dead: List[str] = []
    ok = 0
    fail = 0
    payload = {"title": title, "body": body, "url": url, "tag": tag}
    if not subscriptions:
        log.info("Web push: nessuna subscription da notificare")
        return dead, ok, fail

    log.info(
        "Web push invio a %s subscription(s) title=%s",
        len(subscriptions),
        title[:40],
    )
    for sub in subscriptions:
        endpoint = (sub.get("endpoint") or "") if isinstance(sub, dict) else ""
        try:
            if send_push_to_subscription(sub, payload):
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
            if endpoint:
                dead.append(endpoint)
    log.info(
        "Web push risultato ok=%s fail=%s dead=%s",
        ok,
        fail,
        len(dead),
    )
    return dead, ok, fail
