import json
import re
import time
import logging
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain.agents import create_agent
from database_tools import tool_fetch_email_history

logger = logging.getLogger(__name__)


_ctx = {}

def set_context(merged_context: dict, email: dict, feedback: str):
    _ctx["merged"]   = merged_context
    _ctx["email"]    = email
    _ctx["feedback"] = feedback

# ─── LLM ─────────────────────────────────────────────────
llm_primary  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
llm_fallback = ChatGroq(model="llama-3.1-8b-instant",    temperature=0)

def invoke_llm(prompt: str) -> str:
    try:
        return llm_primary.invoke(prompt).content
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            logger.warning("Primary rate limited. Using fallback.")
            try:
                return llm_fallback.invoke(prompt).content
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")
                raise
        raise


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


# ─── TOOL 2: evaluate_reply ──────────────────────────────
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


# ─── AGENT ───────────────────────────────────────────────
tools = [
    generate_reply,
    evaluate_reply,
    check_intent_coverage,
    fetch_customer_history
]

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

agent = create_agent(
    model=llm_primary,
    tools=tools,
    system_prompt=SYSTEM_PROMPT
)


# ─── ENTRY POINT ─────────────────────────────────────────
def reply_generator(
    merged_context: dict,
    email:          dict,
    feedback:       str = ""
) -> dict:
    reset_tool_call_count()
    rest_token_state()

    set_context(merged_context, email, feedback)

    customer_id = email.get("sender", "unknown")

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
        config={"recursion_limit": 15}
    )

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
    print("="*60 + "\n")
    # ─────────────────────────────────────────────────────

    final = result["messages"][-1].content

    try:
        return json.loads(final)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*\}', final, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {
            "reply":  final,
            "tone":   "unknown",
            "length": "medium"
        }
    



    import json
import re
import time
import logging
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from langchain.agents import create_agent
from database_tools import tool_fetch_email_history
from langchain_core.callbacks import BaseCallbackHandler
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


from langchain_core.callbacks import BaseCallbackHandler

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

# ─── LLM ─────────────────────────────────────────────────
llm_primary   = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY"))
llm_primary2  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY2"))
llm_primary3  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY3"))  # NEW: third Groq account

# HuggingFace fallback



llm_fallback  = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=os.getenv("GROQ_API_KEY"))
llm_fallback2 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=os.getenv("GROQ_API_KEY2"))  # NEW: second Groq account 8b
llm_primary3  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=os.getenv("GROQ_API_KEY3"))  # NEW: third Groq account
llm_google    = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

def invoke_llm(prompt: str) -> str:
    for llm, name in [
        (llm_primary,   "llama-3.3-70b-versatile (Groq acc1)"),
        (llm_primary2,  "llama-3.3-70b-versatile (Groq acc2)"),  # NEW
        (llm_primary3,  "llama-3.3-70b-versatile (Groq acc3)"),  # NEW
        
        (llm_fallback,  "llama-3.1-8b-instant (Groq acc1)"),
        (llm_fallback2, "llama-3.1-8b-instant (Groq acc2)"),     # NEW
        (llm_google,    "gemini-2.5-flash (Google)"),
    ]:
        try:
            return llm.invoke(prompt).content
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower() or "TPD" in str(e) or "503" in str(e) or "UNAVAILABLE" in str(e) or "403" in str(e) or "402" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
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


# ─── TOOL 2: evaluate_reply ──────────────────────────────
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


# ─── AGENT ───────────────────────────────────────────────
tools = [
    generate_reply,
    evaluate_reply,
    check_intent_coverage,
    fetch_customer_history
]

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
def reply_generator(
    merged_context: dict,
    email:          dict,
    feedback:       str = ""
) -> dict:

    set_context(merged_context, email, feedback)

    customer_id = email.get("sender", "unknown")

    # NEW: rotate agent through all models instead of hardcoding one
    result = None
    for llm, name in [
        (llm_primary,  "llama-3.3-70b-versatile (Groq acc1)"),
        (llm_primary2, "llama-3.3-70b-versatile (Groq acc2)"),
        
        (llm_fallback, "llama-3.1-8b-instant (Groq acc1)"),
        (llm_fallback2,"llama-3.1-8b-instant (Groq acc2)"),
        (llm_google,   "gemini-2.5-flash (Google)"),
    ]:
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
            if "429" in str(e) or "rate_limit" in str(e).lower() or "TPD" in str(e) or "503" in str(e) or "UNAVAILABLE" in str(e) or "403" in str(e) or "402" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
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
    print("="*60 + "\n")
    # ─────────────────────────────────────────────────────

    final = result["messages"][-1].content

    try:
        return json.loads(final)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*\}', final, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {
            "reply":  final,
            "tone":   "unknown",
            "length": "medium"
        }
    
    main one 