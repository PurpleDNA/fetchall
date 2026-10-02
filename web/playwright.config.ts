import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: "http://localhost:5174" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run --directory ../api python tests/e2e_server.py",
      url: "http://127.0.0.1:8001/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev -- --port 5174 --strictPort",
      url: "http://localhost:5174",
      env: { VITE_API_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: !process.env.CI,
    },
  ],
});
