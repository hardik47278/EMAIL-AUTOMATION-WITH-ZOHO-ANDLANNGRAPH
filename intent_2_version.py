import os
import time
import logging
from langgraph.graph import StateGraph, END
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from langsmith import traceable

from spam_detection import extract_domain, get_whois_info, dns_checks, virustotal_check
from state_shared import EmailState

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------- LLM POOL ----------------
llm_primary   = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
llm_fallback1 = ChatGroq(model="llama-3.1-8b-instant",    temperature=0)
llm_fallback2 = ChatGroq(model="openai/gpt-oss-20b",      temperature=0)

parser = JsonOutputParser()


INTENT_PROMPT = """
You are an email intent classifier.

Extract ALL intents present in the email using the content AND domain signals provided.

ALLOWED INTENTS:
- otp                 : one-time passwords, verification codes
- promotion           : marketing, offers, discounts, sales
- newsletter          : digests, subscriptions, weekly updates
- order_update        : shipping, delivery, order confirmations
- payment_receipt     : payment received, transaction confirmations
- subscription        : renewals, plan updates
- system_alert        : storage full, password expiry, system notifications
- social_notification : likes, follows, comments, mentions
- job_alert           : job board matches, recruiter blasts
- meeting             : scheduling requests, calendar invites
- task_request        : action items, work requests
- information_request : questions needing a reply
- invoice             : billing, payment requests, purchase orders
- complaint           : issues, disputes, escalations
- legal               : contracts, NDAs, legal notices
- job_offer           : offer letters, salary negotiations
- refund              : refund or chargeback requests
- modification        : change requests, amendments
- payment             : payment requests involving decisions
- casual              : general conversation

RULES:
- Multiple intents can exist together
- Assign confidence (0.0 to 1.0) per intent
- Identify primary intent
- Use domain signals to resolve ambiguity (e.g. suspicious domain on an OTP = likely phishing → classify as complaint or casual)
- Return JSON ONLY

FEW SHOT EXAMPLES:
---
Email: "Your OTP is 4521. Valid for 10 minutes."
Sender: noreply@google.com | known=true, age_days=9000, has_spf=true, vt_flagged=false
Output: {{"intents": [{{"type": "otp", "confidence": 0.99}}], "primary_intent": "otp"}}

---
Email: "Your OTP is 9988. Click here to verify your account."
Sender: noreply@g00gle-secure.com | known=false, age_days=3, has_spf=false, vt_flagged=true
Output: {{"intents": [{{"type": "complaint", "confidence": 0.85}}, {{"type": "otp", "confidence": 0.30}}], "primary_intent": "complaint"}}

---
Email: "50% OFF today only! Exclusive deal for you."
Sender: deals@amazon.in | known=true, age_days=8000, has_spf=true, vt_flagged=false
Output: {{"intents": [{{"type": "promotion", "confidence": 0.97}}], "primary_intent": "promotion"}}

---
Email: "Your weekly digest from Medium is here."
Sender: noreply@medium.com | known=true, age_days=7000, has_spf=true, vt_flagged=false
Output: {{"intents": [{{"type": "newsletter", "confidence": 0.96}}], "primary_intent": "newsletter"}}

---
Email: "Invoice #1234 attached. Payment of 50,000 due by Friday."
Sender: accounts@vendor.com | known=false, age_days=400, has_spf=true, vt_flagged=false
Output: {{"intents": [{{"type": "invoice", "confidence": 0.95}}], "primary_intent": "invoice"}}

---
Email: "Can we schedule a meeting tomorrow at 3pm?"
Sender: john@company.com | known=false, age_days=900, has_spf=true, vt_flagged=false
Output: {{"intents": [{{"type": "meeting", "confidence": 0.95}}, {{"type": "task_request", "confidence": 0.55}}], "primary_intent": "meeting"}}

---
Email: "Production server is down. Immediate action required."
Sender: alerts@company.com | known=false, age_days=1200, has_spf=true, vt_flagged=false
Output: {{"intents": [{{"type": "task_request", "confidence": 0.97}}], "primary_intent": "task_request"}}

---
Now classify this email:

EMAIL:
Subject : {subject}
Sender  : {sender}
Body    : {body}

DOMAIN SIGNALS:
Domain          : {domain}
Known domain    : {is_known}
Domain age days : {age_days}
Has SPF/DMARC   : {has_spf}
VirusTotal flag : {vt_flagged}
VirusTotal info : {vt_info}
WHOIS registrar : {registrar}

OUTPUT ONLY THIS JSON:
{{
  "intents": [
    {{
      "type": "...",
      "confidence": 0.0
    }}
  ],
  "primary_intent": "..."
}}
"""

prompt = PromptTemplate(
    input_variables=[
        "subject", "sender", "body",
        "domain", "is_known", "age_days",
        "has_spf", "vt_flagged", "vt_info", "registrar"
    ],
    template=INTENT_PROMPT
)

chain_primary   = prompt | llm_primary   | parser
chain_fallback1 = prompt | llm_fallback1 | parser
chain_fallback2 = prompt | llm_fallback2 | parser


# ---------------- KNOWN DOMAIN WHITELIST ----------------
KNOWN_DOMAINS = {
    "google.com", "gmail.com", "youtube.com",
    "amazon.com", "amazon.in",
    "flipkart.com", "myntra.com",
    "github.com", "gitlab.com",
    "linkedin.com", "twitter.com", "instagram.com",
    "medium.com", "substack.com",
    "paytm.com", "phonepe.com", "razorpay.com",
    "swiggy.com", "zomato.com",
    "quora.com", "reddit.com",
    "microsoft.com", "outlook.com", "hotmail.com",
    "apple.com", "icloud.com",
    "netflix.com", "spotify.com",
    "juspay.in", "hdfc.com", "icicibank.com",
}


# ---------------- DOMAIN SIGNAL COLLECTOR ----------------
def collect_domain_signals(sender: str) -> dict:
    """Run all 4 tools, return signals. Never raises."""
    signals = {
        "domain":     "unknown",
        "is_known":   False,
        "age_days":   -1,
        "has_spf":    False,
        "vt_flagged": False,
        "vt_info":    "unavailable",
        "registrar":  "unknown",
    }

    # 1. extract domain
    try:
        domain_result    = extract_domain.invoke(sender)
        domain           = domain_result if isinstance(domain_result, str) else str(domain_result)
        signals["domain"]   = domain
        signals["is_known"] = domain in KNOWN_DOMAINS
        logger.info(f"[domain] extracted: {domain} | known={signals['is_known']}")
    except Exception as e:
        logger.warning(f"[domain] extract_domain failed: {e}")
        return signals

    # 2. whois
    try:
        from datetime import datetime
        whois_result         = get_whois_info.invoke(domain)
        signals["registrar"] = whois_result.get("registrar") or "unknown"
        creation_str         = whois_result.get("creation_date", "")
        if creation_str and creation_str not in ("None", ""):
            if isinstance(creation_str, list):
                creation_str = creation_str[0]
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    created = datetime.strptime(str(creation_str)[:19], fmt)
                    signals["age_days"] = (datetime.utcnow() - created).days
                    break
                except ValueError:
                    continue
        logger.info(f"[whois] registrar={signals['registrar']}, age_days={signals['age_days']}")
    except Exception as e:
        logger.warning(f"[whois] get_whois_info failed: {e}")

    # 3. dns
    try:
        dns_result         = dns_checks.invoke(domain)
        signals["has_spf"] = bool(
            dns_result.get("spf") or dns_result.get("dmarc") or dns_result.get("has_spf")
        )
        logger.info(f"[dns] has_spf={signals['has_spf']}")
    except Exception as e:
        logger.warning(f"[dns] dns_checks failed: {e}")

    # 4. virustotal
    try:
        vt_result             = virustotal_check.invoke(domain)
        signals["vt_flagged"] = bool(vt_result.get("flagged") or vt_result.get("malicious"))
        signals["vt_info"]    = str(vt_result.get("info", vt_result.get("reason", "clean")))
        logger.info(f"[vt] flagged={signals['vt_flagged']}, info={signals['vt_info']}")
    except Exception as e:
        logger.warning(f"[vt] virustotal_check failed: {e}")

    return signals


# ---------------- BACKOFF ----------------
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


# ---------------- INTENT AGENT NODE ----------------
@traceable(
        name="intent_agent",
        metadata={
            "node":"intent",
            "version":"2.0"
        },
        tags=["agent","intent"]
)
def intent_agent(state: EmailState) -> EmailState:

    email   = state["email"]
    subject = email.get("subject", "")
    sender  = email.get("sender", "")
    body    = email.get("body", "")[:300]

    # always run all 4 tools
    logger.info(f"[intent] collecting domain signals for: {sender}")
    signals = collect_domain_signals(sender)

    inputs = {
        "subject":    subject,
        "sender":     sender,
        "body":       body,
        "domain":     signals["domain"],
        "is_known":   signals["is_known"],
        "age_days":   signals["age_days"],
        "has_spf":    signals["has_spf"],
        "vt_flagged": signals["vt_flagged"],
        "vt_info":    signals["vt_info"],
        "registrar":  signals["registrar"],
    }

    result = invoke_with_backoff(chain_primary, inputs, "llama-3.3-70b-versatile")
    if result:
        logger.info("Intent: used primary llama-3.3-70b-versatile")
    else:
        logger.warning("Intent: primary failed, trying fallback1 llama-3.1-8b-instant")
        result = invoke_with_backoff(chain_fallback1, inputs, "llama-3.1-8b-instant")
        if result:
            logger.info("Intent: used fallback1 llama-3.1-8b-instant")
        else:
            logger.warning("Intent: fallback1 failed, trying fallback2 openai/gpt-oss-20b")
            result = invoke_with_backoff(chain_fallback2, inputs, "openai/gpt-oss-20b")
            if result:
                logger.info("Intent: used fallback2 openai/gpt-oss-20b")
            else:
                raise RuntimeError("Intent agent: all models failed.")

    logger.info(f"[intent] primary={result.get('primary_intent')} | intents={result.get('intents')}")

    return {
        "intent_result":  result,
        "domain_signals": signals,
    }


# ---------------- ROUTER (unchanged logic) ----------------
def intent_router(state: EmailState) -> EmailState:
    intents     = state["intent_result"].get("intents", [])
    has_meeting = any(i.get("type") == "meeting" for i in intents)
    route       = "meeting_agent" if has_meeting else "agent1"
    return {"route": route}


def route_selector(state: EmailState) -> str:
    return state["route"]


# ---------------- STUBS (unchanged) ----------------
def agent1(state: EmailState) -> EmailState:
    return {
        "status":   "analysis_pipeline",
        "email_id": state["email"].get("id"),
    }


def meeting_agent(state: EmailState) -> EmailState:
    return {
        "status":   "meeting_extracted",
        "email_id": state["email"].get("id"),
    }


# ---------------- GRAPH (unchanged) ----------------
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
            "agent1":        "agent1",
        }
    )

    workflow.add_edge("meeting_agent", END)
    workflow.add_edge("agent1",        END)

    return workflow.compile()


# ---------------- MAIN + TEST BODIES ----------------
if __name__ == "__main__":

    import json

    app = build_intent_graph()

    def make_state(email: dict) -> dict:
        return {
            "email":          email,
            "spam_result":    {},
            "intent_result":  {},
            "domain_signals": {},
            "route":          "",
        }

    test_emails = [
        {
            "name": "OTP - legitimate sender",
            "email": {
                "id":      "001",
                "sender":  "noreply@google.com",
                "subject": "Your Google verification code",
                "body":    "Your OTP is 4521. Valid for 10 minutes. Do not share.",
            }
        },
        {
            "name": "OTP - suspicious sender",
            "email": {
                "id":      "002",
                "sender":  "noreply@g00gle-secure.com",
                "subject": "Your verification code",
                "body":    "Your OTP is 9988. Click here to verify your account now.",
            }
        },
        {
            "name": "Promotion",
            "email": {
                "id":      "003",
                "sender":  "deals@amazon.in",
                "subject": "50% OFF today only!",
                "body":    "Shop now and save big. Limited time offer for Prime members.",
            }
        },
        {
            "name": "Newsletter",
            "email": {
                "id":      "004",
                "sender":  "noreply@medium.com",
                "subject": "Your weekly digest from Medium",
                "body":    "Here are the top stories this week based on your interests.",
            }
        },
        {
            "name": "Invoice",
            "email": {
                "id":      "005",
                "sender":  "accounts@vendor.com",
                "subject": "Invoice #1234 - Payment due Friday",
                "body":    "Please find attached Invoice #1234 for 50,000. Payment due by Friday.",
            }
        },
        {
            "name": "Meeting request",
            "email": {
                "id":      "006",
                "sender":  "john@company.com",
                "subject": "Can we schedule a meeting tomorrow?",
                "body":    "Hi, I wanted to discuss the project. Are you free tomorrow at 3pm?",
            }
        },
        {
            "name": "Production alert",
            "email": {
                "id":      "007",
                "sender":  "alerts@company.com",
                "subject": "URGENT: Production server down",
                "body":    "Production server is down. Immediate action required.",
            }
        },
    ]

    for test in test_emails:
        print(f"\n{'='*60}")
        print(f"TEST: {test['name']}")
        print(f"{'='*60}")

        result = app.invoke(make_state(test["email"]))

        print(f"Primary intent : {result['intent_result'].get('primary_intent')}")
        print(f"Route          : {result['route']}")
        signals = result.get('domain_signals', {})
        print(f"Domain         : {signals.get('domain', 'n/a')}")
        print(f"Known domain   : {signals.get('is_known', 'n/a')}")
        print(f"VT flagged     : {signals.get('vt_flagged', 'n/a')}")
        print(f"All intents    :")
        for i in result['intent_result'].get('intents', []):
            print(f"  {i['type']:<25} confidence={i['confidence']:.2f}")