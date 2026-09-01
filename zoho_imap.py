import time
import logging
import os
from dotenv import load_dotenv
from imapclient import IMAPClient
from tasks import fetch_and_process

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAP_HOST    = os.getenv("ZOHO_IMAP_HOST", "imap.zoho.in")
EMAIL        = os.getenv("ZOHO_EMAIL")
PASSWORD     = os.getenv("ZOHO_APP_PASSWORD")
IDLE_TIMEOUT = 30
IDLE_REFRESH = 1200


def listen():
    while True:
        try:
            with IMAPClient(IMAP_HOST, ssl=True) as client:
                client.login(EMAIL, PASSWORD)
                client.select_folder("INBOX")

                logger.info("✅ Zoho IMAP LOGIN SUCCESS")
                logger.info("👂 Entering IDLE mode...")

                client.idle()
                start_time = time.time()

                while True:
                    responses = client.idle_check(timeout=IDLE_TIMEOUT)

                    if time.time() - start_time > IDLE_REFRESH:
                        client.idle_done()
                        client.idle()
                        start_time = time.time()
                        logger.info("♻️ IDLE connection refreshed")
                        continue

                    if responses:
                        client.idle_done()
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

        except Exception as e:
            logger.error(f"❌ Zoho IMAP error: {e}")
            logger.info("🔄 Reconnecting in 10 seconds...")
            time.sleep(10)


if __name__ == "__main__":
    listen()