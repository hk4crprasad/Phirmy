import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const contactProxy = {
  "/api/contact": {
    target: process.env.CONTACT_API_ORIGIN || "http://127.0.0.1:8102",
    changeOrigin: false,
    rewrite: () => "/v1/public/contact",
  },
};
export default defineConfig({
  plugins: [react()],
  server: { strictPort: true, proxy: contactProxy },
  preview: { strictPort: true, proxy: contactProxy },
});
