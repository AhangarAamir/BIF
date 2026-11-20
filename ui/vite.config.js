import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.BIF_API || "http://127.0.0.1:8000";
const proxied = ["/api", "/agents", "/sessions", "/files", "/widget.js"];

export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(proxied.map((p) => [p, { target, changeOrigin: true }])) },
});
