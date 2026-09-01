import os
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

import json
import redis
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from langgraph.types import Command
from zoho_mail import get_service
from humaninloop2 import hitl_graph
import uvicorn
from summarizer_agent import summarize_email


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


app = FastAPI(title="WorkMates HIL API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── REDIS ─────────────────────────────────────────────────
redis_client = redis.Redis(
    host="localhost",
    port=6379,
    db=3,
    decode_responses=True
)

PENDING_TTL = 3600


# ── MODELS ───────────────────────────────────────────────
class EditRequest(BaseModel):
    edited_reply: str

class RegenerateRequest(BaseModel):
    feedback: str


# ── HELPERS ──────────────────────────────────────────────
def get_pending(thread_id: str) -> dict:
    raw = redis_client.get(f"hitl:pending:{thread_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Pending email not found or expired")
    return json.loads(raw)

def delete_pending(thread_id: str):
    redis_client.delete(f"hitl:pending:{thread_id}")

def get_config(thread_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "service": get_service()
        }
    }


# ── ENDPOINTS ────────────────────────────────────────────

@app.get("/")
def home():
    return {"status": "WorkMates HIL API running"}


@app.get("/emails/pending")
def list_pending():
    keys = redis_client.keys("hitl:pending:*")
    pending = []
    for key in keys:
        try:
            raw  = redis_client.get(key)
            data = json.loads(raw)
            pending.append({
                "thread_id":   data["thread_id"],
                "sender":      data["sender"],
                "subject":     data["subject"],
                "draft_reply": data["draft_reply"],
                "priority":    data.get("priority", "MEDIUM"),
                "timestamp":   data.get("timestamp", ""),
            })
        except Exception:
            continue
    pending.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"pending": pending, "count": len(pending)}


@app.post("/emails/{thread_id}/approve")
def approve_email(thread_id: str):
    pending = get_pending(thread_id)
    try:
        result = hitl_graph.invoke(
            Command(resume={"action": "approve"}),
            config=get_config(thread_id)
        )
        delete_pending(thread_id)
        return {
            "status":      "approved",
            "thread_id":   thread_id,
            "final_reply": result.get("final_reply", ""),
            "sent_to":     pending["sender"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{thread_id}/edit")
def edit_email(thread_id: str, body: EditRequest):
    pending = get_pending(thread_id)
    try:
        result = hitl_graph.invoke(
            Command(resume={
                "action":       "edit",
                "edited_reply": body.edited_reply
            }),
            config=get_config(thread_id)
        )
        delete_pending(thread_id)
        return {
            "status":      "edited",
            "thread_id":   thread_id,
            "final_reply": body.edited_reply,
            "sent_to":     pending["sender"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{thread_id}/regenerate")
def regenerate_email(thread_id: str, body: RegenerateRequest):
    pending = get_pending(thread_id)
    try:
        result = hitl_graph.invoke(
            Command(resume={
                "action":   "regenerate",
                "feedback": body.feedback
            }),
            config=get_config(thread_id)
        )

        if "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            new_draft = payload.get("generated_reply", "")
            pending["draft_reply"] = new_draft
            redis_client.setex(
                f"hitl:pending:{thread_id}",
                PENDING_TTL,
                json.dumps(pending)
            )
            return {
                "status":    "regenerated",
                "thread_id": thread_id,
                "new_draft": new_draft,
                "message":   "New draft ready for review"
            }

        delete_pending(thread_id)
        return {
            "status":      "completed",
            "thread_id":   thread_id,
            "final_reply": result.get("final_reply", "")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/processed")
def list_processed(limit: int = 20):
    try:
        from supabase import create_client
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        result = supabase.table("email_history") \
            .select("*") \
            .order("date", desc=True) \
            .limit(limit) \
            .execute()
        return {"emails": result.data, "count": len(result.data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/stats")
def get_stats():
    try:
        from supabase import create_client
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        all_emails = supabase.table("email_history") \
            .select("*") \
            .execute().data

        today = datetime.now().date().isoformat()
        today_emails = [
            e for e in all_emails
            if e.get("date", "")[:10] == today
        ]
        high_priority = [
            e for e in all_emails
            if e.get("final_priority") == "HIGH" and not e.get("resolved")
        ]
        pending_count = len(redis_client.keys("hitl:pending:*"))

        return {
            "total_today":      len(today_emails),
            "need_attention":   len(high_priority),
            "pending_approval": pending_count,
            "total_processed":  len(all_emails)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/log-only")
def list_log_only(limit: int = 30):
    try:
        from supabase import create_client
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        NO_REPLY_INTENTS = [
            "otp", "promotion", "newsletter", "order_update",
            "payment_receipt", "subscription", "system_alert",
            "social_notification", "job_alert"
        ]
        result = supabase.table("email_history") \
            .select("*") \
            .in_("intent", NO_REPLY_INTENTS) \
            .order("date", desc=True) \
            .limit(limit) \
            .execute()
        return {"emails": result.data, "count": len(result.data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{gmail_id}/summarize")
def summarize(gmail_id: str):
    try:
        from gmail import get_service, extract_body
        from html_cleanup import clean_html_email
        from summarizer_agent import summarize_email

        service  = get_service()
        msg_data = service.users().messages().get(
            userId="me",
            id=gmail_id,
            format="full"
        ).execute()

        email_body = extract_body(msg_data["payload"])
        email_body = clean_html_email(email_body)

        attachments = []
        for part in msg_data["payload"].get("parts", []):
            filename = part.get("filename", "")
            if filename:
                attachments.append({
                    "filename": filename,
                    "text": ""
                })

        if not email_body.strip():
            raise HTTPException(
                status_code=422,
                detail="No email body found"
            )

        result = summarize_email(email_body)
        return {
            "gmail_id":       gmail_id,
            "summary":        result["summary"],
            "entities":       result["entities"],
            "judge_score":    result["judge_score"],
            "judge_feedback": result["judge_feedback"],
            "attempts":       result["attempts"],
            "passed":         result["passed"]
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("SUMMARIZE ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)