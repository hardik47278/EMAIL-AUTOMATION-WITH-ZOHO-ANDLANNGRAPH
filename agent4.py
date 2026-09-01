from typing import TypedDict, Dict, Any
import time
import logging
from langgraph.graph import StateGraph, END
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_groq import ChatGroq
from langsmith import traceable

from database_tools import (
    tool_fetch_email_history,
    tool_fetch_customer_summary,
    tool_fetch_sentiment_trend,
    tool_fetch_email_count
)

logger = logging.getLogger(__name__)


class EmailState(TypedDict):
    customer_id: str
    email: Dict[str, Any]
    email_count: int
    email_history: list
    customer_summary: dict
    sentiment_trend: list
    personalization_context: dict


llm_primary   = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
llm_fallback1 = ChatGroq(model="llama-3.1-8b-instant",    temperature=0)
llm_fallback2 = ChatGroq(model="openai/gpt-oss-20b",      temperature=0)

parser = JsonOutputParser()


CONTEXT_PROMPT = """
You are a Personalization Context Agent.

You analyze a user's email and OPTIONAL historical signals
to infer communication personality.

You do NOT generate replies.
You do NOT assign priority.
You do NOT take actions.

---

# INPUTS YOU MAY RECEIVE

- current email
- email history (optional)
- customer summary (optional)
- sentiment trend (optional)
- email count (optional)

---

# OBJECTIVE

Infer:

1. user_role
2. communication_personality
3. domain_context
4. behavioral_traits
5. is_first_time_user

---

# ROLE RULES

software_engineer → GitHub, PR, bug, deploy
student → assignment, exam, .edu
finance → invoice, billing, payment
HR → hiring
manager → KPIs, reports
sales → leads
unknown → unclear

---

# PERSONALITY

verbosity: short | medium | long
tone: formal | semi-formal | casual
directness: low | medium | high
technical_level: technical | non-technical

---

# DOMAIN

technical | business | academic | financial | mixed | unknown

---

# STRICT RULES

- Use ONLY provided data
- Do NOT hallucinate history
- Be deterministic
- Output ONLY JSON

---

EMAIL:
{email}

HISTORY:
{history}

SUMMARY:
{summary}

SENTIMENT:
{senti}

EMAIL_COUNT:
{count}

---

OUTPUT:

{{
  "user_role": "",
  "communication_personality": {{
    "verbosity": "",
    "tone": "",
    "directness": "",
    "technical_level": ""
  }},
  "domain_context": "",
  "behavioral_traits": [],
  "is_first_time_user": false
}}
"""

prompt = PromptTemplate(
    template=CONTEXT_PROMPT,
    input_variables=["email", "history", "summary", "senti", "count"]
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

@traceable(
        name="personalization_context_agent",
        metadata={
            "node":"personalization_context",
            "version":"1.0"
        },
        tags=["agent","personalization"]
)
def personalization_context_agent(state: EmailState):

    email = state["email"].get("subject", "") + "\n" + state["email"].get("body", "")

    history = tool_fetch_email_history.invoke({"customer_id": state["customer_id"]})
    summary = tool_fetch_customer_summary.invoke({"customer_id": state["customer_id"]})
    senti   = tool_fetch_sentiment_trend.invoke({"customer_id": state["customer_id"]})
    count   = tool_fetch_email_count.invoke({"customer_id": state["customer_id"]})

    inputs = {
        "email":   email,
        "history": str(history),
        "summary": str(summary),
        "senti":   str(senti),
        "count":   count
    }

    result = invoke_with_backoff(chain_primary, inputs, "llama-3.1-8b-instant")
    if result:
        logger.info("✅ Personalization: used primary llama-3.1-8b-instant")
        return {**state, "email_count": count, "email_history": history, "customer_summary": summary, "sentiment_trend": senti, "personalization_context": result}

    logger.warning("⚠️ Personalization: trying fallback1 llama-3.1-8b-instant")
    result = invoke_with_backoff(chain_fallback1, inputs, "llama-3.1-8b-instant")
    if result:
        logger.info("✅ Personalization: used fallback1 llama-3.1-8b-instant")
        return {**state, "email_count": count, "email_history": history, "customer_summary": summary, "sentiment_trend": senti, "personalization_context": result}

    logger.warning("⚠️ Personalization: trying fallback2 openai/gpt-oss-20b")
    result = invoke_with_backoff(chain_fallback2, inputs, "openai/gpt-oss-20b")
    if result:
        logger.info("✅ Personalization: used fallback2 openai/gpt-oss-20b")
        return {**state, "email_count": count, "email_history": history, "customer_summary": summary, "sentiment_trend": senti, "personalization_context": result}

    raise RuntimeError("❌ Personalization agent: all models failed.")


def build_personalization_graph():

    workflow = StateGraph(EmailState)

    workflow.add_node("personalization_context_agent", personalization_context_agent)

    workflow.set_entry_point("personalization_context_agent")

    workflow.add_edge("personalization_context_agent", END)

    return workflow.compile()


if __name__ == "__main__":

    app = build_personalization_graph()

    result = app.invoke({
        "customer_id": "CUST_001",
        "email": {
            "subject": "Bug in deployment pipeline",
            "body": "Our CI/CD is failing on production release"
        }
    })

    print(result["personalization_context"])