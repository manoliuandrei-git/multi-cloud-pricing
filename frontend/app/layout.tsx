import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Multi-Cloud Pricing Calculator",
  description: "Compare cloud service pricing across AWS, Azure, GCP, and Oracle Cloud.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <header className="border-b border-gray-200 bg-white shadow-sm">
          <div className="mx-auto max-w-7xl px-4 py-4 flex items-center gap-3">
            <span className="text-2xl">☁️</span>
            <span className="text-lg font-semibold text-gray-800">
              Multi-Cloud Pricing Calculator
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
        <footer className="border-t border-gray-200 mt-16 py-6 text-center text-sm text-gray-400">
          Powered by Claude AI (Anthropic) · AWS · Azure · GCP · Oracle Cloud
        </footer>
      </body>
    </html>
  );
}
