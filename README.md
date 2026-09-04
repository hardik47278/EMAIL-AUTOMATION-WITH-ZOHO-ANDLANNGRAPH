
# WorkMates — Enterprise AI Email Automation

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0+-purple)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)
![React](https://img.shields.io/badge/React-18+-cyan)
![Redis](https://img.shields.io/badge/Redis-7.0+-red)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-darkgreen)
![LangSmith](https://img.shields.io/badge/LangSmith-Tracing-orange)

> **WorkMates** is a production-grade, multi-agent AI email automation system that reads, classifies, prioritizes, and drafts replies to emails — with human-in-the-loop review before sending. Built on LangGraph, FastAPI, React, Redis, Celery, and Supabase.

---

## Table of Contents

1. [Overview](#overview)
2. [Why Controlled ReAct?](#why-controlled-react)
3. [Agentic vs Automation](#agentic-vs-automation)
4. [Key Challenges and Solutions](#key-challenges-and-solutions)
5. [Architecture](#architecture)
6. [Features](#features)
7. [Tech Stack](#tech-stack)
8. [System Components](#system-components)
9. [Memory Architecture](#memory-architecture)
10. [Pipeline Flow](#pipeline-flow)
11. [Human-in-the-Loop](#human-in-the-loop)
12. [Email Intake Layer](#email-intake-layer)
13. [Agent Details](#agent-details)
14. [Guardrails](#guardrails)
15. [Summarizer Agent](#summarizer-agent)
16. [Dashboard](#dashboard)
17. [Redis + Celery Architecture](#redis--celery-architecture)
18. [LangSmith Integration](#langsmith-integration)
19. [API Endpoints](#api-endpoints)
20. [Environment Variables](#environment-variables)
21. [Installation](#installation)
22. [Running the System](#running-the-system)
23. [Project Structure](#project-structure)
24. [Scaling](#scaling)
25. [Future Improvements](#future-improvements)
26. [License](#license)

---

## Overview

WorkMates is an end-to-end intelligent email automation platform designed for business use. It processes incoming emails through a multi-agent pipeline — detecting spam, classifying intent, assessing priority, personalizing context, and generating high-quality replies — all before presenting them to a human reviewer via a clean React dashboard.

The system is built around three principles:
- **Accuracy** — multiple specialized agents, each doing one job well
- **Safety** — guardrails, PII detection, and prompt injection protection at every layer
- **Control** — human always has final say before any email is sent

---

## Why Controlled ReAct?

> **ReAct = Reasoning + Acting** — the agent thinks, calls a tool, observes the result, and thinks again.

WorkMates uses **Controlled ReAct** — not fully autonomous, not simple automation. Here is why:

**Fully autonomous would mean:**
```
Email arrives → AI replies → sent
No human involved
```
This is risky for business email. A wrong reply to a client costs money, trust, and relationships.

**Simple automation would mean:**
```
Email arrives → template reply → sent
No intelligence
```
This produces generic, unhelpful replies that frustrate customers.

**Controlled ReAct means:**
```
Email arrives
    ↓
Multiple agents reason about it (ReAct loops)
    ↓
Best reply generated and self-evaluated
    ↓
Human reviews and approves
    ↓
Email sent
```

This gives the intelligence of AI with the accountability of human oversight. Agents are free to reason and use tools autonomously within their scope. Humans retain final control over what gets sent.

**Specific agents using ReAct in WorkMates:**

| Agent | Why ReAct | Tools Used |
|---|---|---|
| Spam Detection | Domain needs multi-step tool investigation | WHOIS, DNS, VirusTotal |
| Reply Generator | Self-evaluates and regenerates until quality passes | generate, evaluate, intent-check, history |
| Summarizer | Judges its own output and retries if score < 8 | LLM judge |

**Agents using fixed StateGraph (not ReAct):**

| Agent | Why StateGraph | 
|---|---|
| Meeting Agent | Fixed modes: read/book/modify |
| HIL Graph | Fixed flow: generate → guardrails → human → send |
| Summarizer Graph | Fixed flow: summarize → entities → judge → rewrite |

---

## Agentic vs Automation

| Dimension | Pure Automation | WorkMates (Agentic) |
|---|---|---|
| Reply quality | Template-based | Context-aware, personalized |
| Spam detection | Keyword rules only | Multi-tool agent (WHOIS + DNS + VT) |
| Priority | Fixed rules | LLM reasoning on urgency signals |
| Meeting booking | Not possible | Calendar-aware agent |
| Reply evaluation | None | Self-evaluates and regenerates |
| Human control | None or all | Selective — only at final step |
| Cost | Low | Medium (LLM calls) |
| Accuracy | Low | High |

WorkMates sits at the intersection — agents handle complexity, humans handle accountability.

---

## Key Challenges and Solutions

### 1. Token Budget Exhaustion
**Problem:** Multiple agents × multiple LLM calls = hitting Groq's 100k tokens/day limit fast.

**Solution:**
- Simple tasks (intent, priority, guardrails) → `llama-3.1-8b-instant` (separate TPD limit)
- Complex tasks (spam, reply, meeting) → `llama-3.3-70b-versatile`
- OpenRouter `qwen/qwen3-8b` as fallback when Groq TPD exhausted
- Automatic fallback chain: Groq 70b → Groq 8b → OpenRouter

### 2. Human-in-the-Loop State Persistence
**Problem:** LangGraph pipeline pauses at HIL. How to resume from a browser click?

**Solution:**
- LangGraph `MemorySaver` checkpoints state by `thread_id`
- Redis stores pending HIL state (draft reply, sender, subject)
- FastAPI endpoints resume LangGraph via `Command(resume=...)`
- React polls `/emails/pending` and renders approve/edit/regenerate buttons

### 3. Prompt Injection via Email
**Problem:** Attackers send emails with instructions like "ignore all previous rules".

**Solution:**
- `prompt_safety.py` — dedicated LLM classifier before HIL
- Classifies: SAFE or INJECTION
- If INJECTION → pipeline terminates, email blocked
- Guardrails node sits between reply generator and HIL

### 4. PII Leakage to LLM
**Problem:** Emails contain phone numbers, SSNs, credit card numbers — unsafe to send raw to LLM.

**Solution:**
- Presidio Analyzer detects PII entities
- Presidio Anonymizer replaces with placeholders (`<PHONE_NUMBER>`, `<EMAIL_ADDRESS>`)
- LLM processes anonymized text
- Deanonymizer restores real values in final reply

### 5. Duplicate Email Processing
**Problem:** IMAP listener + Celery beat both active — same email processed twice.

**Solution:**
- Redis db=0 stores processed email IDs with TTL
- `is_duplicate()` check before pipeline entry
- Cache hit → skip, log "duplicate skipped"

### 6. Race Condition in HIL Approval
**Problem:** Two users click Approve simultaneously on same email.

**Solution:**
- `redis_client.getdel()` — atomic get + delete
- First request gets the data, second gets None → 404
- Supabase unique constraint on `gmail_id` as final safeguard

### 7. Reply Quality Consistency
**Problem:** Single LLM call produces inconsistent reply quality.

**Solution:**
- Reply generator is a 4-tool ReAct agent
- Tool 1: `fetch_customer_history` — avoids repeating past replies
- Tool 2: `generate_reply` — produces draft
- Tool 3: `evaluate_reply` — scores 1-10, finds issues
- Tool 4: `check_intent_coverage` — verifies all email intents addressed
- Max 3 regeneration attempts if score < 7

---

## Architecture

> **[IMAGE PLACEHOLDER — Main System Architecture SVG]**
> *Full pipeline from email intake to send, showing all agents, guardrails, HIL, and memory layers*

```
New Email (Zoho)
      ↓
IMAP Listener → Celery → Email Intake Layer
      ↓
Content Merger → Spam Detection
      ↓
Supervisor (intent routing)
      ↓
Agent 1 (Priority) | Agent 2 (Meeting) | Agent 3 (Personalization)
      ↓
Agent Output Combiner
      ↓
Reply Generator (Agentic ReAct)
      ↓
Guardrails (pre-HIL)
      ↓
Human-in-the-Loop
      ↓
Post-HIL Guardrails
      ↓
Send Email (Zoho SMTP) → Memory Writer → Done
```

---

## Features

- **Real-time email detection** via IMAP IDLE mode
- **Spam detection** with multi-tool ReAct agent (WHOIS, DNS, VirusTotal)
- **Intent classification** — billing, meeting, complaint, query, and more
- **Priority assessment** — HIGH / MEDIUM / LOW with reasoning
- **Personalization** — tone, verbosity, technical level, user role inference
- **Meeting agent** — calendar-aware scheduling with read/book/modify modes
- **Agentic reply generator** — self-evaluating, 4-tool ReAct loop
- **Guardrails** — prompt injection detection, tone/safety checks
- **PII shield** — Presidio-based anonymization before LLM, deanonymization after
- **Human-in-the-loop** — browser-based approve/edit/regenerate
- **On-demand summarizer** — LLM judge with entity extraction
- **React user dashboard** — clean HIL interface
- **Admin dashboard** — LangSmith traces, agent scores, pipeline monitoring
- **Zoho Mail integration** — IMAP receive + SMTP send
- **Multi-model fallback** — Groq → OpenRouter with automatic switching
- **LangSmith tracing** — full agent conversation history per email

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Framework | LangGraph, LangChain |
| LLM Provider | Groq (llama-3.3-70b, llama-3.1-8b) |
| LLM Fallback | OpenRouter (qwen3-8b) |
| Backend API | FastAPI + Uvicorn |
| Frontend | React 18 + Tailwind CSS + Vite |
| Task Queue | Celery + Redis |
| Cache | Redis (Docker) |
| Database | Supabase (PostgreSQL) |
| Email (Receive) | Zoho IMAP + IMAPClient |
| Email (Send) | Zoho SMTP |
| PII Detection | Microsoft Presidio + spaCy |
| PDF Processing | Docling, PyMuPDF |
| Tracing | LangSmith |
| Spam Tools | python-whois, dnspython, VirusTotal API |
| Summarizer Metrics | LLM Judge (no external libraries) |

---

## System Components

| File | Purpose |
|---|---|
| `imap_listener.py` | IMAP IDLE listener — detects new emails in real-time |
| `tasks.py` | Celery task definitions — `fetch_and_process` |
| `mainn.py` | Main pipeline orchestrator |
| `zoho_mail.py` | Zoho IMAP fetch + SMTP send (replaces gmail.py) |
| `subgraph.py` | Spam, intent, priority, personalization subgraphs |
| `spam_detection.py` | ReAct spam detection agent with 4 tools |
| `spam_detection_tool.py` | WHOIS, DNS, VirusTotal tool implementations |
| `meeting_agent.py` | Calendar-aware meeting agent (StateGraph) |
| `reply_generator.py` | Agentic reply generator (4-tool ReAct) |
| `humaninloop2.py` | LangGraph HIL graph with interrupt/resume |
| `supervisor_node.py` | Spam detection + supervisor routing graph |
| `context_merger.py` | Merges priority + personalization + meeting outputs |
| `pii_shield.py` | Presidio PII anonymization/deanonymization |
| `prompt_safety.py` | Prompt injection classifier |
| `summarizer_agent.py` | On-demand email summarizer (StateGraph) |
| `duplicate_check.py` | Redis-based email deduplication |
| `supabase_integration.py` | Supabase read/write operations |
| `database_tools.py` | LangChain tools wrapping Supabase queries |
| `api.py` | FastAPI HIL endpoints |
| `html_cleanup.py` | Strip HTML from email body |
| `subject_normalizer.py` | Clean and normalize email subjects |
| `pdf_reader.py` | Extract text from PDF attachments |
| `docx_reader.py` | Extract text from Word attachments |
| `dashboard_admin.py` | Streamlit admin dashboard with LangSmith Tab |

---

## Memory Architecture

WorkMates uses a 3-layer memory hierarchy:

```
L1 — HOT (Redis) — sub-millisecond
├── db=0: Duplicate check cache (email IDs, TTL=24h)
├── db=2: PII session mapping (placeholder ↔ real value)
├── db=3: HIL pending state (draft reply, sender, subject)
└── default: Celery broker + task results

L2 — WARM (planned)
└── pgvector in Supabase for semantic email history search

L3 — COLD (Supabase PostgreSQL) — persistent
├── email_history table (all processed emails)
└── customer_summary table (per-customer context)

LangGraph MemorySaver — in-process
└── HIL graph checkpoint by thread_id
    (pause/resume state between human decisions)

LangSmith — external trace store
└── full agent conversation per email
    (tool calls, inputs, outputs, scores)
```

---

## Pipeline Flow

> **[IMAGE PLACEHOLDER — Pipeline Flow Diagram]**
> *Step-by-step flow from IMAP detection to email sent*

```
1. New email arrives in Zoho inbox
2. IMAP listener detects via IDLE mode
3. Duplicate check → Redis db=0
4. fetch_and_process.delay() → Celery task
5. Email intake: subject normalize, body clean, attachments extract
6. Content merger: unified email text
7. Spam detection: ReAct agent → WHOIS + DNS + VirusTotal
   → SPAM: discard | SAFE: continue
8. Supervisor: checks intent → routes to agents
9. Parallel agents:
   → Priority agent: HIGH/MEDIUM/LOW
   → Meeting agent: calendar check/book
   → Personalization: tone, role, verbosity
10. Context merger: combines all agent outputs
11. Reply generator: 4-tool ReAct loop
    → fetch history → generate → evaluate → check intents
    → regenerate if score < 7 (max 3 attempts)
12. Guardrails: prompt injection + safety check
    → INJECTION: block | SAFE: continue
13. HIL: pause, save to Redis, wait for human
14. Human: approve / edit / regenerate via React
15. Post-HIL guardrails: final safety check
16. Send email via Zoho SMTP
17. Write to Supabase (email_history, customer_summary)
18. Done
```

---

## Human-in-the-Loop

> **[IMAGE PLACEHOLDER — HIL Flow Diagram]**
> *React dashboard showing pending email with approve/edit/regenerate buttons*

> **[IMAGE PLACEHOLDER — React Dashboard Screenshot]**
> *Pending Approvals tab with AI draft and action buttons*

WorkMates uses LangGraph's `interrupt()` mechanism for HIL:

```
Reply generator completes draft
        ↓
Guardrails node passes
        ↓
interrupt() called → pipeline PAUSES
        ↓
State saved to LangGraph MemorySaver (by thread_id)
Draft saved to Redis db=3
        ↓
React dashboard polls GET /emails/pending
        ↓
User sees: sender, subject, AI draft reply
        ↓
User clicks:
  ✅ Approve   → POST /emails/{id}/approve
  ✏️ Edit      → POST /emails/{id}/edit + edited text
  🔄 Regenerate → POST /emails/{id}/regenerate + feedback
        ↓
FastAPI calls Command(resume={"action": "..."})
        ↓
LangGraph resumes from checkpoint
        ↓
Email sent via Zoho SMTP
Redis key deleted
Supabase updated
```

**Race condition protection:**
- `redis_client.getdel()` — atomic get + delete
- Only first request processes, second gets 404
- Supabase unique constraint on `gmail_id`

---

## Email Intake Layer

The intake layer normalizes all incoming email data before agents see it:

| Component | Purpose |
|---|---|
| Dedupe check | Redis cache — skip already-processed emails |
| Subject normalizer | Remove Re:/Fwd: prefixes, clean whitespace |
| Body normalizer | Strip HTML, clean Unicode artifacts |
| Attachment router | Route by file type to correct extractor |
| OCR | Tesseract for scanned PDFs |
| Docling | Advanced PDF/DOCX text extraction |
| Validation | Check file integrity before processing |
| Suspicious filter | Block .apk .exe .bat and other dangerous extensions |

---

## Agent Details

### Spam Detection Agent (ReAct)
```
Tools:
  extract_domain    → get domain from sender email
  get_whois_info    → WHOIS registration data
  dns_checks        → MX, SPF, DKIM records
  virustotal_check  → reputation score

Flow: reason → tool → observe → reason → decision
Output: {"label": "spam|safe", "reason": "...", "tools_used": [...]}
Model: llama-3.3-70b-versatile
```

### Supervisor
```
Input: unified email text
Output: route to priority | meeting | personalization agent
Based on: intent detected from email content
```

### Priority Agent
```
Input: email + context
Output: HIGH | MEDIUM | LOW + reasoning
Signals: urgency words, deadlines, threats, sender role
Model: llama-3.1-8b-instant
```

### Meeting Agent (StateGraph)
```
Modes:
  read_only  → list events, check slots
  booking    → extract date/time, book meeting
  modify     → reschedule, cancel

Tools: list_events, check_slot, extract_date_time, book_meeting
Model: llama-3.3-70b-versatile
```

### Personalization Agent
```
Input: customer email history + current email
Output: tone, verbosity, technical_level, user_role,
        is_first_time, domain_context, behavioral_traits
Model: llama-3.3-70b-versatile
```

### Reply Generator Agent (ReAct)
```
Tools:
  fetch_customer_history  → avoid repeating past replies
  generate_reply          → produce draft from merged context
  evaluate_reply          → score 1-10, find issues
  check_intent_coverage   → verify all email intents addressed

Flow:
  fetch history → generate → evaluate (score < 7?) 
  → regenerate with extra_focus → evaluate again
  → max 3 attempts → return best reply

Model: llama-3.3-70b-versatile
Fallback: llama-3.1-8b-instant → OpenRouter qwen3-8b
```

---

## Guardrails

WorkMates has two guardrail checkpoints:

### Pre-HIL Guardrails (prompt_safety.py)
```
Detects:
- "ignore previous instructions"
- "you are now a different AI"
- "reveal your system prompt"
- "developer mode"
- Role switching, jailbreak patterns

Result: SAFE → continue to HIL | INJECTION → block, end pipeline
Model: llama-3.3-70b-versatile
```

### PII Shield (pii_shield.py)
```
Layer 1: Presidio Analyzer (rule-based)
  → EMAIL_ADDRESS, PHONE_NUMBER, PERSON,
    CREDIT_CARD, SSN, IBAN, IP_ADDRESS

Layer 2: LLM contextual check
  → catches edge cases Presidio misses

Anonymize → LLM processes → Deanonymize
```

### Post-HIL Guardrails
```
Final safety check after human decision
Safety + tone + compliance verification
Pass → send | Flag → re-route to HIL
```

---

## Summarizer Agent

> **On-demand only — triggered by user clicking "Summarize" button in dashboard**

```
Architecture: StateGraph (4 nodes)

Node 1: summarize_node
  → LLM generates 3-5 sentence summary
  → llama-3.1-8b-instant

Node 2: entity_node  
  → LLM extracts structured entities:
    amounts, dates, invoices, deadlines,
    threats, questions, action items

Node 3: judge_node
  → LLM scores summary 1-10
  → checks: completeness, accuracy, clarity
  → if score < 8 → feedback for rewrite

Node 4: rewrite_node (if triggered)
  → regenerates with judge feedback
  → max 2 retries

Output: summary + entities + judge_score + attempts
```

**Integration:**
```
React "Summarize" button
    ↓
POST /emails/{gmail_id}/summarize (api.py)
    ↓
Fetch original email from Zoho API
    ↓
summarizer_agent.py runs
    ↓
Returns summary + score to React
```

---

## Dashboard

### User Dashboard (React — localhost:5173)

> **[IMAGE PLACEHOLDER — React User Dashboard]**
> *Clean 4-tab interface for non-technical users*

```
Tab 1: Pending Approvals
  → AI draft replies waiting for review
  → Approve / Edit / Regenerate buttons
  → Priority badge (HIGH/MEDIUM/LOW)

Tab 2: Inbox
  → All processed emails
  → Filter by priority + intent
  → View reply sent
  → Summarize button

Tab 3: Auto-logged
  → OTP, newsletters, promotions
  → Handled automatically, no HIL needed

Tab 4: Insights
  → Emails today, need attention,
    awaiting approval, total processed
  → Priority breakdown
```

### Admin Dashboard (Streamlit — localhost:8502)

> **[IMAGE PLACEHOLDER — Admin Dashboard Screenshot]**
> *5-tab technical monitoring dashboard*

```
Tab 1: Overview — KPIs, pipeline health
Tab 2: Email Records — full Supabase data
Tab 3: Customers — churn risk, sentiment trends
Tab 4: Email Detail — per-email deep dive
Tab 5: Agent Traces — LangSmith per-customer traces
  → generate_reply drafts
  → evaluate_reply scores
  → check_intent_coverage results
  → human_review decisions
  → guardrails results
```

---

## Redis + Celery Architecture

> **[IMAGE PLACEHOLDER — Redis + Celery Flow Diagram]**
> *IMAP listener → Celery → pipeline flow with Redis as backbone*

```
PRIMARY TRIGGER:
New Email (Zoho)
      ↓
imap_listener.py (IMAP IDLE)
→ detects instantly
      ↓
Redis db=0: duplicate check
      ↓
fetch_and_process.delay()
→ task sent to Celery via Redis broker
      ↓
Celery Worker (tasks.py)
→ picks up task from Redis queue
      ↓
run_pipeline() → full agent pipeline

BACKUP TRIGGER (if IMAP crashes):
Celery Beat → polls Zoho every X minutes
           → same fetch_and_process.delay()
           → same flow

REDIS DB LAYOUT:
db=0 → duplicate check cache
db=1 → Celery broker (task queue)
db=2 → PII session mapping
db=3 → HIL pending state
```

---

## LangSmith Integration

WorkMates traces every agent run to LangSmith:

```
.env configuration:
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://aws.api.smith.langchain.com
LANGCHAIN_PROJECT=WORKMATES

Traces captured per email:
→ spam_detection agent conversation
→ reply_generator tool calls + scores
→ evaluate_reply scores (1-10)
→ check_intent_coverage missing intents
→ human_review decisions
→ guardrails results
→ send_email confirmation

Access via:
→ Admin dashboard Tab 5 (per-customer filtering)
→ Direct: smith.langchain.com
```

---

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Health check |
| GET | `/emails/pending` | List emails waiting for HIL |
| POST | `/emails/{id}/approve` | Approve and send AI reply |
| POST | `/emails/{id}/edit` | Send edited reply |
| POST | `/emails/{id}/regenerate` | Regenerate with feedback |
| GET | `/emails/processed` | Processed emails from Supabase |
| GET | `/emails/log-only` | Auto-logged emails |
| GET | `/emails/stats` | Dashboard stats |
| POST | `/emails/{id}/summarize` | On-demand email summarization |

---

## Environment Variables

```env
# Groq LLM
GROQ_API_KEY=your_groq_key

# OpenRouter fallback
OPENROUTER_API_KEY=your_openrouter_key

# Zoho Mail
ZOHO_EMAIL=your@zohomail.in
ZOHO_APP_PASSWORD=your_app_password
ZOHO_IMAP_HOST=imap.zoho.in
ZOHO_SMTP_HOST=smtp.zoho.in
ZOHO_SMTP_PORT=465

# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=your_supabase_anon_key

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# VirusTotal
VIRUSTOTAL_API_KEY=your_vt_key

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://aws.api.smith.langchain.com
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=WORKMATES

# API Gateway
VALID_API_KEYS=key-hardik-001,key-dev-002
```

---

## Installation

```bash
# 1. Clone repository
git clone https://github.com/yourusername/workmates.git
cd workmates

# 2. Create virtual environment
python -m venv ve
source ve/bin/activate  # Windows: ve\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install spaCy model (for PII detection)
python -m spacy download en_core_web_lg

# 5. Start Redis via Docker
docker run -d --name redis-server -p 6379:6379 redis:7

# 6. Set up environment variables
cp .env.example .env
# edit .env with your keys

# 7. Set up React frontend
cd frontend
npm install
cd ..
```

---

## Running the System

Run each in a separate terminal:

```bash
# Terminal 1 — Redis
docker start redis-server

# Terminal 2 — Celery worker
celery -A tasks worker --loglevel=info

# Terminal 3 — IMAP listener (primary email trigger)
python imap_listener.py

# Terminal 4 — FastAPI (HIL endpoints)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload

# Terminal 5 — React dashboard (user)
cd frontend && npm run dev

# Terminal 6 — Streamlit dashboard (admin, optional)
streamlit run dashboard_admin.py --server.port 8502
```

**Access:**
```
User dashboard  → http://localhost:5173
Admin dashboard → http://localhost:8502
API docs        → http://localhost:8000/docs
```

---

## Project Structure

```
workmates/
├── api.py                    # FastAPI HIL endpoints
├── mainn.py                  # Pipeline orchestrator
├── tasks.py                  # Celery task definitions
├── imap_listener.py          # Zoho IMAP IDLE listener
├── zoho_mail.py              # Zoho fetch + send
├── subgraph.py               # Agent subgraphs
├── spam_detection.py         # Spam ReAct agent
├── spam_detection_tool.py    # WHOIS, DNS, VT tools
├── meeting_agent.py          # Meeting StateGraph agent
├── reply_generator.py        # Reply ReAct agent
├── humaninloop2.py           # HIL LangGraph
├── supervisor_node.py        # Supervisor routing
├── context_merger.py         # Merge agent outputs
├── summarizer_agent.py       # On-demand summarizer
├── pii_shield.py             # Presidio PII protection
├── prompt_safety.py          # Prompt injection detection
├── duplicate_check.py        # Redis deduplication
├── supabase_integration.py   # DB operations
├── database_tools.py         # LangChain DB tools
├── html_cleanup.py           # HTML stripping
├── subject_normalizer.py     # Subject cleaning
├── pdf_reader.py             # PDF text extraction
├── docx_reader.py            # Word text extraction
├── dashboard_admin.py        # Streamlit admin dashboard
├── state_shared.py           # Shared state types
├── credentials/
│   ├── credentials.json
│   └── token.json
├── frontend/                 # React user dashboard
│   ├── src/
│   │   ├── api.js
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── components/
│   │       ├── Sidebar.jsx
│   │       ├── Topbar.jsx
│   │       ├── PendingCard.jsx
│   │       ├── InboxTab.jsx
│   │       ├── LogTab.jsx
│   │       └── Insights.jsx
│   ├── package.json
│   └── vite.config.js
├── langgraph.json            # LangGraph Studio config
├── .env
├── requirements.txt
└── README.md
```

---

## Scaling

### Current Limits
```
~10-20 concurrent emails
Single Celery worker
Single Redis node
MemorySaver (in-process)
Manual refresh in React
```

### Production Scale (1000+ concurrent emails)

> **[IMAGE PLACEHOLDER — Production Scale Architecture]**
> *AWS services mapping for enterprise deployment*

```
IMAP Listeners     → Multiple (one per inbox)
Celery Workers     → Pool with --concurrency=10
Redis              → ElastiCache cluster
LangGraph State    → PostgresSaver (shared across workers)
FastAPI            → Multiple instances behind Nginx/ALB
React              → WebSocket for real-time updates
Database           → RDS PostgreSQL with pgBouncer
Attachments        → S3 storage
Monitoring         → CloudWatch + X-Ray
CI/CD              → GitHub Actions + CodeDeploy
```

### AWS Service Mapping

| Current | AWS Equivalent |
|---|---|
| Docker Redis | ElastiCache |
| Celery + Redis broker | SQS |
| FastAPI on EC2 | ECS + ALB |
| Supabase | RDS PostgreSQL |
| tempfile attachments | S3 |
| Print statements | CloudWatch Logs |
| Manual deploy | CodePipeline |
| Groq | Bedrock (Llama) |

---

## Future Improvements

```
Short term:
→ WebSocket for real-time React updates (no manual refresh)
→ PostgresSaver replacing MemorySaver
→ HIL timeout + auto-escalation after 1 hour
→ LangGraph Studio integration

Medium term:
→ L2 vector memory (pgvector in Supabase)
→ Email thread context (multi-turn awareness)
→ Follow-up agent (monitor unanswered emails)
→ Notification system (WhatsApp/Telegram for HIL)

Long term:
→ SageMaker fine-tuning on approved email data
→ Custom spam classifier (replace LLM calls)
→ Multi-inbox support
→ Knowledge base agent (RAG on company docs)
→ Sentiment trend escalation agent
```

---

## License

MIT License — Built by Hardik Anand, AI Engineer Intern @ Workmates Core2Cloud

---

*WorkMates — Where AI handles the routine, humans handle what matters.*

# 🔴 Redis in the AI Email Pipeline

Redis is the central nervous system of this pipeline. It handles four completely separate jobs, each isolated in its own logical database.

---

## 📦 Database Layout

```
Redis Instance (localhost:6379)
│
├── db=0  →  🟡 Celery Broker      (task queue)
├── db=1  →  🟢 Celery Backend     (task results)
├── db=2  →  🔵 PII Shield         (anonymization sessions)
└── db=3  →  🔴 HITL Pause State   (pending human approvals)
```

---

## 🟡 db=0 — Celery Broker (Task Queue)

**Job:** Hold email processing tasks in a queue between IMAP detection and Celery worker execution.

```
📧 New email arrives in Gmail
        │
        ▼
📡 IMAP IDLE detects it instantly
        │
        ▼
📨 fetch_and_process.delay() called
        │
        ▼
🟡 Task pushed to Redis db=0 queue
        │
        ▼
⚙️  Celery Worker picks up the task
        │
        ▼
🚀 Full pipeline starts processing
```

**Why Redis here:**
Without a broker, tasks would be lost if the worker crashes. Redis holds them safely in a persistent queue until a worker is available.

---

## 🟢 db=1 — Celery Backend (Task Results)

**Job:** Store the results of completed tasks so the system can verify success or trigger retries.

```
⚙️  Celery Worker finishes processing
        │
        ▼
🟢 Result stored in Redis db=1
        │
        ▼
✅ Task marked SUCCESS or FAILURE
        │
        ▼
🔄 Retry triggered on FAILURE (max 3 retries)
```

**Why Redis here:**
Allows real-time monitoring of task status, automatic retries on failure, and confirmation that every email was processed successfully.

---

## 🔵 db=2 — PII Shield (Anonymization Sessions)

**Job:** Store placeholder-to-real-value mappings for the sandwich anonymization pattern. Ensures real customer data never reaches the LLM.

```
📧 Raw email arrives
   "Hi, my Aadhaar is 1234 5678 9012"
        │
        ▼
🔍 Presidio detects PII
        │
        ▼
🔵 Mapping stored in Redis db=2  ←── TTL: 30 mins
   {
     "{{IN_AADHAAR_1}}": "1234 5678 9012",
     "{{PERSON_1}}":     "Rahul Sharma"
   }
        │
        ▼
🤖 LLM sees anonymized text ONLY
   "Hi, my Aadhaar is {{IN_AADHAAR_1}}"
        │
        ▼
💬 LLM generates reply with placeholders
        │
        ▼
🔵 Mapping fetched from Redis db=2
        │
        ▼
✅ Real values restored in final reply
   "Dear Rahul Sharma, your Aadhaar 1234 5678 9012..."
        │
        ▼
🗑️  Mapping auto-deleted after 30 mins
```

**Why Redis here:**
Mappings must survive between the anonymize call and the deanonymize call but must not persist forever. Redis TTL handles automatic expiry without any cleanup code.

---

## 🔴 db=3 — HITL Pause State (Human in the Loop)

**Job:** Store the complete email context while the pipeline is paused waiting for human approval.

```
🤖 Agentic reply generator produces draft
        │
        ▼
⏸️  Pipeline PAUSES at interrupt() node
        │
        ▼
🔴 Context stored in Redis db=3  ←── TTL: 1 hour
   {
     "thread_id":   "19ecb23c...",
     "sender":      "rahul@company.com",
     "subject":     "Production is down",
     "draft_reply": "Dear Rahul, we are...",
     "priority":    "HIGH",
     "timestamp":   "2026-06-15T17:27:04"
   }
        │
        ▼
👨 Human opens dashboard
        │
        ├── ✅ Approve  →  pipeline resumes and sends
        ├── ✏️  Edit    →  edited reply sent
        └── 🔄 Regen   →  new reply generated
                │
                ▼
        ▶️  Pipeline RESUMES via thread_id
                │
                ▼
        📤 Email sent to customer
                │
                ▼
        🗑️  Redis key deleted
                │
                ▼
        💾 Supabase memory updated
```

**Why Redis here:**
The pipeline can pause for minutes or hours. Redis safely holds state with a 1 hour TTL. LangGraph uses the thread_id to resume from exactly the right point. If no human responds within 1 hour the state expires automatically.

---

## 🏗️ Full Architecture

```
                    ┌─────────────────────────────┐
                    │         Gmail Inbox          │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      IMAP IDLE Listener      │
                    │  (real-time email detection) │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   🟡 Redis db=0 — Broker     │
                    │         Task Queue           │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │        Celery Worker         │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   🔵 Redis db=2 — PII Shield │
                    │  anonymize → LLM → restore   │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │     Multi-Agent Pipeline     │
                    │  Spam → Intent → Priority    │
                    │  Personalization → Meeting   │
                    │     Context Merger           │
                    │  Agentic Reply Generator     │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  🔴 Redis db=3 — HITL State  │
                    │   Pipeline PAUSED HERE       │
                    │   Awaiting human decision    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  ✅ Approve / ✏️ Edit / 🔄   │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │         Email Sent           │
                    │  🟢 Redis db=1 — Result      │
                    │  💾 Supabase Memory Updated  │
                    └─────────────────────────────┘
```

---

## 📊 Quick Reference

| DB | Name | Written by | Read by | TTL |
|---|---|---|---|---|
| db=0 🟡 | Celery Broker | IMAP Listener | Celery Worker | On consume |
| db=1 🟢 | Celery Backend | Celery Worker | Monitoring | Configurable |
| db=2 🔵 | PII Shield | pii_shield.py | pii_shield.py | 30 minutes |
| db=3 🔴 | HITL State | mainn.py | React UI | 1 hour |

---

## ▶️ Start Redis

```bash
docker start redis-server
```

Verify:

```bash
docker ps
redis-cli ping   # should return PONG
```
