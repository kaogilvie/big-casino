import { useState, type ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";

export function Collapsible({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-left text-sm font-semibold"
      >
        {title}
        <span className="text-muted-foreground transition-transform" style={{ transform: open ? "rotate(90deg)" : "" }}>
          ›
        </span>
      </button>
      {open && <CardContent className="pt-0">{children}</CardContent>}
    </Card>
  );
}
