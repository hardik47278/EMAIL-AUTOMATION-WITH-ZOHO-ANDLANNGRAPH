import os
import time
import logging
from langgraph.graph import StateGraph, END
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_groq import ChatGroq
from dotenv import load_dotenv

from state_shared import EmailState

load_dotenv()

logger = logging.getLogger(__name__)

llm_primary   = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
llm_fallback1 = ChatGroq(model="llama-3.1-8b-instant",    temperature=0)
llm_fallback2 = ChatGroq(model="openai/gpt-oss-20b",      temperature=0)

parser = JsonOutputParser()

INTENT_PROMPT = """
You are an intent detection agent.

Extract ALL intents present in the email.

Allowed intents:
- meeting
- information_request
- task_request
- modification
- notification
- payment
- casual

Rules:
- Multiple intents can exist together
- Assign confidence (0 to 1)
- Identify primary intent
- Return JSON ONLY

Email:
{email}

OUTPUT ONLY THIS JSON:
{{
  "intents": [
    {{
      "type": "meeting",
      "confidence": 0.9
    }}
  ],
  "primary_intent": "meeting"
}}
"""

prompt = PromptTemplate(
    input_variables=["email"],
    template=INTENT_PROMPT
)

chain_primary   = prompt | llm_primary   | parser
chain_fallback1 = prompt | llm_fallback1 | parser
chain_fallback2 = prompt | llm_fallback2 | parser


def invoke_with_backoff(chain, inputs, model_name, retries=3, base_delay=2):
    for attempt in range(retries):
        try:
            return chain.invoke(inputs)
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                wait = base_delay ** (attempt + 1)
                logger.warning(f"[{model_name}] Rate limit. Retrying in {wait}s... ({attempt+1}/{retries})")
                time.sleep(wait)
            else:
                raise
    return None


def intent_agent(state: EmailState):

    email_text = (
        state["email"].get("subject", "") + " " +
        state["email"].get("body", "")
    )

    inputs = {"email": email_text}

    result = invoke_with_backoff(chain_primary, inputs, "llama-3.3-70b-versatile")
    if result:
        logger.info("✅ Intent: used primary llama-3.3-70b-versatile")
        return {"intent_result": result}

    logger.warning("⚠️ Intent: trying fallback1 llama-3.1-8b-instant")
    result = invoke_with_backoff(chain_fallback1, inputs, "llama-3.1-8b-instant")
    if result:
        logger.info("✅ Intent: used fallback1 llama-3.1-8b-instant")
        return {"intent_result": result}

    logger.warning("⚠️ Intent: trying fallback2 openai/gpt-oss-20b")
    result = invoke_with_backoff(chain_fallback2, inputs, "openai/gpt-oss-20b")
    if result:
        logger.info("✅ Intent: used fallback2 openai/gpt-oss-20b")
        return {"intent_result": result}

    raise RuntimeError("❌ Intent agent: all models failed.")


def intent_router(state: EmailState):

    intents = state["intent_result"].get("intents", [])

    has_meeting = any(
        intent.get("type") == "meeting"
        for intent in intents
    )

    if has_meeting:
        route = "meeting_agent"
    else:
        route = "agent1"

    return {"route": route}


def route_selector(state: EmailState):
    return state["route"]


def agent1(state: EmailState):
    return {
        "status":   "analysis_pipeline",
        "email_id": state["email"].get("id")
    }


def meeting_agent(state: EmailState):
    return {
        "status":   "meeting_extracted",
        "email_id": state["email"].get("id")
    }


def build_intent_graph():

    workflow = StateGraph(EmailState)

    workflow.add_node("intent_agent",  intent_agent)
    workflow.add_node("router",        intent_router)
    workflow.add_node("agent1",        agent1)
    workflow.add_node("meeting_agent", meeting_agent)

    workflow.set_entry_point("intent_agent")

    workflow.add_edge("intent_agent", "router")

    workflow.add_conditional_edges(
        "router",
        route_selector,
        {
            "meeting_agent": "meeting_agent",
            "agent1":        "agent1"
        }
    )

    workflow.add_edge("meeting_agent", END)
    workflow.add_edge("agent1",        END)

    return workflow.compile()


if __name__ == "__main__":

    app = build_intent_graph()

    result = app.invoke({
        "email": {
            "subject": "Can we schedule a meeting tomorrow?",
            "body":    "Hi, I wanted to discuss the project. Are you free tomorrow at 3pm?"
        },
        "spam_result":   {},
        "intent_result": {},
        "route":         ""
    })

    print(result["intent_result"])