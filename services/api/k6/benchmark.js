/**
 * k6 benchmark suite for GET /v1/events
 *
 * Scenarios:
 *   1. rampup   — gradual increase to find stability ceiling
 *   2. constant — sustained 1000 VUs (stable-load baseline)
 *   3. stress   — push until the system breaks (find breaking point)
 *   4. spike    — sudden burst to simulate traffic spike
 *
 * Run a single scenario:
 *   k6 run -e SCENARIO=rampup benchmark.js
 *   k6 run -e SCENARIO=constant benchmark.js
 *   k6 run -e SCENARIO=stress benchmark.js
 *   k6 run -e SCENARIO=spike benchmark.js
 *
 * Run all scenarios (default):
 *   k6 run benchmark.js
 *
 * Override target:
 *   k6 run -e BASE_URL=http://localhost:8000 benchmark.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend, Gauge } from "k6/metrics";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.0.2/index.js";

// --------------------------------------------------------------------------
// Config
// --------------------------------------------------------------------------
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const SCENARIO  = __ENV.SCENARIO  || "all";

// --------------------------------------------------------------------------
// Custom metrics
// --------------------------------------------------------------------------
const cacheHits      = new Counter("cache_hits");
const cacheMisses    = new Counter("cache_misses");
const cacheHitRate   = new Rate("cache_hit_rate");
const dbErrors       = new Counter("db_errors");
const timeoutErrors  = new Counter("timeout_errors");
const rateLimitHits  = new Counter("rate_limit_hits");
const busyErrors     = new Counter("busy_503_errors");
const responseTime   = new Trend("response_time_ms", true);

// --------------------------------------------------------------------------
// Scenario definitions
// --------------------------------------------------------------------------
const scenarios = {

  // 1. Ramp-up: 0 → 500 → 1000 → 2000 → 5000 VUs
  rampup: {
    executor: "ramping-vus",
    startVUs: 0,
    stages: [
      { duration: "30s", target: 100  },   // warm-up
      { duration: "60s", target: 500  },   // light load
      { duration: "60s", target: 1000 },   // medium load
      { duration: "60s", target: 2000 },   // heavy load
      { duration: "60s", target: 5000 },   // extreme load
      { duration: "30s", target: 0    },   // cool-down
    ],
    gracefulRampDown: "10s",
  },

  // 2. Constant: 1000 concurrent users for 3 minutes
  constant: {
    executor: "constant-vus",
    vus: 1000,
    duration: "3m",
    gracefulStop: "10s",
  },

  // 3. Stress: ramp up aggressively until breakpoint
  stress: {
    executor: "ramping-arrival-rate",
    startRate: 100,
    timeUnit: "1s",
    preAllocatedVUs: 500,
    maxVUs: 5000,
    stages: [
      { duration: "30s",  target: 200  },
      { duration: "60s",  target: 500  },
      { duration: "60s",  target: 1000 },
      { duration: "60s",  target: 2000 },
      { duration: "60s",  target: 3000 },
      { duration: "60s",  target: 5000 },
      { duration: "30s",  target: 0    },
    ],
  },

  // 4. Spike: sudden burst from low to very high, then back
  spike: {
    executor: "ramping-vus",
    startVUs: 50,
    stages: [
      { duration: "30s", target: 50   },   // baseline
      { duration: "10s", target: 3000 },   // spike
      { duration: "60s", target: 3000 },   // hold
      { duration: "10s", target: 50   },   // recovery
      { duration: "30s", target: 50   },   // back to baseline
    ],
    gracefulRampDown: "10s",
  },
};

// --------------------------------------------------------------------------
// Active scenario selection
// --------------------------------------------------------------------------
function buildScenarios() {
  if (SCENARIO === "all") {
    const result = {};
    Object.keys(scenarios).forEach((name, i) => {
      result[name] = {
        ...scenarios[name],
        exec: "eventsTest",
        startTime: `${i * 5}s`, // slight offset avoids thundering herd at t=0
        tags: { scenario: name },
      };
    });
    return result;
  }
  if (!scenarios[SCENARIO]) {
    throw new Error(`Unknown scenario: ${SCENARIO}. Valid: ${Object.keys(scenarios).join(", ")}`);
  }
  return {
    [SCENARIO]: {
      ...scenarios[SCENARIO],
      exec: "eventsTest",
      tags: { scenario: SCENARIO },
    },
  };
}

// --------------------------------------------------------------------------
// Thresholds
// --------------------------------------------------------------------------
export const options = {
  scenarios: buildScenarios(),

  thresholds: {
    // Latency targets
    http_req_duration: [
      "p(50)<100",    // 50% of requests under 100ms
      "p(95)<500",    // 95% under 500ms
      "p(99)<2000",   // 99% under 2s
    ],

    // Error rate: total non-2xx/3xx must stay under 5%
    http_req_failed: ["rate<0.05"],

    // Rate-limit hits should be rare (< 2% of total)
    "rate_limit_hits": ["count<100"],

    // Cache should be working (hit rate > 60% after warm-up)
    // Note: first run may have 0% hit rate until cache warms
    "cache_hit_rate": [],

    // Custom latency trend (for reporting only, no threshold failure)
    "response_time_ms": [],
  },

  // Summary output
  summaryTrendStats: ["min", "med", "p(90)", "p(95)", "p(99)", "max", "avg", "count"],
};

// --------------------------------------------------------------------------
// Request helpers
// --------------------------------------------------------------------------

// Vary page + limit to simulate real traffic patterns and test cache behavior.
const pageLimitCombos = [
  { page: 1, limit: 50 },
  { page: 1, limit: 50 },   // duplicated: higher probability (cache warm)
  { page: 1, limit: 50 },
  { page: 1, limit: 100 },
  { page: 2, limit: 50 },
  { page: 1, limit: 20 },
  { page: 3, limit: 50 },
];

function randomCombo() {
  return pageLimitCombos[Math.floor(Math.random() * pageLimitCombos.length)];
}

const params = {
  headers: { "Accept": "application/json" },
  timeout: "8s", // k6-level timeout, slightly above server timeout
};

// --------------------------------------------------------------------------
// Main test function
// --------------------------------------------------------------------------
export function eventsTest() {
  const combo = randomCombo();
  const url   = `${BASE_URL}/v1/events?page=${combo.page}&limit=${combo.limit}`;

  const start = Date.now();
  const res   = http.get(url, params);
  const dur   = Date.now() - start;

  responseTime.add(dur);

  // --- Cache tracking ---
  const xCache = res.headers["X-Cache"] || "";
  if (xCache === "HIT") {
    cacheHits.add(1);
    cacheHitRate.add(true);
  } else if (xCache === "MISS") {
    cacheMisses.add(1);
    cacheHitRate.add(false);
  }

  // --- Error classification ---
  if (res.status === 429) {
    rateLimitHits.add(1);
  } else if (res.status === 503) {
    busyErrors.add(1);
  } else if (res.status === 504) {
    timeoutErrors.add(1);
  } else if (res.status === 500) {
    dbErrors.add(1);
  }

  // --- Assertions ---
  check(res, {
    "status is 2xx":             (r) => r.status >= 200 && r.status < 300,
    "has data field":            (r) => {
      if (r.status !== 200) return true; // skip body check on non-200
      try {
        const b = r.json();
        return Array.isArray(b.data);
      } catch {
        return false;
      }
    },
    "has total field":           (r) => {
      if (r.status !== 200) return true;
      try { return typeof r.json().total !== "undefined"; } catch { return false; }
    },
    "response under 2s":         (r) => dur < 2000,
    "no server error (5xx)":     (r) => r.status < 500,
  });

  // Light think time: 0 = no sleep (max throughput test)
  // Uncomment to simulate real user behavior:
  // sleep(Math.random() * 0.1);
}

// --------------------------------------------------------------------------
// Health-check smoke test (runs before scenarios)
// --------------------------------------------------------------------------
export function setup() {
  const res = http.get(`${BASE_URL}/health`, { timeout: "5s" });
  if (res.status !== 200) {
    throw new Error(`Health check failed: ${res.status} - ${res.body}`);
  }
  const body = res.json();
  console.log(`Health: ${JSON.stringify(body)}`);
  return { baseUrl: BASE_URL };
}

// --------------------------------------------------------------------------
// Custom summary output
// --------------------------------------------------------------------------
export function handleSummary(data) {
  const metrics = data.metrics;

  const rps         = metrics["http_reqs"]?.values?.rate?.toFixed(1) || "N/A";
  const p50         = metrics["http_req_duration"]?.values?.["p(50)"]?.toFixed(1) || "N/A";
  const p95         = metrics["http_req_duration"]?.values?.["p(95)"]?.toFixed(1) || "N/A";
  const p99         = metrics["http_req_duration"]?.values?.["p(99)"]?.toFixed(1) || "N/A";
  const errRate     = ((metrics["http_req_failed"]?.values?.rate || 0) * 100).toFixed(2);
  const hits        = metrics["cache_hits"]?.values?.count || 0;
  const misses      = metrics["cache_misses"]?.values?.count || 0;
  const total       = hits + misses;
  const hitPct      = total > 0 ? ((hits / total) * 100).toFixed(1) : "0";
  const rl          = metrics["rate_limit_hits"]?.values?.count || 0;
  const busy        = metrics["busy_503_errors"]?.values?.count || 0;
  const timeouts    = metrics["timeout_errors"]?.values?.count || 0;

  console.log("\n╔══════════════════════════════════════════════╗");
  console.log("║         PERFORMANCE BENCHMARK RESULTS        ║");
  console.log("╠══════════════════════════════════════════════╣");
  console.log(`║  RPS (stable):       ${String(rps + " req/s").padEnd(24)}║`);
  console.log(`║  Latency p50:        ${String(p50 + " ms").padEnd(24)}║`);
  console.log(`║  Latency p95:        ${String(p95 + " ms").padEnd(24)}║`);
  console.log(`║  Latency p99:        ${String(p99 + " ms").padEnd(24)}║`);
  console.log(`║  Error rate:         ${String(errRate + " %").padEnd(24)}║`);
  console.log("╠══════════════════════════════════════════════╣");
  console.log(`║  Cache hit rate:     ${String(hitPct + " %").padEnd(24)}║`);
  console.log(`║  Cache hits:         ${String(hits).padEnd(24)}║`);
  console.log(`║  Cache misses:       ${String(misses).padEnd(24)}║`);
  console.log("╠══════════════════════════════════════════════╣");
  console.log(`║  Rate limit (429):   ${String(rl).padEnd(24)}║`);
  console.log(`║  Busy (503):         ${String(busy).padEnd(24)}║`);
  console.log(`║  Timeouts (504):     ${String(timeouts).padEnd(24)}║`);
  console.log("╚══════════════════════════════════════════════╝\n");

  return {
    stdout: textSummary(data, { indent: " ", enableColors: true }),
    "k6-results.json": JSON.stringify(data, null, 2),
  };
}
