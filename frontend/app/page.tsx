"use client";

import { useState } from "react";
import { compare } from "@/lib/api";
import type { CompareRequest, CompareResponse } from "@/types";
import PricingForm from "@/components/PricingForm";
import CostEstimateCards from "@/components/CostEstimateCards";
import AIRecommendations from "@/components/AIRecommendations";
import ServiceTable from "@/components/ServiceTable";

export default function HomePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [lastSpecs, setLastSpecs] = useState({ vcpu: 0, memory_gb: 0, storage_gb: 0 });

  async function handleCompare(req: CompareRequest) {
    setLoading(true);
    setError(null);

    try {
      const data = await compare(req);
      setResult(data);
      if (req.specifications) {
        setLastSpecs(req.specifications);
      } else {
        setLastSpecs({ vcpu: 0, memory_gb: 0, storage_gb: 0 });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  const hasCostEstimates =
    result &&
    Object.keys(result.cost_estimates).length > 0 &&
    (lastSpecs.vcpu > 0 || lastSpecs.storage_gb > 0);

  return (
    <div className="space-y-10">
      {/* Hero */}
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900">
          Compare cloud pricing in seconds
        </h1>
        <p className="text-gray-500 max-w-xl mx-auto text-sm">
          Specify your requirements and let AI find the best options across AWS, Azure, GCP, and
          Oracle Cloud.
        </p>
      </div>

      {/* Input */}
      <PricingForm onSubmit={handleCompare} loading={loading} />

      {/* Error */}
      {error && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-5 py-4 text-sm text-red-700">
          <span className="font-semibold">Error: </span>
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-10">
          {/* Summary badge */}
          <div className="flex items-center gap-3 text-sm text-gray-500">
            <span className="rounded-full bg-green-100 text-green-700 px-3 py-1 font-medium">
              ✅ {result.service_count} services · {result.provider_count} providers
            </span>
          </div>

          {/* Cost estimate */}
          {hasCostEstimates && (
            <section className="space-y-3">
              <h2 className="text-xl font-semibold text-gray-800">💰 Estimated Monthly Cost</h2>
              <CostEstimateCards
                estimates={result.cost_estimates}
                vcpu={lastSpecs.vcpu}
                memoryGb={lastSpecs.memory_gb}
                storageGb={lastSpecs.storage_gb}
              />
            </section>
          )}

          {/* AI recommendations */}
          {result.recommendations.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-xl font-semibold text-gray-800">🤖 AI Recommendations</h2>
              <AIRecommendations
                recommendations={result.recommendations}
                summary={result.summary}
              />
            </section>
          )}

          {/* Full service table */}
          <section className="space-y-3">
            <h2 className="text-xl font-semibold text-gray-800">📊 Service Comparison</h2>
            <ServiceTable services={result.services} />
          </section>
        </div>
      )}
    </div>
  );
}
