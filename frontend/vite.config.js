import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.ALPHAFORGE_API_PROXY_TARGET || "http://127.0.0.1:8000";
const proxy = {
  "/api": {
    target: apiTarget,
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 600,
  },
  server: {
    host: "0.0.0.0",
    port: 8501,
    proxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 8501,
    proxy,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
