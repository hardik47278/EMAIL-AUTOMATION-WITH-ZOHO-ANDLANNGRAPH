import json
import re
import os
from datetime import datetime

from langsmith import traceable
import langsmith
from zoho_mail import get_service, fetch_latest_email
from subgraph import (
    run_spam,
    run_intent,
    run_priority,
    run_personalization,
    run_meeting
)
from context_merger2 import context_merger
from humaninloop2 import hitl_graph
from langgraph.types import Command
from supabase_integration import write_email_record, update_customer_summary
import concurrent.futures
import redis as redis_lib
from langsmith import traceable

from pii_shield import anonymize_email, deanonymize_reply
from prompt_safety import classify_prompt_injection


redis_hil = redis_lib.Redis(
    host="localhost",
    port=6379,
    db=3,
    decode_responses=True
)


def extract_email(sender: str) -> str:
    match = re.search(r'<(.+?)>', sender)
    if match:
        return match.group(1)
    return sender



@traceable(
    name="run_pipeline",
    tags=["pipeline", "main"],
    metadata={"version": "1.0"}
)
def run_pipeline():

    service = get_service()
    emails  = fetch_latest_email(service)

    if not emails:
        print("No emails found")
        return

    for email in emails:

        sender_domain = extract_email(
            email.get("sender", "")
        ).split("@")[-1]

        with langsmith.trace(
            name="process_email",
            tags=[
                "production",
                f"domain:{sender_domain}"
            ],
            metadata={
                "email_id":      email.get("id"),
                "email_sender":  email.get("sender"),
                "email_subject": email.get("subject")
            }
        ) as run:

            # ── DEBUG PRINT ───────────────────────────────────
            print("\n" + "="*60)
            print(f"📩 Subject: {email['subject']}")
            print(f"📎 Attachments: {email['attachments']}")
            print(f"\n📄 FULL MERGED BODY:\n{email['body'][:2000]}")
            print("="*60)

            # ── SUSPICIOUS ATTACHMENT CHECK ───────────────────
            attachments = email.get("attachments") or []
            flagged     = [a for a in attachments if a.get("flagged")]

            if flagged:
                filenames = ", ".join(a["filename"] for a in flagged)
                print(f"🚨 Suspicious attachment detected in '{email['subject']}': {filenames}")
                redis_hil.setex(
                    f"hitl:pending:{email['id']}",
                    3600,
                    json.dumps({
                        "thread_id":   email["id"],
                        "sender":      email["sender"],
                        "subject":     email["subject"],
                        "draft_reply": f"⚠️ Suspicious attachment detected: {filenames} — manual review required",
                        "priority":    "HIGH",
                        "timestamp":   datetime.now().isoformat()
                    })
                )
                continue

            print(f"\n📩 Processing: {email['subject']}")

            spam_result = run_spam(email)

            if spam_result["route"] == "spam":
                print("🚨 Spam detected — skipping")
                continue

            intent_result  = run_intent(email)
            intents        = intent_result["intent_result"].get("intents", [])
            primary_intent = intent_result["intent_result"].get("primary_intent", "")

            NO_REPLY_INTENTS = {
                "otp", "promotion", "newsletter", "order_update",
                "payment_receipt", "subscription", "system_alert",
                "social_notification", "job_alert"
            }

            if primary_intent in NO_REPLY_INTENTS:
                print(f"📋 Log-only intent ({primary_intent}) — storing for dashboard, no reply")
                write_email_record(
                    customer_id     = extract_email(email["sender"]),
                    intent          = primary_intent,
                    urgency         = "LOW",
                    sentiment       = "neutral",
                    agent2_priority = "LOW",
                    agent3_priority = "LOW",
                    final_priority  = "LOW",
                    resolved        = True,
                    resolution      = "",
                    gmail_id        = email["id"]
                )
                continue

            has_meeting = any(
                i.get("type") == "meeting"
                for i in intents
            )

            with concurrent.futures.ThreadPoolExecutor() as executor:

                f_priority = executor.submit(run_priority, email)
                f_personal = executor.submit(
                    run_personalization,
                    extract_email(email.get("sender", "")),
                    email
                )
                f_meeting = executor.submit(
                    run_meeting, email
                ) if has_meeting else None

                priority_result        = f_priority.result()
                personalization_result = f_personal.result()
                meeting_result         = f_meeting.result() if f_meeting else None

                if isinstance(personalization_result, str):
                    personalization_result = json.loads(personalization_result)

            merged = context_merger(
                priority_result,
                personalization_result,
                meeting_result,
                intent_result["intent_result"]
            )

            config = {
                "configurable": {
                    "thread_id": email["id"],
                    "service":   service
                }
            }

            # ── SAVE TO REDIS BEFORE HITL ─────────────────────
            redis_hil.setex(
                f"hitl:pending:{email['id']}",
                3600,
                json.dumps({
                    "thread_id":   email["id"],
                    "sender":      email["sender"],
                    "subject":     email["subject"],
                    "draft_reply": "",
                    "priority":    merged.get("priority", "MEDIUM"),
                    "timestamp":   datetime.now().isoformat()
                })
            )

            result = hitl_graph.invoke(
                {
                    "email":          email,
                    "merged_context": merged
                },
                config=config
            )

            # ── UPDATE DRAFT IN REDIS AFTER INTERRUPT ─────────
            if "__interrupt__" in result:
                payload = result["__interrupt__"][0].value
                draft   = payload.get("generated_reply", "")
                raw     = redis_hil.get(f"hitl:pending:{email['id']}")
                if raw:
                    data = json.loads(raw)
                    data["draft_reply"] = draft
                    redis_hil.setex(
                        f"hitl:pending:{email['id']}",
                        3600,
                        json.dumps(data)
                    )

                print(f"⏳ Awaiting human review via dashboard — thread: {email['id']}")
                continue

            # ── NO INTERRUPT: pipeline completed ──────────────
            redis_hil.delete(f"hitl:pending:{email['id']}")

            print("\n✅ Workflow completed")
            print(f"To       : {extract_email(email['sender'])}")
            print(f"Priority : {merged['priority']}")

            write_email_record(
                customer_id     = extract_email(email["sender"]),
                intent          = intents[0].get("type", "unknown") if intents else "unknown",
                urgency         = priority_result["priority_result"].get("priority", "MEDIUM"),
                sentiment       = personalization_result["personalization_context"].get("communication_personality", {}).get("tone", "neutral"),
                agent2_priority = priority_result["priority_result"].get("priority", "MEDIUM"),
                agent3_priority = priority_result["priority_result"].get("priority", "MEDIUM"),
                final_priority  = merged["priority"],
                resolved        = True,
                resolution      = result.get("final_reply", ""),
                gmail_id        = email["id"]
            )

            update_customer_summary(
                extract_email(email["sender"])
            )

            print("💾 Memory updated")


if __name__ == "__main__":
    run_pipeline()