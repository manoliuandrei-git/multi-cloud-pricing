// Shared TypeScript types — mirrors the FastAPI Pydantic models

export type Provider = "AWS" | "Azure" | "GCP" | "OCI";
export type ServiceCategory = "Database" | "Compute" | "Storage" | string;

export interface Specifications {
  vcpu: number;
  memory_gb: number;
  storage_gb: number;
}

export interface CompareRequest {
  user_input: string;
  categories: ServiceCategory[];
  providers: Provider[];
  specifications?: Specifications;
}

export interface ServiceRecord {
  id?: number;
  cloud_provider?: Provider;
  service_name?: string;
  service_category?: string;
  instance_type?: string;   // billing-type category: Compute, Storage, etc.
  metric?: string;          // raw billing metric string
  region?: string;
  price_per_hour?: number;
  price_per_month?: number;
  specifications?: Record<string, unknown>;
}

export interface CostRow {
  label: string;
  detail: string;
  cost: number;
}

export interface ProviderEstimate {
  rows: CostRow[];
  total: number;
}

export interface Recommendation {
  service_info: ServiceRecord;
  reason: string;
  rank?: number;
}

export interface CompareResponse {
  services: ServiceRecord[];
  recommendations: Recommendation[];
  summary?: string;
  cost_estimates: Record<string, ProviderEstimate>;
  provider_count: number;
  service_count: number;
}

export interface AppConfig {
  service_categories: string[];
  providers: Provider[];
}

export interface RefreshStatus {
  needs_refresh: boolean | null;
  error?: string;
}
