from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
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
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDS_PATH,
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def debug_latest_email(service):
    results = service.users().messages().list(
        userId="me",
        maxResults=1
    ).execute()

    msg_id = results["messages"][0]["id"]

    msg = service.users().messages().get(
        userId="me",
        id=msg_id,
        format="full"
    ).execute()

    print("\n================ RAW PAYLOAD ================\n")
    print(json.dumps(msg["payload"], indent=2))

    print("\n================ SNIPPET ================\n")
    print(msg.get("snippet"))


def main():
    service = get_service()
    debug_latest_email(service)


if __name__ == "__main__":
    main()