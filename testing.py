from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import base64
import json

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_PATH = "credentials/credentials.json"
TOKEN_PATH = "credentials/token.json"


def get_service():
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ── MIME tree printer ─────────────────────────────────────────────────────────

def print_mime_tree(part, depth=0):
    indent = "  " * depth
    mime = part.get("mimeType", "?")
    has_data = bool(part.get("body", {}).get("data"))
    size = part.get("body", {}).get("size", 0)
    print(f"{indent}├─ {mime} | data={has_data} | size={size}")
    for sub in part.get("parts", []):
        print_mime_tree(sub, depth + 1)


# ── Raw JSON dump ─────────────────────────────────────────────────────────────

def dump_raw(msg, filename="email_dump.json"):
    with open(filename, "w") as f:
        json.dump(msg, f, indent=2)
    print(f"✅ Full raw message dumped to {filename}")


# ── Body extractor ────────────────────────────────────────────────────────────

def extract_body(payload):
    def decode(data):
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    plain = None
    html = None

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


# ── Fetch latest email ────────────────────────────────────────────────────────

def fetch_latest_email(service):
    results = service.users().messages().list(userId="me", maxResults=1).execute()
    messages = results.get("messages", [])

    if not messages:
        return None, None

    msg_id = messages[0]["id"]
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

    headers = msg["payload"]["headers"]
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
    sender  = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
    body    = extract_body(msg["payload"])

    email = {
        "id": msg_id,
        "sender": sender,
        "subject": subject,
        "body": body,
    }

    return email, msg   # return raw msg too for inspection


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    service = get_service()
    email, raw_msg = fetch_latest_email(service)

    if not email:
        print("No emails found.")
    else:
        print("\n📩 LATEST EMAIL")
        print("=" * 50)
        print("From   :", email["sender"])
        print("Subject:", email["subject"])
        print("-" * 50)
        print("Body:")
        print(email["body"])
        print("=" * 50)

        print("\n🌲 MIME TREE")
        print("=" * 50)
        print_mime_tree(raw_msg["payload"])

        print("\n💾 Dumping raw JSON...")
        dump_raw(raw_msg)