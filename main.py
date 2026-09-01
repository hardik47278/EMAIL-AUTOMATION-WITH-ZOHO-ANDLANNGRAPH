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
from email_sender import get_service
from humaninloop2 import hitl_graph
import uvicorn

load_dotenv()

app = FastAPI(title="WorkMates HIL API")
print("app created:", id(app))

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

redis_client = redis.Redis(host="localhost", port=6379, db=3, decode_responses=True)

PENDING_TTL = 3600

class EditRequest(BaseModel):
    edited_reply: str

class RegenerateRequest(BaseModel):
    feedback: str

def get_pending(thread_id: str) -> dict:
    raw = redis_client.get(f"hitl:pending:{thread_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Pending email not found or expired")
    return json.loads(raw)

def delete_pending(thread_id: str):
    redis_client.delete(f"hitl:pending:{thread_id}")

def get_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "service": get_service()}}

@app.get("/")
def home():
    return {"status": "WorkMates HIL API running"}

@app.get("/emails/pending")
def list_pending():
    keys = redis_client.keys("hitl:pending:*")
    pending = []
    for key in keys:
        try:
            data = json.loads(redis_client.get(key))
            pending.append({
                "thread_id": data["thread_id"], "sender": data["sender"],
                "subject": data["subject"], "draft_reply": data["draft_reply"],
                "priority": data.get("priority", "MEDIUM"), "timestamp": data.get("timestamp", ""),
            })
        except Exception:
            continue
    pending.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"pending": pending, "count": len(pending)}

@app.post("/emails/{thread_id}/approve")
def approve_email(thread_id: str):
    pending = get_pending(thread_id)
    try:
        result = hitl_graph.invoke(Command(resume={"action": "approve"}), config=get_config(thread_id))
        delete_pending(thread_id)
        return {"status": "approved", "thread_id": thread_id, "final_reply": result.get("final_reply", ""), "sent_to": pending["sender"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/emails/{thread_id}/edit")
def edit_email(thread_id: str, body: EditRequest):
    pending = get_pending(thread_id)
    try:
        result = hitl_graph.invoke(Command(resume={"action": "edit", "edited_reply": body.edited_reply}), config=get_config(thread_id))
        delete_pending(thread_id)
        return {"status": "edited", "thread_id": thread_id, "final_reply": body.edited_reply, "sent_to": pending["sender"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/emails/{thread_id}/regenerate")
def regenerate_email(thread_id: str, body: RegenerateRequest):
    pending = get_pending(thread_id)
    try:
        result = hitl_graph.invoke(Command(resume={"action": "regenerate", "feedback": body.feedback}), config=get_config(thread_id))
        if "__interrupt__" in result:
            new_draft = result["__interrupt__"][0].value.get("generated_reply", "")
            pending["draft_reply"] = new_draft
            redis_client.setex(f"hitl:pending:{thread_id}", PENDING_TTL, json.dumps(pending))
            return {"status": "regenerated", "thread_id": thread_id, "new_draft": new_draft, "message": "New draft ready for review"}
        delete_pending(thread_id)
        return {"status": "completed", "thread_id": thread_id, "final_reply": result.get("final_reply", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/emails/processed")
def list_processed(limit: int = 20):
    try:
        from supabase import create_client
        supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        result = supabase.table("email_history").select("*").order("date", desc=True).limit(limit).execute()
        return {"emails": result.data, "count": len(result.data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/emails/stats")
def get_stats():
    try:
        from supabase import create_client
        supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        all_emails = supabase.table("email_history").select("*").execute().data
        today = datetime.now().date().isoformat()
        today_emails = [e for e in all_emails if e.get("date", "")[:10] == today]
        high_priority = [e for e in all_emails if e.get("final_priority") == "HIGH" and not e.get("resolved")]
        return {
            "total_today": len(today_emails),
            "need_attention": len(high_priority),
            "pending_approval": len(redis_client.keys("hitl:pending:*")),
            "total_processed": len(all_emails)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)