"""
Mail Manager API (v2) — vault multi-casella + PEC send/receipts.
Sync IMAP/OAuth provider implementations are hooks: models + routes are ready.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

import mail_provider
import oauth_mail

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mail-manager")

mongo_url = os.environ.get("MONGO_URL") or os.environ.get("MONGO_URI")
if not mongo_url:
    raise RuntimeError("Set MONGO_URL or MONGO_URI")

db_name = os.environ.get("DB_NAME") or "mail_manager"
mongo_cert = os.environ.get("MONGO_CERT_PATH", "/app/certificate/client.pem")
mongo_key = os.environ.get("MONGO_KEY_PATH", "/app/certificate/client-key.pem")

mongo_kwargs: Dict[str, Any] = {}
if Path(mongo_cert).is_file() and Path(mongo_key).is_file():
    combined = Path("/tmp/mongo-client-combined.pem")
    combined.write_text(
        Path(mongo_cert).read_text(encoding="utf-8")
        + "\n"
        + Path(mongo_key).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    mongo_kwargs["tls"] = True
    mongo_kwargs["tlsCertificateKeyFile"] = str(combined)

client = AsyncIOMotorClient(mongo_url, **mongo_kwargs)
db = client[db_name]

SERVER_SECRET = os.environ.get("SERVER_SECRET", "")
if not SERVER_SECRET:
    log.warning("SERVER_SECRET empty — set before production")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

AccountType = Literal["google", "microsoft", "imap", "pec"]
ReceiptType = Literal[
    "accettazione",
    "consegna",
    "mancata_consegna",
    "anomalia",
    "altra",
]


def enc_key(email: str) -> bytes:
    raw = hashlib.sha256(f"{email.lower()}:{SERVER_SECRET}".encode()).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt_secret(value: str, email: str) -> str:
    return Fernet(enc_key(email)).encrypt(value.encode()).decode()


def decrypt_secret(token: str, email: str) -> str:
    return Fernet(enc_key(email)).decrypt(token.encode()).decode()


# --- models ---


class SetupBody(BaseModel):
    email: EmailStr
    master_password: str = Field(min_length=8)


class LoginBody(BaseModel):
    email: EmailStr
    master_password: str


class AuthOk(BaseModel):
    email: str
    message: str = "ok"


class ImapAccountBody(BaseModel):
    email: EmailStr
    master_password: str
    label: str
    address: EmailStr
    account_type: AccountType = "imap"
    imap_host: str
    imap_port: int = 993
    imap_user: str
    imap_password: str = ""
    smtp_host: Optional[str] = None
    smtp_port: int = 465
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    pec_provider: Optional[str] = None  # aruba | legalmail | postecert | intesi | outlook | gmail | other
    color: str = "#4ecdc4"


class ImapAccountUpdateBody(BaseModel):
    email: EmailStr
    master_password: str
    label: Optional[str] = None
    address: Optional[EmailStr] = None
    account_type: Optional[AccountType] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_user: Optional[str] = None
    imap_password: Optional[str] = None  # se vuoto/None: non aggiornare
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    pec_provider: Optional[str] = None
    color: Optional[str] = None


class AccountOut(BaseModel):
    id: str
    type: AccountType
    label: str
    address: str
    color: str
    pec_provider: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    sync_state: str = "idle"
    last_sync_error: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_user: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    auth_method: Optional[str] = None


class OAuthStartBody(BaseModel):
    email: EmailStr
    master_password: str


class OAuthCompleteBody(BaseModel):
    email: EmailStr
    master_password: str
    code: str
    state: str


def public_account(doc: dict) -> AccountOut:
    return AccountOut(
        id=str(doc["_id"]),
        type=doc["type"],
        label=doc["label"],
        address=doc["address"],
        color=doc.get("color", "#4ecdc4"),
        pec_provider=doc.get("pec_provider"),
        last_sync_at=doc.get("last_sync_at"),
        sync_state=doc.get("sync_state", "idle"),
        last_sync_error=doc.get("last_sync_error"),
        imap_host=doc.get("imap_host"),
        imap_port=doc.get("imap_port"),
        imap_user=doc.get("imap_user"),
        smtp_host=doc.get("smtp_host"),
        smtp_port=doc.get("smtp_port"),
        auth_method=doc.get("auth_method") or "password",
    )


class MessageFlagsBody(BaseModel):
    email: EmailStr
    master_password: str
    seen: Optional[bool] = None
    flagged: Optional[bool] = None
    archived: Optional[bool] = None


class SendBody(BaseModel):
    email: EmailStr
    master_password: str
    account_id: str
    to: List[EmailStr]
    cc: List[EmailStr] = []
    bcc: List[EmailStr] = []
    subject: str
    body_text: str = ""
    body_html: Optional[str] = None
    as_pec: bool = False
    reply_to_message_id: Optional[str] = None


class RuleBody(BaseModel):
    email: EmailStr
    master_password: str
    name: str
    match_pec_only: bool = False
    match_account_id: Optional[str] = None
    action: Literal["flag", "priority", "label"] = "priority"
    action_value: str = "high"
    enabled: bool = True


# --- auth helpers ---


async def require_user(email: str, master_password: str) -> dict:
    user = await db.users.find_one({"email": email.lower()})
    if not user or not pwd_context.verify(master_password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide")
    return user


def apply_provider_hosts(
    pec_provider: Optional[str],
    *,
    imap_host: Optional[str],
    imap_port: Optional[int],
    smtp_host: Optional[str],
    smtp_port: Optional[int],
) -> Tuple[str, int, Optional[str], int]:
    presets = mail_provider.IMAP_PRESETS
    if pec_provider and pec_provider in presets:
        preset = presets[pec_provider]
        return (
            imap_host or preset["imap_host"],
            int(imap_port or preset["imap_port"]),
            smtp_host or preset["smtp_host"],
            int(smtp_port or preset["smtp_port"]),
        )
    return (
        imap_host or "",
        int(imap_port or 993),
        smtp_host,
        int(smtp_port or 465),
    )


def outlook_smtp_flags(pec_provider: Optional[str]) -> Dict[str, bool]:
    preset = mail_provider.IMAP_PRESETS.get(pec_provider or "", {})
    return {
        "smtp_ssl": bool(preset.get("smtp_ssl", True)),
        "smtp_starttls": bool(preset.get("smtp_starttls", False)),
    }


async def resolve_mailbox_creds(acc: dict, vault_email: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Ritorna (imap_user, password|None, access_token|None), con refresh OAuth se serve."""
    user = (acc.get("imap_user") or acc.get("address") or "").strip().lower()
    if acc.get("auth_method") == "oauth" and acc.get("oauth_tokens_enc"):
        tokens = oauth_mail.tokens_from_json(
            decrypt_secret(acc["oauth_tokens_enc"], vault_email)
        )
        if int(tokens.get("expires_at") or 0) <= int(time.time()):
            refresh = tokens.get("refresh_token") or ""
            if not refresh:
                raise HTTPException(
                    400, "Sessione OAuth scaduta — ricollega Google/Microsoft"
                )
            provider = "google" if acc.get("type") == "google" else "microsoft"
            refreshed = await oauth_mail.refresh_access_token(provider, refresh)
            await db.accounts.update_one(
                {"_id": acc["_id"]},
                {
                    "$set": {
                        "oauth_tokens_enc": encrypt_secret(
                            oauth_mail.tokens_to_json(refreshed), vault_email
                        ),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            tokens = refreshed
        return user, None, tokens["access_token"]

    if not acc.get("imap_password_enc"):
        raise HTTPException(400, "Account senza password né OAuth")
    pwd = decrypt_secret(acc["imap_password_enc"], vault_email)
    return user, pwd, None


# --- app ---

app = FastAPI(title="Mail Manager API", version="2.0.0")
api = APIRouter(prefix="/api")

origins = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:8081,http://localhost:19006,https://mail.colorsdev.tech",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/health")
async def health():
    return {"ok": True, "service": "mail-manager", "version": "2"}


@api.get("/auth/check_setup")
async def check_setup(email: Optional[str] = None):
    if email:
        user = await db.users.find_one({"email": email.lower()})
        return {"setup_done": bool(user), "email": email.lower() if user else ""}
    # Non prefillare email (allineato a Password Manager)
    return {"setup_done": await db.users.count_documents({}) > 0, "email": ""}


@api.post("/auth/setup", response_model=AuthOk)
async def setup(body: SetupBody):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Utente già registrato")
    await db.users.insert_one(
        {
            "email": email,
            "password_hash": pwd_context.hash(body.master_password),
            "created_at": datetime.utcnow(),
            "biometric_hint": False,
        }
    )
    return AuthOk(email=email, message="Vault creato")


@api.post("/auth/login", response_model=AuthOk)
async def login(body: LoginBody):
    await require_user(body.email.lower(), body.master_password)
    return AuthOk(email=body.email.lower())


# --- accounts ---

PEC_PRESETS = {
    k: v
    for k, v in mail_provider.IMAP_PRESETS.items()
    if k in ("aruba", "legalmail", "postecert", "intesi")
}

IMAP_PRESETS = mail_provider.IMAP_PRESETS


@api.get("/accounts", response_model=List[AccountOut])
async def list_accounts(email: EmailStr, master_password: str):
    await require_user(email.lower(), master_password)
    cur = db.accounts.find({"user_email": email.lower()}).sort("created_at", 1)
    return [public_account(d) async for d in cur]


@api.get("/accounts/pec-presets")
async def pec_presets():
    return PEC_PRESETS


@api.get("/accounts/imap-presets")
async def imap_presets():
    return IMAP_PRESETS


@api.post("/accounts/imap", response_model=AccountOut)
async def add_imap_account(body: ImapAccountBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    if not (body.imap_password or "").strip():
        raise HTTPException(400, "Password IMAP richiesta")
    imap_host, imap_port, smtp_host, smtp_port = apply_provider_hosts(
        body.pec_provider,
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
    )
    flags = outlook_smtp_flags(body.pec_provider)

    account_type = body.account_type
    if body.pec_provider == "gmail":
        account_type = "google"
    elif body.pec_provider == "outlook":
        account_type = "microsoft"
    elif body.pec_provider in ("aruba", "legalmail", "postecert", "intesi"):
        account_type = "pec"

    doc = {
        "user_email": email,
        "type": account_type,
        "label": body.label,
        "address": str(body.address).lower(),
        "color": body.color,
        "pec_provider": body.pec_provider,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "imap_user": (body.imap_user or str(body.address)).strip().lower(),
        "imap_password_enc": encrypt_secret(
            mail_provider.normalize_mailbox_secret(body.imap_password), email
        ),
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_ssl": flags["smtp_ssl"],
        "smtp_starttls": flags["smtp_starttls"],
        "smtp_user": (
            body.smtp_user or body.imap_user or str(body.address)
        ).strip().lower(),
        "smtp_password_enc": encrypt_secret(
            mail_provider.normalize_mailbox_secret(
                body.smtp_password or body.imap_password
            ),
            email,
        ),
        "oauth_tokens_enc": None,
        "last_sync_at": None,
        "sync_state": "idle",
        "created_at": datetime.utcnow(),
    }
    res = await db.accounts.insert_one(doc)
    doc["_id"] = res.inserted_id
    return public_account(doc)


@api.put("/accounts/{account_id}", response_model=AccountOut)
async def update_imap_account(account_id: str, body: ImapAccountUpdateBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        oid = ObjectId(account_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    acc = await db.accounts.find_one({"_id": oid, "user_email": email})
    if not acc:
        raise HTTPException(404, "Account non trovato")

    pec_provider = body.pec_provider if body.pec_provider is not None else acc.get("pec_provider")
    imap_host, imap_port, smtp_host, smtp_port = apply_provider_hosts(
        pec_provider,
        imap_host=body.imap_host if body.imap_host is not None else acc.get("imap_host"),
        imap_port=body.imap_port if body.imap_port is not None else acc.get("imap_port"),
        smtp_host=body.smtp_host if body.smtp_host is not None else acc.get("smtp_host"),
        smtp_port=body.smtp_port if body.smtp_port is not None else acc.get("smtp_port"),
    )
    flags = outlook_smtp_flags(pec_provider)

    updates: Dict[str, Any] = {
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_ssl": flags["smtp_ssl"],
        "smtp_starttls": flags["smtp_starttls"],
        "updated_at": datetime.utcnow(),
    }
    if body.label is not None:
        updates["label"] = body.label
    if body.address is not None:
        updates["address"] = str(body.address).lower()
    if body.imap_user is not None:
        updates["imap_user"] = body.imap_user.strip().lower()
    elif body.address is not None:
        updates["imap_user"] = str(body.address).lower()
    if body.smtp_user is not None:
        updates["smtp_user"] = body.smtp_user.strip().lower()
    if body.color is not None:
        updates["color"] = body.color
    if body.pec_provider is not None:
        updates["pec_provider"] = body.pec_provider
    if body.account_type is not None:
        updates["type"] = body.account_type
    elif pec_provider == "gmail":
        updates["type"] = "google"
    elif pec_provider == "outlook":
        updates["type"] = "microsoft"
    elif pec_provider in ("aruba", "legalmail", "postecert", "intesi"):
        updates["type"] = "pec"

    secret = (body.imap_password or "").strip()
    if secret:
        enc = encrypt_secret(mail_provider.normalize_mailbox_secret(secret), email)
        updates["imap_password_enc"] = enc
        updates["smtp_password_enc"] = encrypt_secret(
            mail_provider.normalize_mailbox_secret(body.smtp_password or secret),
            email,
        )

    await db.accounts.update_one({"_id": oid}, {"$set": updates})
    doc = await db.accounts.find_one({"_id": oid})
    return public_account(doc)


@api.get("/accounts/oauth/status")
async def oauth_providers_status():
    return oauth_mail.oauth_status()


@api.post("/accounts/oauth/{provider}/start")
async def oauth_start(provider: Literal["google", "microsoft"], body: OAuthStartBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    if not oauth_mail.provider_configured(provider):
        raise HTTPException(
            501,
            f"{provider} OAuth non configurato sul server "
            f"(manca CLIENT_ID/SECRET in .env). Vedi backend/.env.EMPTY",
        )
    state = secrets.token_urlsafe(24)
    await db.oauth_pending.insert_one(
        {
            "state": state,
            "provider": provider,
            "user_email": email,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=15),
        }
    )
    return {
        "authorize_url": oauth_mail.build_authorize_url(provider, state),
        "state": state,
        "provider": provider,
    }


@api.post("/accounts/oauth/{provider}/complete", response_model=AccountOut)
async def oauth_complete(provider: Literal["google", "microsoft"], body: OAuthCompleteBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    if not oauth_mail.provider_configured(provider):
        raise HTTPException(501, f"{provider} OAuth non configurato")

    pending = await db.oauth_pending.find_one({"state": body.state, "provider": provider})
    if not pending:
        raise HTTPException(400, "State OAuth non valido o già usato")
    if pending.get("user_email") != email:
        raise HTTPException(400, "State OAuth non corrisponde all'utente vault")
    if pending.get("expires_at") and pending["expires_at"] < datetime.utcnow():
        await db.oauth_pending.delete_one({"_id": pending["_id"]})
        raise HTTPException(400, "State OAuth scaduto — riprova")

    await db.oauth_pending.delete_one({"_id": pending["_id"]})

    try:
        tokens = await oauth_mail.exchange_code(provider, body.code)
        mailbox = await oauth_mail.fetch_mailbox_address(
            provider, tokens["access_token"], tokens.get("id_token")
        )
    except Exception as exc:
        log.exception("OAuth complete failed")
        raise HTTPException(400, f"OAuth fallito: {exc}") from exc

    defaults = oauth_mail.provider_mailbox_defaults(provider)
    existing = await db.accounts.find_one(
        {"user_email": email, "address": mailbox, "auth_method": "oauth"}
    )
    doc_set = {
        **defaults,
        "user_email": email,
        "address": mailbox,
        "imap_user": mailbox,
        "smtp_user": mailbox,
        "auth_method": "oauth",
        "oauth_tokens_enc": encrypt_secret(oauth_mail.tokens_to_json(tokens), email),
        "imap_password_enc": encrypt_secret("", email),
        "smtp_password_enc": encrypt_secret("", email),
        "sync_state": "idle",
        "updated_at": datetime.utcnow(),
    }
    if existing:
        await db.accounts.update_one({"_id": existing["_id"]}, {"$set": doc_set})
        doc = await db.accounts.find_one({"_id": existing["_id"]})
    else:
        doc_set["created_at"] = datetime.utcnow()
        doc_set["last_sync_at"] = None
        res = await db.accounts.insert_one(doc_set)
        doc = await db.accounts.find_one({"_id": res.inserted_id})
    return public_account(doc)


@api.delete("/accounts/{account_id}")
async def delete_account(account_id: str, email: EmailStr, master_password: str):
    from bson import ObjectId
    from bson.errors import InvalidId

    await require_user(email.lower(), master_password)
    try:
        oid = ObjectId(account_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    await db.messages.delete_many({"account_id": account_id, "user_email": email.lower()})
    res = await db.accounts.delete_one({"_id": oid, "user_email": email.lower()})
    if res.deleted_count == 0:
        raise HTTPException(404, "Account non trovato")
    return {"ok": True}


@api.post("/accounts/{account_id}/test")
async def test_account(account_id: str, email: EmailStr, master_password: str):
    """Probe IMAP reale."""
    import asyncio
    from bson import ObjectId
    from bson.errors import InvalidId

    await require_user(email.lower(), master_password)
    try:
        oid = ObjectId(account_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    acc = await db.accounts.find_one({"_id": oid, "user_email": email.lower()})
    if not acc:
        raise HTTPException(404, "Account non trovato")
    # Migra host Outlook obsoleti (smtp.office365.com → smtp-mail.outlook.com)
    if acc.get("pec_provider") == "outlook" or acc.get("type") == "microsoft":
        ih, ip, sh, sp = apply_provider_hosts(
            "outlook",
            imap_host=None,
            imap_port=None,
            smtp_host=None,
            smtp_port=None,
        )
        flags = outlook_smtp_flags("outlook")
        await db.accounts.update_one(
            {"_id": oid},
            {
                "$set": {
                    "imap_host": ih,
                    "imap_port": ip,
                    "smtp_host": sh,
                    "smtp_port": sp,
                    **flags,
                    "pec_provider": "outlook",
                    "type": "microsoft",
                }
            },
        )
        acc = await db.accounts.find_one({"_id": oid}) or acc
    try:
        user, pwd, access_token = await resolve_mailbox_creds(acc, email.lower())
        result = await asyncio.to_thread(
            mail_provider.test_imap,
            acc["imap_host"],
            int(acc.get("imap_port") or 993),
            user,
            pwd or "",
            provider_hint=acc.get("pec_provider") or acc.get("type"),
            access_token=access_token,
        )
        if result.get("host") and result["host"] != acc.get("imap_host"):
            await db.accounts.update_one(
                {"_id": oid}, {"$set": {"imap_host": result["host"]}}
            )
        return {
            **result,
            "type": acc.get("type"),
            "address": acc.get("address"),
            "auth_method": acc.get("auth_method") or "password",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Connessione IMAP fallita: {exc}") from exc


# --- messages ---


@api.get("/messages")
async def list_messages(
    email: EmailStr,
    master_password: str,
    account: Optional[str] = None,
    q: Optional[str] = None,
    unread: Optional[bool] = None,
    pec: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    await require_user(email.lower(), master_password)
    filt: Dict[str, Any] = {"user_email": email.lower()}
    if account:
        filt["account_id"] = account
    if unread is True:
        filt["flags.seen"] = False
    if pec is True:
        filt["is_pec"] = True
    if q:
        filt["$or"] = [
            {"subject": {"$regex": q, "$options": "i"}},
            {"from_addr": {"$regex": q, "$options": "i"}},
            {"snippet": {"$regex": q, "$options": "i"}},
        ]
    skip = (page - 1) * limit
    total = await db.messages.count_documents(filt)
    cur = (
        db.messages.find(filt)
        .sort("date", -1)
        .skip(skip)
        .limit(limit)
    )
    items = []
    async for m in cur:
        items.append(
            {
                "id": str(m["_id"]),
                "account_id": m["account_id"],
                "subject": m.get("subject", ""),
                "from": m.get("from_addr", ""),
                "to": m.get("to_addrs", []),
                "date": m.get("date"),
                "flags": m.get("flags", {}),
                "has_attachments": m.get("has_attachments", False),
                "is_pec": m.get("is_pec", False),
                "snippet": m.get("snippet", ""),
                "priority": m.get("priority"),
            }
        )
    return {"items": items, "page": page, "total": total}


@api.get("/messages/{message_id}")
async def get_message(message_id: str, email: EmailStr, master_password: str):
    from bson import ObjectId
    from bson.errors import InvalidId

    await require_user(email.lower(), master_password)
    try:
        oid = ObjectId(message_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    m = await db.messages.find_one({"_id": oid, "user_email": email.lower()})
    if not m:
        raise HTTPException(404, "Messaggio non trovato")
    body = m.get("body_text", "")
    if m.get("body_enc"):
        try:
            body = decrypt_secret(m["body_enc"], email.lower())
        except Exception:
            body = m.get("body_text", "")
    return {
        "id": str(m["_id"]),
        "account_id": m["account_id"],
        "subject": m.get("subject", ""),
        "from": m.get("from_addr", ""),
        "to": m.get("to_addrs", []),
        "cc": m.get("cc_addrs", []),
        "date": m.get("date"),
        "flags": m.get("flags", {}),
        "has_attachments": m.get("has_attachments", False),
        "attachments": m.get("attachments", []),
        "is_pec": m.get("is_pec", False),
        "body_text": body,
        "body_html": m.get("body_html"),
        "receipts": m.get("receipts", []),
        "priority": m.get("priority"),
    }


@api.post("/messages/{message_id}/flags")
async def set_flags(message_id: str, body: MessageFlagsBody):
    from bson import ObjectId
    from bson.errors import InvalidId

    await require_user(body.email.lower(), body.master_password)
    try:
        oid = ObjectId(message_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    updates: Dict[str, Any] = {}
    if body.seen is not None:
        updates["flags.seen"] = body.seen
    if body.flagged is not None:
        updates["flags.flagged"] = body.flagged
    if body.archived is not None:
        updates["flags.archived"] = body.archived
    if not updates:
        raise HTTPException(400, "Nessun flag")
    res = await db.messages.update_one(
        {"_id": oid, "user_email": body.email.lower()}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Messaggio non trovato")
    return {"ok": True}


@api.post("/messages/send")
async def send_message(body: SendBody):
    """Invio SMTP reale (Gmail app-password, Outlook, IMAP/PEC)."""
    import asyncio
    from bson import ObjectId
    from bson.errors import InvalidId

    email = body.email.lower()
    await require_user(email, body.master_password)
    try:
        oid = ObjectId(body.account_id)
    except InvalidId as exc:
        raise HTTPException(400, "account_id non valido") from exc
    acc = await db.accounts.find_one({"_id": oid, "user_email": email})
    if not acc:
        raise HTTPException(404, "Account non trovato")
    if body.as_pec and acc.get("type") != "pec":
        raise HTTPException(400, "as_pec richiede un account di tipo pec")

    smtp_host = acc.get("smtp_host") or acc.get("imap_host")
    smtp_port = int(acc.get("smtp_port") or 465)
    try:
        smtp_user, smtp_pwd, access_token = await resolve_mailbox_creds(acc, email)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Credenziali SMTP non disponibili: {exc}") from exc

    use_ssl = bool(acc.get("smtp_ssl", smtp_port == 465))
    starttls = bool(acc.get("smtp_starttls", smtp_port == 587))

    now = datetime.utcnow()
    to_addrs = [str(x).lower() for x in body.to]
    cc_addrs = [str(x).lower() for x in body.cc]
    bcc_addrs = [str(x).lower() for x in body.bcc]

    try:
        await asyncio.to_thread(
            mail_provider.send_smtp,
            host=smtp_host,
            port=smtp_port,
            user=smtp_user,
            password=smtp_pwd or "",
            from_addr=acc["address"],
            to_addrs=to_addrs,
            cc_addrs=cc_addrs,
            bcc_addrs=bcc_addrs,
            subject=body.subject,
            body_text=body.body_text or "",
            body_html=body.body_html,
            use_ssl=use_ssl,
            starttls=starttls,
            access_token=access_token,
        )
        send_status = "sent"
        send_error = None
    except Exception as exc:
        log.exception("SMTP send failed")
        send_status = "failed"
        send_error = str(exc)

    receipts = []
    if body.as_pec or acc.get("type") == "pec":
        receipts.append(
            {
                "type": "accettazione",
                "at": now.isoformat() + "Z",
                "status": "sent" if send_status == "sent" else "failed",
                "note": send_error or "Inviata via SMTP PEC",
            }
        )

    doc = {
        "user_email": email,
        "account_id": body.account_id,
        "folder": "sent",
        "subject": body.subject,
        "from_addr": acc["address"],
        "to_addrs": to_addrs,
        "cc_addrs": cc_addrs,
        "date": now,
        "flags": {"seen": True, "flagged": False, "archived": False},
        "has_attachments": False,
        "attachments": [],
        "is_pec": bool(body.as_pec or acc.get("type") == "pec"),
        "snippet": (body.body_text or "")[:160],
        "body_enc": encrypt_secret(body.body_text or "", email),
        "body_html": body.body_html,
        "receipts": receipts,
        "outbox_status": send_status,
        "send_error": send_error,
        "reply_to_message_id": body.reply_to_message_id,
        "created_at": now,
    }
    res = await db.messages.insert_one(doc)
    await db.outbox.insert_one(
        {
            "message_id": str(res.inserted_id),
            "account_id": body.account_id,
            "user_email": email,
            "as_pec": bool(body.as_pec or acc.get("type") == "pec"),
            "status": send_status,
            "error": send_error,
            "created_at": now,
        }
    )
    if send_status != "sent":
        raise HTTPException(400, f"Invio fallito: {send_error}")
    return {
        "id": str(res.inserted_id),
        "queued": False,
        "sent": True,
        "is_pec": doc["is_pec"],
        "receipts": receipts,
        "message": "Messaggio inviato",
    }


@api.get("/messages/{message_id}/export")
async def export_message(message_id: str, email: EmailStr, master_password: str):
    """v2 stub: metadati per ZIP legale (file ZIP reale in worker successivo)."""
    detail = await get_message(message_id, email, master_password)
    return {
        "export_ready": False,
        "format": "zip",
        "includes": ["eml", "receipts", "headers"],
        "message": detail,
        "note": "Generazione ZIP in worker — metadati pronti",
    }


# --- rules (v2) ---


@api.get("/rules")
async def list_rules(email: EmailStr, master_password: str):
    await require_user(email.lower(), master_password)
    cur = db.rules.find({"user_email": email.lower()})
    return [
        {
            "id": str(r["_id"]),
            "name": r["name"],
            "match_pec_only": r.get("match_pec_only", False),
            "match_account_id": r.get("match_account_id"),
            "action": r.get("action"),
            "action_value": r.get("action_value"),
            "enabled": r.get("enabled", True),
        }
        async for r in cur
    ]


@api.post("/rules")
async def create_rule(body: RuleBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    doc = {
        "user_email": email,
        "name": body.name,
        "match_pec_only": body.match_pec_only,
        "match_account_id": body.match_account_id,
        "action": body.action,
        "action_value": body.action_value,
        "enabled": body.enabled,
        "created_at": datetime.utcnow(),
    }
    res = await db.rules.insert_one(doc)
    return {"id": str(res.inserted_id), **{k: doc[k] for k in doc if k != "created_at"}}


# --- sync ---


@api.post("/sync/run")
async def sync_run(email: EmailStr, master_password: str, account_id: Optional[str] = None):
    """Scarica INBOX via IMAP e upserta i messaggi."""
    import asyncio
    from bson import ObjectId
    from bson.errors import InvalidId

    email_l = email.lower()
    await require_user(email_l, master_password)
    filt: Dict[str, Any] = {"user_email": email_l}
    if account_id:
        try:
            filt["_id"] = ObjectId(account_id)
        except InvalidId as exc:
            raise HTTPException(400, "account_id non valido") from exc

    synced = 0
    inserted = 0
    errors: List[str] = []
    async for acc in db.accounts.find(filt):
        aid = str(acc["_id"])
        await db.accounts.update_one(
            {"_id": acc["_id"]}, {"$set": {"sync_state": "running"}}
        )
        try:
            user, pwd, access_token = await resolve_mailbox_creds(acc, email_l)
            fetched = await asyncio.to_thread(
                mail_provider.fetch_inbox,
                acc["imap_host"],
                int(acc.get("imap_port") or 993),
                user,
                pwd or "",
                limit=80,
                account_type=acc.get("type") or "imap",
                provider_hint=acc.get("pec_provider") or acc.get("type"),
                access_token=access_token,
            )
            for m in fetched:
                key = {
                    "user_email": email_l,
                    "account_id": aid,
                    "imap_uid": m["imap_uid"],
                    "folder": "INBOX",
                }
                existing = await db.messages.find_one(key)
                payload = {
                    **key,
                    "message_id": m.get("message_id"),
                    "subject": m.get("subject", ""),
                    "from_addr": m.get("from_addr", ""),
                    "to_addrs": m.get("to_addrs", []),
                    "cc_addrs": m.get("cc_addrs", []),
                    "date": m.get("date") or datetime.utcnow(),
                    "flags": m.get("flags", {}),
                    "has_attachments": m.get("has_attachments", False),
                    "attachments": m.get("attachments", []),
                    "is_pec": m.get("is_pec", False),
                    "snippet": m.get("snippet", ""),
                    "body_enc": encrypt_secret(m.get("body_text") or "", email_l),
                    "body_html": m.get("body_html"),
                    "receipts": m.get("receipts", []),
                    "updated_at": datetime.utcnow(),
                }
                if existing:
                    await db.messages.update_one({"_id": existing["_id"]}, {"$set": payload})
                else:
                    payload["created_at"] = datetime.utcnow()
                    await db.messages.insert_one(payload)
                    inserted += 1
            synced += 1
            await db.accounts.update_one(
                {"_id": acc["_id"]},
                {
                    "$set": {
                        "sync_state": "idle",
                        "last_sync_at": datetime.utcnow(),
                        "last_sync_error": None,
                        "last_sync_count": len(fetched),
                    }
                },
            )
        except Exception as exc:
            log.exception("IMAP sync failed for %s", acc.get("address"))
            errors.append(f"{acc.get('address')}: {exc}")
            await db.accounts.update_one(
                {"_id": acc["_id"]},
                {
                    "$set": {
                        "sync_state": "error",
                        "last_sync_at": datetime.utcnow(),
                        "last_sync_error": str(exc),
                    }
                },
            )

    return {
        "accounts_synced": synced,
        "messages_inserted": inserted,
        "errors": errors,
        "message": "Sync IMAP completato"
        if not errors
        else "Sync completato con errori",
    }


@api.get("/sync/status")
async def sync_status(email: EmailStr, master_password: str):
    await require_user(email.lower(), master_password)
    accounts = []
    async for acc in db.accounts.find({"user_email": email.lower()}):
        accounts.append(
            {
                "id": str(acc["_id"]),
                "address": acc["address"],
                "sync_state": acc.get("sync_state", "idle"),
                "last_sync_at": acc.get("last_sync_at"),
            }
        )
    outbox = await db.outbox.count_documents(
        {"user_email": email.lower(), "status": "queued"}
    )
    return {"accounts": accounts, "outbox_queued": outbox}


@api.post("/dev/seed_demo")
async def seed_demo(email: EmailStr, master_password: str):
    """Inserisce messaggi demo (anche PEC) per provare la UI senza IMAP."""
    email_l = email.lower()
    await require_user(email_l, master_password)
    acc = await db.accounts.find_one({"user_email": email_l})
    if not acc:
        raise HTTPException(400, "Aggiungi prima un account")
    aid = str(acc["_id"])
    now = datetime.utcnow()
    samples = [
        {
            "subject": "Benvenuto in Mail Manager v2",
            "from_addr": "noreply@colorsdev.tech",
            "is_pec": False,
            "snippet": "Inbox unificata pronta.",
            "body": "Questo è un messaggio demo non PEC.",
        },
        {
            "subject": "PEC: Avviso di prova",
            "from_addr": "mittente@pec.example.it",
            "is_pec": True,
            "snippet": "Posta certificata di esempio.",
            "body": "Corpo PEC demo.",
            "receipts": [
                {"type": "accettazione", "at": (now - timedelta(minutes=2)).isoformat() + "Z"},
                {"type": "consegna", "at": now.isoformat() + "Z"},
            ],
        },
    ]
    ids = []
    for s in samples:
        doc = {
            "user_email": email_l,
            "account_id": aid,
            "folder": "INBOX",
            "subject": s["subject"],
            "from_addr": s["from_addr"],
            "to_addrs": [acc["address"]],
            "cc_addrs": [],
            "date": now,
            "flags": {"seen": False, "flagged": False, "archived": False},
            "has_attachments": False,
            "attachments": [],
            "is_pec": s["is_pec"],
            "snippet": s["snippet"],
            "body_enc": encrypt_secret(s["body"], email_l),
            "receipts": s.get("receipts", []),
            "priority": "high" if s["is_pec"] else None,
            "created_at": now,
        }
        r = await db.messages.insert_one(doc)
        ids.append(str(r.inserted_id))
    return {"inserted": ids}


app.include_router(api)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.accounts.create_index([("user_email", 1), ("address", 1)])
    await db.messages.create_index([("user_email", 1), ("date", -1)])
    await db.messages.create_index([("user_email", 1), ("is_pec", 1)])
    await db.outbox.create_index([("user_email", 1), ("status", 1)])
    await db.oauth_pending.create_index("state", unique=True)
    await db.oauth_pending.create_index("expires_at", expireAfterSeconds=0)
    log.info("Mail Manager API v2 ready — db=%s", db_name)
