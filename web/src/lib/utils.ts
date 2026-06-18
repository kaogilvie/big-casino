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
