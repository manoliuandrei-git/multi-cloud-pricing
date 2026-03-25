"use client";

import { useState } from "react";
import type { CompareRequest, Provider, ServiceCategory } from "@/types";

const ALL_PROVIDERS: Provider[] = ["AWS", "Azure", "GCP", "OCI"];
const ALL_CATEGORIES: ServiceCategory[] = ["Database", "Compute", "Storage"];

const PROVIDER_COLORS: Record<string, string> = {
  AWS: "border-amber-400 bg-amber-50 text-amber-800",
  Azure: "border-blue-500 bg-blue-50 text-blue-800",
  GCP: "border-indigo-500 bg-indigo-50 text-indigo-800",
  OCI: "border-red-500 bg-red-50 text-red-800",
};

interface Props {
  onSubmit: (req: CompareRequest) => void;
  loading: boolean;
}

export default function PricingForm({ onSubmit, loading }: Props) {
  const [categories, setCategories] = useState<ServiceCategory[]>(["Database"]);
  const [providers, setProviders] = useState<Provider[]>([...ALL_PROVIDERS]);
  const [vcpu, setVcpu] = useState(4);
  const [memoryGb, setMemoryGb] = useState(16);
  const [storageGb, setStorageGb] = useState(100);
  const [chatInput, setChatInput] = useState("");
  const [mode, setMode] = useState<"form" | "chat">("form");

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault();
    const label = categories.join(", ");
    onSubmit({
      user_input: `${label} service with ${vcpu} vCPU, ${memoryGb} GB RAM, ${storageGb} GB storage`,
      categories,
      providers,
      specifications: { vcpu, memory_gb: memoryGb, storage_gb: storageGb },
    });
  }

  function handleChatSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!chatInput.trim()) return;
    onSubmit({ user_input: chatInput, categories, providers });
  }

  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm p-6 space-y-6">
      {/* Scope selectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Categories */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Service Categories
          </label>
          <div className="flex flex-wrap gap-2">
            {ALL_CATEGORIES.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setCategories(toggle(categories, cat))}
                className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                  categories.includes(cat)
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Providers */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Cloud Providers
          </label>
          <div className="flex flex-wrap gap-2">
            {ALL_PROVIDERS.map((prov) => (
              <button
                key={prov}
                type="button"
                onClick={() => setProviders(toggle(providers, prov))}
                className={`px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-colors ${
                  providers.includes(prov)
                    ? PROVIDER_COLORS[prov]
                    : "bg-white text-gray-400 border-gray-200 hover:border-gray-400"
                }`}
              >
                {prov}
              </button>
            ))}
          </div>
        </div>
      </div>

      <hr className="border-gray-100" />

      {/* Mode tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        {(["form", "chat"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              mode === m
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {m === "form" ? "📝 Form" : "💬 Chat"}
          </button>
        ))}
      </div>

      {/* Form mode */}
      {mode === "form" && (
        <form onSubmit={handleFormSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                vCPU / Cores
              </label>
              <input
                type="number"
                min={1}
                max={128}
                value={vcpu}
                onChange={(e) => setVcpu(Number(e.target.value))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Memory (GB)
              </label>
              <input
                type="number"
                min={1}
                max={1024}
                value={memoryGb}
                onChange={(e) => setMemoryGb(Number(e.target.value))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Storage (GB)
              </label>
              <input
                type="number"
                min={0}
                max={10000}
                step={50}
                value={storageGb}
                onChange={(e) => setStorageGb(Number(e.target.value))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || categories.length === 0 || providers.length === 0}
            className="w-full rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "🔍 Comparing…" : "🔍 Compare Pricing"}
          </button>
        </form>
      )}

      {/* Chat mode */}
      {mode === "chat" && (
        <form onSubmit={handleChatSubmit} className="space-y-4">
          <textarea
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            rows={3}
            placeholder="E.g. I need a PostgreSQL database for production with high availability and 8 vCPU…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
          <button
            type="submit"
            disabled={loading || !chatInput.trim() || providers.length === 0}
            className="w-full rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "🔍 Searching…" : "💬 Find Services"}
          </button>
        </form>
      )}
    </div>
  );
}
