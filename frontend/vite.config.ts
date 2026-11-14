import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../controller/static",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: Object.fromEntries(
      ["/api", "/health", "/docs", "/openapi.json"].map((path) => [
        path,
        "http://127.0.0.1:8000",
      ]),
    ),
  },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
