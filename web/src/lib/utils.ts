import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function money(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** Liabilities shown in accounting parentheses, e.g. ($877.33). */
export function moneyParen(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `(${Math.abs(x).toLocaleString("en-US", { style: "currency", currency: "USD" })})`;
}

/** Human-friendly account-type label. Backend stores lowercase slugs. */
const TYPE_LABELS: Record<string, string> = {
  brokerage: "Brokerage",
  bank: "Bank",
  credit_card: "Credit Card",
  retirement: "Retirement",
  taxes: "Taxes",
  robo_broker: "Robo-broker",
};

export function typeLabel(t: string | null | undefined): string {
  if (!t) return "—";
  return TYPE_LABELS[t] ?? t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
