const KEY = "gc_token";

export function getToken(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(KEY, token);
    else localStorage.removeItem(KEY);
  } catch {
    /* 无法使用本地存储时，登录状态只保留到刷新页面 */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const where = Array.isArray(d.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        return d.type === "extra_forbidden" ? `不允许的字段：${where}` : `${where} ${d.msg}`;
      })
      .join("；");
  }
  return "请求失败";
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const isBinary = body instanceof Blob;
  const resp = await fetch(path, {
    method,
    headers: {
      Authorization: `Bearer ${getToken()}`,
      ...(body === undefined ? {} : { "Content-Type": isBinary ? "application/octet-stream" : "application/json" }),
    },
    body: body === undefined ? undefined : isBinary ? body : JSON.stringify(body),
  });
  const data = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, detailText(data?.detail));
  return data as T;
}

export interface FeeCategory { code: string; name: string; graded: boolean }
export interface Profession {
  code: string;
  name: string;
  pricing_system: { code: string; name: string; engine: string };
  fee_categories: FeeCategory[];
  subcategories: { code: string; name: string }[];
}
export interface BoqItem {
  seq?: number;
  section: string;
  code: string;
  name: string;
  features: string;
  unit: string;
  quantity: string | null;
  source_ref: string;
  anomalies: string[];
}
export interface Fee {
  code: string;
  name: string;
  amount: string;
  formula: string;
  base: string | null;
  rate: string | null;
  locked: boolean;
  basis: string;
  children: Fee[];
}
export interface CalcResult {
  run_id: number;
  total: string;
  rule_code: string | null;
  warnings: string[];
  fees: Fee[];
  items: { boq_item_id: number; quantity: string; labor: string; material: string; machine: string;
           management: string; profit: string; unit_price: string; amount: string }[];
}
export interface Line {
  name: string;
  unit: string;
  content: string;
  labor: string;
  material: string;
  machine: string;
  basis_note: string;
  quota_item_id?: number | null;
}

export function money(value: string | null | undefined): string {
  if (value == null || value === "") return "";
  const [int, frac] = value.split(".");
  const sign = int.startsWith("-") ? "-" : "";
  const digits = int.replace("-", "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return sign + digits + (frac !== undefined ? "." + frac : "");
}
