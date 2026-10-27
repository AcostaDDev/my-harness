import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Object form required: the string shorthand implies changeOrigin: true, which
  // rewrites Host and makes the guard reject the UI Origin (H5.6).
  server: { proxy: { "/api": { target: "http://127.0.0.1:8013", changeOrigin: false } } },
});
