import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".");
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          headers: {
            "X-Insights-User": env.VITE_INSIGHTS_USER ?? "dev",
            "X-Insights-Team": env.VITE_INSIGHTS_TEAM ?? "people-analytics",
          },
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["src/test/setup.ts"],
    },
  };
});
