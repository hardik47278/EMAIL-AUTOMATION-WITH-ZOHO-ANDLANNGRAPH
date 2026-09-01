from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import time

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDS_PATH = "credentials/credentials.json"
TOKEN_PATH = "credentials/token.json"


def gmail_service():
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

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_latest_email(service):
    results = service.users().messages().list(
        userId="me",
        maxResults=1
    ).execute()

    messages = results.get("messages", [])

    if not messages:
        return None

    msg_id = messages[0]["id"]

    message = service.users().messages().get(
        userId="me",
        id=msg_id
    ).execute()

    headers = message["payload"]["headers"]

    subject = "No Subject"
    sender = "Unknown"

    for h in headers:
        if h["name"] == "Subject":
            subject = h["value"]
        elif h["name"] == "From":
            sender = h["value"]

    return msg_id, sender, subject


def watch_inbox(poll_interval=10):
    service = gmail_service()

    last_seen_id = None

    print("🚀 Gmail Watcher Started...\n")

    while True:
        try:
            data = fetch_latest_email(service)

            if data:
                msg_id, sender, subject = data

                # NEW EMAIL DETECTED
                if msg_id != last_seen_id:
                    last_seen_id = msg_id

                    print("\n📩 NEW EMAIL DETECTED")
                    print("From:", sender)
                    print("Subject:", subject)
                    print("-" * 50)

            time.sleep(poll_interval)

        except Exception as e:
            print("Error:", e)
            time.sleep(poll_interval)


if __name__ == "__main__":
    watch_inbox()