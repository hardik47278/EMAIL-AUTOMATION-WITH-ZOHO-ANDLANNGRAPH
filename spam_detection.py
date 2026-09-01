import os
import re
import time
import logging
from unittest import result
import nltk
from datetime import datetime
from functools import wraps

from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

from sklearn.feature_extraction.text import TfidfVectorizer

from langchain_groq import ChatGroq
from langchain.agents import create_agent
from langchain_core.tools import tool

from langchain_core.callbacks import BaseCallbackHandler

from dotenv import load_dotenv

import spam_detection_tool

load_dotenv()

# ---------------- LOGGER ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("spam_detection.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ---------------- NLTK ----------------
nltk.download("stopwords", quiet=True)
nltk.download("wordnet", quiet=True)

stop_words = set(stopwords.words("english"))
lemmatizer = WordNetLemmatizer()


GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
GROQ_API_KEY2 = os.getenv("GROQ_API_KEY2")
GROQ_API_KEY3 = os.getenv("GROQ_API_KEY3")
GROQ_API_KEY4 = os.getenv("GROQ_API_KEY4")

VALID_API_KEYS = set(
    os.getenv("VALID_API_KEYS", "key-hardik-001,key-dev-002").split(",")
)

SPAM_KEYWORDS = [
    "free", "winner", "won", "claim prize", "click here",
    "verify account", "urgent action", "limited offer",
    "reward", "lottery", "congratulations", "exclusive deal",
    "password expired", "bank alert", "act now",
    "cash prize", "gift card", "confirm account", "suspended account"
]

# ---------------- LLM POOL ----------------
llm_primary   = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=GROQ_API_KEY)
llm_primary2  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=GROQ_API_KEY2)
llm_primary3  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=GROQ_API_KEY3)
llm_primary4  = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, api_key=GROQ_API_KEY4)

llm_fallback  = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=GROQ_API_KEY)
llm_fallback2 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=GROQ_API_KEY2)
llm_fallback3 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=GROQ_API_KEY3)
llm_fallback4 = ChatGroq(model="llama-3.1-8b-instant", temperature=0, api_key=GROQ_API_KEY4)

LLM_POOL = [
    (llm_primary,   "llama-3.3-70b-versatile (Groq acc1)"),
    (llm_primary2,  "llama-3.3-70b-versatile (Groq acc2)"),
    (llm_primary3,  "llama-3.3-70b-versatile (Groq acc3)"),
    (llm_primary4,  "llama-3.3-70b-versatile (Groq acc4)"),
    (llm_fallback,  "llama-3.1-8b-instant (Groq acc1)"),
    (llm_fallback2, "llama-3.1-8b-instant (Groq acc2)"),
    (llm_fallback3, "llama-3.1-8b-instant (Groq acc3)"),
    (llm_fallback4, "llama-3.1-8b-instant (Groq acc4)"),
]

RATE_LIMIT_ERRORS = ("429", "rate_limit", "TPD", "503", "UNAVAILABLE", "403", "402", "RESOURCE_EXHAUSTED")

# ---------------- EXPONENTIAL BACKOFF ----------------
MAX_RETRIES    = 3
BASE_DELAY     = 1.0
BACKOFF_FACTOR = 2.0

def is_rate_limit_error(e: Exception) -> bool:
    s = str(e)
    return any(token in s for token in RATE_LIMIT_ERRORS)

def invoke_llm_with_backoff(llm, prompt: str, name: str) -> str:
    delay = BASE_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return llm.invoke(prompt).content
        except Exception as e:
            if is_rate_limit_error(e):
                if attempt < MAX_RETRIES:
                    logger.warning(f"⚠️ {name} rate limited (attempt {attempt}/{MAX_RETRIES}). Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= BACKOFF_FACTOR
                else:
                    logger.warning(f"⚠️ {name} exhausted after {MAX_RETRIES} attempts. Moving to next model.")
                    raise
            else:
                raise
    raise RuntimeError(f"❌ {name} failed after {MAX_RETRIES} retries")

def invoke_llm(prompt: str) -> str:
    for llm, name in LLM_POOL:
        try:
            result = invoke_llm_with_backoff(llm, prompt, name)
            logger.info(f"✅ invoke_llm: used {name}")
            return result
        except Exception as e:
            if is_rate_limit_error(e):
                continue
            raise
    raise RuntimeError("❌ All models in LLM pool exhausted")


# ---------------- AUTH ----------------
def authenticate(api_key: str) -> bool:
    return api_key in VALID_API_KEYS if api_key else False


# ---------------- RATE LIMIT ----------------
_rate_limit_store = {}
RATE_LIMIT_MAX    = 10
RATE_LIMIT_WINDOW = 60

def check_rate_limit(api_key: str) -> bool:
    now = time.time()
    _rate_limit_store.setdefault(api_key, [])
    _rate_limit_store[api_key] = [
        t for t in _rate_limit_store[api_key]
        if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[api_key]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_store[api_key].append(now)
    return True


def api_gateway(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        api_key = kwargs.get("api_key")
        if not authenticate(api_key):
            return {"error": "auth failed"}
        if not check_rate_limit(api_key):
            return {"error": "rate limit"}
        return func(*args, **kwargs)
    return wrapper


# ---------------- PREPROCESSING ----------------
def process_email(text: str):
    text = str(text).lower()
    text = re.sub(r"https\S+", "", text)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    words   = text.split()
    cleaned = [
        lemmatizer.lemmatize(w)
        for w in words
        if w not in stop_words
    ]
    return " ".join(cleaned)


def run_tfidf(full_text: str):
    vectorizer = TfidfVectorizer(
        max_features=100,
        ngram_range=(1, 2),
        stop_words="english"
    )
    tfidf_matrix = vectorizer.fit_transform([full_text])
    words  = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.toarray()[0]
    top    = sorted(zip(words, scores), key=lambda x: x[1], reverse=True)[:10]
    return [w for w, s in top]


def rule_based_spam(full_text: str):
    return [kw for kw in SPAM_KEYWORDS if kw in full_text]


# ---------------- TOOLS ----------------
@tool
def extract_domain(text: str):
    """Extract domain from email address"""
    return spam_detection_tool.extract_domain.invoke(text)

import whois
@tool
def get_whois_info(domain: str):
    """
    Fetch WHOIS information for a given domain using python-whois.

    Args:
        domain (str): Domain name (e.g., "google.com")

    Returns:
        dict: WHOIS details including registrar, creation date,
              expiration date, and name servers.
    """
    try:
        w = whois.whois(domain)
        return {
            "domain":          domain,
            "registrar":       str(w.registrar)       if w.registrar       else None,
            "creation_date":   str(w.creation_date)   if w.creation_date   else None,
            "expiration_date": str(w.expiration_date) if w.expiration_date else None,
            "name_servers":    [str(ns) for ns in w.name_servers] if w.name_servers else None
        }
    except Exception as e:
        return {"domain": domain, "error": str(e)}


@tool
def dns_checks(domain: str):
    """Perform DNS checks for a domain"""
    return spam_detection_tool.dns_checks.invoke(domain)

@tool
def virustotal_check(domain: str):
    """Check domain reputation using VirusTotal"""
    return spam_detection_tool.virustotal_check.invoke(domain)


tools = [
    extract_domain,
    get_whois_info,
    dns_checks,
    virustotal_check
]

# ---------------- CALLBACK ----------------
class ToolTraceHandler(BaseCallbackHandler):

    def __init__(self):
        self._tool_call_count = 0

    def on_tool_start(self, serialized, input_str, **kwargs):
        self._tool_call_count += 1
        print(f"\n{'='*60}")
        print(f"🛠️  TOOL START [{self._tool_call_count}/10]: {serialized.get('name')}")
        print(f"INPUT: {input_str}")
        print("="*60)

    def on_tool_end(self, output, **kwargs):
        print(f"\n📦 TOOL OUTPUT:")
        print(output)

    def on_agent_action(self, action, **kwargs):
        print(f"\n{'-'*60}")
        print(f"🤖 AGENT CALLING TOOL: {action.tool}")
        print(f"ARGS: {action.tool_input}")
        print("-"*60)

    def on_agent_finish(self, finish, **kwargs):
        print(f"\n{'='*60}")
        print("✅ AGENT FINISHED")
        print(finish.return_values)
        print("="*60)


# ---------------- TOOL CALL LIMITER ----------------
TOOL_CALL_LIMIT = 10
_tool_call_count = {"n": 0}

def reset_tool_call_count():
    _tool_call_count["n"] = 0

def make_limited_tool(t):
    """Wrap a tool to enforce the global TOOL_CALL_LIMIT."""

    @tool
    def limited(input: str):
        """Execute tool with call limit enforcement."""

        _tool_call_count["n"] += 1
        if _tool_call_count["n"] > TOOL_CALL_LIMIT:
            logger.warning(f"🚫 Tool call limit ({TOOL_CALL_LIMIT}) reached. Blocking further calls.")
            return {"error": f"Tool call limit of {TOOL_CALL_LIMIT} exceeded. Stop and return final answer."}
        return t.invoke(input)

    limited.name        = t.name
    limited.description = t.description
    return limited

limited_tools = [make_limited_tool(t) for t in tools]


# ---------------- LLM AGENT RUN ----------------
def run_llm(email: dict):
    import json

    handler = ToolTraceHandler()
    reset_tool_call_count()

    result = None
    for llm, name in LLM_POOL:
        delay = BASE_DELAY
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                agent = create_agent(
                    model=llm,
                    tools=limited_tools,
                    system_prompt="""
You are an autonomous spam detection agent.

Use tools when needed:
- extract_domain
- get_whois_info
- dns_checks
- virustotal_check

IMPORTANT: You have a maximum of 10 tool calls total.
Use them efficiently. Stop calling tools once you have enough signal.

Return ONLY JSON:
{
  "label": "spam or safe",
  "reason": "...",
  "tools_used": []
}
"""
                )
                result = agent.invoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": f"""
Sender: {email.get('sender')}
Subject: {email.get('subject')}
Body: {email.get('body')}
"""
                            }
                        ]
                    },
                    config={"recursion_limit": 20},
                    callbacks=[handler]
                )
                logger.info(f"✅ run_llm: used {name}")
                break

            except Exception as e:
                if is_rate_limit_error(e):
                    if attempt < MAX_RETRIES:
                        logger.warning(f"⚠️ {name} rate limited (attempt {attempt}/{MAX_RETRIES}). Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                        delay *= BACKOFF_FACTOR
                    else:
                        logger.warning(f"⚠️ {name} exhausted. Trying next model...")
                        break
                else:
                    raise

        if result is not None:
            break

    if result is None:
        return {"label": "unknown", "reason": "All models exhausted", "tools_used": []}

    print("\n================ AGENT OUTPUT ================\n")
    print(result)

    final_content = result["messages"][-1].content
    try:
        return json.loads(final_content)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', final_content, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"label": "unknown", "reason": final_content, "tools_used": []}


# ---------------- ENTRY POINT ----------------
@api_gateway
def detect_spam(email: dict, api_key: str = None):

    subject = email.get("subject", "")
    body    = email.get("body", "")

    full_text = process_email(subject + " " + body)

    tfidf_keywords  = run_tfidf(full_text)
    keyword_matches = rule_based_spam(full_text)

    llm_result = run_llm(email)

    return {
        "gmail_id":        email.get("id"),
        "sender":          email.get("sender"),
        "subject":         subject,
        "tfidf_keywords":  tfidf_keywords,
        "keyword_matches": keyword_matches,
        "llm_result":      llm_result
    }