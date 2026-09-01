from langchain_core.tools import tool
from supabase_integration import (
    fetch_email_history,
    fetch_email_count,
    fetch_unresolved_issues,
    fetch_customer_summary,
    fetch_sentiment_trend,
    fetch_intent_frequency,
    write_email_record,
    update_customer_summary
)



@tool
def tool_fetch_customer_summary(customer_id: str) -> dict:
    """
    Fetches pre-calculated summary for a customer.
    Always call this FIRST before any other tool.
    Returns churn_risk, health_status, total_emails,
    unresolved_count, sentiment_trend.
    """
    return fetch_customer_summary(customer_id)


@tool
def tool_fetch_email_history(customer_id: str) -> list:
    """
    Fetches full email history for a customer.
    Call this when churn_risk is TRUE or
    when you need detailed past interactions.
    """
    return fetch_email_history(customer_id)


@tool
def tool_fetch_email_count(customer_id: str) -> int:
    """
    Returns total number of emails from this customer.
    Call this to understand how frequently
    this customer contacts support.
    """
    return fetch_email_count(customer_id)


@tool
def tool_fetch_unresolved_issues(customer_id: str) -> list:
    """
    Returns all unresolved emails for this customer.
    Call this when unresolved_count > 0 in summary.
    Critical for priority debate with Agent 2.
    """
    return fetch_unresolved_issues(customer_id)


@tool
def tool_fetch_sentiment_trend(customer_id: str) -> list:
    """
    Returns sentiment over time for this customer.
    Call this when sentiment_trend is declining
    to understand how fast anger is increasing.
    """
    return fetch_sentiment_trend(customer_id)


@tool
def tool_fetch_intent_frequency(customer_id: str) -> dict:
    """
    Returns frequency of each intent for this customer.
    Call this to identify recurring complaint patterns.
    Use this as evidence in priority debate.
    """
    return fetch_intent_frequency(customer_id)


@tool
def tool_write_email_record(
    customer_id: str,
    intent: str,
    urgency: str,
    sentiment: str,
    agent2_priority: str,
    agent3_priority: str,
    final_priority: str,
    resolved: bool = False,
    resolution: str = None,
    resolution_time_mins: int = None
) -> dict:
    """
    Writes new email record to Supabase
    after email is resolved.
    ONLY call this after final priority
    is decided and email is sent.
    """
    return write_email_record(
        customer_id=customer_id,
        intent=intent,
        urgency=urgency,
        sentiment=sentiment,
        agent2_priority=agent2_priority,
        agent3_priority=agent3_priority,
        final_priority=final_priority,
        resolved=resolved,
        resolution=resolution,
        resolution_time_mins=resolution_time_mins
    )


@tool
def tool_update_customer_summary(customer_id: str) -> dict:
    """
    Recalculates and updates customer summary
    after email record is written.
    ALWAYS call this after tool_write_email_record.
    Never call before writing email record.
    """
    return update_customer_summary(customer_id)



READ_TOOLS = [
    tool_fetch_customer_summary,
    tool_fetch_email_history,
    tool_fetch_email_count,
    tool_fetch_unresolved_issues,
    tool_fetch_sentiment_trend,
    tool_fetch_intent_frequency
]

WRITE_TOOLS = [
    tool_write_email_record,
    tool_update_customer_summary
]