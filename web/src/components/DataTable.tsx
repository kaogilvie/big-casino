import { cn } from "@/lib/utils";

export interface Column<T> {
  key: keyof T | string;
  header: string;
  align?: "left" | "right";
  render?: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  empty?: string;
}

export function DataTable<T extends Record<string, any>>({
  columns,
  rows,
  empty = "No data.",
}: DataTableProps<T>) {
  if (!rows.length) {
    return <div className="text-sm text-muted-foreground py-6 text-center">{empty}</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-brand-gray text-muted-foreground">
            {columns.map((c) => (
              <th
                key={String(c.key)}
                className={cn("py-2 px-3 font-medium", c.align === "right" ? "text-right" : "text-left")}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-brand-gray/40 hover:bg-brand-panel/60">
              {columns.map((c) => (
                <td
                  key={String(c.key)}
                  className={cn("py-2 px-3", c.align === "right" ? "text-right tabular-nums" : "text-left")}
                >
                  {c.render ? c.render(row) : String(row[c.key as keyof T] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
