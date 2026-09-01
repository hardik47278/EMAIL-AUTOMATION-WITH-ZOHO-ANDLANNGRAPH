from typing import TypedDict, Optional, List
import json
import time
import logging

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage,ToolMessage

from meeting_tool import (
    check_slot_tool,
    list_events_tool,
    create_event_tool,
    extract_date_tool,
)

logger = logging.getLogger(__name__)


llm_primary   = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
llm_fallback1 = ChatGroq(model="llama-3.1-8b-instant",    temperature=0)
llm_fallback2 = ChatGroq(model="openai/gpt-oss-20b",      temperature=0)

calendar_tools = [
    check_slot_tool,
    list_events_tool,
    create_event_tool,
    extract_date_tool,
]

llm_tools_primary   = llm_primary.bind_tools(calendar_tools)
llm_tools_fallback1 = llm_fallback1.bind_tools(calendar_tools)
llm_tools_fallback2 = llm_fallback2.bind_tools(calendar_tools)


# -------------------------
# BACKOFF HELPER
# -------------------------
def invoke_with_backoff(llm, messages_or_prompt, model_name, retries=3, base_delay=2):
    for attempt in range(retries):
        try:
            return llm.invoke(messages_or_prompt)
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                wait = base_delay ** (attempt + 1)
                logger.warning(f"[{model_name}] Rate limit. Retrying in {wait}s... ({attempt+1}/{retries})")
                time.sleep(wait)
            else:
                raise
    return None


def invoke_llm(messages_or_prompt):
    result = invoke_with_backoff(llm_primary, messages_or_prompt, "llama-3.3-70b-versatile")
    if result:
        return result
    logger.warning("⚠️ Meeting LLM: trying fallback1 llama-3.1-8b-instant")
    result = invoke_with_backoff(llm_fallback1, messages_or_prompt, "llama-3.1-8b-instant")
    if result:
        return result
    logger.warning("⚠️ Meeting LLM: trying fallback2 openai/gpt-oss-20b")
    result = invoke_with_backoff(llm_fallback2, messages_or_prompt, "openai/gpt-oss-20b")
    if result:
        return result
    raise RuntimeError("❌ Meeting agent: all models failed.")


def invoke_llm_tools(messages):
    for llm_tools, name in [
        (llm_tools_primary,   "llama-3.3-70b-versatile"),
        (llm_tools_fallback1, "llama-3.1-8b-instant"),
        (llm_tools_fallback2, "openai/gpt-oss-20b"),
    ]:
        result = invoke_with_backoff(llm_tools, messages, name)
        if result:
            return result
    raise RuntimeError("❌ Meeting agent tools: all models failed.")


# -------------------------
# SAFE JSON PARSER
# -------------------------
def safe_json_parse(text: str):
    try:
        return json.loads(text)
    except Exception:
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return {"intent": "other", "mode": "other", "confidence": 0.0}


# -------------------------
# STATE
# -------------------------
class AgentState(TypedDict):
    gmail_id: str
    sender: str
    subject: str
    body: str
    timestamp: str
    extracted_date: Optional[str]
    extracted_time: Optional[str]
    intent: str
    mode: str
    confidence: Optional[float]
    messages: List
    final_response: Optional[str]
    errors: List[str]
    current_node: str
    need_approval: bool
    approved: Optional[bool]


# -------------------------
# ROUTER NODE
# -------------------------
def email_router_node(state):
    prompt = f"""
Email:
Subject: {state["subject"]}
Body: {state["body"]}

Classify into:
1. read_only
2. booking
3. modify
4. other

Output JSON only:
{{
    "intent":"...",
    "mode":"...",
    "confidence":0.8
}}
"""
    result = invoke_llm(prompt)
    parsed = safe_json_parse(result.content.strip())
    valid_modes = {"read_only","booking","modify","other"}
    mode = parsed.get("mode", "other")
    if mode not in valid_modes:
        mode = "other"


    state["intent"]     = parsed.get("intent","other")
    state["mode"]       = mode
    state["confidence"] = parsed.get("confidence", 0.0)

    return state


# -------------------------
# READ ONLY NODE
# -------------------------
def read_only_calendar_node(state):
    messages = state.get("messages", [])
    allowed_tools = ["list_events_tool", "check_slot_tool"]

    if not messages:
        messages = [HumanMessage(content="Handle calendar read-only request")]

    while True:
        response = invoke_llm_tools(messages)
        messages.append(response)

        if response.tool_calls:
            tool = response.tool_calls[0]
            if tool["name"] not in allowed_tools:
                result = "Tool not allowed in read_only mode"
            elif tool["name"] == "list_events_tool":
                result = list_events_tool.invoke(tool["args"])
            elif tool["name"] == "check_slot_tool":
                result = check_slot_tool.invoke(tool["args"])
                messages.append(ToolMessage(content=str(result), tool_call_id=tool["id"]))
            
        else:
            state["final_response"] = response.content
            break

    state["messages"] = messages
    return state


# -------------------------
# BOOKING NODE
# -------------------------
def booking_react_node(state):
    messages = state.get("messages", [])
    allowed_tools = ["list_events_tool", "check_slot_tool", "extract_date_tool"]

    if not messages:
        messages = [HumanMessage(content="Handle booking request")]

    while True:
        response = invoke_llm_tools(messages)
        messages.append(response)

        if response.tool_calls:
            tool = response.tool_calls[0]
            if tool["name"] not in allowed_tools:
                result = "Tool not allowed in booking mode"
            elif tool["name"] == "list_events_tool":
                result = list_events_tool.invoke(tool["args"])
            elif tool["name"] == "check_slot_tool":
                result = check_slot_tool.invoke(tool["args"])
            elif tool["name"] == "extract_date_tool":
                result = extract_date_tool.invoke(tool["args"])
            messages.append(ToolMessage(content=str(result), tool_call_id=tool["id"]))
        else:
            state["final_response"] = response.content
            state["need_approval"]  = True
            break

    state["messages"] = messages
    return state


def modify_event_node(state):
    messages = state.get("messages", [])

    if not messages:
        messages = [HumanMessage(content="Handle modify event request")]

    while True:
        response = invoke_llm_tools(messages)
        messages.append(response)

        if response.tool_calls:
            tool = response.tool_calls[0]
            if tool["name"] == "list_events_tool":
                result = list_events_tool.invoke(tool["args"])
            elif tool["name"] == "check_slot_tool":
                result = check_slot_tool.invoke(tool["args"])
            elif tool["name"] == "create_event_tool":
                result = create_event_tool.invoke(tool["args"])
            elif tool["name"] == "extract_date_tool":
                result = extract_date_tool.invoke(tool["args"])
            else:
                result = "Tool not allowed"
            messages.append(ToolMessage(content=str(result), tool_call_id=tool["id"]))
        else:
            state["final_response"] = response.content
            state["need_approval"]  = True
            break

    state["messages"] = messages
    return state


# -------------------------
# OTHER NODE
# -------------------------
def other_event_node(state):
    state["final_response"] = "Sorry, I could not classify this request."
    return state


# -------------------------
# APPROVAL NODE
# -------------------------
def human_approval_node(state):
    if not state["need_approval"]:
        return state

    print(state["final_response"])
    decision = input("Approve this action? (yes/no): ").strip().lower()

    if decision == "yes":
        state["approved"]      = True
        state["need_approval"] = False
    else:
        state["approved"]      = False
        state["final_response"] = "Action cancelled"

    return state


# -------------------------
# ROUTING
# -------------------------
def route_next(state):
    return state["mode"]

def route_after_approval(state):
    return "done" if state["approved"] else "cancelled"


# -------------------------
# GRAPH
# -------------------------
workflow = StateGraph(AgentState)

workflow.add_node("router",    email_router_node)
workflow.add_node("read_only", read_only_calendar_node)
workflow.add_node("booking",   booking_react_node)
workflow.add_node("modify",    modify_event_node)
workflow.add_node("other",     other_event_node)
workflow.add_node("approval",  human_approval_node)

workflow.set_entry_point("router")

workflow.add_conditional_edges(
    "router",
    route_next,
    {
        "read_only": "read_only",
        "booking":   "booking",
        "modify":    "modify",
        "other":     "other",
    },
)

workflow.add_edge("read_only", END)
workflow.add_edge("booking",   "approval")
workflow.add_edge("modify",    "approval")
workflow.add_edge("other",     END)

workflow.add_conditional_edges(
    "approval",
    route_after_approval,
    {
        "done":      END,
        "cancelled": END,
    },
)

graph = workflow.compile()


def build_meeting_graph():
    return graph