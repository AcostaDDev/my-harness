import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Development-only work-map fixture (P002-T021, D312): every path under /__map-fixture serves map-fixture.html, so
// the fixture's router paths survive a reload. `apply: "serve"` keeps it out of the build.
function mapFixture(): Plugin {
  return {
    name: "harness-map-fixture",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        if (request.url && /^\/__map-fixture(?:[/?]|$)/.test(request.url)) request.url = "/map-fixture.html";
        next();
      });
    },
  };
}

// The Excalifont subsets are emitted from styles.css as hashed assets; their OFL 1.1 licence, copyright and
// attribution ship beside them under a fixed name (D308, T018 §10.2).
function fontNotice(): Plugin {
  return {
    name: "harness-font-notice",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "assets/Excalifont-OFL-1.1.txt",
        source: readFileSync(new URL("./src/map/fonts/OFL-1.1.txt", import.meta.url)) });
    },
  };
}

export default defineConfig({
  plugins: [react(), mapFixture(), fontNotice()],
  // Object form required: the string shorthand implies changeOrigin: true, which
  // rewrites Host and makes the guard reject the UI Origin (H5.6).
  server: { proxy: { "/api": { target: "http://127.0.0.1:8013", changeOrigin: false } } },
});
