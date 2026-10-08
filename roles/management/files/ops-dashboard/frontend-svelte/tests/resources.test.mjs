import assert from 'node:assert/strict';
import test from 'node:test';
import { podResources, serviceResources, percentLabel, podLabel } from '../src/lib/resources.ts';

const now = 1_000_000;
const service = (overrides = {}) => ({ platform: 'vps', status: 'running', metrics_at: now / 1000,
  cpu_percent: 3, memory_percent: 15, memory_usage_mb: 100, ...overrides });

test('pod totals exclude stopped containers and the ring retains the hottest member', () => {
  const result = podResources([service(), service({ cpu_percent: 130, memory_percent: 92 }),
    service({ status: 'stopped', cpu_percent: 999, memory_usage_mb: 999 })], now);
  assert.equal(result.cpu, 133); // multi-core CPU is not capped at 100 in the value
  assert.equal(result.mb, 200);
  assert.equal(result.cpuPeak, 130);
  assert.equal(result.memoryPeak, 92);
  assert.equal(result.level, 'hot');
  assert.equal(percentLabel(result.cpu), '133%');
});

test('stale or incomplete metrics never become fresh healthy zeroes or complete totals', () => {
  const stale = service({ metrics_at: now / 1000 - 91 });
  const result = podResources([service(), stale], now);
  assert.equal(result.cpu, null);
  assert.equal(result.mb, null);
  assert.equal(result.partial, true);
  assert.equal(serviceResources(stale, now).level, 'unknown');
  assert.equal(serviceResources(service({ cpu_percent: NaN, memory_percent: Infinity }), now).speed, 0);
  assert.equal(serviceResources(service({ platform: 'host' }), now).level, 'unknown');
});

test('stopped groups have no agitation and unresolved pod IDs stay compact', () => {
  const stopped = service({ status: 'stopped' });
  assert.equal(serviceResources(stopped, now).speed, 0);
  assert.equal(podResources([stopped], now).level, 'off');
  assert.equal(podLabel('a'.repeat(64)), 'Pod aaaaaaaa');
  assert.equal(podLabel('metrics-pod'), 'metrics');
});
