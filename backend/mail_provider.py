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
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
import base64 as b64mod
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
                text_body = re.sub(r"<[^>]+>", " ", decoded)
            else:
                text_body = decoded
        except Exception:
            text_body = str(msg.get_payload() or "")
    return text_body.strip(), html_body


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
    "[Google Mail]/Sent Mail",
    "Sent",
    "Sent Items",
    "Sent Messages",
    "INBOX.Sent",
    "INBOX/Sent",
    "Posta inviata",
    "Elementi inviati",
)


def _decode_mailbox_name(raw) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, tuple) and len(raw) >= 3:
        name = raw[2]
        if isinstance(name, bytes):
            return name.decode("utf-8", errors="replace")
        return str(name)
    line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    m = re.search(r'"([^"]+)"\s*$', line)
    if m:
        return m.group(1)
    parts = line.split()
    return parts[-1].strip('"') if parts else None


def list_mailbox_names(client: imaplib.IMAP4) -> List[str]:
    names: List[str] = []
    try:
        typ, data = client.list()
    except Exception as exc:
        log.warning("IMAP LIST fallito: %s", exc)
        return names
    if typ != "OK" or not data:
        return names
    for row in data:
        name = _decode_mailbox_name(row)
        if name:
            names.append(name)
    return names


def resolve_sent_mailbox(client: imaplib.IMAP4) -> Optional[str]:
    boxes = list_mailbox_names(client)
    if not boxes:
        for cand in _SENT_CANDIDATES:
            typ, _ = client.select(cand, readonly=True)
            if typ == "OK":
                return cand
        return None
    lower_map = {b.lower(): b for b in boxes}
    for cand in _SENT_CANDIDATES:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    for b in boxes:
        bl = b.lower()
        if "sent mail" in bl or bl.endswith("/sent") or bl.endswith(".sent"):
            return b
        if bl in ("sent", "sent items", "posta inviata", "elementi inviati"):
            return b
        if "sent" in bl and "spam" not in bl and "trash" not in bl and "bin" not in bl:
            return b
    return None


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
        typ, msg_data = client.fetch(num, "(RFC822 FLAGS UID)")
        if typ != "OK" or not msg_data:
            continue
        raw = None
        flags_raw = b""
        uid = num.decode() if isinstance(num, bytes) else str(num)
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                meta = item[0] if isinstance(item[0], (bytes, bytearray)) else b""
                raw = item[1]
                flags_raw = meta
                m_uid = re.search(rb"UID\s+(\d+)", meta)
                if m_uid:
                    uid = m_uid.group(1).decode()
        if not raw:
            continue
        msg = email.message_from_bytes(raw)
        text_body, html_body = _extract_body(msg)
        seen = b"\\Seen" in flags_raw
        flagged = b"\\Flagged" in flags_raw
        message_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                disp = str(part.get("Content-Disposition") or "")
                if "attachment" in disp.lower() or part.get_filename():
                    attachments.append(
                        {
                            "filename": _decode_header(part.get_filename()) or "file",
                            "content_type": part.get_content_type(),
                        }
                    )
        messages.append(
            {
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
                "is_pec": _looks_like_pec(msg, account_type),
                "snippet": (text_body or "")[:180],
                "body_text": text_body,
                "body_html": html_body,
                "folder": folder_label,
            }
        )
    return messages


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
    client, _used = connect_mailbox(
        host,
        port,
        user,
        password,
        provider_hint=provider_hint or account_type,
        access_token=access_token,
    )
    messages: List[Dict[str, Any]] = []
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
            sent_box = resolve_sent_mailbox(client)
            if sent_box:
                typ, _ = client.select(sent_box, readonly=True)
                if typ == "OK":
                    messages.extend(
                        _fetch_from_selected(
                            client,
                            folder_label="sent",
                            limit=sent_limit if sent_limit is not None else limit,
                            account_type=account_type,
                        )
                    )
                    log.info("Sync Sent mailbox=%s count_limit=%s", sent_box, sent_limit or limit)
                else:
                    log.info("SELECT Sent fallito mailbox=%s", sent_box)
            else:
                log.info("Nessuna mailbox Sent trovata per %s", user)
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
