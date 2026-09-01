import re
import json
import logging
from typing import TypedDict, Annotated

from langchain_groq import ChatGroq
from langchain_classic.chains.summarize import load_summarize_chain
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────
MODEL          = "llama-3.1-8b-instant"
MAX_RETRIES    = 2
PASS_SCORE     = 8
REFINE_THRESHOLD = 500   # tokens — above this use refine chain

llm = ChatGroq(model=MODEL, temperature=0)

# ── INTENT-AWARE ENTITY SCHEMAS ───────────────────────────
ENTITY_SCHEMAS = {
    "invoice": {
        "amounts":      "list of money amounts",
        "invoice_ids":  "list of invoice or order numbers",
        "deadlines":    "list of payment deadlines",
        "bank_details": "any bank or payment info mentioned",
        "disputes":     "any disputed amounts or issues",
        "companies":    "list of company names"
    },
    "complaint": {
        "issue":             "what the problem is",
        "affected_service":  "which service or product is affected",
        "threats":           "any legal threats or escalation warnings",
        "deadline":          "resolution deadline if any",
        "previous_attempts": "any prior attempts to resolve"
    },
    "meeting": {
        "date":      "meeting date",
        "time":      "meeting time",
        "platform":  "zoom, meet, teams, or in-person",
        "topic":     "what the meeting is about",
        "attendees": "list of people involved"
    },
    "task_request": {
        "action_items": "list of tasks being requested",
        "deadline":     "when tasks are due",
        "references":   "PR numbers, ticket IDs, links mentioned",
        "priority":     "urgency level mentioned"
    },
    "casual": {
        "key_question": "main question being asked",
        "context":      "why they are asking",
        "deadline":     "any urgency mentioned"
    },
    "information_request": {
        "what_they_need": "what information is requested",
        "why_they_need":  "reason or context given",
        "deadline":       "when they need it by"
    },
    "payment": {
        "amounts":    "list of amounts",
        "deadlines":  "payment deadlines",
        "method":     "payment method mentioned",
        "references": "transaction IDs, receipts"
    },
    "legal": {
        "legal_action": "type of legal action mentioned",
        "parties":      "companies or people involved",
        "deadline":     "response deadline",
        "documents":    "contracts, NDAs mentioned",
        "demands":      "what they are demanding"
    },
    "refund": {
        "amount":    "refund amount",
        "reason":    "why refund is requested",
        "order_id":  "order or transaction reference",
        "deadline":  "when refund is expected by"
    }
}

DEFAULT_SCHEMA = {
    "key_points": "list of 5 most important points",
    "dates":      "list of dates mentioned",
    "amounts":    "list of amounts mentioned",
    "actions":    "list of actions requested",
    "deadline":   "any deadline mentioned"
}


# ── STATE ─────────────────────────────────────────────────
class SummaryState(TypedDict):
    email_body:    str
    attachments:   list        # [{"filename": ..., "text": ...}]
    intent:        str         # from intent_agent in pipeline

    full_text:     str         # cleaned body + attachments combined
    route:         str         # "ner_llm" or "refine"
    schema:        dict        # intent-aware entity schema

    summary:       str
    entities:      dict

    judge_score:   int
    judge_feedback: str
    attempts:      int
    passed:        bool


# ── EMAIL CLEANER ─────────────────────────────────────────
def clean_email(body: str) -> str:
    """Strip tracking artifacts, forwarded headers, quoted replies, footers."""
    # zero-width and soft-hyphen chars (common in your logs)
    body = body.replace("\u200b", "").replace("\u2007", "").replace("\xad", "").replace("͏", "")
    # forwarded message headers
    body = re.sub(r"-{5,}.*?Forwarded message.*?-{5,}", "", body, flags=re.DOTALL | re.IGNORECASE)
    # quoted reply lines
    body = re.sub(r"\n>.*", "", body)
    # unsubscribe / footer lines
    body = re.sub(r"(unsubscribe|view in browser|privacy policy|help centre|terms of service).*", "", body, flags=re.IGNORECASE)
    # image placeholders
    body = re.sub(r"\[image:.*?\]", "", body, flags=re.IGNORECASE)
    # URLs (keep domain for context but remove long URLs)
    body = re.sub(r"https?://\S{40,}", "", body)
    # excessive whitespace
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r" {2,}", " ", body)
    return body.strip()


def estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 chars."""
    return len(text) // 4


# ── NODE 1: PREPROCESSOR ──────────────────────────────────
def preprocess_node(state: SummaryState) -> SummaryState:
    """Clean email, combine attachments, decide route, pick schema."""

    # clean body
    cleaned_body = clean_email(state["email_body"])

    # combine with attachment text
    full_text = cleaned_body
    for att in state.get("attachments", []):
        att_text = att.get("text", "")
        if att_text:
            fname = att.get("filename", "attachment")
            full_text += f"\n\n[{fname}]:\n{att_text}"

    # estimate total tokens
    total_tokens = estimate_tokens(full_text)
    route = "refine" if total_tokens > REFINE_THRESHOLD else "ner_llm"

    # pick schema
    intent = state.get("intent", "")
    schema = ENTITY_SCHEMAS.get(intent, DEFAULT_SCHEMA)

    logger.info(
        f"[summarizer] cleaned tokens={total_tokens} "
        f"route={route} intent={intent}"
    )

    return {
        **state,
        "full_text": full_text,
        "route":     route,
        "schema":    schema
    }


# ── NODE 2A: NER EXTRACT (short path) ────────────────────
def ner_extract_node(state: SummaryState) -> SummaryState:
    """Pass 1: extract structured entities from full text (cheap model)."""

    schema = state["schema"]

    prompt = f"""Extract information from this email.

EMAIL:
{state["full_text"]}

Extract ONLY these fields:
{json.dumps(schema, indent=2)}

Return ONLY valid JSON with these exact keys. No markdown, no explanation.
"""

    result = llm.invoke(prompt)

    try:
        raw      = result.content.strip()
        raw      = re.sub(r"```json|```", "", raw).strip()
        entities = json.loads(raw)
    except Exception:
        entities = {k: "" for k in schema.keys()}
        logger.warning("[summarizer] entity extraction JSON parse failed, using empty")

    return {**state, "entities": entities}


# ── NODE 2B: NER SUMMARIZE (short path) ──────────────────
def ner_summarize_node(state: SummaryState) -> SummaryState:
    """Pass 2: summarize FROM entities only — no full body needed."""

    prompt = f"""You are an expert email summarizer.

Write a clear 2-4 sentence summary using ONLY these extracted facts.
Do not hallucinate. Do not add anything not in the facts.

EXTRACTED FACTS:
{json.dumps(state["entities"], indent=2)}

Return ONLY the summary text.
"""

    result = llm.invoke(prompt)

    return {**state, "summary": result.content.strip()}


# ── NODE 2C: REFINE CHAIN (long path) ────────────────────
def refine_chain_node(state: SummaryState) -> SummaryState:
    """Refine chain for long emails/attachments — rolling summarization."""

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=50
    )
    chunks = splitter.split_text(state["full_text"])
    docs   = [Document(page_content=c) for c in chunks]

    chain  = load_summarize_chain(llm, chain_type="refine")
    result = chain.invoke({"input_documents": docs})

    summary = result.get("output_text", "").strip()

    # also extract entities from full text for judge
    schema = state["schema"]
    entity_prompt = f"""Extract information from this email.

EMAIL:
{state["full_text"]}

Extract ONLY these fields:
{json.dumps(schema, indent=2)}

Return ONLY valid JSON. No markdown.
"""
    entity_result = llm.invoke(entity_prompt)

    try:
        raw      = entity_result.content.strip()
        raw      = re.sub(r"```json|```", "", raw).strip()
        entities = json.loads(raw)
    except Exception:
        entities = {k: "" for k in schema.keys()}

    logger.info(f"[summarizer] refine chain done. chunks={len(chunks)}")

    return {**state, "summary": summary, "entities": entities}


# ── NODE 3: JUDGE ─────────────────────────────────────────
def judge_node(state: SummaryState) -> SummaryState:
    """Validate summary against extracted entities — no full body needed."""

    prompt = f"""You are an email summary evaluator.

EXTRACTED ENTITIES (ground truth):
{json.dumps(state["entities"], indent=2)}

SUMMARY TO EVALUATE:
{state["summary"]}

Evaluate:
1. Are all entity values mentioned in the summary?
2. Any hallucinations not present in entities?
3. Is summary concise and clear?
4. Missing any critical facts from entities?

Return ONLY valid JSON:
{{
  "score": 1-10,
  "feedback": "specific issues found or ok"
}}
"""

    result = llm.invoke(prompt)

    try:
        raw      = result.content.strip()
        raw      = re.sub(r"```json|```", "", raw).strip()
        data     = json.loads(raw)
        score    = int(data.get("score", 0))
        feedback = data.get("feedback", "")
    except Exception:
        score    = 0
        feedback = "Judge parsing failed"
        logger.warning("[summarizer] judge JSON parse failed")

    logger.info(f"[summarizer] judge score={score} passed={score >= PASS_SCORE}")

    return {
        **state,
        "judge_score":    score,
        "judge_feedback": feedback,
        "passed":         score >= PASS_SCORE
    }


# ── NODE 4: REWRITE ───────────────────────────────────────
def rewrite_node(state: SummaryState) -> SummaryState:
    """Rewrite using entities + feedback — no full body needed."""

    prompt = f"""Improve this email summary.

EXTRACTED FACTS (use these, do not hallucinate):
{json.dumps(state["entities"], indent=2)}

CURRENT SUMMARY:
{state["summary"]}

JUDGE FEEDBACK:
{state["judge_feedback"]}

Fix every issue mentioned in feedback.
Return ONLY the improved summary text.
"""

    result = llm.invoke(prompt)

    return {
        **state,
        "summary":  result.content.strip(),
        "attempts": state["attempts"] + 1
    }


# ── ROUTER ────────────────────────────────────────────────
def route_by_length(state: SummaryState) -> str:
    return state["route"]

def judge_router(state: SummaryState) -> str:
    if state["passed"]:
        return "end"
    if state["attempts"] >= MAX_RETRIES:
        return "end"
    return "rewrite"


# ── BUILD GRAPH ───────────────────────────────────────────
def build_summarizer_graph():
    graph = StateGraph(SummaryState)

    graph.add_node("preprocess",    preprocess_node)
    graph.add_node("ner_extract",   ner_extract_node)
    graph.add_node("ner_summarize", ner_summarize_node)
    graph.add_node("refine_chain",  refine_chain_node)
    graph.add_node("judge",         judge_node)
    graph.add_node("rewrite",       rewrite_node)

    graph.set_entry_point("preprocess")

    # length-based routing
    graph.add_conditional_edges(
        "preprocess",
        route_by_length,
        {
            "ner_llm": "ner_extract",
            "refine":  "refine_chain"
        }
    )

    # short path
    graph.add_edge("ner_extract",   "ner_summarize")
    graph.add_edge("ner_summarize", "judge")

    # long path
    graph.add_edge("refine_chain", "judge")

    # shared judge → rewrite loop
    graph.add_conditional_edges(
        "judge",
        judge_router,
        {
            "rewrite": "rewrite",
            "end":     END
        }
    )
    graph.add_edge("rewrite", "judge")

    return graph.compile()


summarizer_graph = build_summarizer_graph()


# ── ENTRYPOINT ────────────────────────────────────────────
def summarize_email(
    email_body:  str,
    attachments: list = None,
    intent:      str  = ""
) -> dict:
    """
    Main entry point.
    attachments: [{"filename": "invoice.pdf", "text": "extracted text..."}]
    intent: primary_intent from intent_agent (e.g. "invoice", "complaint")
    """
    result = summarizer_graph.invoke({
        "email_body":    email_body,
        "attachments":   attachments or [],
        "intent":        intent,
        "full_text":     "",
        "route":         "",
        "schema":        {},
        "summary":       "",
        "entities":      {},
        "judge_score":   0,
        "judge_feedback": "",
        "attempts":      0,
        "passed":        False
    })

    return {
        "summary":        result["summary"],
        "entities":       result["entities"],
        "judge_score":    result["judge_score"],
        "judge_feedback": result["judge_feedback"],
        "attempts":       result["attempts"],
        "passed":         result["passed"],
        "route":          result["route"]   # tells you which path was used
    }