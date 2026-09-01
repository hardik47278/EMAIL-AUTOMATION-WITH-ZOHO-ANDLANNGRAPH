import re
from gmail import get_service, fetch_latest_email
from subgraph import (
    run_spam,
    run_intent,
    run_priority,
    run_personalization,
    run_meeting
)
from context_merger import context_merger
from humaninloop2 import hitl_graph
from langgraph.types import Command
from supabase_integration import write_email_record, update_customer_summary
import concurrent.futures

from pii_shield import anonymize_email, deanonymize_reply








def extract_email(sender: str) -> str:
    match = re.search(r'<(.+?)>', sender)
    if match:
        return match.group(1)
    return sender


def run_pipeline():

    service = get_service()
    
    from pii_shield import anonymize_email, deanonymize_reply

    emails = fetch_latest_email(service)
    for i, email in enumerate(emails):
      emails[i], session_ids = anonymize_email(email)
      emails[i]["_session_ids"] = session_ids
 

    if not emails:
        print("No emails found")
        return

    for email in emails:

        print(f"\n📩 Processing: {email['subject']}")

        spam_result = run_spam(email)

        if spam_result["route"] == "spam":
            print("🚨 Spam detected — skipping")
            continue

        intent_result = run_intent(email)
        intents = intent_result["intent_result"].get("intents", [])

        has_meeting = any(
            i.get("type") == "meeting"
            for i in intents
        )

        with concurrent.futures.ThreadPoolExecutor() as executor:

            f_priority = executor.submit(run_priority,email)
            f_personal = executor.submit(run_personalization,extract_email(email.get("sender", "")), email)
            f_meeting = executor.submit(run_meeting,email) if has_meeting else None

            priority_result = f_priority.result()
            personalization_result = f_personal.result()
            meeting_result = f_meeting.result() if f_meeting else None
        



     

        merged = context_merger(
            priority_result,
            personalization_result,
            meeting_result
        )

        config = {
            "configurable": {
                "thread_id": email["id"],
                "service": service
            }
        }

        result = hitl_graph.invoke(
            {
                "email": email,
                "merged_context": merged
            },
            config=config
        )

        # ✅ loop until human approves or edits
        while "__interrupt__" in result:

            payload = result["__interrupt__"][0].value

            print("\n⚠️ HUMAN REVIEW REQUIRED")
            print("=" * 50)
            print("Subject:", payload["email_subject"])
            print("Sender :", payload["sender"])
            print("\nGenerated Reply:")
            print("-" * 50)
            print(payload["generated_reply"])
            print("\nActions")
            print("1. approve")
            print("2. edit")
            print("3. regenerate")

            while True:
                choice = input("\nChoice: ").strip()
                if choice in ("1", "2", "3"):
                    break
                print("❌ Invalid choice. Please enter 1, 2, or 3.")

            if choice == "1":
                result = hitl_graph.invoke(
                    Command(resume={"action": "approve"}),
                    config=config
                )

            elif choice == "2":
                edited_reply = input("\nEnter edited reply:\n")
                result = hitl_graph.invoke(
                    Command(resume={"action": "edit", "edited_reply": edited_reply}),
                    config=config
                )

            elif choice == "3":
                feedback = input("\nFeedback for regeneration:\n")
                result = hitl_graph.invoke(
                    Command(resume={"action": "regenerate", "feedback": feedback}),
                    config=config
                )

        print("\n✅ Workflow completed")
        print(f"To       : {extract_email(email['sender'])}")
        print(f"Priority : {merged['priority']}")

        final_reply = result.get("final_reply","")
        session_ids = email.get("_session_ids",{})

        final_reply = deanonymize_reply(final_reply,session_ids)

        write_email_record(
            customer_id     = extract_email(email["sender"]),
            intent          = intents[0].get("type", "unknown") if intents else "unknown",
            urgency         = priority_result["priority_result"].get("priority", "MEDIUM"),
            sentiment       = personalization_result["personalization_context"].get("communication_personality", {}).get("tone", "neutral"),
            agent2_priority = priority_result["priority_result"].get("priority", "MEDIUM"),
            agent3_priority = priority_result["priority_result"].get("priority", "MEDIUM"),
            final_priority  = merged["priority"],
            resolved        = True,
            resolution      = result.get("final_reply", "")
        )

        update_customer_summary(
            extract_email(email["sender"])
        )

        print("💾 Memory updated")



       


if __name__ == "__main__":
    run_pipeline()