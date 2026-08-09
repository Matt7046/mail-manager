"""IMAP/SMTP reale per Mail Manager (Gmail app-password, Outlook, IMAP generico, PEC)."""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
import html as html_lib
import base64 as b64mod
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("mail-manager.provider")

IMAP_PRESETS: Dict[str, Dict[str, Any]] = {
    "gmail": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "smtp_ssl": True,
        "hint": "Usa una App Password Google (account Google → Sicurezza → Password per le app).",
    },
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp-mail.outlook.com",
        "smtp_port": 587,
        "smtp_ssl": False,
        "smtp_starttls": True,
        "imap_fallbacks": ["imap-mail.outlook.com"],
        "hint": (
            "Outlook/Hotmail: 1) Outlook.com → Impostazioni → Posta → Inoltro e IMAP → abilita IMAP. "
            "2) account.microsoft.com → Sicurezza → Password per le app. "
            "Se fallisce ancora, Microsoft può richiedere OAuth (non solo app password)."
        ),
    },
    "aruba": {
        "imap_host": "imaps.pec.aruba.it",
        "imap_port": 993,
        "smtp_host": "smtps.pec.aruba.it",
        "smtp_port": 465,
        "smtp_ssl": True,
    },
    "legalmail": {
        "imap_host": "mbox.legalmail.it",
        "imap_port": 993,
        "smtp_host": "smtp.legalmail.it",
        "smtp_port": 465,
        "smtp_ssl": True,
    },
    "postecert": {
        "imap_host": "mail.postecert.it",
        "imap_port": 993,
        "smtp_host": "mail.postecert.it",
        "smtp_port": 465,
        "smtp_ssl": True,
    },
    "intesi": {
        "imap_host": "imap.ig-trustmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.ig-trustmail.com",
        "smtp_port": 465,
        "smtp_ssl": True,
        "hint": "PEC Intesi Group (ig-trustmail): usa l’indirizzo PEC completo e la password della casella.",
    },
}


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out: List[str] = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _parse_addrs(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [addr.lower() for _name, addr in email.utils.getaddresses([value]) if addr]


def _msg_date(msg: email.message.Message) -> datetime:
    raw = msg.get("Date")
    if raw:
        try:
            dt = email.utils.parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc).replace(tzinfo=None)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.utcnow()


_ZWNJ_RE = re.compile(
    r"(?:&zwnj;|&#8204;|&#x0*200c;|\u200c|\u200b|\ufeff)+",
    re.IGNORECASE,
)


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = html_lib.unescape(s)
    s = _ZWNJ_RE.sub("", s)
    s = re.sub(r"[ \t\f\v\xa0]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _html_to_text(html_s: str) -> str:
    if not html_s:
        return ""
    t = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        "",
        html_s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"</p\s*>", "\n\n", t, flags=re.IGNORECASE)
    t = re.sub(r"</div\s*>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    return _clean_text(t)


def _extract_body(msg: email.message.Message) -> Tuple[str, Optional[str]]:
    text_body = ""
    html_body: Optional[str] = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain" and not text_body:
                text_body = decoded
            elif ctype == "text/html" and html_body is None:
                html_body = decoded
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = decoded
                text_body = _html_to_text(decoded)
            else:
                text_body = decoded
        except Exception:
            text_body = str(msg.get_payload() or "")

    text_body = _clean_text(text_body)
    # Newsletter: plain pieno di &zwnj; / vuoto → deriva dal HTML
    plain_junk = (
        not text_body
        or len(_ZWNJ_RE.findall(text_body)) > 5
        or (html_body and len(text_body) < 40 and len(html_body) > 200)
    )
    if html_body and plain_junk:
        text_body = _html_to_text(html_body) or text_body
    return text_body, html_body


def _extract_inline_parts(msg: email.message.Message) -> List[Dict[str, Any]]:
    """Immagini inline (cid:) da sostituire nel body HTML."""
    parts: List[Dict[str, Any]] = []
    max_one = 2_500_000
    for part in msg.walk():
        cid_raw = part.get("Content-ID") or part.get("Content-Id") or ""
        if not cid_raw:
            continue
        cid = str(cid_raw).strip().strip("<>").strip()
        if not cid:
            continue
        ctype = (part.get_content_type() or "application/octet-stream").lower()
        disp = str(part.get("Content-Disposition") or "").lower()
        fname = (_decode_header(part.get_filename()) or "").lower()
        is_image = ctype.startswith("image/") or fname.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        )
        if not is_image and "inline" not in disp:
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if not payload or len(payload) > max_one:
            continue
        parts.append(
            {
                "cid": cid,
                "content_type": ctype if ctype.startswith("image/") else "image/png",
                "content_base64": b64mod.b64encode(payload).decode("ascii"),
            }
        )
    return parts


def _looks_like_pec(msg: email.message.Message, account_type: str) -> bool:
    if account_type == "pec":
        return True
    subj = (_decode_header(msg.get("Subject")) or "").lower()
    ctype = (msg.get_content_type() or "").lower()
    if "posta certificata" in subj or "ricevuta di" in subj:
        return True
    if "multipart/signed" in ctype or "application/pkcs7-mime" in ctype:
        return True
    return False


def normalize_mailbox_secret(password: str) -> str:
    """Gmail App Password spesso ha spazi (xxxx xxxx xxxx xxxx)."""
    return (password or "").replace(" ", "").replace("\u00a0", "").strip()


def _imap_auth_error(exc: Exception, host: str) -> RuntimeError:
    msg = str(exc)
    low = msg.lower()
    if "gmail" in host.lower() or "google" in low:
        if any(x in low for x in ("authentication failed", "invalid credentials", "login failed", "auth")):
            return RuntimeError(
                "Login Gmail rifiutato. Usa una App Password (non la password dell'account), "
                "con 2FA attiva. Google Account → Sicurezza → Password per le app."
            )
    if any(
        x in host.lower()
        for x in ("outlook", "office365", "hotmail", "live.com")
    ) or "microsoft" in low:
        return RuntimeError(
            "Login Microsoft/Outlook rifiutato (AUTHENTICATE failed). "
            "L’inoltro email NON serve. Serve: Impostazioni Outlook.com → Posta → Inoltro e IMAP → "
            "«Consenti a dispositivi e app di usare IMAP» = ON. "
            "Se IMAP è già attivo e usi App Password, Microsoft ha disabilitato l’accesso con password su questa casella: "
            "serve login OAuth (Modern Auth). "
            f"Dettaglio: {msg}"
        )
    return RuntimeError(f"IMAP {host}: {msg}")


def _try_imap_login(client: imaplib.IMAP4_SSL, user: str, password: str) -> None:
    pwd = normalize_mailbox_secret(password)
    try:
        client.login(user, pwd)
        return
    except Exception as login_exc:
        # Alcuni server Microsoft accettano AUTH PLAIN ma non LOGIN.
        try:
            def _plain(_challenge: bytes) -> bytes:
                return f"\0{user}\0{pwd}".encode("utf-8")

            typ, _ = client.authenticate("PLAIN", _plain)
            if typ == "OK":
                return
        except Exception:
            pass
        raise login_exc


def _imap_connect(host: str, port: int, user: str, password: str) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=45)
    try:
        _try_imap_login(client, user, password)
    except Exception as exc:
        try:
            client.shutdown()
        except Exception:
            pass
        raise _imap_auth_error(exc, host) from exc
    return client


def _outlook_hosts(primary: str) -> List[str]:
    hosts = [primary]
    for h in IMAP_PRESETS.get("outlook", {}).get("imap_fallbacks") or []:
        if h not in hosts:
            hosts.append(h)
    for h in ("outlook.office365.com", "imap-mail.outlook.com"):
        if h not in hosts:
            hosts.append(h)
    return hosts


def _imap_connect_xoauth2(host: str, port: int, user: str, access_token: str) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=45)
    try:
        auth_str = f"user={user}\x01auth=Bearer {access_token}\x01\x01"

        def _xoauth2(_challenge: bytes) -> bytes:
            return auth_str.encode("utf-8")

        typ, data = client.authenticate("XOAUTH2", _xoauth2)
        if typ != "OK":
            raise RuntimeError(f"XOAUTH2 fallito: {typ} {data}")
    except Exception as exc:
        try:
            client.shutdown()
        except Exception:
            pass
        raise _imap_auth_error(exc, host) from exc
    return client


def connect_mailbox(
    host: str,
    port: int,
    user: str,
    password: str = "",
    *,
    provider_hint: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Tuple[imaplib.IMAP4_SSL, str]:
    """Connette IMAP con password oppure XOAUTH2."""
    if access_token:
        is_outlook = (provider_hint or "").lower() in ("outlook", "microsoft") or any(
            x in (host or "").lower() for x in ("outlook", "office365", "hotmail")
        )
        hosts = _outlook_hosts(host) if is_outlook else [host]
        errors: List[str] = []
        for h in hosts:
            try:
                return _imap_connect_xoauth2(h, port, user, access_token), h
            except Exception as exc:
                errors.append(f"{h}: {exc}")
        raise RuntimeError(" | ".join(errors) if errors else "XOAUTH2 IMAP fallito")

    is_outlook = (provider_hint or "").lower() in ("outlook", "microsoft") or any(
        x in (host or "").lower() for x in ("outlook", "office365", "hotmail")
    )
    hosts = _outlook_hosts(host) if is_outlook else [host]
    errors = []
    for h in hosts:
        try:
            return _imap_connect(h, port, user, password), h
        except Exception as exc:
            errors.append(f"{h}: {exc}")
    raise RuntimeError(" | ".join(errors) if errors else "Connessione IMAP fallita")


def test_imap(
    host: str,
    port: int,
    user: str,
    password: str = "",
    *,
    provider_hint: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not (user or "").strip():
        raise RuntimeError("Utente IMAP vuoto: inserisci l'indirizzo email completo")
    client, used_host = connect_mailbox(
        host,
        port,
        user.strip(),
        password,
        provider_hint=provider_hint,
        access_token=access_token,
    )
    try:
        typ, data = client.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"SELECT INBOX fallito: {typ}")
        count = int(data[0]) if data and data[0] else 0
        return {"ok": True, "inbox_count": count, "host": used_host, "user": user.strip()}
    finally:
        try:
            client.logout()
        except Exception:
            pass


_SENT_CANDIDATES = (
    "[Gmail]/Sent Mail",
    "[Gmail]/Posta inviata",
    "[Google Mail]/Sent Mail",
    "[Google Mail]/Posta inviata",
    "Sent",
    "Sent Items",
    "Sent Messages",
    "INBOX.Sent",
    "INBOX/Sent",
    "Posta inviata",
    "Elementi inviati",
    "Messaggi inviati",
)

_GMAIL_ALL_MAIL = (
    "[Gmail]/All Mail",
    "[Gmail]/Tutti i messaggi",
    "[Google Mail]/All Mail",
    "[Google Mail]/Tutti i messaggi",
)


def _decode_mailbox_name(raw) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, tuple) and len(raw) >= 3:
        name = raw[2]
        if isinstance(name, bytes):
            # Gmail LIST: spesso ASCII / modified UTF-7
            try:
                return name.decode("utf-8")
            except Exception:
                return name.decode("latin-1", errors="replace")
        return str(name)
    line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    m = re.search(r'"([^"]+)"\s*$', line)
    if m:
        return m.group(1)
    parts = line.split()
    return parts[-1].strip('"') if parts else None


def _mailbox_flags(raw) -> str:
    if isinstance(raw, tuple) and len(raw) >= 1:
        flags = raw[0]
        if isinstance(flags, bytes):
            return flags.decode("utf-8", errors="replace")
        return str(flags)
    line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    m = re.match(r"^\(([^)]*)\)", line)
    return m.group(1) if m else ""


def list_mailboxes(client: imaplib.IMAP4) -> List[Dict[str, str]]:
    """Lista mailbox con nome + flags IMAP (es. \\Sent)."""
    out: List[Dict[str, str]] = []
    seen: set = set()

    def _ingest(typ, data) -> None:
        if typ != "OK" or not data:
            return
        for row in data:
            if row is None:
                continue
            name = _decode_mailbox_name(row)
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "flags": _mailbox_flags(row)})

    try:
        typ, data = client.list()
        _ingest(typ, data)
    except Exception as exc:
        log.warning("IMAP LIST fallito: %s", exc)
    # Gmail: se manca [Gmail]/*, forza pattern dedicato
    if not any(n.startswith("[Gmail]/") or n.startswith("[Google Mail]/") for n in seen):
        for ref, pat in (('""', "[Gmail]/%"), ('""', "[Google Mail]/%"), ('""', "*")):
            try:
                typ, data = client.list(ref, pat)
                _ingest(typ, data)
            except Exception as exc:
                log.warning("IMAP LIST fallito ref=%s pat=%s: %s", ref, pat, exc)
    return out


def list_mailbox_names(client: imaplib.IMAP4) -> List[str]:
    return [b["name"] for b in list_mailboxes(client)]


def _quote_mailbox(name: str) -> str:
    """
    Quoting IMAP per nomi con spazi / [Gmail]/… .
    Su Python recenti imaplib.select NON aggiunge virgolette → BAD 'Could not parse command'.
    """
    if name is None:
        return '""'
    s = str(name)
    # già quotato correttamente
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _try_select(client: imaplib.IMAP4, mailbox: str, *, log_fail: bool = False) -> bool:
    """SELECT robusto (Gmail IT: Posta inviata / Tutti i messaggi)."""
    if not mailbox:
        return False
    quoted = _quote_mailbox(mailbox)
    last_typ, last_data, last_exc = None, None, None
    for readonly in (True, False):
        try:
            typ, data = client.select(quoted, readonly=readonly)
            if typ == "OK":
                return True
            last_typ, last_data = typ, data
        except Exception as exc:
            last_exc = exc
            continue
    if log_fail:
        log.warning(
            "SELECT fallito mailbox=%r quoted=%s hex=%s typ=%s data=%s exc=%s",
            mailbox,
            quoted,
            mailbox.encode("utf-8", errors="replace").hex(),
            last_typ,
            last_data,
            last_exc,
        )
    return False


def _imap_capabilities(client: imaplib.IMAP4) -> str:
    try:
        caps = client.capabilities
        if isinstance(caps, (tuple, list)):
            return " ".join(
                c.decode() if isinstance(c, (bytes, bytearray)) else str(c) for c in caps
            )
        return str(caps)
    except Exception:
        return ""


def resolve_sent_mailbox(client: imaplib.IMAP4) -> Optional[str]:
    """Trova Sent / Posta inviata (Gmail IT incluso) via \\Sent o nomi noti."""
    # Alcuni server Gmail rispondono meglio a LIST dopo un EXAMINE INBOX
    try:
        client.select(_quote_mailbox("INBOX"), readonly=True)
    except Exception:
        pass
    boxes = list_mailboxes(client)

    # 1) RFC 6154 SPECIAL-USE \\Sent (Gmail lo espone)
    for b in boxes:
        flags = (b.get("flags") or "").upper()
        if "\\SENT" in flags or " SENT" in f" {flags}":
            name = b["name"]
            if _try_select(client, name, log_fail=True):
                log.info("Sent mailbox via \\Sent flag: %s", name)
                return name

    names = [b["name"] for b in boxes]
    lower_map = {n.lower(): n for n in names}

    # 2) Candidati esatti (Gmail EN/IT, Outlook, …)
    for cand in _SENT_CANDIDATES:
        if cand.lower() in lower_map:
            name = lower_map[cand.lower()]
            if _try_select(client, name, log_fail=True):
                return name

    # 3) Match fuzzy: sent / inviata / inviati
    for n in names:
        bl = n.lower()
        if "spam" in bl or "trash" in bl or "cestino" in bl or "junk" in bl or "draft" in bl:
            continue
        if (
            "sent mail" in bl
            or "posta inviata" in bl
            or "messaggi inviati" in bl
            or "elementi inviati" in bl
            or bl.endswith("/sent")
            or bl.endswith(".sent")
            or bl in ("sent", "sent items")
            or ("sent" in bl and "present" not in bl)
            or "inviata" in bl
            or "inviati" in bl
        ):
            if _try_select(client, n, log_fail=True):
                log.info("Sent mailbox via fuzzy name: %s", n)
                return n

    # 4) Fallback: prova SELECT diretto (LIST vuoto / nomi non listati)
    for cand in _SENT_CANDIDATES:
        if _try_select(client, cand, log_fail=True):
            log.info("Sent mailbox via direct SELECT: %s", cand)
            return cand
    if names:
        log.info(
            "Mailbox IMAP disponibili (no Sent): %s",
            ", ".join(repr(n) for n in names[:40]) + ("…" if len(names) > 40 else ""),
        )
    return None


def _parse_fetch_items(
    msg_data,
    *,
    fallback_uid: str,
    folder_label: str,
    account_type: str,
) -> Optional[Dict[str, Any]]:
    raw = None
    flags_blob = b""
    uid = fallback_uid
    for item in msg_data:
        if isinstance(item, tuple) and len(item) >= 2:
            meta = item[0] if isinstance(item[0], (bytes, bytearray)) else b""
            flags_blob += meta + b" "
            body_part = item[1]
            if isinstance(body_part, (bytes, bytearray)) and len(body_part) > 10:
                raw = body_part
            m_uid = re.search(rb"UID\s+(\d+)", meta)
            if m_uid:
                uid = m_uid.group(1).decode()
        elif isinstance(item, (bytes, bytearray)):
            flags_blob += item + b" "
    if not raw:
        return None
    msg = email.message_from_bytes(raw)
    text_body, html_body = _extract_body(msg)
    inline_parts = _extract_inline_parts(msg)
    seen = False
    flagged = False
    m_flags = re.search(rb"FLAGS\s*\(([^)]*)\)", flags_blob, re.I)
    if m_flags:
        inner = m_flags.group(1).lower()
        seen = b"\\seen" in inner
        flagged = b"\\flagged" in inner
    message_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower() or part.get_filename():
                cid = part.get("Content-ID") or part.get("Content-Id")
                if cid and "attachment" not in disp.lower():
                    continue
                attachments.append(
                    {
                        "filename": _decode_header(part.get_filename()) or "file",
                        "content_type": part.get_content_type(),
                    }
                )
    return {
        "imap_uid": uid,
        "message_id": message_id,
        "subject": _decode_header(msg.get("Subject")) or "(senza oggetto)",
        "from_addr": _parse_addrs(msg.get("From"))[0]
        if _parse_addrs(msg.get("From"))
        else _decode_header(msg.get("From")),
        "to_addrs": _parse_addrs(msg.get("To")),
        "cc_addrs": _parse_addrs(msg.get("Cc")),
        "date": _msg_date(msg),
        "flags": {"seen": seen, "flagged": flagged, "archived": False},
        "has_attachments": bool(attachments),
        "attachments": attachments,
        "inline_parts": inline_parts,
        "is_pec": _looks_like_pec(msg, account_type),
        "snippet": (text_body or "")[:180],
        "body_text": text_body,
        "body_html": html_body,
        "folder": folder_label,
    }


def _fetch_from_selected(
    client: imaplib.IMAP4,
    *,
    folder_label: str,
    limit: int,
    account_type: str,
) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    typ, data = client.search(None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    ids = data[0].split()
    ids = ids[-limit:]
    ids.reverse()  # newest first
    for num in ids:
        # FLAGS espliciti: con solo RFC822 spesso non arrivano e tutte le mail restano "non lette"
        typ, msg_data = client.fetch(num, "(FLAGS UID BODY.PEEK[])")
        if typ != "OK" or not msg_data:
            continue
        fallback = num.decode() if isinstance(num, bytes) else str(num)
        parsed = _parse_fetch_items(
            msg_data,
            fallback_uid=fallback,
            folder_label=folder_label,
            account_type=account_type,
        )
        if parsed:
            messages.append(parsed)
    return messages


def _fetch_uids(
    client: imaplib.IMAP4,
    uids: List[bytes],
    *,
    folder_label: str,
    account_type: str,
    uid_prefix: str = "",
) -> List[Dict[str, Any]]:
    """FETCH per UID (es. risultati di UID SEARCH X-GM-RAW)."""
    messages: List[Dict[str, Any]] = []
    for uid_b in uids:
        uid_s = uid_b.decode() if isinstance(uid_b, bytes) else str(uid_b)
        typ, msg_data = client.uid("FETCH", uid_s, "(FLAGS UID BODY.PEEK[])")
        if typ != "OK" or not msg_data:
            continue
        parsed = _parse_fetch_items(
            msg_data,
            fallback_uid=uid_s,
            folder_label=folder_label,
            account_type=account_type,
        )
        if parsed:
            if uid_prefix:
                parsed["imap_uid"] = f"{uid_prefix}{parsed['imap_uid']}"
            messages.append(parsed)
    return messages


def _resolve_gmail_all_mail(client: imaplib.IMAP4) -> Optional[str]:
    boxes = list_mailboxes(client)
    for b in boxes:
        flags = (b.get("flags") or "").upper()
        if "\\ALL" in flags:
            if _try_select(client, b["name"]):
                return b["name"]
    names = {b["name"].lower(): b["name"] for b in boxes}
    for cand in _GMAIL_ALL_MAIL:
        if cand.lower() in names and _try_select(client, names[cand.lower()]):
            return names[cand.lower()]
    for cand in _GMAIL_ALL_MAIL:
        if _try_select(client, cand):
            return cand
    return None


def fetch_gmail_sent_via_raw(
    client: imaplib.IMAP4,
    *,
    limit: int,
    account_type: str,
) -> List[Dict[str, Any]]:
    """
    Fallback Gmail: se la label Sent non è esposta in IMAP, cerca con X-GM-RAW in:sent
    su All Mail / Tutti i messaggi.
    """
    all_box = _resolve_gmail_all_mail(client)
    if not all_box:
        # diagnostica SELECT candidati
        for cand in _GMAIL_ALL_MAIL:
            _try_select(client, cand, log_fail=True)
        log.warning(
            "Gmail All Mail non selezionabile — caps=%s",
            _imap_capabilities(client),
        )
        return []
    typ, data = client.uid("SEARCH", None, "X-GM-RAW", "in:sent")
    if typ != "OK" or not data or not data[0]:
        # alcune librerie vogliono la query già quotata
        typ, data = client.uid("SEARCH", None, "X-GM-RAW", '"in:sent"')
    if typ != "OK" or not data or not data[0]:
        log.warning("Gmail X-GM-RAW in:sent vuoto/fallito typ=%s data=%s", typ, data)
        return []
    ids = data[0].split()
    ids = ids[-limit:]
    ids.reverse()
    messages = _fetch_uids(
        client,
        ids,
        folder_label="sent",
        account_type=account_type,
        uid_prefix="gmraw:",
    )
    log.info(
        "Sync Sent via X-GM-RAW ok mailbox=%s count=%s",
        all_box,
        len(messages),
    )
    return messages


def _fetch_sent_folder(
    client: imaplib.IMAP4,
    *,
    user: str,
    limit: int,
    account_type: str,
    provider_hint: Optional[str],
    is_gmail: bool,
) -> List[Dict[str, Any]]:
    """Trova e scarica Sent; per Gmail ha fallback X-GM-RAW."""
    sent_box = resolve_sent_mailbox(client)
    if not sent_box and is_gmail:
        for cand in (
            "[Gmail]/Posta inviata",
            "[Gmail]/Sent Mail",
            "[Google Mail]/Posta inviata",
            "[Google Mail]/Sent Mail",
        ):
            if _try_select(client, cand, log_fail=True):
                sent_box = cand
                break
    if sent_box:
        typ, data = client.select(_quote_mailbox(sent_box), readonly=True)
        if typ == "OK":
            msgs = _fetch_from_selected(
                client,
                folder_label="sent",
                limit=limit,
                account_type=account_type,
            )
            log.info(
                "Sync Sent ok user=%s mailbox=%s count=%s",
                user,
                sent_box,
                len(msgs),
            )
            return msgs
        log.warning(
            "SELECT Sent fallito mailbox=%s user=%s typ=%s data=%s",
            sent_box,
            user,
            typ,
            data,
        )
    if is_gmail:
        try:
            gm_sent = fetch_gmail_sent_via_raw(
                client, limit=limit, account_type=account_type
            )
            if gm_sent:
                return gm_sent
        except Exception as exc:
            log.warning("Fallback Gmail X-GM-RAW fallito user=%s: %s", user, exc)
    log.warning(
        "Nessuna mailbox Sent trovata per user=%s type=%s hint=%s host_caps=%s",
        user,
        account_type,
        provider_hint,
        _imap_capabilities(client),
    )
    return []


def fetch_inbox(
    host: str,
    port: int,
    user: str,
    password: str = "",
    *,
    limit: int = 50,
    account_type: str = "imap",
    provider_hint: Optional[str] = None,
    access_token: Optional[str] = None,
    include_sent: bool = True,
    sent_limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Scarica INBOX e (opzionale) cartella Sent/Inviate dal provider."""
    hint = provider_hint or account_type
    client, used_host = connect_mailbox(
        host,
        port,
        user,
        password,
        provider_hint=hint,
        access_token=access_token,
    )
    messages: List[Dict[str, Any]] = []
    is_gmail = (account_type or "").lower() in ("google", "gmail") or (
        hint or ""
    ).lower() in ("google", "gmail")
    try:
        typ, _ = client.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError("Impossibile aprire INBOX")
        messages.extend(
            _fetch_from_selected(
                client, folder_label="INBOX", limit=limit, account_type=account_type
            )
        )
        if include_sent:
            sl = sent_limit if sent_limit is not None else limit
            # Connessione fresca per Sent: dopo fetch INBOX Gmail a volte non SELECT-a [Gmail]/*
            sent_client = None
            try:
                sent_client, sent_host = connect_mailbox(
                    used_host or host,
                    port,
                    user,
                    password,
                    provider_hint=hint,
                    access_token=access_token,
                )
                log.info(
                    "Sent sync conn user=%s host=%s gmail=%s",
                    user,
                    sent_host,
                    is_gmail,
                )
                messages.extend(
                    _fetch_sent_folder(
                        sent_client,
                        user=user,
                        limit=sl,
                        account_type=account_type,
                        provider_hint=hint,
                        is_gmail=is_gmail,
                    )
                )
            except Exception as exc:
                log.warning("Sync Sent (conn dedicata) fallito user=%s: %s", user, exc)
                # ultimo tentativo sulla stessa connessione INBOX
                messages.extend(
                    _fetch_sent_folder(
                        client,
                        user=user,
                        limit=sl,
                        account_type=account_type,
                        provider_hint=hint,
                        is_gmail=is_gmail,
                    )
                )
            finally:
                if sent_client is not None:
                    try:
                        sent_client.logout()
                    except Exception:
                        pass
        return messages
    finally:
        try:
            client.logout()
        except Exception:
            pass

def send_smtp(
    *,
    host: str,
    port: int,
    user: str,
    password: str = "",
    from_addr: str,
    to_addrs: List[str],
    cc_addrs: Optional[List[str]] = None,
    bcc_addrs: Optional[List[str]] = None,
    subject: str,
    body_text: str = "",
    body_html: Optional[str] = None,
    use_ssl: bool = True,
    starttls: bool = False,
    access_token: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cc_addrs = cc_addrs or []
    bcc_addrs = bcc_addrs or []
    attachments = attachments or []
    recipients = list(dict.fromkeys([*to_addrs, *cc_addrs, *bcc_addrs]))
    if not recipients:
        raise ValueError("Nessun destinatario")

    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["From"] = from_addr
    root["To"] = ", ".join(to_addrs)
    if cc_addrs:
        root["Cc"] = ", ".join(cc_addrs)

    if body_html:
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(body_text or "", "plain", "utf-8"))
        alt.attach(MIMEText(body_html, "html", "utf-8"))
        root.attach(alt)
    else:
        root.attach(MIMEText(body_text or "", "plain", "utf-8"))

    for att in attachments:
        filename = (att.get("filename") or "allegato").strip() or "allegato"
        ctype = (att.get("content_type") or "application/octet-stream").strip()
        raw_b64 = att.get("content_base64") or ""
        try:
            raw = b64mod.b64decode(raw_b64, validate=False)
        except Exception as exc:
            raise ValueError(f"Allegato non valido ({filename}): {exc}") from exc
        if "/" in ctype:
            maintype, subtype = ctype.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        part = MIMEBase(maintype, subtype)
        part.set_payload(raw)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        root.attach(part)

    payload = root.as_string()

    ctx = ssl.create_default_context()
    pwd = normalize_mailbox_secret(password)

    def _login(smtp: smtplib.SMTP) -> None:
        if access_token:
            auth_str = f"user={user}\x01auth=Bearer {access_token}\x01\x01"

            def _xoauth2(_challenge=None):
                return auth_str

            smtp.auth("XOAUTH2", _xoauth2, initial_response_ok=True)
        else:
            smtp.login(user, pwd)

    if use_ssl and not starttls:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as smtp:
            _login(smtp)
            smtp.sendmail(from_addr, recipients, payload)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            if starttls or port == 587:
                smtp.starttls(context=ctx)
                smtp.ehlo()
            _login(smtp)
            smtp.sendmail(from_addr, recipients, payload)

    return {
        "ok": True,
        "recipients": recipients,
        "attachments": len(attachments),
    }
