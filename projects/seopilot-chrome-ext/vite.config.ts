import { defineConfig } from "vite";
import { resolve } from "path";
import { copyFileSync, mkdirSync, existsSync } from "fs";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        popup: resolve(__dirname, "src/popup/popup.ts"),
        content: resolve(__dirname, "src/content/analyzer.ts"),
        background: resolve(__dirname, "src/background/service-worker.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name].js",
        assetFileNames: "assets/[name].[ext]",
      },
    },
    target: "es2022",
    minify: true,
    sourcemap: false,
  },
  plugins: [
    {
      name: "copy-extension-files",
      closeBundle() {
        const dist = resolve(__dirname, "dist");

        // Copy manifest.json
        copyFileSync(
          resolve(__dirname, "manifest.json"),
          resolve(dist, "manifest.json"),
        );

        // Copy popup.html
        copyFileSync(
          resolve(__dirname, "src/popup/popup.html"),
          resolve(dist, "popup.html"),
        );

        // Copy popup.css
        copyFileSync(
          resolve(__dirname, "src/popup/popup.css"),
          resolve(dist, "popup.css"),
        );

        // Copy icons
        const iconsDir = resolve(dist, "icons");
        if (!existsSync(iconsDir)) {
          mkdirSync(iconsDir, { recursive: true });
        }
        const srcIcons = resolve(__dirname, "src/icons");
        if (existsSync(srcIcons)) {
          for (const size of ["icon16.png", "icon32.png", "icon48.png", "icon128.png"]) {
            const src = resolve(srcIcons, size);
            if (existsSync(src)) {
              copyFileSync(src, resolve(iconsDir, size));
            }
          }
        }
      },
    },
  ],
});
