import streamlit as st
import requests
import json
from datetime import datetime

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="WorkMates",
    page_icon="📧",
    layout="wide"
)

# ── CUSTOM CSS (dark / monospace) ─────────────────────────
st.markdown("""
<style>

@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'JetBrains Mono', monospace;
}

.stApp {
    background-color: #0b0c10;
}

/* ── header banner ── */
.header-banner {
    background: #14151c;
    border: 1px solid #2a2c3a;
    border-radius: 14px;
    padding: 28px 32px;
    margin-bottom: 24px;
}
.header-label {
    color: #8b8fff;
    font-size: 12px;
    letter-spacing: 3px;
    font-weight: 600;
    margin-bottom: 10px;
}
.header-title {
    color: #f5f5fa;
    font-size: 32px;
    font-weight: 700;
    margin-bottom: 10px;
}
.header-sub {
    color: #6b6f80;
    font-size: 13px;
    letter-spacing: 1px;
}

/* ── generic dark card ── */
.email-card {
    background: #14151c;
    border: 1px solid #2a2c3a;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    border-left: 4px solid #6366f1;
}
.priority-high   { border-left-color: #ef4444 !important; }
.priority-medium { border-left-color: #f97316 !important; }
.priority-low    { border-left-color: #22c55e !important; }

/* ── badges ── */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    margin-right: 6px;
    letter-spacing: 1px;
}
.badge-high   { background: #ef444422; color: #ef4444; }
.badge-medium { background: #f9731622; color: #f97316; }
.badge-low    { background: #22c55e22; color: #22c55e; }

/* ── intent badges (log-only box) ── */
.badge-intent {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    background: #6366f122;
    color: #818cf8;
}

/* ── streamlit containers as cards ── */
div[data-testid="stContainer"] {
    background: #14151c;
    border: 1px solid #2a2c3a !important;
    border-radius: 12px;
}

/* ── metric tweaks ── */
div[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
}
div[data-testid="stMetricLabel"] {
    letter-spacing: 2px;
    font-size: 11px;
    color: #6b6f80;
    text-transform: uppercase;
}

/* ── tabs ── */
.stTabs [data-baseweb="tab"] {
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 1px;
}

/* ── buttons ── */
.stButton button {
    font-family: 'JetBrains Mono', monospace;
    border-radius: 8px;
    letter-spacing: 1px;
}

</style>
""", unsafe_allow_html=True)


# ── INTENT CATEGORIES THAT SKIP REPLY/HIL ─────────────────
NO_REPLY_INTENTS = {
    "otp", "promotion", "newsletter", "order_update",
    "payment_receipt", "subscription", "system_alert",
    "social_notification", "job_alert"
}


# ── API HELPERS ───────────────────────────────────────────
def get_pending():
    try:
        r = requests.get(f"{API_URL}/emails/pending", timeout=5)
        return r.json().get("pending", [])
    except:
        return []

def get_processed():
    try:
        r = requests.get(f"{API_URL}/emails/processed?limit=20", timeout=5)
        return r.json().get("emails", [])
    except:
        return []

def get_stats():
    try:
        r = requests.get(f"{API_URL}/emails/stats", timeout=5)
        return r.json()
    except:
        return {}

def get_log_only():
    """Fetch OTP/promo/newsletter/etc emails (no reply generated)."""
    try:
        r = requests.get(f"{API_URL}/emails/log-only?limit=30", timeout=5)
        return r.json().get("emails", [])
    except:
        return []

def approve(thread_id):
    try:
        r = requests.post(f"{API_URL}/emails/{thread_id}/approve", timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def edit_reply(thread_id, edited_reply):
    try:
        r = requests.post(
            f"{API_URL}/emails/{thread_id}/edit",
            json={"edited_reply": edited_reply},
            timeout=10
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def regenerate(thread_id, feedback):
    try:
        r = requests.post(
            f"{API_URL}/emails/{thread_id}/regenerate",
            json={"feedback": feedback},
            timeout=30
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def summarize_email_api(gmail_id):
    try:
        r = requests.post(
            f"{API_URL}/emails/{gmail_id}/summarize",
            timeout=60
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── HEADER BANNER ─────────────────────────────────────────
st.markdown("""
<div class="header-banner">
    <div class="header-label">WORKMATES // EMAIL ASSISTANT</div>
    <div class="header-title">📧 WorkMates Inbox</div>
    <div class="header-sub">LangGraph · Celery · Redis · Supabase · Gmail</div>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([5, 1])
with col2:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

st.divider()

# ── LOAD DATA ─────────────────────────────────────────────
pending   = get_pending()
processed = get_processed()
stats     = get_stats()
log_only  = get_log_only()

# ── TABS ──────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    f"⏳ PENDING APPROVALS ({len(pending)})",
    "📩 INBOX",
    f"🔔 AUTO-LOGGED ({len(log_only)})",
    "📊 INSIGHTS"
])


# ═══════════════════════════════════════════════════════════
# TAB 1 — PENDING APPROVALS
# ═══════════════════════════════════════════════════════════
with tab1:

    if not pending:
        st.success("✅ All caught up! No emails waiting for approval.")
    else:
        st.subheader(f"📬 {len(pending)} email(s) need your review")
        st.caption("Review AI-generated replies before they are sent")
        st.divider()

        for email in pending:
            thread_id   = email["thread_id"]
            sender      = email["sender"]
            subject     = email["subject"]
            draft       = email["draft_reply"]
            priority    = email.get("priority", "MEDIUM")
            timestamp   = email.get("timestamp", "")[:19]

            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(priority, "⚪")
            priority_class = f"priority-{priority.lower()}"

            with st.container(border=True):

                # ── email header ──
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"### {priority_icon} {subject}")
                    st.caption(f"From: {sender} • {timestamp}")
                with col2:
                    st.markdown(f"<span class='badge badge-{priority.lower()}'>{priority}</span>", unsafe_allow_html=True)

                st.divider()

                # ── AI draft reply ──
                st.markdown("**✨ AI Generated Reply**")
                if draft:
                    st.info(draft)
                else:
                    st.warning("Draft not ready yet — pipeline still processing")

                st.divider()

                # ── action buttons ──
                st.markdown("**Choose an action:**")
                b1, b2, b3 = st.columns(3)

                # ── APPROVE ──
                with b1:
                    if st.button(
                        "✅ Send Reply",
                        key=f"approve_{thread_id}",
                        use_container_width=True,
                        type="primary"
                    ):
                        with st.spinner("Sending..."):
                            result = approve(thread_id)
                        if "error" in result:
                            st.error(f"Error: {result['error']}")
                        else:
                            st.success("✅ Reply sent successfully!")
                            st.rerun()

                # ── EDIT ──
                with b2:
                    if st.button(
                        "✏️ Edit Reply",
                        key=f"edit_btn_{thread_id}",
                        use_container_width=True
                    ):
                        st.session_state[f"show_edit_{thread_id}"] = True

                # ── REGENERATE ──
                with b3:
                    if st.button(
                        "🔄 Regenerate",
                        key=f"regen_btn_{thread_id}",
                        use_container_width=True
                    ):
                        st.session_state[f"show_regen_{thread_id}"] = True

                # ── EDIT POPUP ──
                if st.session_state.get(f"show_edit_{thread_id}"):
                    with st.expander("✏️ Edit Reply", expanded=True):
                        edited = st.text_area(
                            "Edit the reply below:",
                            value=draft,
                            height=200,
                            key=f"edit_text_{thread_id}"
                        )
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            if st.button(
                                "📤 Send Edited Reply",
                                key=f"send_edit_{thread_id}",
                                type="primary",
                                use_container_width=True
                            ):
                                with st.spinner("Sending..."):
                                    result = edit_reply(thread_id, edited)
                                if "error" in result:
                                    st.error(f"Error: {result['error']}")
                                else:
                                    st.success("✅ Edited reply sent!")
                                    del st.session_state[f"show_edit_{thread_id}"]
                                    st.rerun()
                        with ec2:
                            if st.button(
                                "Cancel",
                                key=f"cancel_edit_{thread_id}",
                                use_container_width=True
                            ):
                                del st.session_state[f"show_edit_{thread_id}"]
                                st.rerun()

                # ── REGENERATE POPUP ──
                if st.session_state.get(f"show_regen_{thread_id}"):
                    with st.expander("🔄 Regenerate Reply", expanded=True):
                        feedback = st.text_area(
                            "What should the new reply focus on?",
                            placeholder="e.g. Be more formal, mention the refund policy, add meeting availability...",
                            height=100,
                            key=f"regen_text_{thread_id}"
                        )
                        rc1, rc2 = st.columns(2)
                        with rc1:
                            if st.button(
                                "🔄 Generate New Reply",
                                key=f"send_regen_{thread_id}",
                                type="primary",
                                use_container_width=True
                            ):
                                if not feedback.strip():
                                    st.warning("Please enter feedback first")
                                else:
                                    with st.spinner("Regenerating reply..."):
                                        result = regenerate(thread_id, feedback)
                                    if "error" in result:
                                        st.error(f"Error: {result['error']}")
                                    elif result.get("status") == "regenerated":
                                        st.success("✅ New draft ready!")
                                        del st.session_state[f"show_regen_{thread_id}"]
                                        st.rerun()
                                    else:
                                        st.success("✅ Reply sent!")
                                        del st.session_state[f"show_regen_{thread_id}"]
                                        st.rerun()
                        with rc2:
                            if st.button(
                                "Cancel",
                                key=f"cancel_regen_{thread_id}",
                                use_container_width=True
                            ):
                                del st.session_state[f"show_regen_{thread_id}"]
                                st.rerun()

            st.divider()


# ═══════════════════════════════════════════════════════════
# TAB 2 — INBOX
# ═══════════════════════════════════════════════════════════
with tab2:

    st.subheader("📩 Recent Emails")
    st.caption("Emails processed by your AI assistant")

    if not processed:
        st.info("No processed emails yet.")
    else:
        # ── filters ──
        f1, f2 = st.columns(2)
        with f1:
            priorities = ["ALL"] + list(set(
                e.get("final_priority", "MEDIUM")
                for e in processed
                if e.get("final_priority")
            ))
            priority_filter = st.selectbox("Priority", priorities, key="inbox_priority")

        with f2:
            intents = ["ALL"] + list(set(
                e.get("intent", "unknown")
                for e in processed
                if e.get("intent")
            ))
            intent_filter = st.selectbox("Intent", intents, key="inbox_intent")

        # apply filters
        filtered = processed
        if priority_filter != "ALL":
            filtered = [e for e in filtered if e.get("final_priority") == priority_filter]
        if intent_filter != "ALL":
            filtered = [e for e in filtered if e.get("intent") == intent_filter]

        st.caption(f"Showing {len(filtered)} emails")
        st.divider()

        for email in filtered:
            customer   = email.get("customer_id", "Unknown")
            intent     = email.get("intent", "unknown")
            priority   = email.get("final_priority", "MEDIUM")
            sentiment  = email.get("sentiment", "neutral")
            date       = str(email.get("date", ""))[:19]
            resolved   = email.get("resolved", False)
            resolution = email.get("resolution", "")
            gmail_id   = email.get("gmail_id") or email.get("id")

            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(priority, "⚪")
            sentiment_icon = {
                "positive": "😊",
                "neutral":  "😐",
                "negative": "😞",
                "frustrated": "😤",
                "angry": "😠"
            }.get(sentiment, "😐")

            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 1, 1])

                with col1:
                    st.markdown(f"**{priority_icon} {customer}**")
                    st.caption(f"🎯 {intent.replace('_', ' ').title()} • {sentiment_icon} {sentiment} • {date}")

                with col2:
                    st.markdown(f"<span class='badge badge-{priority.lower()}'>{priority}</span>", unsafe_allow_html=True)

                with col3:
                    if resolved:
                        st.markdown("✅ **Sent**")
                    else:
                        st.markdown("⏳ **Pending**")

                if resolution:
                    with st.expander("View Reply Sent"):
                        st.write(resolution)

                # ── SUMMARIZE BUTTON ──
                if gmail_id and st.button("🔍 Summarize", key=f"sum_{gmail_id}"):
                    with st.spinner("Summarizing..."):
                        data = summarize_email_api(gmail_id)

                    if "error" in data:
                        st.error(f"Error: {data['error']}")
                    else:
                        with st.expander("📋 Summary", expanded=True):
                            st.write(data.get("summary", "No summary returned"))
                            scores = data.get("scores", {})
                            st.caption(
                                f"Score: {scores.get('final', 'N/A')} | "
                                f"Attempts: {data.get('attempts', 'N/A')} | "
                                f"Tokens used: {data.get('tokens_used', 'N/A')}"
                            )


# ═══════════════════════════════════════════════════════════
# TAB 3 — AUTO-LOGGED (OTP / Promotion / Newsletter / etc)
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
# TAB 3 — AUTO-LOGGED (OTP / Promotion / Newsletter / etc)
# ═══════════════════════════════════════════════════════════
with tab3:

    st.subheader("🔔 Auto-Logged Emails")
    st.caption("OTP, promotions, newsletters & notifications — no reply generated, no review needed")
    st.divider()

    INTENT_ICONS = {
        "otp":                  "🔑",
        "promotion":            "🏷️",
        "newsletter":           "📰",
        "order_update":         "📦",
        "payment_receipt":      "🧾",
        "subscription":         "🔄",
        "system_alert":         "⚙️",
        "social_notification":  "🔔",
        "job_alert":            "💼",
    }

    if not log_only:
        st.info("No auto-logged emails yet.")
    else:
        # ── COUNT BOXES PER CATEGORY ──
        counts = {}
        for e in log_only:
            intent = e.get("intent", "unknown")
            counts[intent] = counts.get(intent, 0) + 1

        intents_sorted = sorted(counts.items(), key=lambda x: -x[1])
        cols_per_row = 5

        for i in range(0, len(intents_sorted), cols_per_row):
            row = intents_sorted[i:i + cols_per_row]
            cols = st.columns(cols_per_row)
            for col, (intent, count) in zip(cols, row):
                icon = INTENT_ICONS.get(intent, "📌")
                with col:
                    st.metric(
                        f"{icon} {intent.replace('_', ' ').title()}",
                        count
                    )

        st.divider()

        # ── intent filter ──
        intent_options = ["ALL"] + sorted(set(
            e.get("intent", "unknown") for e in log_only if e.get("intent")
        ))
        intent_filter = st.selectbox("Filter by type", intent_options, key="logonly_intent")

        filtered_log = log_only
        if intent_filter != "ALL":
            filtered_log = [e for e in filtered_log if e.get("intent") == intent_filter]

        st.caption(f"Showing {len(filtered_log)} emails")
        st.divider()

        for email in filtered_log:
            customer = email.get("customer_id", "Unknown")
            intent   = email.get("intent", "unknown")
            date     = str(email.get("date", ""))[:19]
            icon     = INTENT_ICONS.get(intent, "📌")

            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{icon} {customer}**")
                    st.caption(f"{date}")
                with col2:
                    st.markdown(
                        f"<span class='badge-intent'>{intent.replace('_', ' ').upper()}</span>",
                        unsafe_allow_html=True
                    )



    

# ═══════════════════════════════════════════════════════════
# TAB 4 — INSIGHTS
# ═══════════════════════════════════════════════════════════
with tab4:

    st.subheader("📊 Your Email Insights")

    # ── KPI cards ──
    total_today      = stats.get("total_today", 0)
    need_attention   = stats.get("need_attention", 0)
    pending_approval = stats.get("pending_approval", 0)
    total_processed  = stats.get("total_processed", 0)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "📩 Emails Today",
        total_today,
        help="Emails processed today"
    )
    c2.metric(
        "🚨 Need Attention",
        need_attention,
        delta=f"-{need_attention}" if need_attention > 0 else None,
        delta_color="inverse",
        help="High priority unresolved emails"
    )
    c3.metric(
        "⏳ Awaiting Approval",
        pending_approval,
        help="Emails waiting for your review"
    )
    c4.metric(
        "✅ Total Processed",
        total_processed,
        help="All emails handled by AI"
    )

    st.divider()

    # ── alerts ──
    if pending_approval > 0:
        st.warning(f"⏳ **{pending_approval} email(s) waiting for your approval** — check the Pending tab")

    if need_attention > 0:
        st.error(f"🚨 **{need_attention} high priority email(s) need attention**")

    if pending_approval == 0 and need_attention == 0:
        st.success("🎉 Everything is under control! No action needed right now.")

    st.divider()

    # ── simple breakdown ──
    if processed:
        st.subheader("Priority Breakdown")
        priority_counts = {}
        for e in processed:
            p = e.get("final_priority", "MEDIUM")
            priority_counts[p] = priority_counts.get(p, 0) + 1

        for p, count in priority_counts.items():
            icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(p, "⚪")
            st.markdown(f"{icon} **{p}** — {count} email(s)")