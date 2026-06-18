import { cn } from "@/lib/utils";

interface TabsProps {
  tabs: string[];
  active: string;
  onChange: (t: string) => void;
}

export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div className="flex gap-1 border-b border-brand-gray">
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={cn(
            "px-4 py-2.5 text-sm font-medium -mb-px border-b-2 transition-colors",
            active === t
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
