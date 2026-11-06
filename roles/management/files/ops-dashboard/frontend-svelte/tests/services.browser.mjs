import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.OPS_SERVICES_BASE || 'http://127.0.0.1:5187';
const output = process.env.OPS_SCREENSHOTS || '/tmp/ops-layout-screenshots';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'],
  ...(process.env.CHROME_BIN ? { executablePath: process.env.CHROME_BIN } : {}) });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
const errors = [], writes = [];
page.on('pageerror', e => errors.push(e.message));
let stale = false;
const service = (name, pod, cpu, mem, mb, status = 'running', platform = 'vps') => ({
  name, pod, platform, status, managed: true, description: '', dependencies: [], memory_mb: 4096,
  cpu_percent: cpu, memory_percent: mem, memory_usage_mb: mb, metrics_at: Date.now() / 1000 - (stale ? 100 : 0),
});
const fixtures = () => [
  service('litellm', 'ai-gateway-pod', 2, 12, 240),
  service('postgres', 'database-pod', 24, 91, 1800), service('redis', 'database-pod', 7, 12, 110),
  service('ops-dashboard', 'management-pod', 3, 15, 126), service('traefik', 'management-pod', 1, 7, 81),
  service('victoria-metrics', 'metrics-pod', 63, 66, 570), service('grafana', 'metrics-pod', 12, 23, 160),
  service('ibeam', 'trading-pod', 2.4, 16, 140), service('ib-mcp-server', 'trading-pod', 1, 38, 100),
  service('media-nginx', 'media-pod', .3, 3, 23), service('unknown', 'unknown-pod', null, null, null),
  service('dev', 'dev-pod', null, null, null, 'stopped'),
  ...Array.from({ length: 7 }, (_, i) => service(`standalone-${i}`, null, i < 4 ? .9 : null, i < 4 ? 20 : null,
    i < 4 ? 71.25 : null, i < 4 ? 'running' : 'stopped')),
  service('crond', null, 0, 0, 0, 'running', 'host'),
  service('remote', 'azure', null, null, null, 'stopped', 'azure'),
];
await page.route('**/api/**', async route => {
  if (route.request().method() !== 'GET') writes.push(route.request().url());
  const path = new URL(route.request().url()).pathname;
  const data = path === '/api/me' ? { username: 'Layout test', role: 'admin', via: 'test', iat: Date.now() / 1000 }
    : path === '/api/services' ? fixtures()
    : path === '/api/triage' ? { host: { load1: 1.2, cpus: 8, mem_used: .74, disk_used: .36 }, alerts: [] }
    : [];
  await route.fulfill({ status: 200, json: data });
});
const card = name => page.locator('.tile').filter({ has: page.locator('.pn', { hasText: new RegExp(`^${name}$`) }) });
try {
  await page.goto(`${base}/m/#/services`);
  await card('database').waitFor();
  assert.equal(await page.locator('.tile').count(), 11);
  assert.match(await card('database').textContent(), /High load/);
  assert.match(await card('management').textContent(), /4.0%.*207 MiB/s);
  assert.match(await card('unknown').textContent(), /No load data/);
  assert.ok(await card('database').locator('.arc[stroke="#FF7B80"]').count());
  assert.equal(await page.locator('.tile.off .agitated').count(), 0);
  await page.screenshot({ path: `${output}/restored-390.png`, fullPage: true });
  await page.getByRole('radio', { name: /Problems/ }).click();
  assert.equal(await page.locator('.tile').count(), 2);
  await page.getByRole('radio', { name: /Stopped/ }).click();
  assert.equal(await page.locator('.tile').count(), 1);
  await page.getByRole('radio', { name: /All/ }).click();
  await card('standalone').click(); await page.locator('.ctr').first().waitFor();
  assert.match(await card('standalone').textContent(), /3.6%.*285 MiB.*4\/7 containers up/s);
  assert.equal(await card('standalone').locator('.shape').count(), 7);
  assert.equal(await page.locator('.ctr').count(), 7);
  assert.equal(await page.getByRole('button', { name: 'Stop', exact: true }).count(), 4);
  assert.equal(await page.getByRole('button', { name: 'Start', exact: true }).count(), 3);
  await card('standalone').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${output}/restored-selected-390.png` });
  await card('trading').click();
  await page.locator('.ctr').filter({ hasText: 'ib-mcp-server' }).waitFor();
  assert.match(await page.locator('.ctr').first().textContent(), /ib-mcp-server|ibeam/);
  await page.getByRole('button', { name: 'Animate container activity' }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.agitated')].every(s => getComputedStyle(s).animationPlayState === 'paused'));
  await page.reload(); await card('database').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Animate container activity' }).getAttribute('aria-pressed'), 'false');
  await page.getByRole('button', { name: 'Animate container activity' }).click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.locator('.agitated').first().evaluate(s => getComputedStyle(s).animationName), 'none');
  for (const width of [320, 390, 640]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (width === 320) await page.screenshot({ path: `${output}/restored-320.png`, fullPage: true });
  }
  stale = true; await page.reload(); await card('database').waitFor();
  assert.match(await card('database').textContent(), /No load data/);
  assert.equal(await card('database').locator('.arc').count(), 0);
  assert.deepEqual(errors, []); assert.deepEqual(writes, []);
  console.log('Services restoration passed: CPU/RAM rings, seven-container reference card, controls, filters, preserved pod groups, motion, stale data and 320/390/640px layouts.');
} finally { await browser.close(); }
