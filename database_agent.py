import os
import json
from typing import TypedDict, Optional, List

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

load_dotenv()

from database_tools import (
    tool_fetch_customer_summary,
    tool_fetch_email_history, 
    tool_fetch_email_count,
    tool_fetch_unresolved_issues,
    tool_fetch_sentiment_trend,
    tool_fetch_intent_frequency,
    tool_write_email_record,
    tool_update_customer_summary
)


llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_tokens=1000
)

all_tools = [
    tool_fetch_customer_summary,
    tool_fetch_email_history,
    tool_fetch_email_count,
    tool_fetch_unresolved_issues,
    tool_fetch_sentiment_trend,
    tool_fetch_intent_frequency,
    tool_write_email_record,
    tool_update_customer_summary
]

llm_with_tools = llm.bind_tools(all_tools)


class EmailState(TypedDict):
    customer_id: str
    intent: str
    urgency: str
    sentiment: str
    agent2_priority: str
    agent3_priority: str
    final_priority: str
    customer_summary: dict
    email_history: list
    unresolved: list
    sentiment_trend: list
    intent_frequency: dict
    email_count: int
    mode: str
    messages: List
    debate_round: int
    consensus: bool
    errors: List[str]


READ_SYSTEM_PROMPT = """
You are customer agent fetcher for a company.
Your job is only to fetch customer data from supabase database
using available tools.

Return only json.
"""


WRITE_SYSTEM_PROMPT = """
You are writing agent for a company.
Your only job is to write resolved email data back to supabase.
"""



def llm_route_decision(state: EmailState) -> str:
    prompt = f"""
    ROUTER PLACEHOLDER
    """

    response = llm.invoke(
        [
            SystemMessage(
                content="Return only read_branch or write_branch or END."
            ),
            HumanMessage(content=prompt)
        ]
    )

    decision = response.content.strip()

    if decision in ["read_branch", "write_branch"]:
        return decision

    return END


def read_branch_node(state: EmailState) -> EmailState:
    allowed_tools = [
        "tool_fetch_customer_summary",
        "tool_fetch_email_history",
        "tool_fetch_email_count",
        "tool_fetch_unresolved_issues",
        "tool_fetch_sentiment_trend",
        "tool_fetch_intent_frequency"
    ]

    messages = state["messages"]

    messages.append(
        SystemMessage(content=READ_SYSTEM_PROMPT)
    )

    messages.append(
        HumanMessage(
            content=f"""
Customer ID: {state["customer_id"]}
Intent: {state["intent"]}
Urgency: {state["urgency"]}
Sentiment: {state["sentiment"]}
Agent 2 priority: {state["agent2_priority"]}
"""
        )
    )

    while True:
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if response.tool_calls:
            tool = response.tool_calls[0]

            if tool["name"] not in allowed_tools:
                result = f"Tool {tool['name']} blocked in read mode"

            elif tool["name"] == "tool_fetch_customer_summary":
                result = tool_fetch_customer_summary.invoke(tool["args"])

            elif tool["name"] == "tool_fetch_email_history":
                result = tool_fetch_email_history.invoke(tool["args"])

            elif tool["name"] == "tool_fetch_email_count":
                result = tool_fetch_email_count.invoke(tool["args"])

            elif tool["name"] == "tool_fetch_unresolved_issues":
                result = tool_fetch_unresolved_issues.invoke(tool["args"])

            elif tool["name"] == "tool_fetch_sentiment_trend":
                result = tool_fetch_sentiment_trend.invoke(tool["args"])

            elif tool["name"] == "tool_fetch_intent_frequency":
                result = tool_fetch_intent_frequency.invoke(tool["args"])

            messages.append({
                "role": "tool",
                "content": str(result)
            })

        else:
            try:
                raw = response.content.strip()

                if raw.startswith("```"):
                    raw = raw.split("```")[1]

                    if raw.startswith("json"):
                        raw = raw[4:]

                parsed = json.loads(raw.strip())

            except Exception:
                parsed = {
                    "customer_summary": {},
                    "email_history": [],
                    "unresolved": [],
                    "sentiment_trend": [],
                    "intent_frequency": {},
                    "email_count": 0
                }

            return {
                **state,
                "customer_summary": parsed.get("customer_summary", {}),
                "email_history": parsed.get("email_history", []),
                "unresolved": parsed.get("unresolved", []),
                "sentiment_trend": parsed.get("sentiment_trend", []),
                "intent_frequency": parsed.get("intent_frequency", {}),
                "email_count": parsed.get("email_count", 0),
                "messages": messages,
                "mode": "read_done"
            }



def write_branch_node(state: EmailState) -> EmailState:
    allowed_tools = [
        "tool_write_email_record",
        "tool_update_customer_summary"
    ]

    messages = [
        SystemMessage(content=WRITE_SYSTEM_PROMPT),
        HumanMessage(
            content=f"""
customer_id: {state["customer_id"]}
intent: {state["intent"]}
urgency: {state["urgency"]}
sentiment: {state["sentiment"]}
resolved: True
"""
        )
    ]

    while True:
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if response.tool_calls:
            tool = response.tool_calls[0]

            if tool["name"] not in allowed_tools:
                result = f"Tool {tool['name']} blocked in write mode"

            elif tool["name"] == "tool_write_email_record":
                result = tool_write_email_record.invoke(tool["args"])

            elif tool["name"] == "tool_update_customer_summary":
                result = tool_update_customer_summary.invoke(tool["args"])

            messages.append({
                "role": "tool",
                "content": str(result)
            })

        else:
            return {
                **state,
                "messages": messages,
                "mode": "write_done"
            }



def mode_router(state: EmailState) -> str:
    decision = llm_route_decision(state)

    if decision == "read_branch":
        return "read_branch"

    if decision == "write_branch":
        return "write_branch"

    return END




def build_agent3_graph():
    graph = StateGraph(EmailState)

    graph.add_node("read_branch", read_branch_node)
    graph.add_node("write_branch", write_branch_node)

    graph.set_entry_point("read_branch")

    graph.add_conditional_edges(
        "read_branch",
        mode_router,
        {
            "read_branch": "read_branch",
            "write_branch": "write_branch",
            END: END
        }
    )

    graph.add_edge("write_branch", END)

    return graph.compile()




if __name__ == "__main__":
    app = build_agent3_graph()

    result = app.invoke({
        "customer_id": "CUST_001",
        "intent": "billing_dispute",
        "urgency": "HIGH",
        "sentiment": "frustrated",
        "agent2_priority": "HIGH",
        "agent3_priority": "",
        "final_priority": "",
        "customer_summary": {},
        "email_history": [],
        "unresolved": [],
        "sentiment_trend": [],
        "intent_frequency": {},
        "email_count": 0,
        "mode": "read",
        "messages": [],
        "debate_round": 0,
        "consensus": False,
        "errors": []
    })

    print("\n─── AGENT 3 OUTPUT ───")
    print(f"Summary:   {result['customer_summary']}")
    print(f"Unresolved:{result['unresolved']}")
    print(f"Mode:      {result['mode']}")