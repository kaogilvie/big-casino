import { useEffect, useState } from "react";
import { usePlaidLink } from "react-plaid-link";
import { api, ACCOUNT_TYPES, type ManualRow, type PlaidItem } from "@/lib/api";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function Status({ msg, error }: { msg: string | null; error: boolean }) {
  if (!msg) return null;
  return <p className={error ? "text-brand-red text-sm" : "text-brand-green text-sm"}>{msg}</p>;
}

/** Inner launcher — only mounted once we have a link token, then auto-opens. */
function PlaidLauncher({ token, onDone }: { token: string; onDone: (msg: string, err: boolean) => void }) {
  const { open, ready } = usePlaidLink({
    token,
    onSuccess: async (_publicToken, metadata) => {
      const inst = metadata.institution?.name || "Unknown";
      try {
        const r = await api.plaidExchange(_publicToken, inst);
        onDone(`Connected ${inst} — imported ${r.summary}.`, false);
      } catch (e: any) {
        onDone(e.message, true);
      }
    },
    onExit: (err) => {
      if (err) onDone(`Plaid: ${err.display_message || err.error_message}`, true);
    },
  });

  useEffect(() => {
    if (ready) open();
  }, [ready, open]);

  return null;
}

function PlaidSection({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<PlaidItem[]>([]);
  const [configured, setConfigured] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const loadItems = () => api.plaidItems().then((r) => setItems(r.items));
  useEffect(() => {
    api.plaidStatus().then((s) => setConfigured(s.configured));
    loadItems();
  }, []);

  const connect = async () => {
    setMsg(null);
    try {
      const { link_token } = await api.plaidLinkToken();
      setToken(link_token);
    } catch (e: any) {
      setMsg(e.message);
      setError(true);
    }
  };

  const finish = (m: string, err: boolean) => {
    setToken(null);
    setMsg(m);
    setError(err);
    loadItems();
    onChanged();
  };

  const refresh = async (id: string, inst: string | null) => {
    try {
      const r = await api.plaidRefresh(id);
      setMsg(`Refreshed ${inst} — ${r.summary}.`);
      setError(false);
      onChanged();
    } catch (e: any) {
      setMsg(e.message);
      setError(true);
    }
  };

  const remove = async (id: string, inst: string | null) => {
    await api.plaidDelete(id);
    setMsg(`Removed ${inst} and its imported data.`);
    setError(false);
    loadItems();
    onChanged();
  };

  return (
    <Card>
      <CardContent className="pt-5 space-y-3">
        <CardTitle className="text-sm">Connected accounts (Plaid)</CardTitle>
        {!configured && (
          <p className="text-brand-red text-sm">
            Plaid not configured — add PLAID_CLIENT_ID and PLAID_SECRET to your .env file.
          </p>
        )}
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">No accounts connected yet.</p>
        ) : (
          <div className="space-y-2">
            {items.map((it) => (
              <div key={it.item_id} className="flex items-center gap-3 text-sm">
                <span className="font-medium flex-1">{it.institution}</span>
                <span className="text-muted-foreground text-xs">
                  Connected {it.created_at?.slice(0, 10)}
                </span>
                <Button size="sm" variant="outline" onClick={() => refresh(it.item_id, it.institution)}>
                  Refresh
                </Button>
                <Button size="sm" variant="destructive" onClick={() => remove(it.item_id, it.institution)}>
                  Delete
                </Button>
              </div>
            ))}
          </div>
        )}
        {configured && (
          <Button onClick={connect} disabled={!!token}>
            + Connect account via Plaid
          </Button>
        )}
        {token && <PlaidLauncher token={token} onDone={finish} />}
        <Status msg={msg} error={error} />
      </CardContent>
    </Card>
  );
}

const UPLOADS: { endpoint: string; label: string; accept: string; extra?: "account" | "label" }[] = [
  { endpoint: "betterment-pdf", label: "Betterment statement (PDF)", accept: ".pdf" },
  { endpoint: "betterment-csv", label: "Betterment CSV", accept: ".csv" },
  { endpoint: "etrade", label: "E*TRADE export (CSV)", accept: ".csv", extra: "account" },
  { endpoint: "robinhood-csv", label: "Robinhood template (CSV)", accept: ".csv" },
  { endpoint: "chase-pdf", label: "Chase credit card (PDF)", accept: ".pdf", extra: "label" },
];

function UploadRow({ u, onChanged }: { u: (typeof UPLOADS)[number]; onChanged: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [extra, setExtra] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const submit = async () => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    if (u.extra === "account") form.append("account", extra || "Individual");
    if (u.extra === "label" && extra) form.append("label", extra);
    try {
      const r = await api.importFile(u.endpoint, form);
      setMsg(`Imported ${r.summary}.`);
      setError(false);
      onChanged();
    } catch (e: any) {
      setMsg(e.message);
      setError(true);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 py-2 border-b border-brand-gray/40">
      <span className="w-56 text-sm">{u.label}</span>
      <input
        type="file"
        accept={u.accept}
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        className="text-xs file:mr-2 file:rounded file:border file:border-brand-gray file:bg-transparent file:px-2 file:py-1 file:text-foreground"
      />
      {u.extra && (
        <input
          placeholder={u.extra === "account" ? "Account name" : "Label (optional)"}
          value={extra}
          onChange={(e) => setExtra(e.target.value)}
          className="bg-transparent border border-brand-gray rounded px-2 py-1 text-xs w-40"
        />
      )}
      <Button size="sm" onClick={submit} disabled={!file}>
        Import
      </Button>
      <Status msg={msg} error={error} />
    </div>
  );
}

const BLANK_ROW: ManualRow = {
  broker: "Robinhood",
  account: "Individual",
  type: "brokerage",
  symbol: "",
  quantity: "",
  cost_per_share: "",
  purchase_date: "",
};

function ManualEntry({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<ManualRow[]>([{ ...BLANK_ROW }]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const update = (i: number, key: keyof ManualRow, val: string) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [key]: val } : r)));

  const submit = async () => {
    const filled = rows.filter((r) => r.symbol.trim());
    if (!filled.length) {
      setMsg("Add at least one row with a symbol (use CASH for cash).");
      setError(true);
      return;
    }
    try {
      const r = await api.importManual(filled);
      setMsg(`Saved ${r.summary}.`);
      setError(false);
      setRows([{ ...BLANK_ROW }]);
      onChanged();
    } catch (e: any) {
      setMsg(e.message);
      setError(true);
    }
  };

  const cell = "bg-transparent border border-brand-gray rounded px-2 py-1 text-xs";
  return (
    <Card>
      <CardContent className="pt-5 space-y-3">
        <CardTitle className="text-sm">Enter holdings manually</CardTitle>
        <p className="text-xs text-muted-foreground">
          One row per purchase (lot) for exact returns. Use <code>CASH</code> as the symbol for a cash
          balance. Saving appends to existing holdings.
        </p>
        <div className="overflow-x-auto">
          <table className="text-xs">
            <thead className="text-muted-foreground">
              <tr>
                {["Broker", "Account", "Type", "Symbol", "Qty", "Cost/share", "Date (YYYY-MM-DD)", ""].map((h) => (
                  <th key={h} className="px-1 py-1 text-left font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-1 py-1"><input className={`${cell} w-24`} value={r.broker} onChange={(e) => update(i, "broker", e.target.value)} /></td>
                  <td className="px-1 py-1"><input className={`${cell} w-24`} value={r.account} onChange={(e) => update(i, "account", e.target.value)} /></td>
                  <td className="px-1 py-1">
                    <select className={cell} value={r.type} onChange={(e) => update(i, "type", e.target.value)}>
                      {ACCOUNT_TYPES.map((t) => (
                        <option key={t} value={t} className="bg-brand-panel">{t}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-1 py-1"><input className={`${cell} w-20`} value={r.symbol} onChange={(e) => update(i, "symbol", e.target.value)} /></td>
                  <td className="px-1 py-1"><input className={`${cell} w-20`} value={r.quantity} onChange={(e) => update(i, "quantity", e.target.value)} /></td>
                  <td className="px-1 py-1"><input className={`${cell} w-24`} value={r.cost_per_share} onChange={(e) => update(i, "cost_per_share", e.target.value)} /></td>
                  <td className="px-1 py-1"><input className={`${cell} w-32`} value={r.purchase_date} onChange={(e) => update(i, "purchase_date", e.target.value)} /></td>
                  <td className="px-1 py-1">
                    {rows.length > 1 && (
                      <button className="text-brand-red px-1" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setRows((rs) => [...rs, { ...BLANK_ROW }])}>
            + Add row
          </Button>
          <Button size="sm" onClick={submit}>
            Save entries
          </Button>
          <Status msg={msg} error={error} />
        </div>
      </CardContent>
    </Card>
  );
}

export function Import({ onChanged }: { onChanged: () => void }) {
  return (
    <div className="space-y-6">
      <PlaidSection onChanged={onChanged} />
      <Card>
        <CardContent className="pt-5">
          <CardTitle className="text-sm mb-3">Upload a file</CardTitle>
          {UPLOADS.map((u) => (
            <UploadRow key={u.endpoint} u={u} onChanged={onChanged} />
          ))}
        </CardContent>
      </Card>
      <ManualEntry onChanged={onChanged} />
    </div>
  );
}
