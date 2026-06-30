// Typed client for the Big Casino FastAPI backend.
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.ts).

export interface Summary {
  investments: number;
  cost_basis: number;
  unrealized: number;
  unrealized_pct: number;
  cash: number;
  liabilities: number;
  net_worth: number;
}

export interface AccountRow {
  account_id: string;
  institution: string | null;
  name: string | null;
  type: string | null;
  holdings_value: number;
  balance: number;
  total_value: number;
  category?: string;
  excluded?: boolean;
}

export interface ManagedAccount {
  account_id: string;
  institution: string;
  name: string;
  type: string;
  excluded: boolean;
  category: string;
}

export interface HoldingRow {
  account_id: string;
  symbol: string;
  quantity: number;
  cost_per_share: number;
  cost_basis_type: string;
  institution: string | null;
  name: string | null;
  type: string | null;
  current_price: number | null;
  cost_basis: number | null;
  market_value: number | null;
  unrealized: number | null;
  unrealized_pct: number | null;
}

export interface BalanceRow {
  account_id: string;
  balance: number;
  institution: string | null;
  name: string | null;
  type: string | null;
}

export interface CardRow {
  account_id: string;
  balance: number;
  institution: string | null;
  name: string | null;
  statement_balance: number | null;
  statement_date: string | null;
  due_date: string | null;
  minimum_payment: number | null;
}

export interface Portfolio {
  summary: Summary;
  accounts: AccountRow[];
  holdings: HoldingRow[];
  balances: BalanceRow[];
  cards: CardRow[];
  prices_as_of: string | null;
  plaid_last_refresh: string | null;
}

export interface PlaidItem {
  item_id: string;
  institution: string | null;
  alias: string | null;
  created_at: string | null;
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as any).detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  portfolio: (includeRetirement: boolean, category: string = "all", hideTaxes: boolean = false) =>
    fetch(`/api/portfolio?include_retirement=${includeRetirement}&category=${category}&hide_taxes=${hideTaxes}`).then((r) =>
      j<Portfolio>(r)
    ),

  listAccounts: () => fetch("/api/accounts").then((r) => j<{ accounts: ManagedAccount[] }>(r)),
  updateAccountSettings: (accountId: string, body: { excluded?: boolean; category?: string }) =>
    fetch(`/api/accounts/${encodeURIComponent(accountId)}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j(r)),

  refreshPrices: () => fetch("/api/refresh-prices", { method: "POST" }).then((r) => j(r)),
  clear: () => fetch("/api/clear", { method: "POST" }).then((r) => j(r)),

  plaidStatus: () => fetch("/api/plaid/status").then((r) => j<{ configured: boolean }>(r)),
  plaidItems: () => fetch("/api/plaid/items").then((r) => j<{ items: PlaidItem[] }>(r)),
  plaidLinkToken: () =>
    fetch("/api/plaid/link-token", { method: "POST" }).then((r) => j<{ link_token: string }>(r)),
  plaidExchange: (public_token: string, institution: string) =>
    fetch("/api/plaid/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ public_token, institution }),
    }).then((r) => j<{ summary: string }>(r)),
  plaidRefresh: (itemId: string) =>
    fetch(`/api/plaid/items/${itemId}/refresh`, { method: "POST" }).then((r) => j<{ summary: string }>(r)),
  plaidSetAlias: (itemId: string, alias: string) =>
    fetch(`/api/plaid/items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alias }),
    }).then((r) => j<{ alias: string | null }>(r)),
  plaidDelete: (itemId: string) =>
    fetch(`/api/plaid/items/${itemId}`, { method: "DELETE" }).then((r) => j(r)),
  plaidRefreshAll: () =>
    fetch("/api/plaid/refresh-all", { method: "POST" }).then((r) =>
      j<{ refreshed: number; errors: { institution: string; error: string }[] }>(r)
    ),

  importFile: (endpoint: string, form: FormData) =>
    fetch(`/api/import/${endpoint}`, { method: "POST", body: form }).then((r) => j<{ summary: string }>(r)),

  importManual: (rows: ManualRow[]) =>
    fetch("/api/import/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rows),
    }).then((r) => j<{ summary: string }>(r)),

  renameAccount: (accountId: string, body: { institution: string; name: string; type: string }) =>
    fetch(`/api/accounts/${encodeURIComponent(accountId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<{ account_id: string }>(r)),
};

export interface ManualRow {
  broker: string;
  account: string;
  type: string;
  symbol: string;
  quantity: number | string;
  cost_per_share: number | string;
  purchase_date: string;
}

export const ACCOUNT_TYPES = ["brokerage", "bank", "credit_card", "retirement", "taxes", "robo_broker"];
