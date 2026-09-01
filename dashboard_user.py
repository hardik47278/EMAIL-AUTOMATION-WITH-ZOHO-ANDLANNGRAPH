import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


@st.cache_data(ttl=30)
def load_emails():
    try:
        return supabase.table("email_history").select("*").order("date", desc=True).execute().data
    except:
        return []


@st.cache_data(ttl=30)
def load_customers():
    try:
        return supabase.table("customer_summary").select("*").execute().data
    except:
        return []


st.set_page_config(
    page_title="AI Email Ops",
    page_icon="📧",
    layout="wide"
)

st.title("📧 AI Email Operations Dashboard")
st.caption("Multi-Agent Email Pipeline • Real-time monitoring")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

emails    = load_emails()
customers = load_customers()

df  = pd.DataFrame(emails)    if emails    else pd.DataFrame()
cdf = pd.DataFrame(customers) if customers else pd.DataFrame()

st.divider()

# ─── PAGE TABS ────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Overview",
    "📩 Email Records",
    "👥 Customers",
    "🔍 Email Detail"
])


# ═══════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ═══════════════════════════════════════════════════════════
with tab1:

    st.subheader("System KPIs")

    if df.empty:
        st.info("No data yet. Run the pipeline to see results.")
    else:
        total     = len(df)
        resolved  = len(df[df["resolved"] == True]) if "resolved" in df else 0
        unresolved = total - resolved
        high_pri  = len(df[df["final_priority"] == "HIGH"]) if "final_priority" in df else 0
        avg_time  = int(df["resolution_time_mins"].dropna().mean()) if "resolution_time_mins" in df else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Emails",     total)
        c2.metric("Resolved",         resolved)
        c3.metric("Unresolved",       unresolved)
        c4.metric("High Priority",    high_pri)
        c5.metric("Avg Resolve Time", f"{avg_time} mins")

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Priority Distribution")
            if "final_priority" in df.columns:
                priority_counts = df["final_priority"].value_counts().reset_index()
                priority_counts.columns = ["priority", "count"]
                fig = px.bar(
                    priority_counts,
                    x="priority",
                    y="count",
                    color="priority",
                    color_discrete_map={
                        "HIGH":   "#ef4444",
                        "MEDIUM": "#f97316",
                        "LOW":    "#22c55e"
                    }
                )
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Sentiment Distribution")
            if "sentiment" in df.columns:
                sentiment_counts = df["sentiment"].value_counts().reset_index()
                sentiment_counts.columns = ["sentiment", "count"]
                fig = px.pie(
                    sentiment_counts,
                    names="sentiment",
                    values="count",
                    hole=0.4
                )
                st.plotly_chart(fig, use_container_width=True)

        col3, col4 = st.columns(2)

        with col3:
            st.subheader("Intent Breakdown")
            if "intent" in df.columns:
                intent_counts = df["intent"].value_counts().reset_index()
                intent_counts.columns = ["intent", "count"]
                fig = px.bar(
                    intent_counts,
                    x="intent",
                    y="count",
                    color="intent"
                )
                st.plotly_chart(fig, use_container_width=True)

        with col4:
            st.subheader("Resolved vs Unresolved")
            if "resolved" in df.columns:
                fig = px.pie(
                    names=["Resolved", "Unresolved"],
                    values=[resolved, unresolved],
                    color_discrete_sequence=["#22c55e", "#ef4444"],
                    hole=0.4
                )
                st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 2 — EMAIL RECORDS
# ═══════════════════════════════════════════════════════════
with tab2:

    st.subheader("All Email Records")

    if df.empty:
        st.info("No email records found.")
    else:
        col1, col2, col3 = st.columns(3)

        with col1:
            priority_filter = st.selectbox(
                "Priority",
                ["ALL"] + list(df["final_priority"].dropna().unique()) if "final_priority" in df else ["ALL"]
            )

        with col2:
            intent_filter = st.selectbox(
                "Intent",
                ["ALL"] + list(df["intent"].dropna().unique()) if "intent" in df else ["ALL"]
            )

        with col3:
            sentiment_filter = st.selectbox(
                "Sentiment",
                ["ALL"] + list(df["sentiment"].dropna().unique()) if "sentiment" in df else ["ALL"]
            )

        filtered_df = df.copy()

        if priority_filter != "ALL" and "final_priority" in filtered_df:
            filtered_df = filtered_df[filtered_df["final_priority"] == priority_filter]

        if intent_filter != "ALL" and "intent" in filtered_df:
            filtered_df = filtered_df[filtered_df["intent"] == intent_filter]

        if sentiment_filter != "ALL" and "sentiment" in filtered_df:
            filtered_df = filtered_df[filtered_df["sentiment"] == sentiment_filter]

        display_cols = [
            col for col in [
                "customer_id", "date", "intent",
                "urgency", "sentiment", "final_priority",
                "resolved", "resolution_time_mins"
            ] if col in filtered_df.columns
        ]

        st.dataframe(
            filtered_df[display_cols],
            use_container_width=True
        )

        st.caption(f"Showing {len(filtered_df)} of {len(df)} records")


# ═══════════════════════════════════════════════════════════
# TAB 3 — CUSTOMER PROFILES
# ═══════════════════════════════════════════════════════════
with tab3:

    st.subheader("Customer Intelligence")

    if cdf.empty:
        st.info("No customer data found.")
    else:
        churn_count   = len(cdf[cdf["churn_risk"] == True]) if "churn_risk" in cdf else 0
        critical_count = len(cdf[cdf["health_status"] == "critical"]) if "health_status" in cdf else 0
        at_risk_count = len(cdf[cdf["health_status"] == "at_risk"]) if "health_status" in cdf else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Customers",  len(cdf))
        c2.metric("Churn Risk",       churn_count,    delta_color="inverse")
        c3.metric("Critical",         critical_count, delta_color="inverse")
        c4.metric("At Risk",          at_risk_count,  delta_color="inverse")

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Health Status")
            if "health_status" in cdf.columns:
                health_counts = cdf["health_status"].value_counts().reset_index()
                health_counts.columns = ["status", "count"]
                fig = px.pie(
                    health_counts,
                    names="status",
                    values="count",
                    color="status",
                    color_discrete_map={
                        "healthy":  "#22c55e",
                        "at_risk":  "#f97316",
                        "critical": "#ef4444"
                    },
                    hole=0.4
                )
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Sentiment Trends")
            if "sentiment_trend" in cdf.columns:
                trend_counts = cdf["sentiment_trend"].value_counts().reset_index()
                trend_counts.columns = ["trend", "count"]
                fig = px.bar(
                    trend_counts,
                    x="trend",
                    y="count",
                    color="trend",
                    color_discrete_map={
                        "improving": "#22c55e",
                        "stable":    "#3b82f6",
                        "declining": "#ef4444"
                    }
                )
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Customer Table")

        display_cols = [
            col for col in [
                "customer_id", "total_emails", "unresolved_count",
                "most_common_intent", "health_status", "churn_risk",
                "sentiment_trend", "avg_resolution_mins", "last_contact_date"
            ] if col in cdf.columns
        ]

        if "churn_risk" in cdf.columns:
            cdf_display = cdf.copy()
            cdf_display["churn_risk"] = cdf_display["churn_risk"].map(
                {True: "⚠️ YES", False: "✅ NO"}
            )
            st.dataframe(cdf_display[display_cols], use_container_width=True)
        else:
            st.dataframe(cdf[display_cols], use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 4 — EMAIL DETAIL
# ═══════════════════════════════════════════════════════════
with tab4:

    st.subheader("Email Detail Viewer")

    if df.empty:
        st.info("No emails found.")
    else:
        customer_list = ["ALL"] + list(df["customer_id"].dropna().unique())

        selected_customer = st.selectbox(
            "Filter by Customer",
            customer_list
        )

        if selected_customer != "ALL":
            detail_df = df[df["customer_id"] == selected_customer]
        else:
            detail_df = df

        if not detail_df.empty:
            selected_idx = st.selectbox(
                "Select Email",
                range(len(detail_df)),
                format_func=lambda i: f"{detail_df.iloc[i].get('date', 'N/A')} | {detail_df.iloc[i].get('intent', 'N/A')} | {detail_df.iloc[i].get('final_priority', 'N/A')}"
            )

            email = detail_df.iloc[selected_idx]

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### 📋 Email Info")
                st.write(f"**Customer:**  {email.get('customer_id', 'N/A')}")
                st.write(f"**Date:**      {email.get('date', 'N/A')}")
                st.write(f"**Intent:**    {email.get('intent', 'N/A')}")
                st.write(f"**Urgency:**   {email.get('urgency', 'N/A')}")
                st.write(f"**Sentiment:** {email.get('sentiment', 'N/A')}")

            with col2:
                st.markdown("#### 🎯 Priority & Resolution")
                st.write(f"**Agent 2 Priority:** {email.get('agent2_priority', 'N/A')}")
                st.write(f"**Agent 3 Priority:** {email.get('agent3_priority', 'N/A')}")
                st.write(f"**Final Priority:**   {email.get('final_priority', 'N/A')}")
                st.write(f"**Resolved:**         {email.get('resolved', 'N/A')}")
                st.write(f"**Resolution Time:**  {email.get('resolution_time_mins', 'N/A')} mins")

            st.markdown("#### 💬 Resolution")
            resolution = email.get("resolution", "")
            if resolution:
                st.text_area(
                    "Reply Sent",
                    value=resolution,
                    height=150,
                    disabled=True
                )
            else:
                st.info("No resolution recorded yet")