from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import base64
import zipfile
import tempfile

from duplicate_check import is_duplicate
from download_attachment import save_attachment
from pdf_reader import extract_pdf_text
from docx_reader import extract_docx_text
from ppt_reader import extract_ppt_text
from csv_reader import extract_csv
from html_cleanup import clean_html_email
from subject_normalizer import normalize_subject
from spam_detection import detect_spam


SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send"
]

CREDS_PATH = "credentials/credentials.json"
TOKEN_PATH  = "credentials/token.json"

SUSPICIOUS_EXTENSIONS = {
    ".apk", ".exe", ".msi", ".bat", ".cmd",
    ".ps1", ".vbs", ".jar", ".sh", ".py",
    ".rb", ".pl", ".php", ".scr", ".pif",
    ".com", ".hta", ".wsf"
}


def get_service():
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDS_PATH,
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def extract_body(payload):

    def decode(data):
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    plain = None
    html  = None

    def walk(part):
        nonlocal plain, html

        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")

        if mime == "text/plain" and data and not plain:
            plain = decode(data)

        elif mime == "text/html" and data and not html:
            html = decode(data)

        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)

    return plain or html or "⚠️ No readable body found"


# -----------------------------
# FETCH EMAIL + ATTACHMENTS
# -----------------------------
from datetime import datetime

today = datetime.now().strftime("%Y/%m/%d")


def fetch_latest_email(service):

    results = service.users().messages().list(
        userId="me",
        maxResults=10,
        q="is:unread"
    ).execute()

    messages = results.get("messages", [])

    if not messages:
        return None

    emails = []

    for msg in messages:
        msg_id = msg["id"]

        # -----------------------------
        # GET FULL EMAIL FIRST
        # -----------------------------
        msg_data = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full"
        ).execute()

        headers = msg_data["payload"]["headers"]

        subject = "No Subject"
        sender  = "Unknown"

        for h in headers:
            if h["name"] == "Subject":
                subject = normalize_subject(h["value"])
            elif h["name"] == "From":
                sender = h["value"]

        # -----------------------------
        # BODY CLEANING
        # -----------------------------
        body = extract_body(msg_data["payload"])
        body = clean_html_email(body)

        # -----------------------------
        # ✅ PROPER DEDUP CHECK
        # -----------------------------
        if is_duplicate({
            "gmail_id": msg_id,
            "sender":   sender,
            "subject":  subject,
            "body":     body
        }):
            print(f"⚡ CACHE HIT (duplicate skipped): {msg_id}")
            continue

        # -----------------------------
        # ATTACHMENTS
        # -----------------------------
        payload     = msg_data["payload"]
        pdf_results = []

        for part in payload.get("parts", []):

            filename      = part.get("filename", "")
            body_data     = part.get("body", {})
            attachment_id = body_data.get("attachmentId")

            if not filename or not attachment_id:
                continue

            filename_lower = filename.lower()
            ext            = os.path.splitext(filename_lower)[1]

            # -----------------------------
            # ✅ SUSPICIOUS EXTENSION CHECK
            # -----------------------------
            if ext in SUSPICIOUS_EXTENSIONS:
                print(f"🚨 Suspicious attachment detected: {filename}")
                pdf_results.append({
                    "filename": filename,
                    "text":     f"⚠️ SUSPICIOUS ATTACHMENT: {ext} file detected. Flagged for human review.",
                    "flagged":  True
                })
                continue

            path = save_attachment(
                service,
                msg_id,
                attachment_id,
                filename
            )

            text = ""

            # -----------------------------
            # ✅ ZIP HANDLING
            # -----------------------------
            if filename_lower.endswith(".zip"):
                zip_flagged = False

                with zipfile.ZipFile(path, 'r') as z:
                    for name in z.namelist():
                        inner_ext = os.path.splitext(name)[1].lower()

                        # suspicious file inside zip
                        if inner_ext in SUSPICIOUS_EXTENSIONS:
                            print(f"🚨 Suspicious file inside ZIP: {name}")
                            pdf_results.append({
                                "filename": filename,
                                "text":     f"⚠️ SUSPICIOUS FILE INSIDE ZIP: {name} ({inner_ext}) — flagged for human review.",
                                "flagged":  True
                            })
                            zip_flagged = True
                            break

                        # extract PDF inside zip
                        elif inner_ext == ".pdf":
                            with tempfile.TemporaryDirectory() as tmpdir:
                                z.extract(name, tmpdir)
                                inner_path = os.path.join(tmpdir, name)
                                inner_text = extract_pdf_text(inner_path)
                                if inner_text:
                                    text += f"\n[{name}]\n{inner_text}"

                        # extract DOCX inside zip
                        elif inner_ext == ".docx":
                            with tempfile.TemporaryDirectory() as tmpdir:
                                z.extract(name, tmpdir)
                                inner_path = os.path.join(tmpdir, name)
                                inner_text = extract_docx_text(inner_path)
                                if inner_text:
                                    text += f"\n[{name}]\n{inner_text}"

                        # extract PPTX inside zip
                        elif inner_ext == ".pptx":
                            with tempfile.TemporaryDirectory() as tmpdir:
                                z.extract(name, tmpdir)
                                inner_path = os.path.join(tmpdir, name)
                                inner_text = extract_ppt_text(inner_path)
                                if inner_text:
                                    text += f"\n[{name}]\n{inner_text}"

                        # extract CSV inside zip
                        elif inner_ext == ".csv":
                            with tempfile.TemporaryDirectory() as tmpdir:
                                z.extract(name, tmpdir)
                                inner_path = os.path.join(tmpdir, name)
                                inner_text = extract_csv(inner_path)
                                if inner_text:
                                    text += f"\n[{name}]\n{inner_text}"

                if zip_flagged:
                    continue  # flagged entry already added

                if text:
                    pdf_results.append({
                        "filename": filename,
                        "text":     text.strip()
                    })

                continue  # done with zip

            # -----------------------------
            # NORMAL FILES
            # -----------------------------
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

            pdf_results.append({
                "filename": filename,
                "text":     text
            })

        # -----------------------------
        # ✅ MERGE ATTACHMENTS INTO BODY
        # -----------------------------
        attachment_text = ""
        if pdf_results:
            for att in pdf_results:
                attachment_text += f"\n\n📎 Attachment: {att['filename']}\n{att['text']}"

        emails.append({
            "id":          msg_id,
            "sender":      sender,
            "subject":     subject,
            "body":        body + attachment_text,
            "attachments": pdf_results if pdf_results else None
        })

    return emails


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":

    service = get_service()
    emails  = fetch_latest_email(service)

    if emails:
        for email in emails:
            spam_result = detect_spam(email, api_key="key-hardik-001")
            print("\n📩 EMAIL")
            print("=" * 50)
            print("From   :", email["sender"])
            print("Subject:", email["subject"])
            print("\nBody:\n", email["body"])
            print("\n📎 ATTACHMENTS:\n", email["attachments"])
            print("\n🚨 SPAM CHECK")
            print("=" * 50)
            print("TF-IDF Keywords :", spam_result["tfidf_keywords"])
            print("LLM Label       :", spam_result["llm_result"]["label"])
            print("Reason          :", spam_result["llm_result"]["reason"])
    else:
        print("No emails found.")