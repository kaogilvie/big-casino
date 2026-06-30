import { useEffect, useState } from "react";
import { usePlaidLink } from "react-plaid-link";
import { api, ACCOUNT_TYPES, type ManagedAccount, type ManualRow, type PlaidItem } from "@/lib/api";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Collapsible } from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";
import { typeLabel } from "@/lib/utils";

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

function PlaidItemRow({
  it,
  onRefresh,
  onRemove,
  onAliasSaved,
}: {
  it: PlaidItem;
  onRefresh: (id: string, label: string | null) => void;
  onRemove: (id: string, label: string | null) => void;
  onAliasSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [alias, setAlias] = useState(it.alias ?? "");
  const label = it.alias || it.institution;

  const save = async () => {
    await api.plaidSetAlias(it.item_id, alias.trim());
    setEditing(false);
    onAliasSaved();
  };

  return (
    <div className="flex items-center gap-3 text-sm">
      {editing ? (
        <div className="flex items-center gap-2 flex-1">
          <input
            autoFocus
            className="bg-transparent border border-brand-gray rounded px-2 py-1 text-sm w-56"
            placeholder={it.institution ?? "Alias"}
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
          <Button size="sm" onClick={save}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setAlias(it.alias ?? ""); setEditing(false); }}>
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex items-baseline gap-2 flex-1">
          <span className="font-medium">{label}</span>
          {it.alias && <span className="text-muted-foreground text-xs">({it.institution})</span>}
          <button className="text-muted-foreground hover:text-foreground text-xs" onClick={() => setEditing(true)}>
            ✎ alias
          </button>
        </div>
      )}
      <span className="text-muted-foreground text-xs">Connected {it.created_at?.slice(0, 10)}</span>
      <Button size="sm" variant="outline" onClick={() => onRefresh(it.item_id, label)}>
        Refresh
      </Button>
      <Button size="sm" variant="destructive" onClick={() => onRemove(it.item_id, label)}>
        Delete
      </Button>
    </div>
  );
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
              <PlaidItemRow
                key={it.item_id}
                it={it}
                onRefresh={refresh}
                onRemove={remove}
                onAliasSaved={loadItems}
              />
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
      <div className="space-y-3">
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
                        <option key={t} value={t} className="bg-brand-panel">{typeLabel(t)}</option>
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
      </div>
  );
}

function AccountRow({ a, onChanged }: { a: ManagedAccount; onChanged: () => void }) {
  const [institution, setInstitution] = useState(a.institution);
  const [name, setName] = useState(a.name);
  const [type, setType] = useState(a.type);
  const [category, setCategory] = useState(a.category);
  const [excluded, setExcluded] = useState(a.excluded);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const dirty =
    institution !== a.institution ||
    name !== a.name ||
    type !== a.type ||
    category !== a.category ||
    excluded !== a.excluded;

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (category !== a.category || excluded !== a.excluded) {
        await api.updateAccountSettings(a.account_id, { category, excluded });
      }
      if (institution !== a.institution || name !== a.name || type !== a.type) {
        await api.renameAccount(a.account_id, { institution, name, type });
      }
      onChanged();
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  };

  const input = "bg-transparent border border-brand-gray rounded px-2 py-1 text-xs";
  return (
    <tr className={`border-b border-brand-gray/40 ${excluded ? "opacity-50" : ""}`}>
      <td className="px-2 py-1.5"><input className={`${input} w-28`} value={institution} onChange={(e) => setInstitution(e.target.value)} /></td>
      <td className="px-2 py-1.5"><input className={`${input} w-48`} value={name} onChange={(e) => setName(e.target.value)} /></td>
      <td className="px-2 py-1.5">
        <select className={input} value={type} onChange={(e) => setType(e.target.value)}>
          {ACCOUNT_TYPES.map((t) => <option key={t} value={t} className="bg-brand-panel">{typeLabel(t)}</option>)}
        </select>
      </td>
      <td className="px-2 py-1.5">
        <div className="inline-flex rounded border border-brand-gray overflow-hidden text-xs">
          <button
            className={category === "personal" ? "bg-primary text-primary-foreground px-2 py-1" : "px-2 py-1"}
            onClick={() => setCategory("personal")}
          >
            Personal
          </button>
          <button
            className={category === "ko" ? "bg-primary text-primary-foreground px-2 py-1" : "px-2 py-1"}
            onClick={() => setCategory("ko")}
          >
            &amp;KO
          </button>
        </div>
      </td>
      <td className="px-2 py-1.5 text-center">
        <input type="checkbox" checked={excluded} onChange={(e) => setExcluded(e.target.checked)} />
      </td>
      <td className="px-2 py-1.5">
        {dirty && (
          <Button size="sm" onClick={save} disabled={busy}>
            Save
          </Button>
        )}
        {err && <div className="text-brand-red text-xs">{err}</div>}
      </td>
    </tr>
  );
}

function ManageAccounts({ onChanged }: { onChanged: () => void }) {
  const [accounts, setAccounts] = useState<ManagedAccount[]>([]);
  const load = () => api.listAccounts().then((r) => setAccounts(r.accounts));
  useEffect(() => {
    load();
  }, []);

  const changed = () => {
    load();
    onChanged();
  };

  return (
    <Card>
      <CardContent className="pt-5">
        <CardTitle className="text-sm mb-1">Manage accounts</CardTitle>
        <p className="text-xs text-muted-foreground mb-3">
          Rename, re-type, tag as Personal or &amp;KO, or exclude an account from all views (e.g. a
          broken Plaid feed). Excluded accounts stay in the database and can be restored here.
        </p>
        <div className="overflow-x-auto">
          <table className="text-xs">
            <thead className="text-muted-foreground">
              <tr>
                {["Institution", "Name", "Type", "Category", "Exclude", ""].map((h) => (
                  <th key={h} className="px-2 py-1 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <AccountRow key={a.account_id} a={a} onChanged={changed} />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export function Configuration({ onChanged }: { onChanged: () => void }) {
  return (
    <div className="space-y-6">
      <PlaidSection onChanged={onChanged} />
      <ManageAccounts onChanged={onChanged} />
      <Collapsible title="Upload a file">
        {UPLOADS.map((u) => (
          <UploadRow key={u.endpoint} u={u} onChanged={onChanged} />
        ))}
      </Collapsible>
      <Collapsible title="Enter holdings manually">
        <ManualEntry onChanged={onChanged} />
      </Collapsible>
    </div>
  );
}
