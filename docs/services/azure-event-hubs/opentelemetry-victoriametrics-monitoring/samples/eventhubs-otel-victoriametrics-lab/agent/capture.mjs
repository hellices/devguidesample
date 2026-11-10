// Usage: node capture.mjs <dashboard-path[?viewPanel=N]> <output.png> [fromMs] [toMs] [width]
// Reads GRAFANA_URL (https), GRAFANA_USER, GRAFANA_PASSWORD and GRAFANA_CA_FILE from the
// environment and writes only the PNG. Credentials are typed into the login form and never persisted.
import { X509Certificate } from 'node:crypto';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import tls from 'node:tls';
import { chromium } from 'playwright';

const [dashboardPath, output, from = 'now-1h', to = 'now', width = '1600'] = process.argv.slice(2);
if (!dashboardPath || !output) {
  console.error('usage: node capture.mjs <dashboard-path> <output.png> [from] [to]');
  process.exit(2);
}
const base = process.env.GRAFANA_URL?.replace(/\/$/, '');
const user = process.env.GRAFANA_USER ?? 'admin';
const password = process.env.GRAFANA_PASSWORD;
if (!base || !password) {
  console.error('GRAFANA_URL and GRAFANA_PASSWORD are required');
  process.exit(2);
}
if (!base.startsWith('https://') || !process.env.GRAFANA_CA_FILE) {
  console.error('GRAFANA_URL must be https and GRAFANA_CA_FILE must pin the gateway certificate');
  process.exit(2);
}

// Chromium never talks to Grafana directly. It talks plain HTTP to a loopback proxy, and the
// proxy reaches Grafana over TLS that trusts only the gateway certificate (ca replaces the default
// roots) and also requires the presented leaf to be that exact certificate, so neither a public
// certificate nor another certificate chained to it can receive credentials.
const target = new URL(base);
const caPem = readFileSync(process.env.GRAFANA_CA_FILE, 'utf8');
const pinnedFingerprint = new X509Certificate(caPem).fingerprint256;
const agent = new https.Agent({
  ca: caPem,
  keepAlive: true,
  checkServerIdentity: (host, cert) => tls.checkServerIdentity(host, cert)
    ?? (cert.fingerprint256 === pinnedFingerprint ? undefined : new Error('Grafana presented a certificate other than the pinned one')),
});
let local;
const proxy = http.createServer((req, res) => {
  const headers = { ...req.headers, host: target.host };
  for (const name of ['origin', 'referer']) {
    if (headers[name]) headers[name] = headers[name].replace(local, target.origin);
  }
  const upstream = https.request(
    { host: target.hostname, port: target.port || 443, method: req.method, path: req.url, headers, agent },
    (response) => {
      const out = { ...response.headers };
      if (out.location) {
        const location = new URL(out.location, target.origin);
        if (location.origin !== target.origin) {
          response.resume();
          res.writeHead(502).end('redirect outside the pinned Grafana origin refused');
          return;
        }
        out.location = `${location.pathname}${location.search}${location.hash}`;
      }
      res.writeHead(response.statusCode, out);
      response.pipe(res);
    },
  );
  upstream.on('error', (error) => res.writeHead(502).end(`pinned TLS connection failed: ${error.message}`));
  req.pipe(upstream);
});
await new Promise((resolve) => proxy.listen(0, '127.0.0.1', resolve));
local = `http://127.0.0.1:${proxy.address().port}`;

// Fail before typing credentials if the pinned TLS handshake does not succeed.
await new Promise((resolve, reject) => {
  const request = https.get(`${base}/api/health`, { agent }, (response) => {
    response.resume();
    response.statusCode === 200 ? resolve() : reject(new Error(`health returned ${response.statusCode}`));
  });
  request.on('error', reject);
  // A gateway that accepts TLS but never answers must still fail in bounded time.
  request.setTimeout(15000, () => request.destroy(new Error('Grafana health check timed out')));
}).catch((error) => {
  proxy.close();
  throw error;
});

async function gotoOk(page, target, options) {
  const response = await page.goto(target, options);
  if (!response || !response.ok()) throw new Error(`GET ${target} returned ${response ? response.status() : 'no response'}`);
  return response;
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(width), height: 1000 }, deviceScaleFactor: 1 });
// Only the loopback proxy origin is reachable from the page.
await page.route('**/*', (route) => (new URL(route.request().url()).origin === local ? route.continue() : route.abort()));
try {
  await gotoOk(page, `${local}/login`);
  if (new URL(page.url()).origin !== local) throw new Error(`unexpected login origin ${page.url()}`);
  await page.getByTestId('data-testid Username input field').fill(user);
  await page.getByTestId('data-testid Password input field').fill(password);
  await page.getByTestId('data-testid Login button').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));

  // Grafana answers a missing dashboard route with 200 and an in-app error page, so confirm the
  // dashboard and its panels through the API (same session) before rendering it.
  const uid = /^\/d(?:-solo)?\/([^/?#]+)/.exec(dashboardPath)?.[1];
  if (!uid) throw new Error(`dashboard path must start with /d/<uid>: ${dashboardPath}`);
  const api = await page.request.get(`${local}/api/dashboards/uid/${encodeURIComponent(uid)}`);
  if (!api.ok()) throw new Error(`dashboard ${uid} returned ${api.status()}`);
  const panels = (await api.json()).dashboard?.panels ?? [];
  if (!panels.length) throw new Error(`dashboard ${uid} has no panels`);
  // viewPanel must name a real panel (rows included), or Grafana shows a not-found view instead.
  const viewPanel = new URLSearchParams(dashboardPath.split('?')[1] ?? '').get('viewPanel');
  if (viewPanel !== null) {
    const ids = [];
    const walk = (items) => items.forEach((item) => { ids.push(String(item.id)); walk(item.panels ?? []); });
    walk(panels);
    if (!ids.includes(viewPanel)) throw new Error(`dashboard ${uid} has no panel ${viewPanel}`);
  }

  const separator = dashboardPath.includes('?') ? '&' : '?';
  const url = `${local}${dashboardPath}${separator}orgId=1&from=${from}&to=${to}&kiosk`;
  // A server error renders a page without loading bars; never capture it.
  await gotoOk(page, url, { waitUntil: 'networkidle' });

  // Grafana lazily renders panels inside its own scroll container; grow the viewport until the
  // height stays the same, and refuse to capture a layout that never settled.
  let height = 0;
  let stable = false;
  for (let i = 0; i < 12; i += 1) {
    const next = await page.evaluate(() => {
      const scroller = document.querySelector('[data-testid="data-testid dashboard-scrollbar"], .scrollbar-view, main') ?? document.body;
      return Math.max(scroller.scrollHeight, document.body.scrollHeight);
    });
    if (next === height) {
      stable = true;
      break;
    }
    height = next;
    await page.setViewportSize({ width: Number(width), height: height + 40 });
    await page.waitForLoadState('networkidle');
  }
  if (!stable) throw new Error(`dashboard height did not settle (last ${height}px); not capturing a partial page`);
  await page.waitForFunction(
    () => document.querySelectorAll('[aria-label="Panel loading bar"], [data-testid="data-testid panel loading bar"]').length === 0,
    null,
    { timeout: 60000 },
  );
  await page.waitForTimeout(2000);
  await page.screenshot({ path: output, fullPage: true });
  console.log(`captured ${output} (${height}px)`);
} finally {
  await browser.close();
  proxy.close();
  agent.destroy();
}
