"use client";

import type { Recommendation } from "@/types";

const PROVIDER_BORDER: Record<string, string> = {
  AWS:   "border-l-amber-400",
  Azure: "border-l-blue-500",
  GCP:   "border-l-indigo-500",
  OCI:   "border-l-red-500",
};

interface Props {
  recommendations: Recommendation[];
  summary?: string;
}

export default function AIRecommendations({ recommendations, summary }: Props) {
  if (recommendations.length === 0) return null;

  const top3 = recommendations.slice(0, 3);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 grid-cols-1 md:grid-cols-3">
        {top3.map((rec, i) => {
          const svc = rec.service_info;
          const provider = svc.cloud_provider ?? "Unknown";
          const borderColor = PROVIDER_BORDER[provider] ?? "border-l-gray-300";

          return (
            <div
              key={i}
              className={`rounded-xl border border-gray-200 border-l-4 bg-white p-5 shadow-sm ${borderColor}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    #{i + 1} · {provider}
                  </span>
                  <h4 className="mt-1 text-sm font-semibold text-gray-800 leading-snug">
                    {svc.service_name ?? "Unknown service"}
                  </h4>
                </div>
                <span className="shrink-0 text-lg font-bold text-green-600">
                  ${(svc.price_per_month ?? 0).toFixed(2)}
                  <span className="text-xs font-normal text-gray-500">/mo</span>
                </span>
              </div>
              <p className="mt-3 text-xs text-gray-500 leading-relaxed">{rec.reason}</p>
            </div>
          );
        })}
      </div>

      {summary && (
        <div className="rounded-lg bg-blue-50 border border-blue-100 px-4 py-3 text-sm text-blue-800">
          <span className="font-semibold">AI Summary: </span>
          {summary}
        </div>
      )}
    </div>
  );
}
