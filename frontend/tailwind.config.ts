import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        aws: "#FF9900",
        azure: "#0078D4",
        gcp: "#4285F4",
        oci: "#F80000",
      },
    },
  },
  plugins: [],
};

export default config;
