/// <reference types="vitest/config" />
import { copyFileSync, existsSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

const here = dirname(fileURLToPath(import.meta.url))

/** Ships the notify-client bundle next to the lab so nginx can inject it into project pages. */
function copyNotifyClient(): Plugin {
  return {
    name: "copy-notify-client",
    apply: "build",
    closeBundle() {
      const src = resolve(here, "../../packages/notify-client/dist/notify.js")
      if (!existsSync(src)) {
        throw new Error(
          `notify.js not found at ${src}. Build @portfolio/notify-client first ` +
            "(the lab build script does this for you).",
        )
      }
      copyFileSync(src, resolve(here, "dist/notify.js"))
    },
  }
}

export default defineConfig({
  base: "/lab/",
  plugins: [react(), copyNotifyClient()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      // SSE-friendly: no timeouts, and ws passthrough for HMR-adjacent tooling.
      "/api": { target: "http://localhost:8000", changeOrigin: false, ws: true, timeout: 0 },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
})
