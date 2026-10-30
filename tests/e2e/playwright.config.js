// RNF-07 / RNF-08: los mismos flujos en Chromium (Chrome, Edge), Firefox y WebKit (Safari),
// en escritorio 1920×1080, laptop 1366×768 y iPad junto al sillón.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./specs",
  globalSetup: "./global-setup.js",
  fullyParallel: true,
  reporter: [["list"]],
  use: { baseURL: process.env.BASE_URL || "http://127.0.0.1:8080", trace: "retain-on-failure" },
  projects: [
    { name: "chrome-1920", use: { ...devices["Desktop Chrome"], viewport: { width: 1920, height: 1080 } } },
    { name: "edge-1366", use: { ...devices["Desktop Edge"], channel: undefined, viewport: { width: 1366, height: 768 } } },
    { name: "firefox", use: { ...devices["Desktop Firefox"], viewport: { width: 1366, height: 768 } } },
    { name: "safari", use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } } },
    { name: "ipad", use: { ...devices["iPad Pro 11 landscape"] } },
  ],
});
