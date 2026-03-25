"""
Multi-Cloud Pricing Calculator — FastAPI Backend
Exposes REST endpoints consumed by the Next.js frontend.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sure local modules are importable when run from any cwd
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from config import config
from agents.mapping_agent import map_services
from agents.comparison_agent import compare_services
from utils.pricing_refresh import refresh_pricing_now, pricing_manager
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Multi-Cloud Pricing Calculator API",
    description="FastAPI backend for comparing cloud service pricing across AWS, Azure, GCP, and OCI.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Tighten in production to your Vercel domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALL_PROVIDERS = ["AWS", "Azure", "GCP", "OCI"]

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class Specifications(BaseModel):
    vcpu: int = Field(4, ge=1, le=128)
    memory_gb: int = Field(16, ge=1, le=1024)
    storage_gb: int = Field(100, ge=0, le=10000)


class CompareRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    categories: list[str] = Field(default=["Database"])
    providers: list[str] = Field(default=ALL_PROVIDERS)
    specifications: Optional[Specifications] = None


class ServiceRecord(BaseModel):
    id: Optional[int] = None
    cloud_provider: Optional[str] = None
    service_name: Optional[str] = None
    service_category: Optional[str] = None
    instance_type: Optional[str] = None
    metric: Optional[str] = None
    region: Optional[str] = None
    price_per_hour: Optional[float] = None
    price_per_month: Optional[float] = None
    specifications: Optional[dict] = None


class CostRow(BaseModel):
    label: str
    detail: str
    cost: float


class ProviderEstimate(BaseModel):
    rows: list[CostRow]
    total: float


class CompareResponse(BaseModel):
    services: list[ServiceRecord]
    recommendations: list[dict]
    summary: Optional[str] = None
    cost_estimates: dict[str, ProviderEstimate]
    provider_count: int
    service_count: int


# ---------------------------------------------------------------------------
# Cost estimation logic (ported from Streamlit app)
# ---------------------------------------------------------------------------

def _compute_cost_estimate(
    services: list[dict],
    vcpu: int,
    memory_gb: int,
    storage_gb: int,
) -> dict[str, dict]:
    from collections import defaultdict

    by_provider: dict = defaultdict(list)
    for s in services:
        prov = s.get("cloud_provider", "")
        if prov:
            by_provider[prov].append(s)

    results: dict = {}

    for provider, prov_svcs in by_provider.items():
        compute_rows = [s for s in prov_svcs if s.get("instance_type") == "Compute"]
        storage_rows = [s for s in prov_svcs if s.get("instance_type") == "Storage"]
        memory_rows = [
            s for s in prov_svcs
            if (s.get("metric") or "").lower()
            in ("per gb per month", "per gigabyte per month", "gb memory per month")
        ]

        rows: list[dict] = []
        total = 0.0

        # Compute
        if compute_rows:
            row = compute_rows[0]
            metric_low = (row.get("metric") or "").lower()
            is_per_unit = any(
                kw in metric_low for kw in ("ocpu", "ecpu", "vcpu per hour", "per compute hour")
            )
            if is_per_unit:
                cost = round(row["price_per_hour"] * vcpu * 730, 2)
                unit = "OCPU" if "ocpu" in metric_low else "ECPU"
                detail = f"{vcpu} {unit}s × ${row['price_per_hour']:.4f}/hr × 730 hrs — {row['service_name']}"
            else:
                candidates = [
                    s for s in compute_rows
                    if int((s.get("specifications") or {}).get("vcpu") or 0) >= vcpu
                ]
                best = candidates[0] if candidates else compute_rows[0]
                cost = round(float(best.get("price_per_month") or 0), 2)
                detail = f"Nearest tier: {best['service_name']} (tier price includes all resources)"

            rows.append({"label": f"Compute ({vcpu} vCPU)", "detail": detail, "cost": cost})
            total += cost

        # Storage
        if storage_rows and storage_gb > 0:
            row = storage_rows[0]
            metric_low = (row.get("metric") or "").lower()
            is_per_gb = any(kw in metric_low for kw in ("gb", "gigabyte", "terabyte", "tb"))
            if is_per_gb:
                cost = round(float(row["price_per_month"]) * storage_gb, 2)
                detail = f"{storage_gb} GB × ${row['price_per_month']:.4f}/GB/mo — {row['service_name']}"
            else:
                cost = round(float(row.get("price_per_month") or 0), 2)
                detail = f"Storage tier: {row['service_name']}"

            rows.append({"label": f"Storage ({storage_gb} GB)", "detail": detail, "cost": cost})
            total += cost

        # Memory (OCI separate billing)
        if memory_rows and memory_gb > 0:
            row = memory_rows[0]
            cost = round(float(row["price_per_month"]) * memory_gb, 2)
            detail = f"{memory_gb} GB × ${row['price_per_month']:.4f}/GB/mo — {row['service_name']}"
            rows.append({"label": f"Memory ({memory_gb} GB)", "detail": detail, "cost": cost})
            total += cost

        if rows:
            results[provider] = {"rows": rows, "total": round(total, 2)}

    return results


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """Liveness check"""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/config")
def get_config():
    """Return frontend-relevant config values (no secrets)"""
    return {
        "service_categories": config.SERVICE_CATEGORIES,
        "providers": ALL_PROVIDERS,
    }


@app.post("/api/compare", response_model=CompareResponse)
def compare(req: CompareRequest):
    """
    Main comparison endpoint.

    Queries the DB for each selected category, merges, filters by provider,
    runs AI agents, computes cost estimates, and returns everything the
    frontend needs in a single response.
    """
    try:
        specs = req.specifications
        spec_dict = specs.model_dump() if specs else {}

        all_services: list[dict] = []
        seen_ids: set = set()
        combined_requirements: dict = {}

        # Step 1: query DB per category
        for category in req.categories:
            mapping_result = map_services(req.user_input, category, spec_dict)
            if mapping_result.get("error"):
                logger.warning(f"Mapping error for {category}: {mapping_result['error']}")
                continue

            for svc in mapping_result.get("matched_services", []):
                svc_id = svc.get("id")
                if svc_id not in seen_ids:
                    seen_ids.add(svc_id)
                    all_services.append(svc)

            combined_requirements.update(mapping_result.get("requirements", {}))

        # Step 2: filter by selected providers
        if set(req.providers) != set(ALL_PROVIDERS):
            all_services = [s for s in all_services if s.get("cloud_provider") in req.providers]

        if not all_services:
            raise HTTPException(
                status_code=404,
                detail="No matching services found. Try different categories or providers.",
            )

        # Step 3: AI comparison
        comparison_result = compare_services(
            services=all_services,
            user_requirements=combined_requirements,
            user_input=req.user_input,
        )

        # Step 4: cost estimate
        vcpu = spec_dict.get("vcpu", 0)
        memory_gb = spec_dict.get("memory_gb", 0)
        storage_gb = spec_dict.get("storage_gb", 0)
        cost_estimates = (
            _compute_cost_estimate(all_services, vcpu, memory_gb, storage_gb)
            if vcpu or storage_gb
            else {}
        )

        return CompareResponse(
            services=all_services,
            recommendations=comparison_result.get("recommendations", []),
            summary=comparison_result.get("summary"),
            cost_estimates=cost_estimates,
            provider_count=len({s.get("cloud_provider") for s in all_services}),
            service_count=len(all_services),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compare failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh")
def refresh_pricing(force: bool = False):
    """Trigger a pricing data refresh"""
    try:
        stats = refresh_pricing_now(force=force)
        return stats
    except Exception as e:
        logger.error(f"Refresh failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/refresh/status")
def refresh_status():
    """Check whether pricing data needs a refresh"""
    try:
        needs_refresh = pricing_manager.check_if_refresh_needed()
        return {"needs_refresh": needs_refresh}
    except Exception as e:
        return {"needs_refresh": None, "error": str(e)}
