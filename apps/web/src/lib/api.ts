export type Row = Record<string, any>;

export class APIError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let refreshing: Promise<boolean> | null = null;
export function refreshSession() {
  if (!refreshing) {
    const previousCsrf = csrf();
    const rotate = async () => {
      // Another tab may already have rotated our shared cookies while this
      // request waited for the lock. Retrying then uses its fresh access JWT.
      if (csrf() !== previousCsrf) return true;
      return (
        await fetch("/backend/v1/auth/refresh", {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRF-Token": csrf() },
        })
      ).ok;
    };
    const acrossTabs = async (): Promise<boolean> => {
      if (typeof navigator !== "undefined" && navigator.locks)
        return await navigator.locks.request("studio-session-refresh", rotate);
      return await rotate();
    };
    refreshing = acrossTabs()
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export async function authenticatedFetch(
  path: string,
  options: RequestInit = {},
) {
  const perform = () => {
    const headers = new Headers(options.headers);
    if (!["GET", "HEAD"].includes(options.method || "GET"))
      headers.set("X-CSRF-Token", csrf());
    return fetch("/backend" + path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  };
  let response = await perform();
  if (
    response.status === 401 &&
    !/^\/v1\/auth\/(signin|signup|refresh|reset-password|verify-email|forgot-password)/.test(
      path,
    ) &&
    (await refreshSession())
  )
    response = await perform();
  return response;
}

export function csrf() {
  if (typeof document === "undefined") return "";
  return (
    document.cookie
      .split("; ")
      .find((x) => x.startsWith("studio_csrf="))
      ?.split("=")
      .slice(1)
      .join("=") || ""
  );
}

export async function api<T = Row>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD"].includes(options.method || "GET"))
    headers.set("X-CSRF-Token", csrf());
  const response = await authenticatedFetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    let detail: any;
    try {
      detail = await response.json();
    } catch {
      detail = { detail: response.statusText };
    }
    const message =
      typeof detail.detail === "string"
        ? detail.detail
        : detail.detail?.message || JSON.stringify(detail.detail || detail);
    throw new APIError(message, response.status, detail.detail?.code);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function command<T = Row>(
  path: string,
  body: unknown = {},
  method = "POST",
  idempotent = false,
) {
  return api<T>(path, {
    method,
    body: JSON.stringify(body),
    headers: idempotent
      ? { "Idempotency-Key": crypto.randomUUID() }
      : undefined,
  });
}

export function money(minor: number, currency = "INR") {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format((minor || 0) / 100);
}

export function when(value?: string) {
  return value
    ? new Date(value).toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}
