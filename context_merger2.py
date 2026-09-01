NO_LOG_ONLY_INTENTS = {
    "otp", "promotion", "newsletter",
    "order_update", "payment_receipt",
    "subscription", "system_alert",
    "social_notification", "job_alert"
}
from langsmith import traceable

@traceable(name="context_merger", tags=["context", "merger"], metadata={"version": "1.0"})
def context_merger(
    priority_result:        dict,
    personalization_result: dict,
    meeting_result:         dict | None,
    intent_result:          dict          # ← add this param
) -> dict:

    priority    = priority_result.get("priority_result", {})
    personality = personalization_result.get("personalization_context", {})
    comm        = personality.get("communication_personality", {})

    meeting_booked = False
    meeting_date   = None
    meeting_time   = None

    if meeting_result:
        meeting_booked = meeting_result.get("approved", False)
        meeting_date   = meeting_result.get("extracted_date", None)
        meeting_time   = meeting_result.get("extracted_time", None)

    primary_intent = intent_result.get("primary_intent", "")

    # ── conditional logic ─────────────────────────────
    log_only     = primary_intent in NO_LOG_ONLY_INTENTS
    requires_hil = not log_only

    return {
        # existing fields unchanged
        "priority":        priority.get("priority", "MEDIUM"),
        "priority_reason": priority.get("reason", ""),
        "user_role":       personality.get("user_role", "unknown"),
        "tone":            comm.get("tone", "formal"),
        "verbosity":       comm.get("verbosity", "medium"),
        "technical_level": comm.get("technical_level", "non-technical"),
        "is_first_time":   personality.get("is_first_time_user", False),
        "domain_context":  personality.get("domain_context", "unknown"),
        "meeting_booked":  meeting_booked,
        "meeting_date":    meeting_date,
        "meeting_time":    meeting_time,

        # new fields
        "primary_intent":  primary_intent,
        "log_only":        log_only,        # True → store in log + dashboard
        "requires_hil":    requires_hil     # False → skip HIL box
    }