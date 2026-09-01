from gmail import get_service, fetch_latest_email
from subgraph import run_spam, run_intent, run_priority, run_personalization, run_meeting

def run_pipeline():
    service = get_service()
    emails  = fetch_latest_email(service)

    if not emails:
        print("No emails found")
        return

    for email in emails:
        
        # Step 1 — spam check
        spam_result = run_spam(email)
        
        if spam_result["route"] == "spam":
            print(f"Spam detected: {email['subject']}")
            continue
        
        # Step 2 — intent
        intent_result = run_intent(email)
        intents       = intent_result["intent_result"]["intents"]
        has_meeting   = any(i["type"] == "meeting" for i in intents)
        
        # Step 3 — parallel agents
        priority_result         = run_priority(email)
        personalization_result  = run_personalization(email["sender"], email)
        
        # Step 4 — meeting if needed
        meeting_result = run_meeting(email) if has_meeting else None
        
        # Step 5 — context merger (coming next)
        print(f"Priority:        {priority_result['priority_result']}")
        print(f"Personalization: {personalization_result['personalization_context']}")
        print(f"Meeting:         {meeting_result}")

if __name__ == "__main__":
    run_pipeline()