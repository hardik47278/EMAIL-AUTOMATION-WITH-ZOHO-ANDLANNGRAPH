import { useCallback, useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import Sidebar from "./components/Sidebar.jsx";
import Topbar from "./components/Topbar.jsx";
import PendingCard from "./components/PendingCard.jsx";
import InboxTab from "./components/InboxTab.jsx";
import LogTab from "./components/LogTab.jsx";
import Insights from "./components/Insights.jsx";
import { getPending, getProcessed, getStats, getLogOnly } from "./api.js";

const PAGE_META = {
  pending: { title: "Pending approvals", subtitle: "Review AI-generated replies before they're sent" },
  inbox: { title: "Inbox", subtitle: "Emails processed by your AI assistant" },
  logged: { title: "Auto-logged", subtitle: "OTP, promotions, newsletters & notifications — no review needed" },
  insights: { title: "Insights", subtitle: "How your inbox is trending" },
};

export default function App() {
  const [active, setActive] = useState("pending");
  const [pending, setPending] = useState([]);
  const [processed, setProcessed] = useState([]);
  const [stats, setStats] = useState({});
  const [logOnly, setLogOnly] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const [priorityFilter, setPriorityFilter] = useState("ALL");
  const [intentFilter, setIntentFilter] = useState("ALL");
  const [logFilter, setLogFilter] = useState("ALL");

  const loadAll = useCallback(async () => {
    setRefreshing(true);
    const [p, pr, s, l] = await Promise.all([getPending(), getProcessed(), getStats(), getLogOnly()]);
    setPending(p);
    setProcessed(pr);
    setStats(s);
    setLogOnly(l);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const meta = PAGE_META[active];
  const counts = {
    pending: pending.length,
    inbox: 0,
    logged: logOnly.length,
    insights: 0,
  };

  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar active={active} onChange={setActive} counts={counts} />

      <div className="flex-1">
        <Topbar title={meta.title} subtitle={meta.subtitle} onRefresh={loadAll} refreshing={refreshing} />

        <main className="mx-auto max-w-5xl px-8 py-8">
          {active === "pending" && (
            <>
              {pending.length === 0 ? (
                <div className="flex flex-col items-center gap-3 rounded-xl2 border border-dashed border-line bg-surface py-16 text-center">
                  <CheckCircle2 size={28} className="text-low" />
                  <p className="text-[14px] font-semibold text-ink">All caught up!</p>
                  <p className="text-[13px] text-ink3">No emails waiting for approval.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {pending.map((email) => (
                    <PendingCard key={email.thread_id} email={email} onChanged={loadAll} />
                  ))}
                </div>
              )}
            </>
          )}

          {active === "inbox" && (
            <InboxTab
              processed={processed}
              priorityFilter={priorityFilter}
              intentFilter={intentFilter}
              onPriorityChange={setPriorityFilter}
              onIntentChange={setIntentFilter}
            />
          )}

          {active === "logged" && <LogTab logOnly={logOnly} filter={logFilter} onFilterChange={setLogFilter} />}

          {active === "insights" && <Insights stats={stats} processed={processed} />}
        </main>
      </div>
    </div>
  );
}
