import type { Portfolio } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/DataTable";
import { money, moneyParen, typeLabel } from "@/lib/utils";
import { RefreshBar } from "@/components/RefreshBar";

interface Props {
  data: Portfolio;
  onRefreshAccounts: () => void;
  refreshingAccounts: boolean;
  plaidLastRefresh: string | null;
}

export function Accounts({ data, onRefreshAccounts, refreshingAccounts, plaidLastRefresh }: Props) {
  if (!data.accounts.length) {
    return <div className="text-sm text-muted-foreground py-8 text-center">No accounts yet.</div>;
  }

  return (
    <div className="flex flex-col gap-4">
      <RefreshBar
        label="Refresh accounts"
        timestamp={plaidLastRefresh}
        onClick={onRefreshAccounts}
        loading={refreshingAccounts}
        loadingLabel="Refreshing…"
      />
      <Card>
        <CardContent className="pt-5">
          <DataTable
            rows={data.accounts}
            columns={[
              {
                key: "account",
                header: "Account",
                render: (a) => `${a.institution ?? "?"} · ${a.name ?? a.account_id}`,
              },
              { key: "type", header: "Type", render: (a) => typeLabel(a.type) },
              { key: "holdings_value", header: "Holdings", align: "right", render: (a) => money(a.holdings_value) },
              {
                key: "balance",
                header: "Cash / Balance",
                align: "right",
                render: (a) =>
                  a.type === "credit_card" ? (
                    <span className="text-brand-red">{moneyParen(a.balance)}</span>
                  ) : (
                    money(a.balance)
                  ),
              },
              {
                key: "total_value",
                header: "Total",
                align: "right",
                render: (a) =>
                  a.type === "credit_card" ? (
                    <span className="text-brand-red">{moneyParen(a.balance)}</span>
                  ) : (
                    money(a.total_value)
                  ),
              },
            ]}
          />
          <p className="text-xs text-muted-foreground mt-3">
            Rename, re-type, categorize, or exclude accounts in the <strong>Configuration</strong> tab.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
