import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 构建产物输出到后端包内，由后端直接提供界面（桌面版和云端版相同）。
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/gcpricing/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
