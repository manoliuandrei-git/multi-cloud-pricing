"use client";

import { useState, useMemo } from "react";
import type { ServiceRecord } from "@/types";

const PROVIDER_BADGE: Record<string, string> = {
  AWS:   "bg-amber-100  text-amber-700",
  Azure: "bg-blue-100   text-blue-700",
  GCP:   "bg-indigo-100 text-indigo-700",
  OCI:   "bg-red-100    text-red-700",
};

interface Props {
  services: ServiceRecord[];
}

export default function ServiceTable({ services }: Props) {
  const allProviders = useMemo(
    () => [...new Set(services.map((s) => s.cloud_provider ?? ""))].filter(Boolean).sort(),
    [services]
  );
  const allBillingTypes = useMemo(
    () => [...new Set(services.map((s) => s.instance_type ?? ""))].filter(Boolean).sort(),
    [services]
  );

  const [selectedProviders, setSelectedProviders] = useState<string[]>(allProviders);
  const [selectedBilling, setSelectedBilling] = useState<string[]>(allBillingTypes);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  const filtered = useMemo(
    () =>
      services.filter(
        (s) =>
          selectedProviders.includes(s.cloud_provider ?? "") &&
          selectedBilling.includes(s.instance_type ?? "")
      ),
    [services, selectedProviders, selectedBilling]
  );

  function toggleRow(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const selectedTotal = useMemo(
    () =>
      services
        .filter((s) => s.id !== undefined && selected.has(s.id))
        .reduce((sum, s) => sum + (s.price_per_month ?? 0), 0),
    [services, selected]
  );

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-6">
        <div>
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wide mr-2">
            Provider
          </span>
          {allProviders.map((p) => (
            <button
              key={p}
              onClick={() => setSelectedProviders(toggle(selectedProviders, p))}
              className={`mr-1 px-2 py-0.5 rounded-full text-xs font-medium border transition-colors ${
                selectedProviders.includes(p)
                  ? PROVIDER_BADGE[p] ?? "bg-gray-100 text-gray-700"
                  : "border-gray-200 text-gray-400 hover:border-gray-400"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <div>
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wide mr-2">
            Billing Type
          </span>
          {allBillingTypes.map((bt) => (
            <button
              key={bt}
              onClick={() => setSelectedBilling(toggle(selectedBilling, bt))}
              className={`mr-1 px-2 py-0.5 rounded-full text-xs font-medium border transition-colors ${
                selectedBilling.includes(bt)
                  ? "bg-gray-700 text-white border-gray-700"
                  : "border-gray-200 text-gray-400 hover:border-gray-400"
              }`}
            >
              {bt}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
            <tr>
              <th className="w-8 px-4 py-3" />
              <th className="px-4 py-3 text-left">Provider</th>
              <th className="px-4 py-3 text-left">Service</th>
              <th className="px-4 py-3 text-left">Billing Type</th>
              <th className="px-4 py-3 text-left">Metric</th>
              <th className="px-4 py-3 text-left">Region</th>
              <th className="px-4 py-3 text-right">$/Month</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                  No services match the current filters.
                </td>
              </tr>
            ) : (
              filtered.map((svc, idx) => {
                const id = svc.id ?? idx;
                const isSelected = selected.has(id);
                return (
                  <tr
                    key={id}
                    onClick={() => toggleRow(id)}
                    className={`cursor-pointer transition-colors ${
                      isSelected ? "bg-blue-50" : "hover:bg-gray-50"
                    }`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        readOnly
                        className="h-4 w-4 rounded border-gray-300 text-blue-600"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                          PROVIDER_BADGE[svc.cloud_provider ?? ""] ?? "bg-gray-100 text-gray-700"
                        }`}
                      >
                        {svc.cloud_provider}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-800">{svc.service_name}</td>
                    <td className="px-4 py-3 text-gray-600">{svc.instance_type ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-500 max-w-xs truncate">{svc.metric ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-500">{svc.region ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-800">
                      ${(svc.price_per_month ?? 0).toFixed(2)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Selection total */}
      {selected.size > 0 && (
        <div className="rounded-xl bg-green-50 border border-green-200 px-6 py-4 text-center">
          <p className="text-lg font-bold text-green-700">
            Total selected:{" "}
            <span className="text-2xl">
              ${selectedTotal.toLocaleString("en-US", { minimumFractionDigits: 2 })}
            </span>
            /month
          </p>
          <p className="text-sm text-green-600">{selected.size} service(s) selected</p>
        </div>
      )}
    </div>
  );
}
