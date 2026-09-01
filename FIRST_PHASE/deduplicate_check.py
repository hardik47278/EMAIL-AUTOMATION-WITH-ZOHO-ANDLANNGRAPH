import hashlib
from redis_client import r


# -----------------------------
# Create a stable email fingerprint
# -----------------------------
def create_email_fingerprint(email: dict) -> str:
    """
    Creates a unique hash for an email using:
    sender + subject + body
    """

    raw = (
        email.get("sender", "").strip().lower()
        + email.get("subject", "").strip().lower()
        + email.get("body", "").strip().lower()
    )

    return hashlib.sha256(raw.encode()).hexdigest()


# -----------------------------
# Check if email is duplicate
# -----------------------------
def is_duplicate(email: dict) -> bool:
    """
    Returns True if email already processed
    """

    email_id = email.get("id")
    fingerprint = create_email_fingerprint(email)

    # Redis keys
    id_key = f"EMAIL:ID:{email_id}"
    fp_key = f"EMAIL:FP:{fingerprint}"

    # 1. Check by Gmail message ID
    if r.exists(id_key):
        return True

    # 2. Check by content fingerprint
    if r.exists(fp_key):
        return True

    return False


# -----------------------------
# Mark email as processed
# -----------------------------
def mark_as_processed(email: dict, ttl_days: int = 7):
    """
    Store email in Redis so future duplicates are detected
    """

    email_id = email.get("id")
    fingerprint = create_email_fingerprint(email)

    id_key = f"EMAIL:ID:{email_id}"
    fp_key = f"EMAIL:FP:{fingerprint}"

    ttl_seconds = ttl_days * 24 * 3600

    # Store both keys
    r.setex(id_key, ttl_seconds, "1")
    r.setex(fp_key, ttl_seconds, "1")


# -----------------------------
# Combined helper
# -----------------------------
def check_and_store(email: dict) -> bool:
    """
    Returns:
        True  -> duplicate (ignore)
        False -> new email (process + store)
    """

    if is_duplicate(email):
        return True

    mark_as_processed(email)
    return False