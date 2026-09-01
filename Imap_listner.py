import time
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from imapclient import IMAPClient
from tasks import fetch_and_process

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAP_HOST    = "imap.gmail.com"
EMAIL        = "hard230104027@iiitmanipur.ac.in"
IDLE_TIMEOUT = 30       # check every 30 seconds
IDLE_REFRESH = 1200     # refresh every 20 minutes
TOKEN_PATH   = "credentials/token.json"


def get_token():
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)

    if not creds.valid:
        if creds.refresh_token:
            logger.info("🔑 Refreshing OAuth token...")
            creds.refresh(Request())
            # Save refreshed token back to disk
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            logger.info("✅ Token refreshed and saved")
        else:
            raise RuntimeError(
                "❌ No refresh token available — re-run OAuth flow to generate a new token.json"
            )

    return creds.token


def listen():
    while True:
        try:
            token = get_token()

            with IMAPClient(IMAP_HOST, ssl=True) as client:
                client.oauth2_login(EMAIL, token)
                client.select_folder("INBOX")

                logger.info("✅ IMAP LOGIN SUCCESS")
                logger.info("👂 Entering IDLE mode...")

                client.idle()
                start_time = time.time()

                while True:
                    responses = client.idle_check(timeout=IDLE_TIMEOUT)

                    # Refresh IDLE every 20 mins
                    if time.time() - start_time > IDLE_REFRESH:
                        client.idle_done()
                        client.idle()
                        start_time = time.time()
                        logger.info("♻️ IDLE connection refreshed")
                        continue

                    if responses:
                        client.idle_done()

                        # Check for unseen emails
                        unseen = client.search(["UNSEEN"])

                        if unseen:
                            logger.info(f"📩 {len(unseen)} new email(s) detected!")
                            fetch_and_process.delay()
                            logger.info("🚀 Task sent to Celery worker")
                        else:
                            logger.info("⚡ Flag change only — no new emails")

                        client.idle()
                        start_time = time.time()

                    else:
                        logger.info("⏱ Waiting for new emails...")

        except RuntimeError as e:
            # No refresh token — pointless to retry
            logger.error(e)
            break

        except Exception as e:
            error_msg = str(e)
            if "AUTHENTICATIONFAILED" in error_msg:
                logger.error("❌ Auth failed — will retry with refreshed token")
            else:
                logger.error(f"❌ IMAP error: {e}")
            logger.info("🔄 Reconnecting in 10 seconds...")
            time.sleep(10)


if __name__ == "__main__":
    listen()