from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command


from prompt_safety import classify_prompt_injection
from reply_generator import reply_generator
from zoho_mail import send_email
from zoho_mail import get_service

class HITLState(TypedDict):
    
    
    email: dict
    merged_context: dict

    reply: dict

    decision: dict | None
    final_reply: str
    human_feedback: str

def reply_generator_node(state: HITLState):

    reply = reply_generator(
        state["merged_context"],
        state["email"],
        state.get("human_feedback", "")
    )

    return {
        "reply": reply,
        "decision":None,
        "human_feedback":""
    }


def guardrials_node(state: HITLState):
    email_text = state["email"].get("body","") + " " + state["email"].get("subject","")
    result = classify_prompt_injection(email_text)
    if result == "INJECTION":
        print("🚨 PROMPT INJECTION DETECTED — blocking email")
        return {"route": "block"}
    
    print("✅ Guardrails passed")
    return {"route":"block"}

    return {"route":"human_review"}


def guardrails_router(state:HITLState):
    return state.get("route","human_review")

def human_review_node(state: HITLState):

    reply_data = state.get("reply") or {}

    decision = interrupt(
        {
            "type": "email_review",

            "email_subject": state["email"]["subject"],
            "sender": state["email"]["sender"],

            "generated_reply": reply_data.get("reply", ""),

            "tone": reply_data.get("tone", ""),
            "length": reply_data.get("length", ""),

            "actions": [
                "approve",
                "edit",
                "regenerate"
            ]
        }
    )

    human_feedback = " "
    if decision.get("action") == "regenrate":
        human_feedback = decision.get("feedback","")


    return {
        "decision": decision,
        "human_feedback":human_feedback
    }




def review_router(state: HITLState):

    action = state["decision"]["action"]

    if action == "approve":
        return "send_email"

    if action == "edit":
        return "send_email"

    if action == "regenerate":
        return "reply_generator"

    return "send_email"


# -------------------------
# Send Email Node
# -------------------------
def send_email_node(state: HITLState):

    service = get_service()

    action = state["decision"]["action"]

    if action == "edit":
        final_reply = state["decision"].get("edited_reply", "")
    else:
        final_reply = state.get("reply", {}).get("reply", "")

        service = get_service()

    send_email(
        service=service,
        to=state["email"]["sender"],
        subject=state["email"]["subject"],
        body=final_reply
    )

    return {
        "final_reply": final_reply
    }


builder = StateGraph(HITLState)

builder.add_node(
    "reply_generator",
    reply_generator_node
)

builder.add_node(
    "human_review",
    human_review_node
)

builder.add_node(
    "send_email",
    send_email_node
)

builder.add_node(
    "guardrails",
    guardrials_node
)



builder.add_edge(
    START,
    "reply_generator"
)

builder.add_edge("reply_generator","guardrails")

builder.add_conditional_edges(
    "guardrails",
    guardrails_router,
    {
        "human_review": "human_review",
        "block": END
    }
)

builder.add_conditional_edges(
    "human_review",
    review_router
)

builder.add_edge(
    "send_email",
    END
)

from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import os
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoints.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)


memory = SqliteSaver(conn)

hitl_graph = builder.compile(
    checkpointer=memory
)

