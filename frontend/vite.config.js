import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // `python run.py --dev`: hot reload on :5173, API calls proxied to Flask.
    proxy: { "/api": `http://127.0.0.1:${process.env.PLUMBLINE_API_PORT || 5000}` },
  },
  build: {
    chunkSizeWarningLimit: 600, // three.js is lazy-loaded with the 3D view
    rollupOptions: {
      output: { manualChunks: { three: ["three"] } },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.js",
  },
});
