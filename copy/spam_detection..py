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


GROQ_API_KEY = os.getenv("GROQ_API_KEY")

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


def authenticate(api_key: str) -> bool:
    return api_key in VALID_API_KEYS if api_key else False



_rate_limit_store = {}
RATE_LIMIT_MAX = 10
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

def process_email(text: str):
    text = str(text).lower()
    text = re.sub(r"https\S+", "", text)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    words = text.split()

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
    words = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.toarray()[0]

    top = sorted(zip(words, scores), key=lambda x: x[1], reverse=True)[:10]

    return [w for w, s in top]


def rule_based_spam(full_text: str):
    return [kw for kw in SPAM_KEYWORDS if kw in full_text]


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
            "domain": domain,
            "registrar": str(w.registrar) if w.registrar else None,
            "creation_date": str(w.creation_date) if w.creation_date else None,
            "expiration_date": str(w.expiration_date) if w.expiration_date else None,
            "name_servers": (
                [str(ns) for ns in w.name_servers]
                if w.name_servers else None
            )
        }

    except Exception as e:
        return {
            "domain": domain,
            "error": str(e)
        }


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


class ToolTraceHandler(BaseCallbackHandler):

    def on_tool_start(self, serialized, input_str, **kwargs):
        print("\n🛠️ TOOL START:", serialized.get("name"))
        print("Input:", input_str)

    def on_tool_end(self, output, **kwargs):
        print("🧾 TOOL OUTPUT:", output)

    def on_agent_action(self, action, **kwargs):
        print("\n🤖 AGENT ACTION:", action.tool)
        print("Input:", action.tool_input)

    def on_agent_finish(self, finish, **kwargs):
        print("\n✅ FINAL RESULT:", finish.return_values)

def run_llm(email: dict):
    llm = "groq:llama-3.3-70b-versatile"

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt="""
You are an autonomous spam detection agent.

Use tools when needed:
- extract_domain
- get_whois_info
- dns_checks
- virustotal_check

Return ONLY JSON:
{
  "label": "spam or safe",
  "reason": "...",
  "tools_used": []
}
"""
    )

    result = agent.invoke({
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
    })

    print("\n================ AGENT OUTPUT ================\n")
    print(result)

    # ✅ parse here, inside the function
    import json
    final_content = result["messages"][-1].content
    try:
        return json.loads(final_content)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', final_content, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"label": "unknown", "reason": final_content, "tools_used": []}


@api_gateway
def detect_spam(email: dict, api_key: str = None):

    subject = email.get("subject", "")
    body = email.get("body", "")

    full_text = process_email(subject + " " + body)

    tfidf_keywords = run_tfidf(full_text)
    keyword_matches = rule_based_spam(full_text)

    llm_result = run_llm(email)

    return {
        "gmail_id": email.get("id"),
        "sender": email.get("sender"),
        "subject": subject,
        "tfidf_keywords": tfidf_keywords,
        "keyword_matches": keyword_matches,
        "llm_result": llm_result
    }