// Captures a Managed Grafana dashboard or Explore view without an interactive login.
// The Entra access token is sent as a bearer header on every request, so nothing is stored.
//
// GRAFANA_TOKEN=$(az account get-access-token --resource https://dashboard.azure.com \
//   --query accessToken -o tsv) node capture.mjs "<grafana-url-path-and-query>" out.png [width] [height]
import { chromium } from "playwright";

const [path, out, width = "1600", height = "1200"] = process.argv.slice(2);
const base = process.env.GRAFANA_URL.replace(/\/$/, "");
const token = process.env.GRAFANA_TOKEN;

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: Number(width), height: Number(height) },
  deviceScaleFactor: 1,
  extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  locale: "ko-KR",
  timezoneId: "Asia/Seoul",
});
const page = await context.newPage();
await page.goto(base + path, { waitUntil: "networkidle", timeout: 120000 });
// Panels load lazily; wait until no panel is still showing a loading indicator.
await page.waitForTimeout(4000);
await page.waitForFunction(
  () => document.querySelectorAll('[aria-label="Panel loading bar"], [data-testid="panel-loading-bar"]').length === 0,
  null,
  { timeout: 60000 },
).catch(() => {});
await page.waitForTimeout(2000);
// Grafana scrolls inside its own container, so size the viewport to the content instead of fullPage.
await page.screenshot({ path: out });
await browser.close();
console.log(`saved ${out}`);
