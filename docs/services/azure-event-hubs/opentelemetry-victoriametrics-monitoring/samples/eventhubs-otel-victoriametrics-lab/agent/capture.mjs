// Usage: node capture.mjs <dashboard-path[?viewPanel=N]> <output.png> [fromMs] [toMs] [width]
// Reads GRAFANA_URL, GRAFANA_USER, GRAFANA_PASSWORD from the process environment and
// writes only the PNG. Credentials are typed into the login form and never persisted.
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(width), height: 1000 }, deviceScaleFactor: 1 });
try {
  await page.goto(`${base}/login`);
  await page.getByTestId('data-testid Username input field').fill(user);
  await page.getByTestId('data-testid Password input field').fill(password);
  await page.getByTestId('data-testid Login button').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));

  const separator = dashboardPath.includes('?') ? '&' : '?';
  const url = `${base}${dashboardPath}${separator}orgId=1&from=${from}&to=${to}&kiosk`;
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
}
