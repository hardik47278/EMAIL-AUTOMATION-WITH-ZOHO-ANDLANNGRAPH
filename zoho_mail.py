import os
import re
import imaplib
import smtplib
import email
import zipfile
import tempfile
import logging

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from dotenv import load_dotenv

from duplicate_check import is_duplicate
from pdf_reader import extract_pdf_text
from docx_reader import extract_docx_text
from ppt_reader import extract_ppt_text
from csv_reader import extract_csv
from html_cleanup import clean_html_email
from subject_normalizer import normalize_subject

load_dotenv()

logger = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────
ZOHO_EMAIL       = os.getenv("ZOHO_EMAIL")
ZOHO_PASSWORD    = os.getenv("ZOHO_APP_PASSWORD")
ZOHO_IMAP_HOST   = os.getenv("ZOHO_IMAP_HOST", "imap.zoho.in")
ZOHO_IMAP_PORT   = 993
ZOHO_SMTP_HOST   = os.getenv("ZOHO_SMTP_HOST", "smtp.zoho.in")
ZOHO_SMTP_PORT   = int(os.getenv("ZOHO_SMTP_PORT", 465))

SUSPICIOUS_EXTENSIONS = {
    ".apk", ".exe", ".msi", ".bat", ".cmd",
    ".ps1", ".vbs", ".jar", ".sh", ".py",
    ".rb", ".pl", ".php", ".scr", ".pif",
    ".com", ".hta", ".wsf"
}


# ── HELPERS ───────────────────────────────────────────────
def decode_str(value):
    """Decode email header string"""
    decoded = decode_header(value)
    result  = ""
    for part, enc in decoded:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="ignore")
        else:
            result += part
    return result


def extract_body(msg):
    """Extract plain text or HTML body from email.message object"""
    plain = None
    html  = None

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp  = str(part.get("Content-Disposition", ""))

            if "attachment" in disp:
                continue

            if ctype == "text/plain" and not plain:
                plain = part.get_payload(decode=True).decode("utf-8", errors="ignore")
            elif ctype == "text/html" and not html:
                html = part.get_payload(decode=True).decode("utf-8", errors="ignore")
    else:
        plain = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

    return plain or html or "⚠️ No readable body found"


def save_attachment(part, filename):
    """Save attachment to temp file, return path"""
    tmpdir = tempfile.mkdtemp()
    path   = os.path.join(tmpdir, filename)
    with open(path, "wb") as f:
        f.write(part.get_payload(decode=True))
    return path


# ── GET SERVICE (returns IMAP connection) ─────────────────
def get_service():
    """Returns IMAP client — drop-in replacement for Gmail get_service()"""
    client = imaplib.IMAP4_SSL(ZOHO_IMAP_HOST, ZOHO_IMAP_PORT)
    client.login(ZOHO_EMAIL, ZOHO_PASSWORD)
    return client


# ── FETCH EMAILS ──────────────────────────────────────────
def fetch_latest_email(service=None):
    """
    Fetch unread emails from Zoho.
    service param kept for compatibility with existing code.
    """
    try:
        client = imaplib.IMAP4_SSL(ZOHO_IMAP_HOST, ZOHO_IMAP_PORT)
        client.login(ZOHO_EMAIL, ZOHO_PASSWORD)
        client.select("INBOX")

        # fetch unread
        _, msg_ids = client.search(None, "UNSEEN")
        id_list    = msg_ids[0].split()

        if not id_list:
            client.logout()
            return None

        emails = []

        for msg_id_bytes in id_list[-10:]:  # last 10 unread
            msg_id = msg_id_bytes.decode()

            # fetch full email
            _, data = client.fetch(msg_id, "(RFC822)")
            raw     = data[0][1]
            msg     = email.message_from_bytes(raw)

            # headers
            subject = normalize_subject(decode_str(msg.get("Subject", "No Subject")))
            sender  = decode_str(msg.get("From", "Unknown"))

            # body
            body = extract_body(msg)
            body = clean_html_email(body)

            # dedup check
            if is_duplicate({
                "gmail_id": msg_id,
                "sender":   sender,
                "subject":  subject,
                "body":     body
            }):
                print(f"⚡ CACHE HIT (duplicate skipped): {msg_id}")
                continue

            # attachments
            pdf_results = []

            if msg.is_multipart():
                for part in msg.walk():
                    filename = part.get_filename()
                    if not filename:
                        continue

                    filename       = decode_str(filename)
                    filename_lower = filename.lower()
                    ext            = os.path.splitext(filename_lower)[1]

                    # suspicious check
                    if ext in SUSPICIOUS_EXTENSIONS:
                        print(f"🚨 Suspicious attachment: {filename}")
                        pdf_results.append({
                            "filename": filename,
                            "text":     f"⚠️ SUSPICIOUS ATTACHMENT: {ext} flagged for review.",
                            "flagged":  True
                        })
                        continue

                    path = save_attachment(part, filename)
                    text = ""

                    # zip handling
                    if filename_lower.endswith(".zip"):
                        zip_flagged = False
                        with zipfile.ZipFile(path, "r") as z:
                            for name in z.namelist():
                                inner_ext = os.path.splitext(name)[1].lower()
                                if inner_ext in SUSPICIOUS_EXTENSIONS:
                                    print(f"🚨 Suspicious inside ZIP: {name}")
                                    pdf_results.append({
                                        "filename": filename,
                                        "text":     f"⚠️ SUSPICIOUS FILE INSIDE ZIP: {name}",
                                        "flagged":  True
                                    })
                                    zip_flagged = True
                                    break
                                elif inner_ext == ".pdf":
                                    with tempfile.TemporaryDirectory() as tmpdir:
                                        z.extract(name, tmpdir)
                                        text += extract_pdf_text(os.path.join(tmpdir, name))
                                elif inner_ext == ".docx":
                                    with tempfile.TemporaryDirectory() as tmpdir:
                                        z.extract(name, tmpdir)
                                        text += extract_docx_text(os.path.join(tmpdir, name))
                                elif inner_ext == ".pptx":
                                    with tempfile.TemporaryDirectory() as tmpdir:
                                        z.extract(name, tmpdir)
                                        text += extract_ppt_text(os.path.join(tmpdir, name))
                                elif inner_ext == ".csv":
                                    with tempfile.TemporaryDirectory() as tmpdir:
                                        z.extract(name, tmpdir)
                                        text += extract_csv(os.path.join(tmpdir, name))
                        if zip_flagged:
                            continue
                        if text:
                            pdf_results.append({"filename": filename, "text": text.strip()})
                        continue

                    elif filename_lower.endswith(".pdf"):
                        text = extract_pdf_text(path)
                    elif filename_lower.endswith(".docx"):
                        text = extract_docx_text(path)
                    elif filename_lower.endswith(".pptx"):
                        text = extract_ppt_text(path)
                    elif filename_lower.endswith(".csv"):
                        text = extract_csv(path)
                    else:
                        continue

                    if text:
                        pdf_results.append({"filename": filename, "text": text})

            # merge attachments into body
            attachment_text = ""
            for att in pdf_results:
                attachment_text += f"\n\n📎 Attachment: {att['filename']}\n{att['text']}"

            emails.append({
                "id":          msg_id,
                "sender":      sender,
                "subject":     subject,
                "body":        body + attachment_text,
                "attachments": pdf_results if pdf_results else None
            })

        client.logout()
        return emails if emails else None

    except Exception as e:
        logger.error(f"❌ Zoho fetch error: {e}")
        return None


# ── SEND EMAIL ────────────────────────────────────────────
def send_email(
    service,          # kept for compatibility, not used
    to:      str,
    subject: str,
    body:    str
) -> dict:
    """Send email via Zoho SMTP — drop-in replacement for Gmail send_email()"""
    try:
        msg                    = MIMEMultipart()
        msg["From"]            = ZOHO_EMAIL
        msg["To"]              = to
        msg["Subject"]         = f"Re: {subject}"
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL(ZOHO_SMTP_HOST, ZOHO_SMTP_PORT) as smtp:
            smtp.login(ZOHO_EMAIL, ZOHO_PASSWORD)
            smtp.sendmail(ZOHO_EMAIL, to, msg.as_string())

        print(f"✅ Email sent to {to} via Zoho")
        return {"status": "sent", "to": to}

    except Exception as e:
        logger.error(f"❌ Zoho send error: {e}")
        raise


# ── TEST ──────────────────────────────────────────────────
if __name__ == "__main__":
    emails = fetch_latest_email()
    if emails:
        for e in emails:
            print("From:", e["sender"])
            print("Subject:", e["subject"])
            print("Body:", e["body"][:200])
    else:
        print("No emails found.")