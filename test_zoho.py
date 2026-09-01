# test_zoho.py
from imapclient import IMAPClient
import os
from dotenv import load_dotenv
load_dotenv()

with IMAPClient("imap.zoho.in", ssl=True) as client:
    client.login(
        os.getenv("ZOHO_EMAIL"),
        os.getenv("ZOHO_APP_PASSWORD")
    )
    client.select_folder("INBOX")
    print("✅ Zoho IMAP connected!")
    unseen = client.search(["UNSEEN"])
    print(f"Unread emails: {len(unseen)}")