"""
Mail Manager API (v2) — vault multi-casella + PEC send/receipts.
Sync IMAP/OAuth provider implementations are hooks: models + routes are ready.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, File, Form, HTTPException, Query, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError
from starlette.middleware.cors import CORSMiddleware

import mail_provider
import oauth_mail
import push_notify

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


class PushSubscribeBody(BaseModel):
    email: EmailStr
    master_password: str
    endpoint: str
    keys: Dict[str, str]
    expiration_time: Optional[float] = None


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


class MessageAuthBody(BaseModel):
    email: EmailStr
    master_password: str


class AttachmentIn(BaseModel):
    filename: str = "allegato"
    content_type: str = "application/octet-stream"
    content_base64: str = ""


class SendBody(BaseModel):
    email: EmailStr
    master_password: str
    account_id: str
    to: List[str]
    cc: List[str] = []
    bcc: List[str] = []
    subject: str = ""
    body_text: str = ""
    body_html: Optional[str] = None
    as_pec: bool = False
    reply_to_message_id: Optional[str] = None
    attachments: List[AttachmentIn] = []


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


async def dedupe_users_by_email() -> int:
    """Keep oldest vault user per email; delete later duplicates."""
    pipeline = [
        {"$addFields": {"email_norm": {"$toLower": {"$ifNull": ["$email", ""]}}}},
        {"$match": {"email_norm": {"$ne": ""}}},
        {"$sort": {"created_at": 1, "_id": 1}},
        {
            "$group": {
                "_id": "$email_norm",
                "keep_id": {"$first": "$_id"},
                "all_ids": {"$push": "$_id"},
                "count": {"$sum": 1},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ]
    removed = 0
    async for group in db.users.aggregate(pipeline):
        dup_ids = [oid for oid in group["all_ids"] if oid != group["keep_id"]]
        if not dup_ids:
            continue
        result = await db.users.delete_many({"_id": {"$in": dup_ids}})
        removed += result.deleted_count
        await db.users.update_one(
            {"_id": group["keep_id"]},
            {"$set": {"email": group["_id"]}},
        )
    return removed


@api.post("/auth/setup", response_model=AuthOk)
async def setup(body: SetupBody):
    email = body.email.lower()
    if await db.users.find_one({"email": email}, sort=[("created_at", 1), ("_id", 1)]):
        raise HTTPException(400, "Questa email è già registrata. Accedi invece.")
    try:
        await db.users.insert_one(
            {
                "email": email,
                "password_hash": pwd_context.hash(body.master_password),
                "created_at": datetime.utcnow(),
                "biometric_hint": False,
            }
        )
    except DuplicateKeyError:
        raise HTTPException(400, "Questa email è già registrata. Accedi invece.")
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
    folder: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    await require_user(email.lower(), master_password)
    email_l = email.lower()
    filt: Dict[str, Any] = {"user_email": email_l}
    if account:
        # Sempre stringa: evita mismatch ObjectId vs str che faceva fallire il filtro account
        filt["account_id"] = str(account)
    folder_l = (folder or "inbox").lower()
    if folder_l == "trash":
        filt["folder"] = "trash"
    elif folder_l == "sent":
        filt["folder"] = "sent"
    else:
        # Ricevute (inbox): escludi cestino e inviate (legacy senza folder = inbox)
        filt["folder"] = {"$nin": ["trash", "sent"]}
    if unread is True:
        # Non lette: seen=false OPPURE flag assente (messaggi syncati senza seen)
        and_clauses_unread = {
            "$or": [
                {"flags.seen": False},
                {"flags.seen": {"$exists": False}},
                {"flags": {"$exists": False}},
            ]
        }
    else:
        and_clauses_unread = None

    and_clauses: List[Dict[str, Any]] = []
    if and_clauses_unread:
        and_clauses.append(and_clauses_unread)

    # Account PEC: servono per filtro e badge (query leggera su accounts)
    pec_acc_ids: List[str] = [
        str(a["_id"])
        async for a in db.accounts.find(
            {
                "user_email": email_l,
                "$or": [
                    {"type": "pec"},
                    {
                        "pec_provider": {
                            "$in": ["aruba", "legalmail", "postecert", "intesi"]
                        }
                    },
                ],
            },
            {"_id": 1},
        )
    ]
    pec_acc_set = set(pec_acc_ids)

    if pec is True:
        # Un solo $in su is_pec + account PEC (evita $or a 4 rami lenti)
        pec_or: List[Dict[str, Any]] = [
            {"is_pec": {"$in": [True, 1, "1", "true"]}},
        ]
        if pec_acc_ids:
            pec_or.append({"account_id": {"$in": pec_acc_ids}})
        and_clauses.append({"$or": pec_or})

    if q:
        and_clauses.append(
            {
                "$or": [
                    {"subject": {"$regex": q, "$options": "i"}},
                    {"from_addr": {"$regex": q, "$options": "i"}},
                    {"snippet": {"$regex": q, "$options": "i"}},
                ]
            }
        )

    if and_clauses:
        filt["$and"] = and_clauses

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
        raw_pec = m.get("is_pec")
        is_pec = bool(raw_pec in (True, 1, "1", "true")) or (
            str(m.get("account_id") or "") in pec_acc_set
        )
        flags = dict(m.get("flags") or {})
        seen_val = flags.get("seen")
        flags["seen"] = seen_val is True or seen_val in (1, "1", "true", "True")
        items.append(
            {
                "id": str(m["_id"]),
                "account_id": str(m.get("account_id") or ""),
                "subject": m.get("subject", ""),
                "from": m.get("from_addr", ""),
                "to": m.get("to_addrs", []),
                "date": m.get("date"),
                "flags": flags,
                "has_attachments": m.get("has_attachments", False),
                "is_pec": is_pec,
                "snippet": m.get("snippet", ""),
                "priority": m.get("priority"),
                "folder": m.get("folder") or "INBOX",
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
    # Apertura messaggio → segna come letta
    flags = m.get("flags") or {}
    if flags.get("seen") is not True:
        await db.messages.update_one(
            {"_id": oid},
            {"$set": {"flags.seen": True, "updated_at": datetime.utcnow()}},
        )
        flags = {**flags, "seen": True}
    body = m.get("body_text", "")
    if m.get("body_enc"):
        try:
            body = decrypt_secret(m["body_enc"], email.lower())
        except Exception:
            body = m.get("body_text", "")
    # Pulisci &zwnj; / zero-width anche su messaggi già syncati
    body = mail_provider._clean_text(body or "")
    html_body = m.get("body_html") or ""
    if html_body and (not body or len(body) < 40):
        derived = mail_provider._html_to_text(html_body)
        if derived:
            body = derived
    # Sostituisci cid: → data: per immagini inline
    inline_parts = m.get("inline_parts") or []
    if html_body and inline_parts:
        for part in inline_parts:
            cid = (part.get("cid") or "").strip()
            if not cid:
                continue
            data_url = (
                f"data:{part.get('content_type') or 'image/png'};base64,"
                f"{part.get('content_base64') or ''}"
            )
            html_body = re.sub(
                rf"(?i)cid:<?{re.escape(cid)}?>?",
                data_url,
                html_body,
            )
    # Non esporre content_base64 nel dettaglio (download dedicato)
    att_out = []
    for a in m.get("attachments") or []:
        if not isinstance(a, dict):
            continue
        att_out.append(
            {
                "filename": a.get("filename") or "allegato",
                "content_type": a.get("content_type") or "application/octet-stream",
                "size": a.get("size"),
            }
        )
    return {
        "id": str(m["_id"]),
        "account_id": m["account_id"],
        "subject": m.get("subject", ""),
        "from": m.get("from_addr", ""),
        "to": m.get("to_addrs", []),
        "cc": m.get("cc_addrs", []),
        "date": m.get("date"),
        "flags": flags,
        "has_attachments": m.get("has_attachments", False) or bool(att_out),
        "attachments": att_out,
        "is_pec": m.get("is_pec", False),
        "body_text": body,
        "body_html": html_body or None,
        "receipts": m.get("receipts", []),
        "priority": m.get("priority"),
        "folder": m.get("folder") or "INBOX",
    }


@api.get("/messages/{message_id}/attachments/{att_index}")
async def download_attachment(
    message_id: str,
    att_index: int,
    email: EmailStr,
    master_password: str,
    filename: Optional[str] = None,
):
    """Scarica un allegato dal provider IMAP (on-demand)."""
    import asyncio
    from bson import ObjectId
    from bson.errors import InvalidId
    from fastapi.responses import Response
    from urllib.parse import quote

    email_l = email.lower()
    await require_user(email_l, master_password)
    if att_index < 0:
        raise HTTPException(400, "Indice allegato non valido")
    try:
        oid = ObjectId(message_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    m = await db.messages.find_one({"_id": oid, "user_email": email_l})
    if not m:
        raise HTTPException(404, "Messaggio non trovato")

    def _file_response(raw: bytes, fname: str, ctype: str):
        if not raw:
            raise HTTPException(400, "Allegato vuoto")
        safe_ascii = re.sub(r"[^\w.\-]+", "_", fname).strip("._") or "allegato"
        disp = (
            f'attachment; filename="{safe_ascii}"; '
            f"filename*=UTF-8''{quote(fname)}"
        )
        return Response(
            content=raw,
            media_type=(ctype or "application/octet-stream").split(";")[0].strip()
            or "application/octet-stream",
            headers={
                "Content-Disposition": disp,
                "Cache-Control": "private, max-age=60",
                "X-Content-Type-Options": "nosniff",
            },
        )

    # Allegato salvato in chiaro (es. inviati dall'app) → download diretto
    stored = m.get("attachments") or []
    if 0 <= att_index < len(stored) and isinstance(stored[att_index], dict):
        b64 = (stored[att_index].get("content_base64") or "").strip()
        if b64:
            import base64 as _b64

            try:
                raw = _b64.b64decode(b64, validate=False)
            except Exception:
                raw = b""
            if raw:
                return _file_response(
                    raw,
                    stored[att_index].get("filename") or filename or "allegato",
                    stored[att_index].get("content_type")
                    or "application/octet-stream",
                )

    imap_uid = (m.get("imap_uid") or "").strip()
    if not imap_uid:
        raise HTTPException(
            404,
            "Allegato non scaricabile: messaggio non ancora sincronizzato da IMAP",
        )
    try:
        acc_oid = ObjectId(m["account_id"])
    except Exception as exc:
        raise HTTPException(400, "Account messaggio non valido") from exc
    acc = await db.accounts.find_one({"_id": acc_oid, "user_email": email_l})
    if not acc:
        raise HTTPException(404, "Account non trovato")

    want_name = (filename or "").strip() or None
    if not want_name and 0 <= att_index < len(stored) and isinstance(stored[att_index], dict):
        want_name = (stored[att_index].get("filename") or "").strip() or None

    try:
        user, pwd, access_token = await resolve_mailbox_creds(acc, email_l)
        att = await asyncio.to_thread(
            mail_provider.fetch_attachment,
            acc["imap_host"],
            int(acc.get("imap_port") or 993),
            user,
            pwd or "",
            imap_uid=imap_uid,
            folder=m.get("folder") or "INBOX",
            index=att_index,
            account_type=acc.get("type") or "imap",
            provider_hint=acc.get("pec_provider") or acc.get("type"),
            access_token=access_token,
            want_filename=want_name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Download allegato fallito msg=%s idx=%s", message_id, att_index)
        raise HTTPException(400, f"Download fallito: {exc}") from exc

    return _file_response(
        att.get("data") or b"",
        att.get("filename") or want_name or "allegato",
        att.get("content_type") or "application/octet-stream",
    )


@api.post("/messages/{message_id}/trash")
async def trash_message(message_id: str, body: MessageAuthBody):
    from bson import ObjectId
    from bson.errors import InvalidId

    email_l = body.email.lower()
    await require_user(email_l, body.master_password)
    try:
        oid = ObjectId(message_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    res = await db.messages.update_one(
        {"_id": oid, "user_email": email_l},
        {"$set": {"folder": "trash", "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Messaggio non trovato")
    return {"ok": True, "folder": "trash"}


@api.post("/messages/{message_id}/restore")
async def restore_message(message_id: str, body: MessageAuthBody):
    from bson import ObjectId
    from bson.errors import InvalidId

    email_l = body.email.lower()
    await require_user(email_l, body.master_password)
    try:
        oid = ObjectId(message_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    m = await db.messages.find_one({"_id": oid, "user_email": email_l})
    if not m:
        raise HTTPException(404, "Messaggio non trovato")
    if (m.get("folder") or "").lower() != "trash":
        raise HTTPException(400, "Il messaggio non è nel cestino")
    await db.messages.update_one(
        {"_id": oid},
        {"$set": {"folder": "INBOX", "updated_at": datetime.utcnow()}},
    )
    return {"ok": True, "folder": "INBOX"}


@api.delete("/messages/{message_id}")
async def delete_message_permanent(
    message_id: str, email: EmailStr, master_password: str
):
    """Eliminazione definitiva (consentita solo dal cestino)."""
    from bson import ObjectId
    from bson.errors import InvalidId

    email_l = email.lower()
    await require_user(email_l, master_password)
    try:
        oid = ObjectId(message_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    m = await db.messages.find_one({"_id": oid, "user_email": email_l})
    if not m:
        raise HTTPException(404, "Messaggio non trovato")
    if (m.get("folder") or "").lower() != "trash":
        raise HTTPException(
            400, "Sposta prima il messaggio nel cestino per eliminarlo definitivamente"
        )
    await db.messages.delete_one({"_id": oid})
    return {"ok": True}


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


async def _deliver_and_store_sent(
    *,
    email: str,
    account_id: str,
    acc: dict,
    to_addrs: List[str],
    cc_addrs: List[str],
    bcc_addrs: List[str],
    subject: str,
    body_text: str,
    body_html: Optional[str],
    as_pec: bool,
    reply_to_message_id: Optional[str],
    att_payload: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Invio SMTP + salvataggio in cartella Inviate / outbox."""
    import asyncio
    import base64 as _b64

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

    # Per SMTP preferisci i bytes grezzi; per Mongo salva anche base64
    smtp_atts: List[Dict[str, Any]] = []
    att_meta: List[Dict[str, Any]] = []
    for a in att_payload:
        raw = a.get("content_bytes")
        raw_b64 = (a.get("content_base64") or "").strip()
        if not isinstance(raw, (bytes, bytearray)):
            try:
                raw = _b64.b64decode(raw_b64, validate=False)
            except Exception as exc:
                raise HTTPException(
                    400, f"Allegato non valido ({a.get('filename')})"
                ) from exc
        raw = bytes(raw)
        if not raw_b64:
            raw_b64 = _b64.b64encode(raw).decode("ascii")
        size = len(raw)
        log.info(
            "Send allegato name=%s size=%s b64_len=%s",
            a.get("filename"),
            size,
            len(raw_b64),
        )
        smtp_atts.append(
            {
                "filename": a["filename"],
                "content_type": a["content_type"],
                "content_bytes": raw,
                "content_base64": raw_b64,
                "size": size,
            }
        )
        att_meta.append(
            {
                "filename": a["filename"],
                "content_type": a["content_type"],
                "size": size,
                "content_base64": raw_b64,
            }
        )

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
            subject=subject,
            body_text=body_text or "",
            body_html=body_html,
            use_ssl=use_ssl,
            starttls=starttls,
            access_token=access_token,
            attachments=smtp_atts,
        )
        send_status = "sent"
        send_error = None
    except Exception as exc:
        log.exception("SMTP send failed")
        send_status = "failed"
        send_error = str(exc)

    receipts = []
    if as_pec or acc.get("type") == "pec":
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
        "account_id": account_id,
        "folder": "sent",
        "subject": subject,
        "from_addr": acc["address"],
        "to_addrs": to_addrs,
        "cc_addrs": cc_addrs,
        "date": now,
        "flags": {"seen": True, "flagged": False, "archived": False},
        "has_attachments": bool(att_meta),
        "attachments": att_meta,
        "is_pec": bool(as_pec or acc.get("type") == "pec"),
        "snippet": (body_text or "")[:160],
        "body_enc": encrypt_secret(body_text or "", email),
        "body_html": body_html,
        "receipts": receipts,
        "outbox_status": send_status,
        "send_error": send_error,
        "reply_to_message_id": reply_to_message_id,
        "created_at": now,
    }
    res = await db.messages.insert_one(doc)
    await db.outbox.insert_one(
        {
            "message_id": str(res.inserted_id),
            "account_id": account_id,
            "user_email": email,
            "as_pec": bool(as_pec or acc.get("type") == "pec"),
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
        "attachment_sizes": [a["size"] for a in att_meta],
    }


def _norm_addrs(vals: List[str]) -> List[str]:
    out: List[str] = []
    for raw in vals:
        s = (raw or "").strip()
        if not s:
            continue
        m = re.search(r"<([^>]+)>", s)
        addr = (m.group(1) if m else s).strip().lower()
        if "@" not in addr:
            raise HTTPException(400, f"Destinatario non valido: {raw}")
        out.append(addr)
    return out


@api.post("/messages/send")
async def send_message(body: SendBody):
    """Invio SMTP (JSON; allegati opzionali in base64)."""
    from bson import ObjectId
    from bson.errors import InvalidId
    import base64 as _b64

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

    to_addrs = _norm_addrs([str(x) for x in body.to])
    cc_addrs = _norm_addrs([str(x) for x in body.cc])
    bcc_addrs = _norm_addrs([str(x) for x in body.bcc])
    if not to_addrs:
        raise HTTPException(400, "Inserisci almeno un destinatario valido")

    MAX_ATT = 10
    MAX_ONE = 12 * 1024 * 1024
    MAX_ALL = 25 * 1024 * 1024
    att_payload: List[Dict[str, Any]] = []
    total_raw = 0
    if len(body.attachments) > MAX_ATT:
        raise HTTPException(400, f"Massimo {MAX_ATT} allegati per messaggio")

    for a in body.attachments:
        name = (a.filename or "allegato").strip() or "allegato"
        raw_b64 = (a.content_base64 or "").strip()
        if raw_b64.startswith("data:") and "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        try:
            raw = _b64.b64decode(raw_b64, validate=False)
        except Exception as exc:
            raise HTTPException(400, f"Allegato non valido ({name})") from exc
        if len(raw) > MAX_ONE:
            raise HTTPException(400, f"Allegato troppo grande ({name}): max 12 MB")
        total_raw += len(raw)
        if total_raw > MAX_ALL:
            raise HTTPException(400, "Dimensione totale allegati oltre 25 MB")
        att_payload.append(
            {
                "filename": name,
                "content_type": a.content_type or "application/octet-stream",
                "content_bytes": raw,
                "content_base64": raw_b64,
                "size": len(raw),
            }
        )

    return await _deliver_and_store_sent(
        email=email,
        account_id=body.account_id,
        acc=acc,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        bcc_addrs=bcc_addrs,
        subject=body.subject,
        body_text=body.body_text or "",
        body_html=body.body_html,
        as_pec=body.as_pec,
        reply_to_message_id=body.reply_to_message_id,
        att_payload=att_payload,
    )


@api.post("/messages/send-form")
async def send_message_form(
    email: str = Form(...),
    master_password: str = Form(...),
    account_id: str = Form(...),
    to: str = Form(...),
    subject: str = Form(""),
    body_text: str = Form(""),
    body_html: Optional[str] = Form(None),
    as_pec: str = Form("false"),
    reply_to_message_id: Optional[str] = Form(None),
    cc: str = Form(""),
    bcc: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
):
    """Invio SMTP con allegati binari (multipart/form-data)."""
    from bson import ObjectId
    from bson.errors import InvalidId
    import base64 as _b64

    email_l = email.lower().strip()
    await require_user(email_l, master_password)
    try:
        oid = ObjectId(account_id)
    except InvalidId as exc:
        raise HTTPException(400, "account_id non valido") from exc
    acc = await db.accounts.find_one({"_id": oid, "user_email": email_l})
    if not acc:
        raise HTTPException(404, "Account non trovato")

    as_pec_b = str(as_pec or "").strip().lower() in ("1", "true", "yes", "on")
    if as_pec_b and acc.get("type") != "pec":
        raise HTTPException(400, "as_pec richiede un account di tipo pec")

    def _split_addrs(s: str) -> List[str]:
        return [p.strip() for p in (s or "").replace(";", ",").split(",") if p.strip()]

    to_addrs = _norm_addrs(_split_addrs(to))
    cc_addrs = _norm_addrs(_split_addrs(cc))
    bcc_addrs = _norm_addrs(_split_addrs(bcc))
    if not to_addrs:
        raise HTTPException(400, "Inserisci almeno un destinatario valido")

    MAX_ATT = 10
    MAX_ONE = 12 * 1024 * 1024
    MAX_ALL = 25 * 1024 * 1024
    upload_files = [f for f in (files or []) if f is not None]
    if len(upload_files) > MAX_ATT:
        raise HTTPException(400, f"Massimo {MAX_ATT} allegati per messaggio")

    att_payload: List[Dict[str, Any]] = []
    total_raw = 0
    for uf in upload_files:
        name = (uf.filename or "allegato").strip() or "allegato"
        raw = await uf.read()
        if not raw:
            raise HTTPException(400, f"Allegato vuoto ({name})")
        if len(raw) > MAX_ONE:
            raise HTTPException(400, f"Allegato troppo grande ({name}): max 12 MB")
        total_raw += len(raw)
        if total_raw > MAX_ALL:
            raise HTTPException(400, "Dimensione totale allegati oltre 25 MB")
        ctype = (uf.content_type or "application/octet-stream").split(";")[0].strip()
        att_payload.append(
            {
                "filename": name,
                "content_type": ctype or "application/octet-stream",
                "content_bytes": raw,
                "content_base64": _b64.b64encode(raw).decode("ascii"),
                "size": len(raw),
            }
        )
        log.info("Upload form allegato name=%s bytes=%s", name, len(raw))

    return await _deliver_and_store_sent(
        email=email_l,
        account_id=account_id,
        acc=acc,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        bcc_addrs=bcc_addrs,
        subject=subject or "",
        body_text=body_text or "",
        body_html=body_html,
        as_pec=as_pec_b,
        reply_to_message_id=reply_to_message_id,
        att_payload=att_payload,
    )



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


async def sync_accounts_for_user(
    email_l: str,
    account_id: Optional[str] = None,
    *,
    notify: bool = True,
) -> Dict[str, Any]:
    """Sync IMAP per un vault user. Usato da API e worker periodico."""
    import asyncio
    from bson import ObjectId
    from bson.errors import InvalidId

    filt: Dict[str, Any] = {"user_email": email_l}
    if account_id:
        try:
            filt["_id"] = ObjectId(account_id)
        except InvalidId as exc:
            raise HTTPException(400, "account_id non valido") from exc

    synced = 0
    inserted = 0
    errors: List[str] = []
    new_previews: List[Dict[str, str]] = []

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
                limit=100,
                account_type=acc.get("type") or "imap",
                provider_hint=acc.get("pec_provider") or acc.get("type"),
                access_token=access_token,
            )
            for m in fetched:
                src_folder = (m.get("folder") or "INBOX").lower()
                is_sent = src_folder == "sent"
                lookup = {
                    "user_email": email_l,
                    "account_id": aid,
                    "imap_uid": m["imap_uid"],
                }
                if is_sent:
                    # Cartella Inviate (IMAP Sent + eventuali duplicate da compose)
                    existing = await db.messages.find_one(
                        {**lookup, "folder": "sent"}
                    )
                    if not existing and m.get("message_id"):
                        existing = await db.messages.find_one(
                            {
                                "user_email": email_l,
                                "account_id": aid,
                                "folder": "sent",
                                "message_id": m["message_id"],
                            }
                        )
                    folder = "sent"
                else:
                    # match inbox/trash/legacy — non toccare messaggi "sent"
                    existing = await db.messages.find_one(
                        {
                            **lookup,
                            "$or": [
                                {"folder": {"$in": ["INBOX", "trash"]}},
                                {"folder": {"$exists": False}},
                                {"folder": None},
                            ],
                        }
                    )
                    folder = "INBOX"
                    if existing and (existing.get("folder") or "").lower() == "trash":
                        # non riportare in inbox messaggi già nel cestino
                        folder = "trash"
                # Non azzerare "letto in app" se IMAP non riporta ancora \Seen
                imap_flags = dict(m.get("flags") or {})
                if existing and (existing.get("flags") or {}).get("seen") is True:
                    imap_flags["seen"] = True
                payload = {
                    **lookup,
                    "folder": folder,
                    "message_id": m.get("message_id"),
                    "subject": m.get("subject", ""),
                    "from_addr": m.get("from_addr", ""),
                    "to_addrs": m.get("to_addrs", []),
                    "cc_addrs": m.get("cc_addrs", []),
                    "date": m.get("date") or datetime.utcnow(),
                    "flags": imap_flags,
                    "has_attachments": m.get("has_attachments", False),
                    "attachments": m.get("attachments", []),
                    "inline_parts": m.get("inline_parts") or [],
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
                    # Push solo per nuove ricevute, non per sync Sent
                    if not is_sent:
                        inserted += 1
                        if len(new_previews) < 5:
                            new_previews.append(
                                {
                                    "subject": (m.get("subject") or "(senza oggetto)")[:80],
                                    "from": (m.get("from_addr") or "")[:60],
                                    "is_pec": "1" if m.get("is_pec") else "0",
                                    "account": acc.get("label") or acc.get("address") or "",
                                }
                            )
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
        except HTTPException as exc:
            errors.append(f"{acc.get('address')}: {exc.detail}")
            await db.accounts.update_one(
                {"_id": acc["_id"]},
                {
                    "$set": {
                        "sync_state": "error",
                        "last_sync_at": datetime.utcnow(),
                        "last_sync_error": str(exc.detail),
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

    if notify and inserted > 0 and new_previews:
        await notify_user_new_mail(email_l, inserted, new_previews)

    return {
        "accounts_synced": synced,
        "messages_inserted": inserted,
        "errors": errors,
        "new_previews": new_previews,
        "message": "Sync IMAP completato"
        if not errors
        else "Sync completato con errori",
    }


async def _load_push_subs(email_l: str) -> List[Dict[str, Any]]:
    subs: List[Dict[str, Any]] = []
    async for s in db.push_subscriptions.find({"user_email": email_l}):
        subs.append(
            {
                "endpoint": s["endpoint"],
                "keys": s.get("keys") or {},
            }
        )
    return subs


async def _purge_dead_push_subs(email_l: str, dead: List[str]) -> int:
    if not dead:
        return 0
    res = await db.push_subscriptions.delete_many(
        {"user_email": email_l, "endpoint": {"$in": dead}}
    )
    removed = int(res.deleted_count or 0)
    if removed:
        log.info("Push: rimosse %s subscription scadute per %s", removed, email_l)
    return removed


async def notify_user_new_mail(
    email_l: str, inserted: int, previews: List[Dict[str, str]]
) -> None:
    if not push_notify.vapid_configured():
        log.warning("Push nuova mail saltata: VAPID non configurato (%s)", email_l)
        return
    first = previews[0] if previews else {}
    pec = first.get("is_pec") == "1"
    title = "Nuova PEC" if pec and inserted == 1 else (
        f"{inserted} nuove email" if inserted > 1 else "Nuova email"
    )
    body = first.get("subject") or "Hai ricevuto un nuovo messaggio"
    if first.get("from"):
        body = f"Da {first['from']}: {body}"
    if first.get("account"):
        body = f"[{first['account']}] {body}"

    subs = await _load_push_subs(email_l)
    if not subs:
        log.info("Push nuova mail: nessuna subscription per %s (+%s)", email_l, inserted)
        return
    dead, ok, fail = push_notify.notify_new_mail(
        subs, title=title, body=body[:180], url="/", tag="new-mail"
    )
    await _purge_dead_push_subs(email_l, dead)
    log.info(
        "Push nuova mail user=%s inserted=%s subs=%s ok=%s fail=%s dead=%s",
        email_l,
        inserted,
        len(subs),
        ok,
        fail,
        len(dead),
    )


@api.post("/sync/run")
async def sync_run(email: EmailStr, master_password: str, account_id: Optional[str] = None):
    """Scarica INBOX via IMAP e upserta i messaggi."""
    email_l = email.lower()
    await require_user(email_l, master_password)
    return await sync_accounts_for_user(email_l, account_id, notify=True)


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
                "last_sync_error": acc.get("last_sync_error"),
            }
        )
    outbox = await db.outbox.count_documents(
        {"user_email": email.lower(), "status": "queued"}
    )
    return {"accounts": accounts, "outbox_queued": outbox}


# --- web push ---


@api.get("/push/vapid-public-key")
async def push_vapid_public_key():
    key = push_notify.get_vapid_public()
    if not key:
        raise HTTPException(503, "Web Push non configurato")
    return {"publicKey": key}


@api.post("/push/subscribe")
async def push_subscribe(body: PushSubscribeBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    if not body.endpoint or not body.keys.get("p256dh") or not body.keys.get("auth"):
        raise HTTPException(400, "Subscription incompleta")
    host = ""
    try:
        from urllib.parse import urlparse

        host = urlparse(body.endpoint).netloc
    except Exception:
        host = ""
    await db.push_subscriptions.update_one(
        {"user_email": email, "endpoint": body.endpoint},
        {
            "$set": {
                "user_email": email,
                "endpoint": body.endpoint,
                "keys": {
                    "p256dh": body.keys["p256dh"],
                    "auth": body.keys["auth"],
                },
                "expiration_time": body.expiration_time,
                "updated_at": datetime.utcnow(),
                "endpoint_host": host,
            },
            "$setOnInsert": {"created_at": datetime.utcnow()},
        },
        upsert=True,
    )
    log.info("Push subscribe user=%s host=%s", email, host or "?")
    return {"ok": True, "endpoint_host": host}


class PushTestBody(BaseModel):
    email: EmailStr
    master_password: str


@api.post("/push/test")
async def push_test(_body: PushTestBody):
    """Disabilitato: la notifica di prova non viene piu inviata."""
    raise HTTPException(410, "Notifica di prova disabilitata")

@api.delete("/push/subscribe")
async def push_unsubscribe(email: EmailStr, master_password: str, endpoint: str):
    await require_user(email.lower(), master_password)
    await db.push_subscriptions.delete_one(
        {"user_email": email.lower(), "endpoint": endpoint}
    )
    return {"ok": True}


@api.post("/dev/seed_demo")
async def seed_demo(email: EmailStr, master_password: str):
    """Disabilitato: i messaggi demo non sono più supportati."""
    await require_user(email.lower(), master_password)
    raise HTTPException(
        status.HTTP_410_GONE,
        "Seed demo disabilitato. Usa /api/dev/purge_demo_messages per rimuovere i vecchi demo.",
    )


@api.post("/dev/purge_demo_messages")
async def purge_demo_messages(email: EmailStr, master_password: str):
    """Elimina messaggi demo (soggetti noti) per l'utente autenticato."""
    email_l = email.lower()
    await require_user(email_l, master_password)
    demo_subjects = [
        "Benvenuto in Mail Manager",
        "PEC: Avviso di prova",
    ]
    filt: Dict[str, Any] = {
        "user_email": email_l,
        "$or": [
            {"subject": {"$regex": s, "$options": "i"}} for s in demo_subjects
        ]
        + [
            {"from_addr": {"$regex": r"noreply@colorsdev\.tech", "$options": "i"}},
            {"from_addr": {"$regex": r"mittente@pec\.example\.it", "$options": "i"}},
        ],
    }
    res = await db.messages.delete_many(filt)
    return {"ok": True, "deleted": res.deleted_count}


app.include_router(api)

_sync_task = None


async def peek_and_notify_for_user(email_l: str) -> Dict[str, Any]:
    """
    Poll rapido INBOX (solo header): push in pochi secondi.
    Il body completo arriva dal sync periodico / click notifica / pull.
    """
    import asyncio

    notified = 0
    errors: List[str] = []
    previews: List[Dict[str, str]] = []

    async for acc in db.accounts.find({"user_email": email_l}):
        aid = str(acc["_id"])
        try:
            user, pwd, access_token = await resolve_mailbox_creds(acc, email_l)
            since = acc.get("last_notify_uid")
            # Prima volta: ancora il cursore all'ultimo UID senza spam di notifiche storiche
            bootstrap = since is None or since == ""
            peeked = await asyncio.to_thread(
                mail_provider.peek_new_inbox_headers,
                acc["imap_host"],
                int(acc.get("imap_port") or 993),
                user,
                pwd or "",
                since_uid=None if bootstrap else str(since),
                limit=20 if bootstrap else 15,
                account_type=acc.get("type") or "imap",
                provider_hint=acc.get("pec_provider") or acc.get("type"),
                access_token=access_token,
            )
            if not peeked:
                continue
            max_uid = max(int(m["imap_uid"]) for m in peeked)
            if bootstrap:
                await db.accounts.update_one(
                    {"_id": acc["_id"]},
                    {"$set": {"last_notify_uid": str(max_uid)}},
                )
                continue

            for m in peeked:
                lookup = {
                    "user_email": email_l,
                    "account_id": aid,
                    "imap_uid": m["imap_uid"],
                    "folder": "INBOX",
                }
                existing = await db.messages.find_one(
                    {
                        **{k: lookup[k] for k in ("user_email", "account_id", "imap_uid")},
                        "$or": [
                            {"folder": {"$in": ["INBOX", "trash"]}},
                            {"folder": {"$exists": False}},
                            {"folder": None},
                        ],
                    }
                )
                if existing:
                    continue
                payload = {
                    **lookup,
                    "message_id": m.get("message_id"),
                    "subject": m.get("subject", ""),
                    "from_addr": m.get("from_addr", ""),
                    "to_addrs": m.get("to_addrs", []),
                    "cc_addrs": [],
                    "date": m.get("date") or datetime.utcnow(),
                    "flags": m.get("flags") or {"seen": False},
                    "has_attachments": False,
                    "attachments": [],
                    "inline_parts": [],
                    "is_pec": m.get("is_pec", False),
                    "snippet": m.get("snippet") or "",
                    "body_enc": encrypt_secret("", email_l),
                    "body_html": None,
                    "receipts": [],
                    "header_only": True,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
                await db.messages.insert_one(payload)
                notified += 1
                if len(previews) < 5:
                    previews.append(
                        {
                            "subject": (m.get("subject") or "(senza oggetto)")[:80],
                            "from": (m.get("from_addr") or "")[:60],
                            "is_pec": "1" if m.get("is_pec") else "0",
                            "account": acc.get("label") or acc.get("address") or "",
                        }
                    )

            await db.accounts.update_one(
                {"_id": acc["_id"]},
                {"$set": {"last_notify_uid": str(max_uid)}},
            )
        except HTTPException as exc:
            errors.append(f"{acc.get('address')}: {exc.detail}")
        except Exception as exc:
            log.warning("Peek notify fallito %s: %s", acc.get("address"), exc)
            errors.append(f"{acc.get('address')}: {exc}")

    if notified > 0 and previews:
        await notify_user_new_mail(email_l, notified, previews)

    return {"notified": notified, "errors": errors}


async def background_sync_loop():
    """
    Due ritmi:
    - peek/notify ogni NOTIFY_POLL_SECONDS (default 5s) → push rapide
    - full sync ogni SYNC_INTERVAL_SECONDS (default 120s) → body/allegati, senza ripush
    """
    import asyncio
    import time

    notify_every = max(5, int(os.environ.get("NOTIFY_POLL_SECONDS") or 5))
    sync_every = max(60, int(os.environ.get("SYNC_INTERVAL_SECONDS") or 120))
    log.info(
        "Background: notify ogni %ss, full sync ogni %ss",
        notify_every,
        sync_every,
    )
    await asyncio.sleep(8)
    last_full_sync = 0.0
    while True:
        loop_started = time.monotonic()
        try:
            emails = await db.accounts.distinct("user_email")
            for email_l in emails:
                if not email_l:
                    continue
                try:
                    result = await peek_and_notify_for_user(email_l)
                    if result.get("notified"):
                        log.info(
                            "Peek notify %s: +%s",
                            email_l,
                            result["notified"],
                        )
                except Exception:
                    log.exception("Peek notify fallito per %s", email_l)

            now = time.monotonic()
            if now - last_full_sync >= sync_every:
                for email_l in emails:
                    if not email_l:
                        continue
                    try:
                        # notify=False: le push le fa già il peek
                        result = await sync_accounts_for_user(email_l, notify=False)
                        if result.get("messages_inserted"):
                            log.info(
                                "Background sync %s: +%s messaggi",
                                email_l,
                                result["messages_inserted"],
                            )
                    except Exception:
                        log.exception("Background sync fallito per %s", email_l)
                last_full_sync = now
        except Exception:
            log.exception("Background loop error")

        elapsed = time.monotonic() - loop_started
        await asyncio.sleep(max(1.0, notify_every - elapsed))


async def ensure_vapid_keys():
    info = push_notify.init_vapid_from_env()
    if info.get("source") == "env":
        log.info("VAPID keys da env")
        return
    doc = await db.settings.find_one({"_id": "vapid"})
    if doc and doc.get("public_key") and doc.get("private_key"):
        push_notify.set_vapid_keys(doc["public_key"], doc["private_key"])
        log.info("VAPID keys da Mongo")
        return
    keys = push_notify.generate_vapid_keypair()
    await db.settings.update_one(
        {"_id": "vapid"},
        {
            "$set": {
                "public_key": keys["public_key"],
                "private_key": keys["private_key"],
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    push_notify.set_vapid_keys(keys["public_key"], keys["private_key"])
    log.info("VAPID keys generate e salvate in Mongo")


@app.on_event("startup")
async def startup():
    global _sync_task
    import asyncio

    removed = await dedupe_users_by_email()
    if removed:
        log.info("Removed %s duplicate user document(s)", removed)
    await db.users.create_index("email", unique=True)
    await db.accounts.create_index([("user_email", 1), ("address", 1)])
    await db.messages.create_index([("user_email", 1), ("date", -1)])
    await db.messages.create_index([("user_email", 1), ("is_pec", 1)])
    await db.messages.create_index(
        [("user_email", 1), ("account_id", 1), ("imap_uid", 1), ("folder", 1)],
        unique=False,
    )
    await db.outbox.create_index([("user_email", 1), ("status", 1)])
    await db.oauth_pending.create_index("state", unique=True)
    await db.oauth_pending.create_index("expires_at", expireAfterSeconds=0)
    await db.push_subscriptions.create_index(
        [("user_email", 1), ("endpoint", 1)], unique=True
    )
    await ensure_vapid_keys()
    _sync_task = asyncio.create_task(background_sync_loop())
    log.info("Mail Manager API v2 ready — db=%s", db_name)
