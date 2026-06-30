import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Portfolio } from "@/lib/api";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/DataTable";
import { Metric } from "@/components/Metric";
import { money, moneyParen, typeLabel } from "@/lib/utils";

const AMBER = "#FCA917";
const BLUE = "#00B2FF";
const RED = "#FF5A4D";
const PIE_COLORS = [AMBER, BLUE, "#FFD37A", "#7AD3FF", "#C8902A", "#2ECC71", "#9A9A9A"];

export function Overview({ data }: { data: Portfolio }) {
  const { summary, accounts, balances } = data;

  // Value by institution (holdings market value + positive balances).
  const instMap = new Map<string, number>();
  for (const a of accounts) {
    if (a.holdings_value > 0) {
      const k = a.institution || "?";
      instMap.set(k, (instMap.get(k) || 0) + a.holdings_value);
    }
  }
  for (const b of balances) {
    if (b.type !== "credit_card" && b.balance > 0) {
      const k = b.institution || "?";
      instMap.set(k, (instMap.get(k) || 0) + b.balance);
    }
  }
  const instData = [...instMap.entries()].map(([name, value]) => ({ name, value }));

  // Value by account — holdings (amber) + cash (blue) + liabilities (red, negative).
  const acctData = accounts
    .map((a) => {
      const full = `${a.institution ?? "?"} · ${a.name ?? a.account_id}`;
      const isLiab = a.type === "credit_card";
      const isRobo = a.type === "robo_broker";
      const value = isLiab ? -Math.abs(a.balance) : a.total_value;
      return { label: full, value, isLiab, isRobo };
    })
    .filter((d) => d.value !== 0)
    .sort((a, b) => a.value - b.value);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Net worth" value={money(summary.net_worth)} />
        <Metric label="Investments" value={money(summary.investments)} />
        <Metric label="Cash" value={money(summary.cash)} />
        <Metric
          label="Credit card balance"
          value={money(-Math.abs(summary.liabilities))}
          positive={false}
          valueRed
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-5">
            <CardTitle className="mb-3 text-sm">Value by institution</CardTitle>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={instData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={70}
                  outerRadius={110}
                  isAnimationActive={false}
                  label={(e: any) => e.name}
                >
                  {instData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: any) => money(Number(v))}
                  contentStyle={{ background: "#161616", border: "1px solid #3E3E3E" }}
                  labelStyle={{ color: "#ffffff" }}
                  itemStyle={{ color: "#ffffff" }}
                />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-5">
            <CardTitle className="mb-3 text-sm">Value by account</CardTitle>
            <ResponsiveContainer width="100%" height={Math.max(300, acctData.length * 40)}>
              <BarChart data={acctData} layout="vertical" margin={{ left: 10, right: 20 }}>
                <XAxis type="number" tickFormatter={(v) => money(v)} stroke="#9A9A9A" fontSize={11} />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={280}
                  stroke="#9A9A9A"
                  fontSize={11}
                  interval={0}
                />
                <Tooltip
                  formatter={(v: any) => money(Number(v))}
                  contentStyle={{ background: "#161616", border: "1px solid #3E3E3E" }}
                  labelStyle={{ color: "#ffffff" }}
                  itemStyle={{ color: "#ffffff" }}
                  cursor={{ fill: "#ffffff10" }}
                />
                <Bar dataKey="value" isAnimationActive={false}>
                  {acctData.map((d, i) => (
                    <Cell key={i} fill={d.isLiab ? RED : (d.isRobo || d.value <= 0) ? BLUE : AMBER} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-5">
          <CardTitle className="mb-3 text-sm">Cash &amp; balances</CardTitle>
          <DataTable
            rows={balances}
            columns={[
              {
                key: "account",
                header: "Account",
                render: (b) => `${b.institution ?? "?"} · ${b.name ?? b.account_id}`,
              },
              { key: "type", header: "Type", render: (b) => typeLabel(b.type) },
              {
                key: "balance",
                header: "Balance",
                align: "right",
                render: (b) =>
                  b.type === "credit_card" ? (
                    <span className="text-brand-red">{moneyParen(b.balance)}</span>
                  ) : (
                    money(b.balance)
                  ),
              },
            ]}
          />
        </CardContent>
      </Card>
    </div>
  );
}
