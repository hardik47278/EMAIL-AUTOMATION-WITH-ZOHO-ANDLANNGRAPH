from typing import TypedDict, Dict, Any
import time
import logging
from langgraph.graph import StateGraph, END
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_groq import ChatGroq
from langsmith import traceable

logger = logging.getLogger(__name__)

class PriorityState(TypedDict):
    email: Dict[str, Any]
    priority_result: Dict[str, Any]


PRIORITY_PROMPT = """
You are an Email Prioritization Agent for a SOFTWARE DEVELOPER.

Your job is to assign a priority to the email.

PRIORITY LEVELS:
- HIGH: urgent work, production issues, bug fixes, code reviews, deployment failures
- MEDIUM: meetings, project updates, internal discussions
- LOW: marketing, promotions, newsletters, spam

IMPORTANT SIGNALS:
- github.com, gitlab.com → usually HIGH
- .edu → usually MEDIUM
- urgent, asap, blocking, critical, production issue → HIGH
- marketing domains → LOW

RULES:
- Understand meaning, not just keywords
- Understand meaning  from entire content
- If it blocks work or production → HIGH
- If informational → MEDIUM
- If irrelevant/promotional → LOW

EMAIL:
{email}

OUTPUT ONLY JSON:

{{
  "priority": "HIGH | MEDIUM | LOW",
  "reason": "one line explanation"
}}
"""

llm_primary   = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
llm_fallback1 = ChatGroq(model="llama-3.1-8b-instant",    temperature=0)
llm_fallback2 = ChatGroq(model="openai/gpt-oss-20b",      temperature=0)

parser = JsonOutputParser()

prompt = PromptTemplate(
    template=PRIORITY_PROMPT,
    input_variables=["email"]
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
        name="priority_agent",
        metadata={
            "node":"priority",
            "version":"1.0"
        },
        tags=["agent","priority"]
)


def priority_agent(state: PriorityState):

    email_text = (
        state["email"].get("subject", "") + "\n" +
        state["email"].get("body", "")
    )

    inputs = {"email": email_text}

    result = invoke_with_backoff(chain_primary, inputs, "llama-3.1-8b-instant")
    if result:
        logger.info("✅ Priority: used primary llama-3.1-8b-instant")
        return {"priority_result": result}

    logger.warning("⚠️ Priority: trying fallback1 llama-3.1-8b-instant")
    result = invoke_with_backoff(chain_fallback1, inputs, "llama-3.1-8b-instant")
    if result:
        logger.info("✅ Priority: used fallback1 llama-3.1-8b-instant")
        return {"priority_result": result}

    logger.warning("⚠️ Priority: trying fallback2 openai/gpt-oss-20b")
    result = invoke_with_backoff(chain_fallback2, inputs, "openai/gpt-oss-20b")
    if result:
        logger.info("✅ Priority: used fallback2 openai/gpt-oss-20b")
        return {"priority_result": result}

    raise RuntimeError("❌ Priority agent: all models failed.")


def build_priority_graph():

    workflow = StateGraph(PriorityState)

    workflow.add_node("priority_agent", priority_agent)

    workflow.set_entry_point("priority_agent")

    workflow.add_edge("priority_agent", END)

    return workflow.compile()