import { defineConfig } from "vite"

export default defineConfig({
  build: {
    lib: {
      entry: "src/index.ts",
      name: "OrchNotify",
      formats: ["iife"],
      fileName: () => "notify.js",
    },
    minify: true,
    target: "es2022",
  },
  test: {
    environment: "jsdom",
  },
})
