import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Production assets use fixed file names so Django can reference them
// directly (docs/decisions.md §11). Content hashing (collectstatic with
// ManifestStaticFilesStorage) is not set up yet; see README.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        "brand-list": "src/main.tsx",
        main: "scss/main.scss",
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "[name].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
  server: {
    // `npm run dev`: forward API calls to the Django web service.
    proxy: { "/api": "http://web:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});
