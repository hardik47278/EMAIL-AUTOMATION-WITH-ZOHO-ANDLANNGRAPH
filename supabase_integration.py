import os
from supabase import create_client, Client
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)


def fetch_email_history(customer_id: str) -> list:
    try:
        result = supabase.table("email_history") \
            .select("*") \
            .eq("customer_id", customer_id) \
            .order("date", desc=True) \
            .execute()
        return result.data
    except Exception as e:
        print(f"Error: {e}")
        return []


def fetch_email_count(customer_id: str) -> int:
    try:
        result = supabase.table("email_history") \
            .select("id", count="exact") \
            .eq("customer_id", customer_id) \
            .execute()
        return result.count or 0
    except Exception as e:
        print(f"Error: {e}")
        return 0


def fetch_unresolved_issues(customer_id: str) -> list:
    try:
        result = supabase.table("email_history") \
            .select("*") \
            .eq("customer_id", customer_id) \
            .eq("resolved", False) \
            .execute()
        return result.data
    except Exception as e:
        print(f"Error: {e}")
        return []


def fetch_customer_summary(customer_id: str) -> dict:
    try:
        result = supabase.table("customer_summary") \
            .select("*") \
            .eq("customer_id", customer_id) \
            .execute()
        if result.data:
            return result.data[0]
        return {}
    except Exception as e:
        print(f"Error: {e}")
        return {}


def fetch_sentiment_trend(customer_id: str) -> list:
    try:
        result = supabase.table("email_history") \
            .select("date, sentiment") \
            .eq("customer_id", customer_id) \
            .order("date", desc=False) \
            .execute()
        return result.data
    except Exception as e:
        print(f"Error: {e}")
        return []


def fetch_intent_frequency(customer_id: str) -> dict:
    try:
        result = supabase.table("email_history") \
            .select("intent") \
            .eq("customer_id", customer_id) \
            .execute()
        frequency = {}
        for row in result.data:
            intent = row["intent"]
            frequency[intent] = frequency.get(intent, 0) + 1
        return dict(sorted(frequency.items(), key=lambda x: x[1], reverse=True))
    except Exception as e:
        print(f"Error: {e}")
        return {}


def write_email_record(
    customer_id: str,
    intent: str,
    urgency: str,
    sentiment: str,
    agent2_priority: str,
    agent3_priority: str,
    final_priority: str,
    resolved: bool = False,
    resolution: Optional[str] = None,
    resolution_time_mins: Optional[int] = None,
    gmail_id: Optional[str] = None


) -> dict:
    try:
        data = {
            "customer_id":          customer_id,
            "date":                 datetime.now().isoformat(),
            "intent":               intent,
            "urgency":              urgency,
            "sentiment":            sentiment,
            "agent2_priority":      agent2_priority,
            "agent3_priority":      agent3_priority,
            "final_priority":       final_priority,
            "resolved":             resolved,
            "resolution":           resolution,
            "resolution_time_mins": resolution_time_mins,
            "gmail_id":             gmail_id

        }
        result = supabase.table("email_history").insert(data).execute()
        return result.data[0] if result.data else {}
    except Exception as e:
        print(f"Error: {e}")
        return {}


def update_customer_summary(customer_id: str) -> dict:
    try:
        history      = fetch_email_history(customer_id)
        unresolved   = fetch_unresolved_issues(customer_id)
        sentiments   = fetch_sentiment_trend(customer_id)
        intent_freq  = fetch_intent_frequency(customer_id)

        total_emails       = len(history)
        unresolved_count   = len(unresolved)
        most_common_intent = list(intent_freq.keys())[0] if intent_freq else None

        resolved_emails    = [e for e in history if e["resolved"] and e["resolution_time_mins"]]
        avg_resolution     = int(sum(e["resolution_time_mins"] for e in resolved_emails) / len(resolved_emails)) if resolved_emails else 0

        score_map = {"positive": 3, "neutral": 2, "frustrated": 1, "dissatisfied": 1, "angry": 0}
        recent    = sentiments[-5:]
        scores    = [score_map.get(s["sentiment"], 2) for s in recent]
        mid       = len(scores) // 2
        first_half  = sum(scores[:mid]) / max(len(scores[:mid]), 1)
        second_half = sum(scores[mid:]) / max(len(scores[mid:]), 1)

        if second_half > first_half + 0.5:
            sentiment_trend = "improving"
        elif second_half < first_half - 0.5:
            sentiment_trend = "declining"
        else:
            sentiment_trend = "stable"

        churn_risk = (
            unresolved_count >= 2 or
            sentiment_trend == "declining" or
            total_emails >= 5 or
            most_common_intent in ["churn_signal", "billing_dispute"]
        )

        if churn_risk and unresolved_count >= 2:
            health_status = "critical"
        elif churn_risk or sentiment_trend == "declining":
            health_status = "at_risk"
        else:
            health_status = "healthy"

        summary_data = {
            "customer_id":         customer_id,
            "total_emails":        total_emails,
            "unresolved_count":    unresolved_count,
            "most_common_intent":  most_common_intent,
            "last_contact_date":   datetime.now().isoformat(),
            "sentiment_trend":     sentiment_trend,
            "churn_risk":          churn_risk,
            "health_status":       health_status,
            "avg_resolution_mins": avg_resolution,
            "last_updated":        datetime.now().isoformat()
        }

        result = supabase.table("customer_summary").upsert(summary_data).execute()
        return result.data[0] if result.data else {}

    except Exception as e:
        print(f"Error: {e}")
        return {}