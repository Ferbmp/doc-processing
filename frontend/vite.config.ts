import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Inside docker compose the API is reachable as http://api:8000. Running the
// dev server on the host instead, it is http://localhost:8000.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    watch: { usePolling: true },
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
