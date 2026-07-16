import react from "@vitejs/plugin-react";
import tailwind from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwind()],
  server: {
    port: 5173,
    proxy: {
      // SSE must not be buffered by the proxy or the board fills in one lump at the end.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
