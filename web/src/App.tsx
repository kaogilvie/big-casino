import { useCallback, useEffect, useState } from "react";
import { api, type Portfolio } from "@/lib/api";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Overview } from "@/views/Overview";
import { Holdings } from "@/views/Holdings";
import { Accounts } from "@/views/Accounts";
import { Cards } from "@/views/Cards";
import { Import } from "@/views/Import";

const TABS = ["Overview", "Holdings", "Accounts", "Credit Cards", "Import"];

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [showRetirement, setShowRetirement] = useState(false);
  const [data, setData] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .portfolio(showRetirement)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [showRetirement]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="min-h-screen max-w-6xl mx-auto px-6 py-6">
      <header className="flex items-center justify-between mb-2">
        <h1 className="text-3xl font-bold tracking-tight">
          Big Casino <span className="text-base font-normal text-muted-foreground">by &amp;KO</span>
        </h1>
        <div className="flex items-center gap-2">
          {tab === "Overview" && (
            <Button variant="outline" size="sm" onClick={() => setShowRetirement((v) => !v)}>
              {showRetirement ? "Hide retirement" : "View retirement"}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => api.refreshPrices().then(load)}>
            Refresh prices
          </Button>
        </div>
      </header>
      <p className="text-sm text-muted-foreground mb-4">
        Your personal finance dashboard, local and private.
        {data?.prices_as_of && ` · Prices as of ${data.prices_as_of}`}
      </p>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      <div className="py-6">
        {error && <p className="text-brand-red text-sm mb-4">Error: {error}</p>}
        {!data && !error && <p className="text-muted-foreground">Loading…</p>}
        {data && (
          <>
            {tab === "Overview" && <Overview data={data} />}
            {tab === "Holdings" && <Holdings data={data} />}
            {tab === "Accounts" && <Accounts data={data} onChanged={load} />}
            {tab === "Credit Cards" && <Cards data={data} />}
            {tab === "Import" && <Import onChanged={load} />}
          </>
        )}
      </div>
    </div>
  );
}
