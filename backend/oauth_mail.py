"""OAuth2 + XOAUTH2 helpers for Gmail and Microsoft Outlook IMAP/SMTP."""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx

log = logging.getLogger("mail-manager.oauth")

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"

MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_GRAPH_ME = "https://graph.microsoft.com/v1.0/me"

GOOGLE_SCOPES = " ".join(
    [
        "openid",
        "email",
        "profile",
        "https://mail.google.com/",
    ]
)

MS_SCOPES = " ".join(
    [
        "offline_access",
        "openid",
        "email",
        "profile",
        "https://outlook.office.com/IMAP.AccessAsUser.All",
        "https://outlook.office.com/SMTP.Send",
    ]
)


def provider_configured(provider: str) -> bool:
    p = provider.lower()
    if p == "google":
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
    if p == "microsoft":
        return bool(
            os.environ.get("MICROSOFT_CLIENT_ID") and os.environ.get("MICROSOFT_CLIENT_SECRET")
        )
    return False


def oauth_status() -> Dict[str, Any]:
    return {
        "google": {
            "configured": provider_configured("google"),
            "redirect_uri": os.environ.get(
                "GOOGLE_REDIRECT_URI", "https://mail.colorsdev.tech/oauth/google/callback"
            ),
        },
        "microsoft": {
            "configured": provider_configured("microsoft"),
            "redirect_uri": os.environ.get(
                "MICROSOFT_REDIRECT_URI",
                "https://mail.colorsdev.tech/oauth/microsoft/callback",
            ),
        },
    }


def build_authorize_url(provider: str, state: str) -> str:
    p = provider.lower()
    if p == "google":
        cid = os.environ["GOOGLE_CLIENT_ID"]
        redir = os.environ.get(
            "GOOGLE_REDIRECT_URI", "https://mail.colorsdev.tech/oauth/google/callback"
        )
        q = urlencode(
            {
                "client_id": cid,
                "redirect_uri": redir,
                "response_type": "code",
                "scope": GOOGLE_SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )
        return f"{GOOGLE_AUTH}?{q}"
    if p == "microsoft":
        cid = os.environ["MICROSOFT_CLIENT_ID"]
        redir = os.environ.get(
            "MICROSOFT_REDIRECT_URI",
            "https://mail.colorsdev.tech/oauth/microsoft/callback",
        )
        q = urlencode(
            {
                "client_id": cid,
                "redirect_uri": redir,
                "response_type": "code",
                "response_mode": "query",
                "scope": MS_SCOPES,
                "state": state,
            }
        )
        return f"{MS_AUTH}?{q}"
    raise ValueError(f"Provider sconosciuto: {provider}")


async def exchange_code(provider: str, code: str) -> Dict[str, Any]:
    p = provider.lower()
    async with httpx.AsyncClient(timeout=30) as client:
        if p == "google":
            redir = os.environ.get(
                "GOOGLE_REDIRECT_URI", "https://mail.colorsdev.tech/oauth/google/callback"
            )
            r = await client.post(
                GOOGLE_TOKEN,
                data={
                    "code": code,
                    "client_id": os.environ["GOOGLE_CLIENT_ID"],
                    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                    "redirect_uri": redir,
                    "grant_type": "authorization_code",
                },
            )
        elif p == "microsoft":
            redir = os.environ.get(
                "MICROSOFT_REDIRECT_URI",
                "https://mail.colorsdev.tech/oauth/microsoft/callback",
            )
            r = await client.post(
                MS_TOKEN,
                data={
                    "code": code,
                    "client_id": os.environ["MICROSOFT_CLIENT_ID"],
                    "client_secret": os.environ["MICROSOFT_CLIENT_SECRET"],
                    "redirect_uri": redir,
                    "grant_type": "authorization_code",
                    "scope": MS_SCOPES,
                },
            )
        else:
            raise ValueError(f"Provider sconosciuto: {provider}")
        if r.status_code >= 400:
            raise RuntimeError(f"Token exchange fallito ({r.status_code}): {r.text[:400]}")
        data = r.json()
    return normalize_token_payload(data)


async def refresh_access_token(provider: str, refresh_token: str) -> Dict[str, Any]:
    p = provider.lower()
    async with httpx.AsyncClient(timeout=30) as client:
        if p == "google":
            r = await client.post(
                GOOGLE_TOKEN,
                data={
                    "client_id": os.environ["GOOGLE_CLIENT_ID"],
                    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        elif p == "microsoft":
            r = await client.post(
                MS_TOKEN,
                data={
                    "client_id": os.environ["MICROSOFT_CLIENT_ID"],
                    "client_secret": os.environ["MICROSOFT_CLIENT_SECRET"],
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": MS_SCOPES,
                },
            )
        else:
            raise ValueError(f"Provider sconosciuto: {provider}")
        if r.status_code >= 400:
            raise RuntimeError(f"Refresh token fallito ({r.status_code}): {r.text[:400]}")
        data = r.json()
        if not data.get("refresh_token"):
            data["refresh_token"] = refresh_token
    return normalize_token_payload(data)


def normalize_token_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    expires_in = int(data.get("expires_in") or 3600)
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or "",
        "expires_at": int(time.time()) + expires_in - 60,
        "token_type": data.get("token_type") or "Bearer",
        "scope": data.get("scope") or "",
        "id_token": data.get("id_token"),
    }


def _email_from_id_token(id_token: Optional[str]) -> str:
    if not id_token:
        return ""
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return (
            (data.get("email") or data.get("preferred_username") or data.get("upn") or "")
            .lower()
            .strip()
        )
    except Exception:
        return ""


async def fetch_mailbox_address(
    provider: str, access_token: str, id_token: Optional[str] = None
) -> str:
    p = provider.lower()
    if p == "microsoft":
        email = _email_from_id_token(id_token)
        if email and "@" in email:
            return email
        # fallback: some tenants expose /me with outlook token via graph if consented
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(MS_GRAPH_ME, headers=headers)
            if r.status_code < 400:
                me = r.json()
                email = (
                    (me.get("mail") or me.get("userPrincipalName") or "").lower().strip()
                )
                if email and "@" in email:
                    return email
        raise RuntimeError(
            "Impossibile leggere l'email dall'id_token Microsoft — riprova il login OAuth"
        )

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        if p == "google":
            r = await client.get(GOOGLE_USERINFO, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"Google userinfo fallito: {r.text[:300]}")
            email = (r.json().get("email") or "").lower().strip()
        else:
            raise ValueError(f"Provider sconosciuto: {provider}")
    if not email or "@" not in email:
        raise RuntimeError("Impossibile determinare l'indirizzo email dall'account OAuth")
    return email


def xoauth2_string(user: str, access_token: str) -> str:
    return f"user={user}\x01auth=Bearer {access_token}\x01\x01"


def xoauth2_b64(user: str, access_token: str) -> str:
    return base64.b64encode(xoauth2_string(user, access_token).encode("utf-8")).decode(
        "ascii"
    )


def tokens_to_json(tokens: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or "",
            "expires_at": int(tokens.get("expires_at") or 0),
            "token_type": tokens.get("token_type") or "Bearer",
            "scope": tokens.get("scope") or "",
        }
    )


def tokens_from_json(raw: str) -> Dict[str, Any]:
    return json.loads(raw)


def provider_mailbox_defaults(provider: str) -> Dict[str, Any]:
    p = provider.lower()
    if p == "google":
        return {
            "type": "google",
            "pec_provider": "gmail",
            "label": "Gmail",
            "color": "#ea4335",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "smtp_ssl": True,
            "smtp_starttls": False,
        }
    if p == "microsoft":
        return {
            "type": "microsoft",
            "pec_provider": "outlook",
            "label": "Outlook",
            "color": "#0078d4",
            "imap_host": "outlook.office365.com",
            "imap_port": 993,
            "smtp_host": "smtp-mail.outlook.com",
            "smtp_port": 587,
            "smtp_ssl": False,
            "smtp_starttls": True,
        }
    raise ValueError(f"Provider sconosciuto: {provider}")
