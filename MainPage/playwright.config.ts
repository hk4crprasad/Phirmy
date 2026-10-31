import { defineConfig } from "@playwright/test";
import fs from "node:fs";

const executablePath =
  process.env.CHROMIUM_PATH ||
  (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined);

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  workers: 2,
  reporter: "list",
  outputDir: "../artifacts/mainpage/test-results",
  use: {
    baseURL: "http://127.0.0.1:3202",
    browserName: "chromium",
    launchOptions: {
      ...(executablePath ? { executablePath } : {}),
      args: ["--no-sandbox"],
    },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --port 3202",
    url: "http://127.0.0.1:3202",
    reuseExistingServer: !process.env.CI,
  },
});
