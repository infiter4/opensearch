import react from "@vitejs/plugin-react";
import tailwind from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwind()],
  server: {
    port: 5173,
    // Bind IPv4 too. Vite's default binds ::1 only, so http://localhost:5173 worked while
    // http://127.0.0.1:5173 was refused outright — same URL to a human, dead page in a browser.
    host: "0.0.0.0",
    strictPort: true,
    proxy: {
      // SSE must not be buffered by the proxy or the board fills in one lump at the end.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
