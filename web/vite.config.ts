import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Local development only. The built image serves the API and the front end
    // from one origin, so this proxy exists purely so that `npm run dev`
    // reaches an API on another port without CORS — and, importantly, so the
    // session cookie is treated as first-party in development too.
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
