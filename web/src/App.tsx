import { useCallback, useEffect, useState } from "react";
import { api, type Portfolio } from "@/lib/api";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Overview } from "@/views/Overview";
import { Holdings } from "@/views/Holdings";
import { Accounts } from "@/views/Accounts";
import { Cards } from "@/views/Cards";
import { Configuration } from "@/views/Import";

const TABS = ["Overview", "Holdings", "Accounts", "Credit Cards", "Configuration"];
const CATEGORIES: { label: string; value: string }[] = [
  { label: "All", value: "all" },
  { label: "Personal", value: "personal" },
  { label: "&KO", value: "ko" },
];

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [showRetirement, setShowRetirement] = useState(false);
  const [category, setCategory] = useState("all");
  const [data, setData] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshingAccounts, setRefreshingAccounts] = useState(false);
  const [hideTaxes, setHideTaxes] = useState(true);

  const load = useCallback(() => {
    setError(null);
    api
      .portfolio(showRetirement, category, hideTaxes)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [showRetirement, category, hideTaxes]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen max-w-6xl mx-auto px-6 py-6">
      <header className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Big Casino <span className="text-base font-normal text-muted-foreground">by &amp;KO</span>
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Your personal finance dashboard, local and private.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-md border border-brand-gray overflow-hidden text-sm">
            {CATEGORIES.map((c) => (
              <button
                key={c.value}
                onClick={() => setCategory(c.value)}
                className={
                  category === c.value
                    ? "bg-primary text-primary-foreground px-3 py-1.5"
                    : "px-3 py-1.5 text-muted-foreground hover:text-foreground"
                }
              >
                {c.label}
              </button>
            ))}
          </div>
          {tab === "Overview" && (
            <Button variant="outline" size="sm" onClick={() => setShowRetirement((v) => !v)}>
              {showRetirement ? "Hide retirement" : "View retirement"}
            </Button>
          )}
          {tab === "Overview" && (
            <Button variant="outline" size="sm" onClick={() => setHideTaxes((v) => !v)}>
              {hideTaxes ? "View tax reserved" : "Hide tax reserved"}
            </Button>
          )}
        </div>
      </header>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      <div className="py-6">
        {error && <p className="text-brand-red text-sm mb-4">Error: {error}</p>}
        {!data && !error && <p className="text-muted-foreground">Loading…</p>}
        {data && (
          <>
            {tab === "Overview" && <Overview data={data} />}
            {tab === "Holdings" && (
              <Holdings
                data={data}
                onRefreshPrices={() => api.refreshPrices().then(load)}
                pricesAsOf={data.prices_as_of}
              />
            )}
            {tab === "Accounts" && (
              <Accounts
                data={data}
                onRefreshAccounts={() => {
                  setRefreshingAccounts(true);
                  api.plaidRefreshAll().then(load).finally(() => setRefreshingAccounts(false));
                }}
                refreshingAccounts={refreshingAccounts}
                plaidLastRefresh={data.plaid_last_refresh}
              />
            )}
            {tab === "Credit Cards" && (
              <Cards
                data={data}
                onRefreshAccounts={() => {
                  setRefreshingAccounts(true);
                  api.plaidRefreshAll().then(load).finally(() => setRefreshingAccounts(false));
                }}
                refreshingAccounts={refreshingAccounts}
                plaidLastRefresh={data.plaid_last_refresh}
              />
            )}
            {tab === "Configuration" && <Configuration onChanged={load} />}
          </>
        )}
      </div>
    </div>
  );
}
