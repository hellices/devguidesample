// Captures a Managed Grafana dashboard or panel without an interactive login.
// The Entra access token is attached only to requests for the Grafana origin, is never forwarded
// across a redirect, and is never stored.
//
// GRAFANA_TOKEN=$(az account get-access-token --resource https://dashboard.azure.com \
//   --query accessToken -o tsv) node capture.mjs "<grafana-url-path-and-query>" out.png [width] [minHeight]
import { chromium } from "playwright";

const [path, out, width = "1600", minHeight = "900"] = process.argv.slice(2);
const { GRAFANA_URL, GRAFANA_TOKEN } = process.env;
if (!GRAFANA_URL || !GRAFANA_TOKEN || !path || !out) {
  console.error("usage: GRAFANA_URL=... GRAFANA_TOKEN=... node capture.mjs <path-and-query> <out.png> [width] [minHeight]");
  process.exit(2);
}
const base = GRAFANA_URL.replace(/\/$/, "");
const grafanaOrigin = new URL(base).origin;
const viewportWidth = Number(width);

const PANEL_LOADING = '[aria-label="Panel loading bar"], [data-testid="panel-loading-bar"]';

async function waitForPanels(page) {
  await page.waitForTimeout(3000);
  await page.waitForFunction((selector) => document.querySelectorAll(selector).length === 0, PANEL_LOADING, {
    timeout: 60000,
  });
  await page.waitForTimeout(1500);
}

const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: viewportWidth, height: Number(minHeight) },
    deviceScaleFactor: 1,
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
  });
  await context.route("**/*", async (route) => {
    const request = route.request();
    if (new URL(request.url()).origin !== grafanaOrigin) {
      return route.continue();
    }
    // maxRedirects: 0 hands any redirect back to the browser as a new request, which
    // passes through this handler again and gets no token if it leaves the Grafana origin.
    const response = await route.fetch({
      headers: { ...request.headers(), authorization: `Bearer ${GRAFANA_TOKEN}` },
      maxRedirects: 0,
    });
    return route.fulfill({ response });
  });

  const page = await context.newPage();
  await page.goto(base + path, { waitUntil: "networkidle", timeout: 120000 });
  await waitForPanels(page);

  // Grafana scrolls inside its own container, so grow the viewport to that container's content
  // height; the newly visible panels then load lazily and are awaited again.
  const contentHeight = await page.evaluate(() => {
    const scrollers = [...document.querySelectorAll("*")].filter(
      (el) => el.scrollHeight > el.clientHeight + 1 && ["auto", "scroll"].includes(getComputedStyle(el).overflowY),
    );
    const extra = scrollers.reduce((max, el) => Math.max(max, el.scrollHeight - el.clientHeight), 0);
    return Math.max(document.documentElement.scrollHeight, window.innerHeight + extra);
  });
  if (contentHeight > Number(minHeight)) {
    await page.setViewportSize({ width: viewportWidth, height: Math.ceil(contentHeight) });
    await waitForPanels(page);
  }
  await page.screenshot({ path: out });
  console.log(`saved ${out} (${viewportWidth}x${Math.max(Math.ceil(contentHeight), Number(minHeight))})`);
} catch (error) {
  console.error(`capture failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
