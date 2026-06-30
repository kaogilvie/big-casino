import type { Portfolio } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { DataTable } from "@/components/DataTable";
import { money } from "@/lib/utils";
import { RefreshBar } from "@/components/RefreshBar";

interface Props {
  data: Portfolio;
  onRefreshPrices: () => void;
  pricesAsOf: string | null;
}

export function Holdings({ data, onRefreshPrices, pricesAsOf }: Props) {
  const rows = data.holdings.filter((h) => h.symbol !== "CASH");
  return (
    <div className="flex flex-col gap-4">
      <RefreshBar
        label="Refresh prices"
        timestamp={pricesAsOf}
        onClick={onRefreshPrices}
      />
      <Card>
        <CardContent className="pt-5">
          <DataTable
            rows={rows}
            empty="No holdings yet. Import or connect an account."
            columns={[
              { key: "symbol", header: "Symbol" },
              {
                key: "account",
                header: "Account",
                render: (h) => `${h.institution ?? "?"} · ${h.name ?? ""}`,
              },
              { key: "quantity", header: "Qty", align: "right", render: (h) => h.quantity.toFixed(4) },
              { key: "current_price", header: "Price", align: "right", render: (h) => money(h.current_price) },
              { key: "market_value", header: "Value", align: "right", render: (h) => money(h.market_value) },
              { key: "cost_basis", header: "Cost", align: "right", render: (h) => money(h.cost_basis) },
              {
                key: "unrealized",
                header: "Gain/Loss",
                align: "right",
                render: (h) => (
                  <span className={(h.unrealized ?? 0) >= 0 ? "text-brand-green" : "text-brand-red"}>
                    {money(h.unrealized)}
                    {h.unrealized_pct != null ? ` (${h.unrealized_pct.toFixed(1)}%)` : ""}
                  </span>
                ),
              },
            ]}
          />
        </CardContent>
      </Card>
    </div>
  );
}
