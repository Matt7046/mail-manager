"""
Mail Manager API (v2) — vault multi-casella + PEC send/receipts.
Sync IMAP/OAuth provider implementations are hooks: models + routes are ready.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

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
    imap_password: str
    smtp_host: Optional[str] = None
    smtp_port: int = 465
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    pec_provider: Optional[str] = None  # aruba | legalmail | postecert | other
    color: str = "#4ecdc4"


class AccountOut(BaseModel):
    id: str
    type: AccountType
    label: str
    address: str
    color: str
    pec_provider: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    sync_state: str = "idle"


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
    )


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
    "aruba": {
        "imap_host": "imaps.pec.aruba.it",
        "imap_port": 993,
        "smtp_host": "smtps.pec.aruba.it",
        "smtp_port": 465,
    },
    "legalmail": {
        "imap_host": "mbox.legalmail.it",
        "imap_port": 993,
        "smtp_host": "smtp.legalmail.it",
        "smtp_port": 465,
    },
    "postecert": {
        "imap_host": "mail.postecert.it",
        "imap_port": 993,
        "smtp_host": "mail.postecert.it",
        "smtp_port": 465,
    },
}


@api.get("/accounts", response_model=List[AccountOut])
async def list_accounts(email: EmailStr, master_password: str):
    await require_user(email.lower(), master_password)
    cur = db.accounts.find({"user_email": email.lower()}).sort("created_at", 1)
    return [public_account(d) async for d in cur]


@api.get("/accounts/pec-presets")
async def pec_presets():
    return PEC_PRESETS


@api.post("/accounts/imap", response_model=AccountOut)
async def add_imap_account(body: ImapAccountBody):
    email = body.email.lower()
    await require_user(email, body.master_password)
    if body.account_type == "pec" and body.pec_provider and body.pec_provider in PEC_PRESETS:
        preset = PEC_PRESETS[body.pec_provider]
        imap_host = body.imap_host or preset["imap_host"]
        imap_port = body.imap_port or preset["imap_port"]
        smtp_host = body.smtp_host or preset["smtp_host"]
        smtp_port = body.smtp_port or preset["smtp_port"]
    else:
        imap_host, imap_port = body.imap_host, body.imap_port
        smtp_host, smtp_port = body.smtp_host, body.smtp_port

    doc = {
        "user_email": email,
        "type": body.account_type,
        "label": body.label,
        "address": str(body.address).lower(),
        "color": body.color,
        "pec_provider": body.pec_provider,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "imap_user": body.imap_user,
        "imap_password_enc": encrypt_secret(body.imap_password, email),
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": body.smtp_user or body.imap_user,
        "smtp_password_enc": encrypt_secret(
            body.smtp_password or body.imap_password, email
        ),
        "oauth_tokens_enc": None,
        "last_sync_at": None,
        "sync_state": "idle",
        "created_at": datetime.utcnow(),
    }
    res = await db.accounts.insert_one(doc)
    doc["_id"] = res.inserted_id
    return public_account(doc)


@api.post("/accounts/oauth/{provider}/start")
async def oauth_start(provider: Literal["google", "microsoft"], email: EmailStr):
    """Hook: restituisce URL OAuth da aprire nel browser."""
    if provider == "google":
        cid = os.environ.get("GOOGLE_CLIENT_ID", "")
        redir = os.environ.get("GOOGLE_REDIRECT_URI", "")
        if not cid:
            raise HTTPException(501, "GOOGLE_CLIENT_ID non configurato")
        url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={cid}&redirect_uri={redir}"
            "&response_type=code&scope=https://mail.google.com/"
            f"&access_type=offline&prompt=consent&state={email}"
        )
        return {"authorize_url": url}
    cid = os.environ.get("MICROSOFT_CLIENT_ID", "")
    redir = os.environ.get("MICROSOFT_REDIRECT_URI", "")
    if not cid:
        raise HTTPException(501, "MICROSOFT_CLIENT_ID non configurato")
    url = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        f"?client_id={cid}&redirect_uri={redir}"
        "&response_type=code&scope=offline_access%20https://outlook.office.com/IMAP.AccessAsUser.All"
        f"&state={email}"
    )
    return {"authorize_url": url}


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
    """Probe connessione — stub v2 finché non c'è client IMAP."""
    await require_user(email.lower(), master_password)
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        oid = ObjectId(account_id)
    except InvalidId as exc:
        raise HTTPException(400, "ID non valido") from exc
    acc = await db.accounts.find_one({"_id": oid, "user_email": email.lower()})
    if not acc:
        raise HTTPException(404, "Account non trovato")
    return {
        "ok": True,
        "message": "Credenziali salvate. Sync IMAP reale in arrivo.",
        "host": acc.get("imap_host"),
        "type": acc.get("type"),
    }


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
    """
    v2: accetta anche as_pec=True.
    Invio SMTP reale = TODO provider; qui crea outbox + messaggio locale + receipt placeholder.
    """
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

    now = datetime.utcnow()
    receipts = []
    if body.as_pec or acc.get("type") == "pec":
        receipts.append(
            {
                "type": "accettazione",
                "at": now.isoformat() + "Z",
                "status": "pending_provider",
                "note": "In attesa di invio SMTP PEC reale",
            }
        )

    doc = {
        "user_email": email,
        "account_id": body.account_id,
        "folder": "sent",
        "subject": body.subject,
        "from_addr": acc["address"],
        "to_addrs": [str(x).lower() for x in body.to],
        "cc_addrs": [str(x).lower() for x in body.cc],
        "date": now,
        "flags": {"seen": True, "flagged": False, "archived": False},
        "has_attachments": False,
        "attachments": [],
        "is_pec": bool(body.as_pec or acc.get("type") == "pec"),
        "snippet": (body.body_text or "")[:160],
        "body_enc": encrypt_secret(body.body_text or "", email),
        "body_html": body.body_html,
        "receipts": receipts,
        "outbox_status": "queued",
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
            "status": "queued",
            "created_at": now,
        }
    )
    return {
        "id": str(res.inserted_id),
        "queued": True,
        "is_pec": doc["is_pec"],
        "receipts": receipts,
        "message": "Messaggio in outbox (SMTP provider da collegare)",
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
    await require_user(email.lower(), master_password)
    filt: Dict[str, Any] = {"user_email": email.lower()}
    if account_id:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            filt["_id"] = ObjectId(account_id)
        except InvalidId as exc:
            raise HTTPException(400, "account_id non valido") from exc
    n = 0
    async for acc in db.accounts.find(filt):
        await db.accounts.update_one(
            {"_id": acc["_id"]},
            {"$set": {"sync_state": "queued", "last_sync_at": datetime.utcnow()}},
        )
        n += 1
    return {
        "queued": n,
        "message": "Sync accodato (worker IMAP da collegare). Seed demo con POST /api/dev/seed_demo",
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
    log.info("Mail Manager API v2 ready — db=%s", db_name)
