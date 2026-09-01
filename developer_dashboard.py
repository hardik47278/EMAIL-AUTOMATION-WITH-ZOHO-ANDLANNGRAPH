import os
import streamlit as st
import redis
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── PAGE CONFIG ───────────────────────────────────────────
st.set_page_config(
    page_title="WorkMates — Dev Dashboard",
    page_icon="🛠️",
    layout="wide"
)

# ── CUSTOM CSS ────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.dev-header {
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 24px;
}

.status-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 24px;
}

.status-card {
    background: #0f0f1a;
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}

.status-dot-alive {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #22c55e;
    box-shadow: 0 0 8px #22c55e88;
    margin-right: 6px;
    animation: pulse 2s infinite;
}

.status-dot-dead {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #ef4444;
    margin-right: 6px;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
}

.metric-card {
    background: #0f0f1a;
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 18px;
}

.metric-label {
    font-size: 11px;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 6px;
}

.metric-value {
    font-size: 28px;
    font-weight: 600;
    color: #e2e8f0;
    font-family: 'JetBrains Mono', monospace;
}

.metric-sub {
    font-size: 12px;
    color: #6b7280;
    margin-top: 4px;
}

.trace-row {
    background: #0f0f1a;
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
}

.trace-row:hover {
    border-color: #6366f1;
}

.node-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
}

.node-model      { background: #6366f122; color: #818cf8; }
.node-analysis   { background: #f59e0b22; color: #fbbf24; }
.node-agent      { background: #06b6d422; color: #22d3ee; }
.node-guardrails { background: #8b5cf622; color: #a78bfa; }
.node-send       { background: #22c55e22; color: #4ade80; }
.node-other      { background: #6b728022; color: #9ca3af; }

.error-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    background: #ef444422;
    color: #f87171;
}

.interrupt-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    background: #f59e0b22;
    color: #fbbf24;
}

.ok-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    background: #22c55e22;
    color: #4ade80;
}

.section-title {
    font-size: 13px;
    font-weight: 600;
    color: #6366f1;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 12px;
}

.hitl-bar {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 8px;
}

.hitl-label {
    font-size: 12px;
    color: #9ca3af;
    width: 90px;
    font-family: 'JetBrains Mono', monospace;
}

.hitl-fill {
    height: 8px;
    border-radius: 4px;
}

.celery-task {
    background: #0f0f1a;
    border: 1px solid #1e1e3a;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #9ca3af;
}
</style>
""", unsafe_allow_html=True)


# ── CLIENTS ───────────────────────────────────────────────
redis_client = redis.Redis(
    host="localhost", port=6379, db=3, decode_responses=True
)
redis_celery = redis.Redis(
    host="localhost", port=6379, db=0, decode_responses=True
)

def get_langsmith_client():
    from langsmith import Client
    return Client(
        api_url=os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
        api_key=os.getenv("LANGCHAIN_API_KEY")
    )


# ── STATUS CHECKS ─────────────────────────────────────────
def check_redis():
    try:
        redis_client.ping()
        return True, "Connected"
    except Exception as e:
        return False, str(e)

def check_imap():
    try:
        alive = redis_client.exists("health:imap")
        if alive:
            ttl = redis_client.ttl("health:imap")
            return True, f"Heartbeat ({ttl}s ago)"
        return False, "No heartbeat — listener may be down"
    except:
        return False, "Redis unreachable"

def check_celery():
    try:
        from celery_app import celery
        inspect = celery.control.inspect(timeout=2)
        ping = inspect.ping()
        if ping:
            workers = list(ping.keys())
            return True, f"{len(workers)} worker(s) online"
        return False, "No workers responding"
    except Exception as e:
        return False, str(e)

def check_supabase():
    try:
        from supabase import create_client
        sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        sb.table("email_history").select("customer_id").limit(1).execute()
        return True, "Connected"
    except Exception as e:
        return False, str(e)

def check_gmail():
    try:
        from email_sender import get_service
        svc = get_service()
        svc.users().getProfile(userId="me").execute()
        return True, "Authenticated"
    except Exception as e:
        return False, str(e)


# ── LANGSMITH DATA ────────────────────────────────────────
@st.cache_data(ttl=30)
def fetch_langsmith_runs(limit=50):
    try:
        client = get_langsmith_client()
        runs = list(client.list_runs(
            project_name=os.getenv("LANGCHAIN_PROJECT", "WORKMATES"),
            limit=limit
        ))
        return runs, None
    except Exception as e:
        return [], str(e)

def classify_node(name):
    name = (name or "").lower()
    if name == "model":           return "node-model",      "model"
    if "analysis" in name:        return "node-analysis",   "analysis"
    if "agent" in name:           return "node-agent",      "agent"
    if "guardrail" in name:       return "node-guardrails", "guardrails"
    if "send" in name:            return "node-send",       "send_email"
    return "node-other", name

def is_interrupt_error(error_str):
    return error_str and "GraphInterrupt" in error_str

def is_real_error(error_str):
    return error_str and "GraphInterrupt" not in error_str


# ── REDIS HITL COUNTERS ───────────────────────────────────
def get_hitl_counts():
    approve  = int(redis_client.get("hitl:actions:approve")    or 0)
    edit     = int(redis_client.get("hitl:actions:edit")       or 0)
    regen    = int(redis_client.get("hitl:actions:regenerate") or 0)
    return approve, edit, regen

def get_celery_tasks():
    try:
        from celery_app import celery
        inspect = celery.control.inspect(timeout=2)
        active    = inspect.active()    or {}
        reserved  = inspect.reserved()  or {}
        stats     = inspect.stats()     or {}

        active_tasks   = [t for v in active.values()   for t in v]
        reserved_tasks = [t for v in reserved.values() for t in v]

        total_executed = 0
        for worker_stats in stats.values():
            total = worker_stats.get("total", {})
            total_executed += sum(total.values()) if isinstance(total, dict) else 0

        return active_tasks, reserved_tasks, total_executed, None
    except Exception as e:
        return [], [], 0, str(e)


# ══════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════
st.markdown("""
<div class="dev-header">
    <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#6366f1;letter-spacing:0.15em;text-transform:uppercase;">
        WorkMates // Developer Dashboard
    </span>
    <h2 style="margin:6px 0 2px;color:#e2e8f0;font-size:22px;">Pipeline Observability</h2>
    <span style="font-size:12px;color:#6b7280;font-family:'JetBrains Mono',monospace;">
        LangGraph · Celery · Redis · Supabase · Gmail
    </span>
</div>
""", unsafe_allow_html=True)

col_title, col_refresh = st.columns([5, 1])
with col_refresh:
    if st.button("⟳ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════
# SECTION 1 — SYSTEM STATUS
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-title">▸ System Status</div>', unsafe_allow_html=True)

with st.spinner("Checking services..."):
    redis_ok,    redis_msg    = check_redis()
    imap_ok,     imap_msg     = check_imap()
    celery_ok,   celery_msg   = check_celery()
    supabase_ok, supabase_msg = check_supabase()
    gmail_ok,    gmail_msg    = check_gmail()

services = [
    ("Redis",     redis_ok,    redis_msg,    "🗄️"),
    ("IMAP",      imap_ok,     imap_msg,     "📡"),
    ("Celery",    celery_ok,   celery_msg,   "⚙️"),
    ("Supabase",  supabase_ok, supabase_msg, "🗃️"),
    ("Gmail API", gmail_ok,    gmail_msg,    "📧"),
]

cols = st.columns(5)
for col, (name, ok, msg, icon) in zip(cols, services):
    dot   = "status-dot-alive" if ok else "status-dot-dead"
    color = "#22c55e" if ok else "#ef4444"
    label = "LIVE" if ok else "DOWN"
    with col:
        st.markdown(f"""
        <div class="status-card">
            <div style="font-size:22px;margin-bottom:8px">{icon}</div>
            <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:4px">{name}</div>
            <div><span class="{dot}"></span><span style="font-size:12px;color:{color};font-weight:600">{label}</span></div>
            <div style="font-size:11px;color:#6b7280;margin-top:4px;font-family:'JetBrains Mono',monospace">{msg}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# SECTION 2 — PIPELINE METRICS
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-title">▸ Pipeline Metrics</div>', unsafe_allow_html=True)

runs, ls_error = fetch_langsmith_runs(limit=100)

# compute metrics from runs
if runs:
    langgraph_runs = [r for r in runs if r.name == "LangGraph"]
    model_runs     = [r for r in runs if r.name == "model"]
    send_runs      = [r for r in runs if r.name == "send_email"]

    real_errors    = [r for r in runs if is_real_error(r.error)]
    interrupts     = [r for r in runs if is_interrupt_error(r.error)]

    avg_e2e     = sum(r.latency for r in langgraph_runs) / len(langgraph_runs) if langgraph_runs else 0
    avg_model   = sum(r.latency for r in model_runs)     / len(model_runs)     if model_runs     else 0
    total_tokens = sum(r.total_tokens or 0 for r in runs)
    error_rate  = (len(real_errors) / len(runs) * 100) if runs else 0
    queue_depth = len(redis_client.keys("hitl:pending:*"))
else:
    avg_e2e = avg_model = total_tokens = error_rate = queue_depth = 0

m1, m2, m3, m4, m5 = st.columns(5)

with m1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Avg E2E Latency</div>
        <div class="metric-value">{avg_e2e:.1f}s</div>
        <div class="metric-sub">per email (LangGraph runs)</div>
    </div>""", unsafe_allow_html=True)

with m2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Avg Model Latency</div>
        <div class="metric-value">{avg_model:.2f}s</div>
        <div class="metric-sub">LLM call only</div>
    </div>""", unsafe_allow_html=True)

with m3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Tokens Used</div>
        <div class="metric-value">{total_tokens:,}</div>
        <div class="metric-sub">last 100 runs</div>
    </div>""", unsafe_allow_html=True)

with m4:
    err_color = "#ef4444" if error_rate > 5 else "#22c55e"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Error Rate</div>
        <div class="metric-value" style="color:{err_color}">{error_rate:.1f}%</div>
        <div class="metric-sub">{len(real_errors)} real errors in last 100</div>
    </div>""", unsafe_allow_html=True)

with m5:
    q_color = "#ef4444" if queue_depth > 5 else "#f59e0b" if queue_depth > 0 else "#22c55e"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Redis Queue Depth</div>
        <div class="metric-value" style="color:{q_color}">{queue_depth}</div>
        <div class="metric-sub">pending HITL approvals</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# SECTION 3 — NODE LATENCY + HITL BREAKDOWN
# ══════════════════════════════════════════════════════════
col_left, col_right = st.columns(2)

# ── Node breakdown ──
with col_left:
    st.markdown('<div class="section-title">▸ Avg Latency by Node</div>', unsafe_allow_html=True)

    node_names = ["model", "guardrails", "send_email", "tools", "analysis", "human_review"]
    node_data  = {}
    for r in runs:
        n = r.name or "unknown"
        if n not in node_data:
            node_data[n] = []
        node_data[n].append(r.latency or 0)

    display_nodes = [(n, sum(v)/len(v), len(v)) for n, v in node_data.items()
                     if n not in ("LangGraph", "review_router", "guardrails_router", "RunnableSequence")]
    display_nodes.sort(key=lambda x: x[1], reverse=True)

    max_lat = max((x[1] for x in display_nodes), default=1)

    for node_name, avg_lat, count in display_nodes[:8]:
        css_class, _ = classify_node(node_name)
        bar_pct = int((avg_lat / max_lat) * 100)
        st.markdown(f"""
        <div style="margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                <span class="node-badge {css_class}">{node_name}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#9ca3af">
                    {avg_lat:.3f}s avg · {count} runs
                </span>
            </div>
            <div style="background:#1e1e3a;border-radius:4px;height:6px">
                <div style="background:#6366f1;width:{bar_pct}%;height:6px;border-radius:4px"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── HITL action breakdown ──
with col_right:
    st.markdown('<div class="section-title">▸ HITL Action Breakdown</div>', unsafe_allow_html=True)

    approve_n, edit_n, regen_n = get_hitl_counts()
    total_hitl = approve_n + edit_n + regen_n

    if total_hitl == 0:
        st.info("No HITL actions recorded yet.\n\nCounters increment when you approve/edit/regenerate via the API.")
        st.caption("Make sure Redis counter increments are added to api_server.py endpoints.")
    else:
        actions = [
            ("Approved",     approve_n, "#22c55e"),
            ("Edited",       edit_n,    "#f59e0b"),
            ("Regenerated",  regen_n,   "#6366f1"),
        ]
        for label, count, color in actions:
            pct = int((count / total_hitl) * 100) if total_hitl else 0
            st.markdown(f"""
            <div class="hitl-bar" style="margin-bottom:14px">
                <span class="hitl-label">{label}</span>
                <div style="flex:1;background:#1e1e3a;border-radius:4px;height:10px">
                    <div style="background:{color};width:{pct}%;height:10px;border-radius:4px"></div>
                </div>
                <span style="font-family:'JetBrains Mono',monospace;font-size:12px;
                             color:#9ca3af;margin-left:10px;width:60px;text-align:right">
                    {count} ({pct}%)
                </span>
            </div>
            """, unsafe_allow_html=True)

        approval_rate = int((approve_n / total_hitl) * 100)
        color = "#22c55e" if approval_rate >= 70 else "#f59e0b" if approval_rate >= 40 else "#ef4444"
        st.markdown(f"""
        <div style="margin-top:16px;padding:14px;background:#0f0f1a;
                    border:1px solid #2a2a4a;border-radius:8px;text-align:center">
            <div style="font-size:11px;color:#6b7280;font-family:'JetBrains Mono',monospace;
                        text-transform:uppercase;letter-spacing:0.08em">AI Approval Rate</div>
            <div style="font-size:32px;font-weight:600;color:{color};
                        font-family:'JetBrains Mono',monospace">{approval_rate}%</div>
            <div style="font-size:11px;color:#6b7280">of drafts approved without changes</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# SECTION 4 — CELERY WORKER STATUS
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-title">▸ Celery Worker</div>', unsafe_allow_html=True)

active_tasks, reserved_tasks, total_executed, celery_err = get_celery_tasks()

ca, cb, cc = st.columns(3)
with ca:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Active Tasks</div>
        <div class="metric-value">{len(active_tasks)}</div>
        <div class="metric-sub">running right now</div>
    </div>""", unsafe_allow_html=True)
with cb:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Queued Tasks</div>
        <div class="metric-value">{len(reserved_tasks)}</div>
        <div class="metric-sub">waiting to run</div>
    </div>""", unsafe_allow_html=True)
with cc:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Executed</div>
        <div class="metric-value">{total_executed}</div>
        <div class="metric-sub">since worker started</div>
    </div>""", unsafe_allow_html=True)

if active_tasks:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**Currently running:**")
    for t in active_tasks:
        st.markdown(f"""
        <div class="celery-task">
            ⚙️ <b style="color:#e2e8f0">{t.get('name','unknown')}</b>
            &nbsp;·&nbsp; id: {t.get('id','')[:16]}...
            &nbsp;·&nbsp; started: {t.get('time_start','')}
        </div>
        """, unsafe_allow_html=True)

if celery_err:
    st.warning(f"Celery inspect error: {celery_err}")

st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# SECTION 5 — PER-RUN TRACE TABLE
# ══════════════════════════════════════════════════════════
st.markdown('<div class="section-title">▸ Recent Runs — LangSmith Traces</div>', unsafe_allow_html=True)

if ls_error:
    st.error(f"LangSmith error: {ls_error}")
elif not runs:
    st.info("No runs fetched.")
else:
    # filters
    f1, f2, f3 = st.columns(3)
    with f1:
        all_names  = sorted(set(r.name or "unknown" for r in runs))
        node_filter = st.multiselect("Filter by node", all_names, default=[], key="node_filter")
    with f2:
        status_filter = st.selectbox("Status", ["ALL", "✅ OK", "⚠️ Interrupt", "❌ Error"], key="status_filter")
    with f3:
        show_limit = st.slider("Show last N runs", 10, 100, 30, key="run_limit")

    filtered_runs = runs
    if node_filter:
        filtered_runs = [r for r in filtered_runs if r.name in node_filter]
    if status_filter == "✅ OK":
        filtered_runs = [r for r in filtered_runs if not r.error]
    elif status_filter == "⚠️ Interrupt":
        filtered_runs = [r for r in filtered_runs if is_interrupt_error(r.error)]
    elif status_filter == "❌ Error":
        filtered_runs = [r for r in filtered_runs if is_real_error(r.error)]

    filtered_runs = filtered_runs[:show_limit]

    # header
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:140px 1fr 80px 80px 60px 100px;
                gap:8px;padding:8px 18px;
                font-size:11px;color:#6b7280;
                font-family:'JetBrains Mono',monospace;
                text-transform:uppercase;letter-spacing:0.08em;
                border-bottom:1px solid #2a2a4a;margin-bottom:8px">
        <span>Node</span>
        <span>Time</span>
        <span>Latency</span>
        <span>Tokens</span>
        <span>Status</span>
        <span>Trace</span>
    </div>
    """, unsafe_allow_html=True)

    for run in filtered_runs:
        css_class, _ = classify_node(run.name)
        latency_str  = f"{run.latency:.3f}s" if run.latency else "—"
        tokens_str   = str(run.total_tokens) if run.total_tokens else "—"
        time_str     = run.start_time.strftime("%H:%M:%S") if run.start_time else "—"

        if is_interrupt_error(run.error):
            status_html = '<span class="interrupt-badge">⚠ HITL</span>'
        elif is_real_error(run.error):
            status_html = '<span class="error-badge">❌ ERR</span>'
        else:
            status_html = '<span class="ok-badge">✓ OK</span>'

        trace_html = f'<a href="{run.url}" target="_blank" style="color:#6366f1;font-size:11px;text-decoration:none">→ trace</a>' if run.url else "—"

        st.markdown(f"""
        <div class="trace-row" style="display:grid;
             grid-template-columns:140px 1fr 80px 80px 60px 100px;
             gap:8px;align-items:center">
            <span class="node-badge {css_class}">{run.name or 'unknown'}</span>
            <span style="color:#6b7280">{time_str}</span>
            <span style="color:#e2e8f0">{latency_str}</span>
            <span style="color:#9ca3af">{tokens_str}</span>
            {status_html}
            {trace_html}
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# SECTION 6 — FOOTER NOTE
# ══════════════════════════════════════════════════════════
st.markdown("""
<div style="border-top:1px solid #2a2a4a;padding-top:16px;
            font-family:'JetBrains Mono',monospace;font-size:11px;color:#374151">
    ⚠️ &nbsp;HITL counters require Redis increments in api_server.py — 
    add <code style="color:#6366f1">redis_client.incr("hitl:actions:approve")</code> etc. to each endpoint. &nbsp;·&nbsp;
    IMAP heartbeat requires <code style="color:#6366f1">redis_client.setex("health:imap", 60, "alive")</code> in listen() loop.
</div>
""", unsafe_allow_html=True)