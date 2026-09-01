from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import base64

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

CREDS_PATH = "credentials/credentials.json"
TOKEN_PATH = "credentials/token.json"

TOPIC_NAME = "projects/whatsappbookingbot/topics/gmail-notifications"


# -----------------------------
# AUTH + GMAIL SERVICE
# -----------------------------
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


def enable_gmail_watch(service):
    request = {
        "topicName": TOPIC_NAME,
        "labelIds": ["INBOX"]
    }

    response = service.users().watch(
        userId="me",
        body=request
    ).execute()

    print("✅ Gmail Watch Enabled (Pub/Sub Connected)")
    print("History ID:", response.get("historyId"))
    print("Expiration:", response.get("expiration"))

    return response


# -----------------------------
# STEP 2: FETCH EMAIL (USED AFTER PUBSUB NOTIFICATION)
# -----------------------------
def fetch_email_by_id(service, msg_id):
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

    return sender, subject


# -----------------------------
# STEP 3: SIMULATED HANDLER (REAL FLOW WILL COME FROM PUB/SUB)
# -----------------------------
def handle_new_email(service, msg_id):
    sender, subject = fetch_email_by_id(service, msg_id)

    print("\n📩 NEW EMAIL (REAL-TIME EVENT)")
    print("From:", sender)
    print("Subject:", subject)
    print("-" * 50)


# -----------------------------
# MAIN
# -----------------------------
def main():
    service = gmail_service()

    # IMPORTANT STEP
    enable_gmail_watch(service)

    print("\n🚀 System is now LIVE (waiting for Pub/Sub events)")
    print("NOTE: Next step is Pub/Sub listener (Step 4)\n")

    # NO LOOP NEEDED HERE ANYMORE
    # Pub/Sub will trigger your backend instead


if __name__ == "__main__":
    main()