from supervisor_node import build_spam_graph
from intent_2_version import build_intent_graph
from agent1 import build_priority_graph
from agent4 import build_personalization_graph
from meeting_agent import build_meeting_graph
from langsmith import traceable


spam_graph            = build_spam_graph()
intent_graph          = build_intent_graph()
priority_graph        = build_priority_graph()
personalization_graph = build_personalization_graph()
meeting_graph         = build_meeting_graph()

@traceable(name="run_spam", tags=["run", "spam"], metadata={"version": "1.0"})
def run_spam(email: dict) -> dict:
    return spam_graph.invoke({
        "email":       email,
        "spam_result": {},
        "route":       ""
    })


@traceable(name="run_intent", tags=["run", "intent"], metadata={"version": "2.0"})
def run_intent(email: dict) -> dict:
    return intent_graph.invoke({
        "email":         email,
        "spam_result":   {},
        "intent_result": {},
        "domain_signals": {},
        "log_only": False,
        "requires_hil": True,
        "route":         ""
    })

@traceable(name="run_priority", tags=["run", "priority"], metadata={"version": "1.0"})
def run_priority(email: dict) -> dict:
    return priority_graph.invoke({
        "email":           email,
        "priority_result": {}
    })

@traceable(name="run_personalization", tags=["run", "personalization"], metadata={"version": "1.0"})
def run_personalization(customer_id: str, email: dict) -> dict:
    return personalization_graph.invoke({
        "customer_id":             customer_id,
        "email":                   email,
        "email_count":             0,
        "email_history":           [],
        "customer_summary":        {},
        "sentiment_trend":         [],
        "personalization_context": {}
    })


@traceable(name="run_meeting", tags=["run", "meeting"], metadata={"version": "1.0"})
def run_meeting(email: dict) -> dict:
    return meeting_graph.invoke({
        "gmail_id":       email.get("id", ""),
        "sender":         email.get("sender", ""),
        "subject":        email.get("subject", ""),
        "body":           email.get("body", ""),
        "timestamp":      email.get("timestamp", ""),
        "extracted_date": None,
        "extracted_time": None,
        "intent":         "",
        "mode":           None,
        "confidence":     None,
        "messages":       [],
        "final_response": None,
        "errors":         [],
        "current_node":   "",
        "need_approval":  False,
        "approved":       None
    })