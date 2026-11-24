/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 900 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // The machine is shared: keep the worker pool small.
    pool: "threads",
    maxWorkers: 2,
    testTimeout: 15000,
  },
});
