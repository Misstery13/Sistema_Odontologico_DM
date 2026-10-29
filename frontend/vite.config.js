import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // en desarrollo: Django en :8000 y Go en :8081 (en Docker lo resuelve Caddy)
  server: { proxy: { "/api": "http://localhost:8000", "/pay": "http://localhost:8081" } },
});
