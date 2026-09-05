import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, Vite sirve la UI en 5173 y reenvia la API al lienzo-server (7321).
// En produccion, `npm run build` deja web/dist y lienzo-server lo sirve directo.
const api = "http://127.0.0.1:7321";
const paths = ["/sessions", "/pending", "/events", "/rescan", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(paths.map((p) => [p, { target: api, changeOrigin: true }])),
  },
  build: { outDir: "dist", emptyOutDir: true },
});
