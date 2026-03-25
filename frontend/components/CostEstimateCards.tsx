"use client";

import type { ProviderEstimate } from "@/types";

const PROVIDER_COLORS: Record<string, string> = {
  AWS:   "border-amber-400  text-amber-600",
  Azure: "border-blue-500   text-blue-600",
  GCP:   "border-indigo-500 text-indigo-600",
  OCI:   "border-red-500    text-red-600",
};

interface Props {
  estimates: Record<string, ProviderEstimate>;
  vcpu: number;
  memoryGb: number;
  storageGb: number;
}

export default function CostEstimateCards({ estimates, vcpu, memoryGb, storageGb }: Props) {
  const providers = Object.keys(estimates).sort();

  if (providers.length === 0) {
    return (
      <p className="text-sm text-gray-500 italic">
        No unit-price data available to compute an estimate for the selected services.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Based on{" "}
        <span className="font-medium text-gray-700">
          {vcpu} vCPU · {memoryGb} GB RAM · {storageGb} GB Storage
        </span>
        {" "}— OCI prices are per-unit (multiplied by quantity); AWS/Azure/GCP show the nearest
        matching tier price.
      </p>

      <div className={`grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-${Math.min(providers.length, 4)}`}>
        {providers.map((provider) => {
          const est = estimates[provider];
          const color = PROVIDER_COLORS[provider] ?? "border-gray-300 text-gray-600";

          return (
            <div
              key={provider}
              className={`rounded-xl border-2 bg-white p-5 shadow-sm ${color.split(" ")[0]}`}
            >
              <h3 className={`text-base font-semibold ${color.split(" ")[1]}`}>
                {provider}
              </h3>

              <p className="mt-1 text-3xl font-bold text-gray-900">
                ${est.total.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                <span className="text-base font-normal text-gray-500">/mo</span>
              </p>

              <table className="mt-3 w-full text-sm">
                <tbody>
                  {est.rows.map((row, i) => (
                    <tr key={i} className="border-t border-gray-100">
                      <td className="py-1 text-gray-600">{row.label}</td>
                      <td className="py-1 text-right font-medium text-gray-800">
                        ${row.cost.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mt-3 space-y-0.5">
                {est.rows.map((row, i) => (
                  <p key={i} className="text-xs text-gray-400 leading-snug">
                    {row.detail}
                  </p>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
