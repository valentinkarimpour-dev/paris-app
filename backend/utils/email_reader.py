"""
Utilitaire IMAP — connexion Gmail + lecture des emails non traités.
"""

import email
import imaplib
import logging
import os
from email.header import decode_header
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_env():
    # Cherche .env en remontant depuis ce fichier jusqu'à 4 niveaux
    current = Path(__file__).parent
    for _ in range(4):
        candidate = current / ".env"
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return
        current = current.parent


def get_imap_client() -> imaplib.IMAP4_SSL | None:
    _load_env()
    addr = os.environ.get("NEWSLETTER_EMAIL")
    pwd  = os.environ.get("NEWSLETTER_IMAP_PASSWORD")
    if not addr or not pwd:
        logger.warning("[email_reader] NEWSLETTER_EMAIL ou NEWSLETTER_IMAP_PASSWORD manquant")
        return None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(addr, pwd)
        return mail
    except Exception as e:
        logger.error("[email_reader] Connexion IMAP échouée : %s", e)
        return None


def decode_header_value(raw: str) -> str:
    parts = []
    for chunk, enc in decode_header(raw):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def get_email_body(msg) -> tuple[str, str]:
    """Retourne (html, texte_brut) du premier part trouvé."""
    html, text = "", ""
    for part in msg.walk():
        ct = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        decoded = payload.decode("utf-8", errors="replace")
        if ct == "text/html" and not html:
            html = decoded
        elif ct == "text/plain" and not text:
            text = decoded
    return html, text


def fetch_emails(sender_domain: str, max_count: int = 50) -> list[dict]:
    """
    Récupère jusqu'à max_count emails d'un expéditeur donné (filtré par domaine).
    Retourne une liste de dicts {message_id, subject, sender, date, html, text}.
    """
    mail = get_imap_client()
    if not mail:
        return []

    mail.select("INBOX")
    _, msgs = mail.search(None, "ALL")
    ids = msgs[0].split()

    results = []
    for mid in reversed(ids):
        if len(results) >= max_count:
            break
        try:
            _, data = mail.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            sender = msg.get("From", "")
            if sender_domain not in sender:
                continue

            html, text = get_email_body(msg)
            results.append({
                "message_id": msg.get("Message-ID", str(mid)),
                "subject":    decode_header_value(msg.get("Subject", "")),
                "sender":     sender,
                "date":       msg.get("Date", ""),
                "html":       html,
                "text":       text,
            })
        except Exception as e:
            logger.warning("[email_reader] Erreur lecture email %s : %s", mid, e)

    mail.logout()
    logger.info("[email_reader] %d emails récupérés pour %s", len(results), sender_domain)
    return results
