import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface MetricProps {
  label: string;
  value: string;
  delta?: string;
  positive?: boolean;
}

export function Metric({ label, value, delta, positive = true }: MetricProps) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground mb-1.5">{label}</div>
      <div className="text-2xl font-bold tracking-tight">{value}</div>
      {delta && (
        <div className={cn("text-sm mt-1", positive ? "text-brand-green" : "text-brand-red")}>
          {positive ? "▲" : "▼"} {delta}
        </div>
      )}
    </Card>
  );
}
