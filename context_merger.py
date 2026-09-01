def context_merger(
    priority_result:        dict,
    personalization_result: dict,
    meeting_result:         dict | None
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

    return {
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
        "meeting_time":    meeting_time
    }