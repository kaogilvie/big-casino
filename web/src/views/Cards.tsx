import type { Portfolio } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/DataTable";
import { Metric } from "@/components/Metric";
import { money } from "@/lib/utils";

function dueLabel(due: string | null): string {
  if (!due) return "—";
  const d = new Date(due + "T00:00:00");
  const days = Math.round((d.getTime() - Date.now()) / 86400000);
  const when = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  if (days < 0) return `${when} (overdue)`;
  if (days === 0) return `${when} (today)`;
  return `${when} (${days}d)`;
}

export function Cards({ data }: { data: Portfolio }) {
  const cards = data.cards;
  const totalOwed = cards.reduce((s, c) => s + (c.balance || 0), 0);
  const totalStatement = cards.reduce((s, c) => s + (c.statement_balance || 0), 0);
  const totalMin = cards.reduce((s, c) => s + (c.minimum_payment || 0), 0);

  if (!cards.length) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        No credit cards yet. Connect a card via Plaid in the Import tab.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Metric label="Current balance (owed)" value={money(totalOwed)} />
        <Metric label="Statement balance (to avoid interest)" value={money(totalStatement)} />
        <Metric label="Minimum due" value={money(totalMin)} />
      </div>

      <Card>
        <CardContent className="pt-5">
          <DataTable
            rows={cards}
            columns={[
              {
                key: "card",
                header: "Card",
                render: (c) => `${c.institution ?? "?"} · ${c.name ?? c.account_id}`,
              },
              { key: "balance", header: "Current balance", align: "right", render: (c) => money(c.balance) },
              {
                key: "statement_balance",
                header: "Statement balance",
                align: "right",
                render: (c) => money(c.statement_balance),
              },
              {
                key: "minimum_payment",
                header: "Min. payment",
                align: "right",
                render: (c) => money(c.minimum_payment),
              },
              { key: "due_date", header: "Payment due", align: "right", render: (c) => dueLabel(c.due_date) },
            ]}
          />
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        <strong>Statement balance</strong> is what to pay by the due date to avoid interest. Statement
        detail comes from Plaid; cards connected without the liabilities product show current balance only.
      </p>
    </div>
  );
}
