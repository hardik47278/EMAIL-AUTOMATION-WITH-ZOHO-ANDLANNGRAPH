import uuid
import json
import re
import logging
import redis
from datetime import datetime
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_anonymizer import AnonymizerEngine
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()

logging.basicConfig(level=logging.INFO)
audit_logger = logging.getLogger("pii_audit")


redis_client = redis.Redis(
    host="localhost",
    port=6379,
    db=2,
    decode_responses=True
)
MAPPING_TTL = 1800


analyzer   = AnalyzerEngine()
anonymizer = AnonymizerEngine()

llm    = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
parser = StrOutputParser()

CONTEXTUAL_PII_PROMPT = """
You are a privacy protection agent for a SaaS product company.

Review this text for sensitive information that regex cannot detect:
- Business confidential data
- Implicit credentials or passwords
- Internal company financial figures
- Sensitive business strategies
- Personal health information
- Confidential relationship information

Text:
{text}

Rules:
- If sensitive content found replace with {{SENSITIVE_CONTEXT}}
- If nothing sensitive found return text unchanged
- Return ONLY the cleaned text
- No explanation
- No preamble
"""

prompt = PromptTemplate(
    template=CONTEXTUAL_PII_PROMPT,
    input_variables=["text"]
)

llm_chain = prompt | llm | parser

# ─── QUICK CHECK PATTERNS ────────────────────────────────
QUICK_PATTERNS = {
    "email":       r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone":       r"\b[6-9]\d{9}\b",
    "aadhaar":     r"\b\d{4}\s\d{4}\s\d{4}\b",
    "pan":         r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "api_key":     r"(sk-|pk-|api-)[a-zA-Z0-9]{20,}",
    "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
}

# ─── CUSTOM RECOGNIZERS ──────────────────────────────────
analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="IN_AADHAAR",
    patterns=[Pattern("aadhaar", r"\b\d{4}\s\d{4}\s\d{4}\b", 0.9)],
    context=["aadhaar", "uid", "uidai"]
))

analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="IN_PAN",
    patterns=[Pattern("pan", r"\b[A-Z]{5}\d{4}[A-Z]\b", 0.9)],
    context=["pan", "income tax", "tax"]
))

analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="IN_UPI",
    patterns=[Pattern("upi", r"\b[\w\.\-]+@[\w]+\b", 0.85)],
    context=["upi", "gpay", "phonepe", "paytm"]
))

analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="IN_PHONE",
    patterns=[Pattern("indian_phone", r"\b[6-9]\d{9}\b", 0.85)],
    context=["phone", "mobile", "call", "contact"]
))

analyzer.registry.add_recognizer(PatternRecognizer(
    supported_entity="API_KEY",
    patterns=[Pattern("api_key", r"\b(sk-|pk-|api-)[a-zA-Z0-9]{20,}\b", 0.95)],
    context=["api", "key", "token", "secret"]
))

ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "CREDIT_CARD", "LOCATION", "IN_AADHAAR",
    "IN_PAN", "IN_UPI", "IN_PHONE", "API_KEY"
]


def quick_check(text: str) -> bool:
    for pattern in QUICK_PATTERNS.values():
        if re.search(pattern, text):
            return True
    return False



def audit_log(entity_types: list, text_length: int, stage: str):
    audit_logger.info(json.dumps({
        "event":        "pii_detected",
        "stage":        stage,
        "entity_types": entity_types,
        "text_length":  text_length,
        "timestamp":    datetime.now().isoformat()
    }))



@traceable(name="anonymize")
def anonymize(text: str) -> tuple[str, str]:
    if not text or not text.strip():
        return text, None


    if not quick_check(text):
        # Still run LLM contextual check
        try:
            text = llm_chain.invoke({"text": text})
        except Exception as e:
            audit_logger.warning(f"LLM contextual check failed: {e}")
        return text, None

    # Presidio structured PII detection
    results = analyzer.analyze(
        text=text,
        entities=ENTITIES,
        language="en"
    )

    entity_counters = {}
    entity_mapping  = {}
    placeholder_map = {}

    for result in sorted(results, key=lambda x: x.start):
        entity_type = result.entity_type
        original    = text[result.start:result.end]

        if original in placeholder_map:
            continue

        entity_counters[entity_type] = entity_counters.get(entity_type, 0) + 1
        placeholder = f"{{{{{entity_type}_{entity_counters[entity_type]}}}}}"

        placeholder_map[original]   = placeholder
        entity_mapping[placeholder] = original

    anonymized_text = text
    for original in sorted(placeholder_map.keys(), key=len, reverse=True):
        anonymized_text = anonymized_text.replace(original, placeholder_map[original])

    # Audit log
    if results:
        audit_log(
            entity_types=list(set(r.entity_type for r in results)),
            text_length=len(text),
            stage="presidio"
        )


    try:
        anonymized_text = llm_chain.invoke({"text": anonymized_text})
        audit_logger.info("✅ LLM contextual PII check completed")
    except Exception as e:
        audit_logger.warning(f"LLM contextual check failed: {e}")

    # Store mapping in Redis
    session_id = str(uuid.uuid4())
    redis_client.setex(
        f"pii_session:{session_id}",
        MAPPING_TTL,
        json.dumps(entity_mapping)
    )

    return anonymized_text, session_id

@traceable(name="deanonymize")
def deanonymize(text: str, session_id: str) -> str:
    if not session_id or not text:
        return text

    mapping_json = redis_client.get(f"pii_session:{session_id}")

    if not mapping_json:
        audit_logger.warning(f"Session {session_id} not found or expired")
        return text

    entity_mapping = json.loads(mapping_json)

    restored_text = text
    for placeholder, original in sorted(
        entity_mapping.items(),
        key=lambda x: len(x[0]),
        reverse=True
    ):
        restored_text = restored_text.replace(placeholder, original)

    return restored_text

@traceable(name="anonymize_email", tags=["anonymize", "email"], metadata={"version": "1.0"})
def anonymize_email(email: dict) -> tuple[dict, dict]:
    session_ids = {}

    if email.get("subject"):
        anon_subject, sid = anonymize(email["subject"])
        email["subject"]  = anon_subject
        if sid:
            session_ids["subject"] = sid

    if email.get("body"):
        anon_body, sid = anonymize(email["body"])
        email["body"]  = anon_body
        if sid:
            session_ids["body"] = sid

    if email.get("attachments"):
        session_ids["attachments"] = []
        for i, attachment in enumerate(email["attachments"]):
            if attachment.get("text"):
                anon_text, sid     = anonymize(attachment["text"])
                attachment["text"] = anon_text
                if sid:
                    session_ids["attachments"].append({
                        "index":      i,
                        "session_id": sid
                    })

    return email, session_ids

@traceable(name="deanonymize_reply", tags=["deanonymize", "reply"], metadata={"version": "1.0"})
def deanonymize_reply(reply: str, session_ids: dict) -> str:
    if not reply:
        return reply

    restored = reply

    if session_ids.get("body"):
        restored = deanonymize(restored, session_ids["body"])

    if session_ids.get("subject"):
        restored = deanonymize(restored, session_ids["subject"])

    return restored