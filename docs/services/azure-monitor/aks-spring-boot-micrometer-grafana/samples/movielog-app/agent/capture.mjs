// Captures a Managed Grafana dashboard or Explore view without an interactive login.
// The Entra access token is attached only to requests for the Grafana origin and is never stored.
//
// GRAFANA_TOKEN=$(az account get-access-token --resource https://dashboard.azure.com \
//   --query accessToken -o tsv) node capture.mjs "<grafana-url-path-and-query>" out.png [width] [height]
import { chromium } from "playwright";

const [path, out, width = "1600", height = "1200"] = process.argv.slice(2);
const { GRAFANA_URL, GRAFANA_TOKEN } = process.env;
if (!GRAFANA_URL || !GRAFANA_TOKEN || !path || !out) {
  console.error("usage: GRAFANA_URL=... GRAFANA_TOKEN=... node capture.mjs <path-and-query> <out.png> [width] [height]");
  process.exit(2);
}
const base = GRAFANA_URL.replace(/\/$/, "");
const grafanaOrigin = new URL(base).origin;

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: Number(width), height: Number(height) },
  deviceScaleFactor: 1,
  locale: "ko-KR",
  timezoneId: "Asia/Seoul",
});
// Send the bearer token to Grafana only, never to CDNs or other hosts the page loads.
await context.route("**/*", (route) => {
  const request = route.request();
  if (new URL(request.url()).origin !== grafanaOrigin) {
    return route.continue();
  }
  return route.continue({ headers: { ...request.headers(), authorization: `Bearer ${GRAFANA_TOKEN}` } });
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
