// Captures a Managed Grafana dashboard or panel without an interactive login.
// The Entra access token is attached only to requests for the Grafana origin, is never forwarded
// across a redirect, is never stored, and is redacted from anything this script prints.
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

// Playwright errors can echo request headers, so nothing is printed without passing through here.
const redact = (text) =>
  String(text).split(GRAFANA_TOKEN).join("<redacted>").replace(/(authorization:\s*)\S.*$/gim, "$1<redacted>");
process.on("unhandledRejection", (error) => {
  console.error(`capture failed: ${redact(error?.message ?? error).split("\n")[0]}`);
  process.exit(1);
});

const PANEL_LOADING = '[aria-label="Panel loading bar"], [data-testid="panel-loading-bar"]';
const PANEL = "[data-viz-panel-key], .react-grid-item";

async function waitForPanels(page) {
  await page.waitForTimeout(3000);
  await page.waitForFunction((selector) => document.querySelectorAll(selector).length === 0, PANEL_LOADING, {
    timeout: 60000,
  });
  await page.waitForTimeout(1500);
}

const routeErrors = [];

async function assertRendered(page) {
  if (routeErrors.length) {
    throw new Error(routeErrors.join("; "));
  }
  // An epoch time range saved in the dashboard JSON renders as "Invalid date" and queries from=NaN.
  const text = await page.locator("body").innerText();
  if (/\bNo data\b|\bInvalid date\b/.test(text)) {
    throw new Error("rendered dashboard shows No data or Invalid date");
  }
  if (/\/subscriptions\/|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/i.test(text)) {
    throw new Error("rendered dashboard shows a resource or subscription identifier");
  }
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
    try {
      const response = await route.fetch({
        headers: { ...request.headers(), authorization: `Bearer ${GRAFANA_TOKEN}` },
        maxRedirects: 0,
        timeout: 120000,
      });
      if (new URL(request.url()).pathname === "/api/ds/query" && !response.ok()) {
        routeErrors.push(`${request.method()} /api/ds/query: HTTP ${response.status()}`);
      }
      return route.fulfill({ response });
    } catch (error) {
      // Only the error name: the message can contain the request headers.
      routeErrors.push(`${request.method()} ${new URL(request.url()).pathname}: ${error.name}`);
      return route.abort("failed");
    }
  });

  const page = await context.newPage();
  const response = await page.goto(base + path, { waitUntil: "networkidle", timeout: 120000 });
  // A bad token (401) or route (404) fails here; a sign-in page on another origin fails on the origin check.
  if (!response || !response.ok()) {
    throw new Error(`HTTP ${response ? response.status() : "no response"} for ${path}`);
  }
  if (new URL(page.url()).origin !== grafanaOrigin || new URL(page.url()).pathname.startsWith("/login")) {
    throw new Error(`ended outside the Grafana dashboard: ${new URL(page.url()).pathname}`);
  }
  await waitForPanels(page);
  // A missing dashboard UID still returns 200 with a "Dashboard not found" page and no panels.
  if ((await page.locator(PANEL).count()) === 0) {
    throw new Error(`no panels rendered for ${path}`);
  }

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
  // Checked only after the last wait, so panels that loaded lazily after the viewport grew are included.
  await assertRendered(page);
  await page.screenshot({ path: out });
  console.log(`saved ${out} (${viewportWidth}x${Math.max(Math.ceil(contentHeight), Number(minHeight))})`);
} catch (error) {
  console.error(`capture failed: ${redact(error.message).split("\n")[0]}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
