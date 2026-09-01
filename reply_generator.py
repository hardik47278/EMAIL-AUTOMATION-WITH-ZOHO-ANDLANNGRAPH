import json
import re
import time
import logging
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from database_tools import tool_fetch_email_history
from langchain_core.callbacks import BaseCallbackHandler
import os
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()

logger = logging.getLogger(__name__)


# ─── TRACE HANDLER ───────────────────────────────────────
class AgentTraceHandler(BaseCallbackHandler):

    def on_tool_start(self, serialized, input_str, **kwargs):
        print("\n" + "="*60)
        print(f"🛠️ TOOL START: {serialized.get('name')}")
        print(f"INPUT: {input_str}")
        print("="*60)

    def on_tool_end(self, output, **kwargs):
        print("\n📦 TOOL OUTPUT:")
        print(output)

    def on_agent_action(self, action, **kwargs):
        print("\n" + "-"*60)
        print(f"🤖 AGENT CALLING TOOL: {action.tool}")
        print(f"ARGS: {action.tool_input}")
        print("-"*60)

    def on_agent_finish(self, finish, **kwargs):
        print("\n" + "="*60)
        print("✅ AGENT FINISHED")
        print(finish.return_values)
        print("="*60)


_ctx = {}

def set_context(merged_context: dict, email: dict, feedback: str):
    _ctx["merged"]   = merged_context
    _ctx["email"]    = email
    _ctx["feedback"] = feedback


# ─── TOOL CALL LIMITER ───────────────────────────────────
TOOL_CALL_LIMIT = 8
_tool_call_count = {"n": 0}

def reset_tool_call_count():
    _tool_call_count["n"] = 0

def make_limited_tool(t):
    """Wrap a tool to enforce the global TOOL_CALL_LIMIT."""

    @tool(t.name, args_schema=t.args_schema)
    def limited(*args, **kwargs):
        _tool_call_count["n"] += 1
        if _tool_call_count["n"] > TOOL_CALL_LIMIT:
            logger.warning(f"🚫 Tool call limit ({TOOL_CALL_LIMIT}) reached. Blocking further calls.")
            return json.dumps({"error": f"Tool call limit of {TOOL_CALL_LIMIT} exceeded. Stop and return final JSON now."})
        return t.invoke(kwargs if kwargs else (args[0] if args else {}))

    limited.description = t.description
    return limited


# ─── TOKEN BUDGET ─────────────────────────────────────────
TOKEN_BUDGET = 15000
_token_state = {"used": 0, "budget_hit": False}

def reset_token_state():
    _token_state["used"]       = 0
    _token_state["budget_hit"] = False


# ─── LLM ─────────────────────────────────────────────────
llm_primary   = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY"))
llm_primary2  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY2"))
llm_primary3  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY3"))  # NEW: third Groq account

llm_fallback  = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=os.getenv("GROQ_API_KEY"))
llm_fallback2 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=os.getenv("GROQ_API_KEY2"))  # NEW: second Groq account 8b
llm_google    = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

LLM_CHAIN = [
    (llm_primary,   "llama-3.3-70b-versatile (Groq acc1)"),
    (llm_primary2,  "llama-3.3-70b-versatile (Groq acc2)"),
    (llm_primary3,  "llama-3.3-70b-versatile (Groq acc3)"),
    (llm_fallback,  "llama-3.1-8b-instant (Groq acc1)"),
    (llm_fallback2, "llama-3.1-8b-instant (Groq acc2)"),
    (llm_google,    "gemini-2.5-flash (Google)"),
]

RATE_LIMIT_ERRORS = ("429", "rate_limit", "TPD", "503", "UNAVAILABLE", "403", "402", "RESOURCE_EXHAUSTED")

def is_rate_limit_error(e: Exception) -> bool:
    s = str(e)
    return any(token in s for token in RATE_LIMIT_ERRORS)


def invoke_llm(prompt: str) -> str:
    # ── budget pre-check ──
    if _token_state["used"] >= TOKEN_BUDGET:
        _token_state["budget_hit"] = True
        logger.warning(f"🚫 Token budget ({TOKEN_BUDGET}) exhausted.")
        return json.dumps({"error": "Token budget exhausted. Return final JSON now."})

    for llm, name in LLM_CHAIN:
        try:
            response = llm.invoke(prompt)

            # track tokens (Groq returns token_usage; Gemini may not)
            usage       = response.response_metadata.get("token_usage", {})
            call_tokens = usage.get("total_tokens", len(prompt) // 4 + len(response.content) // 4)
            _token_state["used"] += call_tokens

            logger.info(f"✅ invoke_llm: used {name} | tokens this call: {call_tokens} | total: {_token_state['used']}")
            return response.content

        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning(f"⚠️ {name} rate limited. Trying next...")
                continue
            raise

    raise RuntimeError("❌ All models exhausted")


# ─── TOOL 1: generate_reply ──────────────────────────────
@tool
def generate_reply(extra_focus: str = "") -> str:
    """
    Generate a draft email reply from merged context.
    Pass extra_focus to address specific missing intents.
    """
    ctx   = _ctx["merged"]
    email = _ctx["email"]
    fb    = _ctx["feedback"]

    prompt = f"""
You are a professional email reply generator.

CONTEXT:
Priority:        {ctx.get("priority",        "MEDIUM")}
Priority Reason: {ctx.get("priority_reason", "")}
User Role:       {ctx.get("user_role",       "unknown")}
Tone:            {ctx.get("tone",            "unknown")}
Verbosity:       {ctx.get("verbosity",       "unknown")}
Technical Level: {ctx.get("technical_level", "unknown")}
Is First Time:   {ctx.get("is_first_time",   "unknown")}
Domain:          {ctx.get("domain_context",  "unknown")}
Meeting Booked:  {ctx.get("meeting_booked",  False)}
Meeting Date:    {ctx.get("meeting_date",    "N/A")}
Meeting Time:    {ctx.get("meeting_time",    "N/A")}

ORIGINAL EMAIL:
Subject: {email.get("subject", "")}
Body:    {email.get("body",    "")}

HUMAN FEEDBACK: {fb}
EXTRA FOCUS:    {extra_focus}

RULES:
- HIGH priority → urgent, empathetic, fast resolution
- MEDIUM → normal helpful tone
- LOW → brief, friendly
- If tone unknown → infer from email content
- If verbosity unknown → infer from email length
- If technical unknown → infer from email content
- meeting_booked True → confirm date and time
- is_first_time True → warm welcome

OUTPUT ONLY JSON:
{{
  "reply":  "full reply text",
  "tone":   "formal | casual",
  "length": "short | medium | long"
}}
"""
    return invoke_llm(prompt)



@tool
def evaluate_reply(draft: str) -> str:
    """
    Evaluate a draft reply.
    Returns score out of 10, issues found, and pass/fail.
    Score >= 7 is passing.
    """
    ctx   = _ctx["merged"]
    email = _ctx["email"]

    prompt = f"""
You are a strict email quality evaluator.

ORIGINAL EMAIL:
Subject: {email.get("subject", "")}
Body:    {email.get("body",    "")}

EXPECTED TONE:      {ctx.get("tone",      "unknown")}
EXPECTED VERBOSITY: {ctx.get("verbosity", "unknown")}

DRAFT REPLY:
{draft}

EVALUATE:
1. Does tone match expected? If unknown infer from email.
2. Does length match verbosity? If unknown infer from email.
3. Is reply polite and professional?
4. Does it avoid hallucinated information?
5. Does it actually address the email?
6. Is it free of contradictions?

OUTPUT ONLY JSON:
{{
  "score":  7,
  "issues": ["list of issues or empty"],
  "pass":   true
}}
"""
    return invoke_llm(prompt)


# ─── TOOL 3: check_intent_coverage ───────────────────────
@tool
def check_intent_coverage(draft: str) -> str:
    """
    Check if all intents in the original email
    are covered in the draft reply.
    Returns missing intents.
    """
    email = _ctx["email"]

    prompt = f"""
You are an intent coverage checker.

ORIGINAL EMAIL:
Subject: {email.get("subject", "")} 
Body:    {email.get("body",    "")}

DRAFT REPLY:
{draft}

TASK:
1. Extract ALL intents from original email
2. Check which intents draft addresses
3. List missing intents

OUTPUT ONLY JSON:
{{
  "intents_found":   ["billing", "complaint"],
  "intents_covered": ["complaint"],
  "missing":         ["billing"],
  "all_covered":     false
}}
"""
    return invoke_llm(prompt)


# ─── TOOL 4: fetch_customer_history ──────────────────────
@tool
def fetch_customer_history(customer_id: str) -> str:
    """
    Fetch past emails sent to this customer from Supabase.
    Use this to avoid sending a repeated reply.
    """
    try:
        history = tool_fetch_email_history.invoke(
            {"customer_id": customer_id}
        )
        if not history:
            return json.dumps({
                "past_replies": [],
                "repeat_risk":  False
            })

        past_replies = [
            h.get("resolution", "")
            for h in history[:3]
            if h.get("resolution")
        ]

        return json.dumps({
            "past_replies": past_replies,
            "repeat_risk":  len(past_replies) > 0
        })

    except Exception as e:
        logger.warning(f"fetch_customer_history failed: {e}")
        return json.dumps({
            "past_replies": [],
            "repeat_risk":  False
        })


# ─── AGENT TOOLS (wrapped with call limiter) ─────────────
_raw_tools = [
    generate_reply,
    evaluate_reply,
    check_intent_coverage,
    fetch_customer_history
]

tools = [make_limited_tool(t) for t in _raw_tools]


SYSTEM_PROMPT = """
You are an agentic email reply generator.

Your job:
1. fetch_customer_history to avoid repeating past replies
2. generate_reply to create a draft
3. evaluate_reply to score the draft
4. check_intent_coverage to find missing intents
5. If score < 7 OR missing intents exist:
   → call generate_reply again with extra_focus on missing intents
6. Maximum 3 regeneration attempts
7. Return the best reply as final JSON

You have a maximum of 8 tool calls total. Use them efficiently.
If you receive a "Tool call limit exceeded" or "Token budget exhausted" error,
stop calling tools and immediately return your best final JSON.

If tone or verbosity is unknown:
  Infer from email content directly.
  Do not use formal as default.
  Match the sender's own communication style.

FINAL OUTPUT must be valid JSON:
{
  "reply":  "final reply text here",
  "tone":   "formal | casual",
  "length": "short | medium | long"
}
"""

handler = AgentTraceHandler()


# ─── ENTRY POINT ─────────────────────────────────────────
@traceable(name="reply_generator", tags=["agent", "reply_generator"], metadata={"version": "1.0"})
def reply_generator(
    merged_context: dict,
    email:          dict,
    feedback:       str = ""
) -> dict:

    reset_tool_call_count()
    reset_token_state()
    set_context(merged_context, email, feedback)

    customer_id = email.get("sender", "unknown")

    # rotate agent through all models
    result = None
    for llm, name in LLM_CHAIN:
        try:
            agent = create_agent(model=llm, tools=tools, system_prompt=SYSTEM_PROMPT)
            result = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": f"""
Generate the best possible reply for this email.

Customer ID: {customer_id}
Subject: {email.get("subject", "")}
Feedback: {feedback}

Steps:
1. fetch_customer_history("{customer_id}")
2. generate_reply()
3. evaluate_reply(draft)
4. check_intent_coverage(draft)
5. retry if needed (max 3)
6. return JSON
"""
                        }
                    ]
                },
                config={"recursion_limit": 30},
                callbacks=[handler]
            )
            logger.info(f"✅ reply_generator: used {name}")
            break
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning(f"⚠️ {name} exhausted, trying next...")
                continue
            raise

    if result is None:
        return {"reply": "All models exhausted", "tone": "unknown", "length": "medium"}

    # ─── OUTPUT VISIBILITY ────────────────────────────────
    print("\n" + "="*60)
    print("🤖 REPLY AGENT — FULL CONVERSATION")
    print("="*60)

    for i, msg in enumerate(result["messages"]):
        role = msg.__class__.__name__

        if role == "HumanMessage":
            print(f"\n👤 USER:\n{msg.content[:200]}")

        elif role == "AIMessage":
            if msg.content:
                print(f"\n🤖 AGENT THINKS:\n{msg.content[:300]}")
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"\n⚡ AGENT CALLS: {tc['name']}")
                    print(f"   Args: {str(tc['args'])[:150]}")

        elif role == "ToolMessage":
            print(f"\n🔧 TOOL RESULT [{msg.name}]:")
            print(f"   {str(msg.content)[:300]}")

    print("\n" + "="*60)
    print("✅ FINAL REPLY:")
    print(result["messages"][-1].content[:500])
    print(f"🪙 Tokens used: {_token_state['used']} | Tool calls: {_tool_call_count['n']} | Budget hit: {_token_state['budget_hit']}")
    print("="*60 + "\n")
    

    final = result["messages"][-1].content

    try:
        parsed = json.loads(final)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*\}', final, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except Exception:
                parsed = {"reply": final, "tone": "unknown", "length": "medium"}
        else:
            parsed = {"reply": final, "tone": "unknown", "length": "medium"}

    parsed["tokens_used"] = _token_state["used"]
    parsed["tool_calls"]  = _tool_call_count["n"]
    parsed["budget_hit"]  = _token_state["budget_hit"]

    return parsed