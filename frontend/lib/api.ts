/**
 * API client for the FastAPI backend.
 * All calls go through Next.js rewrites → /api/backend/* → FastAPI.
 */
import type {
  AppConfig,
  CompareRequest,
  CompareResponse,
  RefreshStatus,
} from "@/types";

const BASE = "/api/backend";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `Request failed: ${res.status}`);
  }

  return res.json() as Promise<T>;
}

/** Fetch service categories and supported providers from the backend */
export async function getConfig(): Promise<AppConfig> {
  return request<AppConfig>("/config");
}

/** Run the full comparison pipeline */
export async function compare(payload: CompareRequest): Promise<CompareResponse> {
  return request<CompareResponse>("/compare", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Check whether pricing data needs refreshing */
export async function getRefreshStatus(): Promise<RefreshStatus> {
  return request<RefreshStatus>("/refresh/status");
}

/** Trigger a pricing data refresh */
export async function refreshPricing(force = false): Promise<unknown> {
  return request(`/refresh?force=${force}`, { method: "POST" });
}

/** Simple health check */
export async function health(): Promise<{ status: string }> {
  return request("/health");
}
