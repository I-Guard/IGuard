/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: "#0b0f17", raised: "#111827", card: "#151d2e", hover: "#1b2540" },
        line: "#27324a",
        ink: { DEFAULT: "#e6ebf5", dim: "#9aa7c2", faint: "#66738f" },
        brand: { DEFAULT: "#4f8cff", strong: "#2f6fe8" },
        ok: "#2fbf71", warn: "#f0a63a", crit: "#ef5350", info: "#5ab0ff",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "sans-serif"], mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};
