import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// The dev proxy is why there is no CORS in dev and no base-URL switch in the client:
// every request goes to /api on the Vite origin, mocked or not. See backend §14.1.
//
// The target is overridable because 8000 is a popular port — the backend's own
// entrypoint hardcodes it, so when it is taken you run uvicorn on another one:
//   .venv/bin/python -m uvicorn wines_ai.main:app --port 8001
//   VITE_BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev
const BACKEND = process.env.VITE_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND,
        changeOrigin: false,
        // SSE through a proxy needs buffering off, or the stream arrives in one lump.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            proxyRes.headers["x-accel-buffering"] = "no";
          });
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
