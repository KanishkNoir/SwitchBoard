import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy API calls to the Switchboard backend on :8765.
// In production, `vite build` emits dist/ which FastAPI serves directly.
const backend = "http://127.0.0.1:8765";
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": backend,
      "/inbox": backend,
      "/rules": backend,
      "/settings": backend,
      "/passport": backend,
      "/away": backend,
      "/canary": backend,
      "/demo": backend,
      "/human": backend,
      "/evaluation": backend,
      "/decisions": backend,
      "/health": backend,
      "/stream": backend,
    },
  },
  build: { outDir: "dist" },
});
