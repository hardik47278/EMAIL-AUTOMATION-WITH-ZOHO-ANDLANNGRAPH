import redis
import hashlib
from datetime import datetime

r = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_fingerprint(email: dict) -> str:
    """
    fallback fingerprint if message_id missing
    """
    raw = (
        email.get("sender", "") +
        email.get("subject", "") +
        email.get("body", "")
    )
    return sha256(raw)


def is_duplicate(email: dict) -> bool:

    message_id = email.get("message_id")
    gmail_id = email.get("gmail_id")

    if message_id:
        key = f"email:msgid:{message_id}"
        if r.exists(key):
            return True
        r.setex(key, 86400 * 7, 1)  # 7 days TTL

    # 2. Gmail ID check
    if gmail_id:
        key = f"email:gmail:{gmail_id}"
        if r.exists(key):
            return True
        r.setex(key, 86400 * 7, 1)

  
    fp = build_fingerprint(email)
    key = f"email:fp:{fp}"

    if r.exists(key):
        return True

    r.setex(key, 86400 * 3, 1) 

    return False