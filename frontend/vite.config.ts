import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Inside docker compose the API is reachable as http://api:8000. Running the
// dev server on the host instead, it is http://localhost:8000.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    watch: { usePolling: true },
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
