import { useState } from "react";
import { api, ACCOUNT_TYPES, type AccountRow, type Portfolio } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { money, moneyParen } from "@/lib/utils";

function EditRow({
  a,
  onSaved,
  onCancel,
}: {
  a: AccountRow;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [institution, setInstitution] = useState(a.institution ?? "");
  const [name, setName] = useState(a.name ?? "");
  const [type, setType] = useState(a.type ?? "brokerage");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      await api.renameAccount(a.account_id, { institution, name, type });
      onSaved();
    } catch (e: any) {
      setErr(e.message);
      setSaving(false);
    }
  };

  const input = "bg-transparent border border-brand-gray rounded px-2 py-1 text-sm";
  return (
    <tr className="border-b border-brand-gray/40 bg-brand-panel/40">
      <td className="py-2 px-3">
        <div className="flex gap-2">
          <input className={`${input} w-28`} value={institution} onChange={(e) => setInstitution(e.target.value)} />
          <input className={`${input} flex-1`} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {err && <div className="text-brand-red text-xs mt-1">{err}</div>}
      </td>
      <td className="py-2 px-3">
        <select className={input} value={type} onChange={(e) => setType(e.target.value)}>
          {ACCOUNT_TYPES.map((t) => (
            <option key={t} value={t} className="bg-brand-panel">
              {t}
            </option>
          ))}
        </select>
      </td>
      <td className="py-2 px-3 text-right tabular-nums">{money(a.holdings_value)}</td>
      <td className="py-2 px-3 text-right tabular-nums">{money(a.balance)}</td>
      <td className="py-2 px-3 text-right">
        <div className="flex gap-2 justify-end">
          <Button size="sm" onClick={save} disabled={saving}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </div>
      </td>
    </tr>
  );
}

export function Accounts({ data, onChanged }: { data: Portfolio; onChanged: () => void }) {
  const [editing, setEditing] = useState<string | null>(null);

  if (!data.accounts.length) {
    return <div className="text-sm text-muted-foreground py-8 text-center">No accounts yet.</div>;
  }

  const saved = () => {
    setEditing(null);
    onChanged();
  };

  return (
    <Card>
      <CardContent className="pt-5 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-brand-gray text-muted-foreground">
              <th className="py-2 px-3 text-left font-medium">Account</th>
              <th className="py-2 px-3 text-left font-medium">Type</th>
              <th className="py-2 px-3 text-right font-medium">Holdings</th>
              <th className="py-2 px-3 text-right font-medium">Cash / Balance</th>
              <th className="py-2 px-3 text-right font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {data.accounts.map((a) =>
              editing === a.account_id ? (
                <EditRow key={a.account_id} a={a} onSaved={saved} onCancel={() => setEditing(null)} />
              ) : (
                <tr key={a.account_id} className="border-b border-brand-gray/40 hover:bg-brand-panel/60">
                  <td className="py-2 px-3">{`${a.institution ?? "?"} · ${a.name ?? a.account_id}`}</td>
                  <td className="py-2 px-3">{a.type}</td>
                  <td className="py-2 px-3 text-right tabular-nums">{money(a.holdings_value)}</td>
                  <td className="py-2 px-3 text-right tabular-nums">
                    {a.type === "credit_card" ? (
                      <span className="text-brand-red">{moneyParen(a.balance)}</span>
                    ) : (
                      money(a.balance)
                    )}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(a.account_id)}>
                      Edit
                    </Button>
                  </td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
