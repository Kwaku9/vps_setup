/**
 * OpenTelemetry tracing for aicortex-chat mobile.
 *
 * Spans are sent to the public OTLP/HTTP ingest at otel.aicortex.cloud,
 * which forwards via Alloy → Tempo. Auth uses a static bearer token from
 * EXPO_PUBLIC_OTEL_TOKEN, baked into the build at compile time.
 *
 * Side-effect import this file once at app entry (see app/_layout.tsx).
 *
 * To trace a code block:
 *   import { tracer } from '@/services/tracing';
 *   const span = tracer.startSpan('my.operation');
 *   try { ... span.setAttribute('foo', 'bar'); ... }
 *   catch (e) { span.recordException(e); span.setStatus({ code: SpanStatusCode.ERROR }); throw e; }
 *   finally { span.end(); }
 */

import {
  trace,
  context,
  SpanStatusCode,
  type Tracer,
} from '@opentelemetry/api';
import {
  BasicTracerProvider,
  BatchSpanProcessor,
  type ReadableSpan,
  type SpanExporter,
} from '@opentelemetry/sdk-trace-base';
import { ExportResultCode, type ExportResult } from '@opentelemetry/core';
import { Resource } from '@opentelemetry/resources';
import {
  SEMRESATTRS_SERVICE_NAME,
  SEMRESATTRS_SERVICE_VERSION,
  SEMRESATTRS_DEPLOYMENT_ENVIRONMENT,
} from '@opentelemetry/semantic-conventions';
import { Platform } from 'react-native';

// ── Config ─────────────────────────────────────────────────────────

const OTEL_ENDPOINT =
  process.env.EXPO_PUBLIC_OTEL_ENDPOINT ?? 'https://otel.aicortex.cloud/v1/traces';
const OTEL_TOKEN = process.env.EXPO_PUBLIC_OTEL_TOKEN ?? '';
const SERVICE_NAME = 'aicortex-chat-mobile';
const SERVICE_VERSION = '1.0.0';
const DEPLOYMENT_ENV = __DEV__ ? 'development' : 'production';

// ── Custom fetch-based OTLP/HTTP JSON exporter ─────────────────────
// Avoids @opentelemetry/exporter-trace-otlp-http which assumes browser globals
// (XMLHttpRequest, navigator.sendBeacon) that React Native doesn't fully provide.

class FetchOTLPExporter implements SpanExporter {
  private shutdownInProgress = false;

  export(spans: ReadableSpan[], resultCallback: (r: ExportResult) => void): void {
    if (this.shutdownInProgress || spans.length === 0) {
      resultCallback({ code: ExportResultCode.SUCCESS });
      return;
    }
    if (!OTEL_TOKEN) {
      // Silent no-op if token isn't set — avoids leaking dev errors to the user.
      resultCallback({ code: ExportResultCode.SUCCESS });
      return;
    }

    const payload = this.toOTLPJson(spans);

    fetch(OTEL_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${OTEL_TOKEN}`,
      },
      body: JSON.stringify(payload),
    })
      .then((res) => {
        if (res.ok) {
          resultCallback({ code: ExportResultCode.SUCCESS });
        } else {
          resultCallback({
            code: ExportResultCode.FAILED,
            error: new Error(`OTLP export failed: HTTP ${res.status}`),
          });
        }
      })
      .catch((err) => {
        resultCallback({
          code: ExportResultCode.FAILED,
          error: err instanceof Error ? err : new Error(String(err)),
        });
      });
  }

  shutdown(): Promise<void> {
    this.shutdownInProgress = true;
    return Promise.resolve();
  }

  forceFlush(): Promise<void> {
    return Promise.resolve();
  }

  // Convert SDK ReadableSpans into OTLP/HTTP JSON wire format.
  private toOTLPJson(spans: ReadableSpan[]) {
    if (spans.length === 0) return { resourceSpans: [] };

    // All spans here share one provider/resource.
    const resource = spans[0].resource;
    const resourceAttrs = Object.entries(resource.attributes).map(([k, v]) => ({
      key: k,
      value: toAnyValue(v),
    }));

    // Group by InstrumentationScope (tracer name).
    const scopeMap = new Map<string, { name: string; version?: string; spans: ReadableSpan[] }>();
    for (const span of spans) {
      const scopeKey = `${span.instrumentationLibrary.name}@${span.instrumentationLibrary.version ?? ''}`;
      if (!scopeMap.has(scopeKey)) {
        scopeMap.set(scopeKey, {
          name: span.instrumentationLibrary.name,
          version: span.instrumentationLibrary.version,
          spans: [],
        });
      }
      scopeMap.get(scopeKey)!.spans.push(span);
    }

    return {
      resourceSpans: [
        {
          resource: { attributes: resourceAttrs },
          scopeSpans: Array.from(scopeMap.values()).map((scope) => ({
            scope: { name: scope.name, version: scope.version },
            spans: scope.spans.map((s) => ({
              traceId: s.spanContext().traceId,
              spanId: s.spanContext().spanId,
              parentSpanId: s.parentSpanId,
              name: s.name,
              kind: s.kind + 1, // OTLP enum is 1-indexed; SDK is 0-indexed
              startTimeUnixNano: hrTimeToNanos(s.startTime),
              endTimeUnixNano: hrTimeToNanos(s.endTime),
              attributes: Object.entries(s.attributes).map(([k, v]) => ({
                key: k,
                value: toAnyValue(v),
              })),
              events: s.events.map((e: { time: [number, number]; name: string; attributes?: Record<string, unknown> }) => ({
                timeUnixNano: hrTimeToNanos(e.time),
                name: e.name,
                attributes: Object.entries(e.attributes ?? {}).map(([k, v]) => ({
                  key: k,
                  value: toAnyValue(v),
                })),
              })),
              status: {
                code: s.status.code,
                message: s.status.message,
              },
            })),
          })),
        },
      ],
    };
  }
}

function hrTimeToNanos(hr: [number, number]): string {
  // hr is [seconds, nanoseconds]
  return (BigInt(hr[0]) * 1_000_000_000n + BigInt(hr[1])).toString();
}

function toAnyValue(v: unknown): Record<string, unknown> {
  if (typeof v === 'string') return { stringValue: v };
  if (typeof v === 'boolean') return { boolValue: v };
  if (typeof v === 'number') {
    return Number.isInteger(v) ? { intValue: v } : { doubleValue: v };
  }
  if (Array.isArray(v)) {
    return { arrayValue: { values: v.map(toAnyValue) } };
  }
  return { stringValue: String(v) };
}

// ── Provider initialization ────────────────────────────────────────

const provider = new BasicTracerProvider({
  resource: new Resource({
    [SEMRESATTRS_SERVICE_NAME]: SERVICE_NAME,
    [SEMRESATTRS_SERVICE_VERSION]: SERVICE_VERSION,
    [SEMRESATTRS_DEPLOYMENT_ENVIRONMENT]: DEPLOYMENT_ENV,
    'os.type': Platform.OS,
    'os.version': String(Platform.Version),
  }),
});

provider.addSpanProcessor(
  new BatchSpanProcessor(new FetchOTLPExporter(), {
    // Tuned for mobile: small batches, frequent flushes, modest queue.
    maxQueueSize: 256,
    maxExportBatchSize: 32,
    scheduledDelayMillis: 5_000,
    exportTimeoutMillis: 15_000,
  }),
);

provider.register();

export const tracer: Tracer = trace.getTracer(SERVICE_NAME, SERVICE_VERSION);
export { context, SpanStatusCode };
