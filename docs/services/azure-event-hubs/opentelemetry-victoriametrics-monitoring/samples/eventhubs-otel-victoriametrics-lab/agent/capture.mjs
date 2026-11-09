// Usage: node capture.mjs <dashboard-path[?viewPanel=N]> <output.png> [fromMs] [toMs] [width]
// Reads GRAFANA_URL (https), GRAFANA_USER, GRAFANA_PASSWORD and GRAFANA_CA_FILE from the
// environment and writes only the PNG. Credentials are typed into the login form and never persisted.
import { readFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
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
// proxy reaches Grafana over TLS that trusts only the pinned gateway certificate (ca replaces the
// default roots), so no other certificate - including a valid public one - can receive credentials.
const target = new URL(base);
const agent = new https.Agent({ ca: readFileSync(process.env.GRAFANA_CA_FILE, 'utf8'), keepAlive: true });
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
  https.get(`${base}/api/health`, { agent }, (response) => {
    response.resume();
    response.statusCode === 200 ? resolve() : reject(new Error(`health returned ${response.statusCode}`));
  }).on('error', reject);
});

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(width), height: 1000 }, deviceScaleFactor: 1 });
// Only the loopback proxy origin is reachable from the page.
await page.route('**/*', (route) => (new URL(route.request().url()).origin === local ? route.continue() : route.abort()));
try {
  await page.goto(`${local}/login`);
  if (new URL(page.url()).origin !== local) throw new Error(`unexpected login origin ${page.url()}`);
  await page.getByTestId('data-testid Username input field').fill(user);
  await page.getByTestId('data-testid Password input field').fill(password);
  await page.getByTestId('data-testid Login button').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));

  const separator = dashboardPath.includes('?') ? '&' : '?';
  const url = `${local}${dashboardPath}${separator}orgId=1&from=${from}&to=${to}&kiosk`;
  await page.goto(url, { waitUntil: 'networkidle' });

  // Grafana lazily renders panels inside its own scroll container; grow the viewport until stable.
  let height = 0;
  for (let i = 0; i < 6; i += 1) {
    const next = await page.evaluate(() => {
      const scroller = document.querySelector('[data-testid="data-testid dashboard-scrollbar"], .scrollbar-view, main') ?? document.body;
      return Math.max(scroller.scrollHeight, document.body.scrollHeight);
    });
    if (next === height) break;
    height = next;
    await page.setViewportSize({ width: Number(width), height: height + 40 });
    await page.waitForLoadState('networkidle');
  }
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
