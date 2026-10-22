import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Forward API calls to FastAPI so the browser never deals with CORS (dev server and `vite preview`).
const proxy = { "/api": "http://localhost:8000" };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
});
